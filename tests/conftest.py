import os
from pathlib import Path

import pytest


def _load_key(env_var: str) -> str | None:
    """Read an API key from the environment, falling back to .env.mykg.

    The CLI loads .env.mykg via load_dotenv() but pytest does not, so tests that
    need a real key have to read it themselves.
    """
    key = os.environ.get(env_var, "").strip()
    if not key:
        env_file = Path(__file__).parent.parent / ".env.mykg"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith(env_var + "="):
                    key = line.partition("=")[2].strip()
                    break
    return key or None


# Env var(s) each provider profile authenticates with, in resolution order.
# Mirrors the fallbacks in src/mykg/llm/config.py.
PROVIDER_KEY_VARS: dict[str, tuple[str, ...]] = {
    "openrouter-free": ("OPENROUTER_AUTH_TOKEN", "OPENROUTER_API_KEY"),
    "anthropic-claude": ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY"),
    "openai": ("OPENAI_API_KEY",),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY"),
    "ollama-local": (),  # local inference — no key
}


def provider_key(profile: str) -> str | None:
    """First configured key for a profile, or None. Empty tuple => no key needed."""
    for var in PROVIDER_KEY_VARS.get(profile, ()):
        key = _load_key(var)
        if key:
            return key
    return None


def provider_key_var_label(profile: str) -> str:
    """Human-readable name of the env var(s) a profile expects, for skip messages."""
    variables = PROVIDER_KEY_VARS.get(profile, ())
    return " or ".join(variables) if variables else "(no key required)"


def _key_fixture(profile: str) -> str:
    """Resolve a profile's key or skip, naming every env var it accepts."""
    key = provider_key(profile)
    if not key:
        pytest.skip(f"{provider_key_var_label(profile)} not set")
    return key


@pytest.fixture(scope="session")
def openrouter_api_key():
    return _key_fixture("openrouter-free")


@pytest.fixture(scope="session")
def gemini_api_key():
    return _key_fixture("gemini")


@pytest.fixture(scope="session")
def anthropic_api_key():
    return _key_fixture("anthropic-claude")


@pytest.fixture(scope="session")
def openai_api_key():
    return _key_fixture("openai")


@pytest.fixture
def span_exporter():
    """An in-memory OTel span exporter wired into the process-global
    TracerProvider for the duration of one test.

    Production code (mykg.orchestrator, pass1.py, etc.) caches its tracer
    at import time via a module-level `_tracer = get_tracer()`. This is
    intentional and correct in production: opentelemetry.trace.get_tracer()
    returns a ProxyTracer that forwards to whatever TracerProvider is
    active *at span-creation time*, not at get_tracer()-call time — so a
    tracer cached before mykg.tracing.setup_tracing() runs still correctly
    picks up the real provider once setup_tracing() installs it.

    That also means tests cannot isolate spans by installing a *new*
    TracerProvider per test (set_tracer_provider() is a process-wide
    set-once operation — every call after the first is silently ignored,
    and every already-cached ProxyTracer keeps forwarding to whichever
    provider won that first call). Instead, this fixture installs exactly
    one real TracerProvider the first time it runs, then on every test
    (including the first) swaps in a fresh InMemorySpanExporter as that
    provider's only span processor — so each test only sees the spans
    produced during its own body, regardless of import order or which
    module cached its tracer first.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        # First test in the process to need real tracing: install the one
        # SDK TracerProvider every ProxyTracer in the process will forward
        # to from now on (set_tracer_provider() only ever succeeds once).
        provider = TracerProvider(resource=Resource.create({"service.name": "mykg-test"}))
        trace.set_tracer_provider(provider)

    exporter = InMemorySpanExporter()
    span_processor = SimpleSpanProcessor(exporter)

    # Swap in this test's own processor list so spans from earlier/later
    # tests never leak into this test's assertions.
    old_processors = list(provider._active_span_processor._span_processors)
    provider._active_span_processor._span_processors = (span_processor,)

    yield exporter

    provider._active_span_processor._span_processors = tuple(old_processors)
    exporter.clear()


@pytest.fixture(scope="session")
def live_corpus(tmp_path_factory):
    d = tmp_path_factory.mktemp("corpus")
    (d / "people.md").write_text(
        "Alice is a software engineer at Acme Corp. "
        "Bob manages the infrastructure team at Acme Corp."
    )
    (d / "projects.md").write_text(
        "Acme Corp is building a distributed database called Prometheus. "
        "Alice leads the Prometheus project."
    )
    (d / "history.md").write_text(
        "Acme Corp was founded in 2010. Bob joined in 2015 and Alice in 2018."
    )
    return d
