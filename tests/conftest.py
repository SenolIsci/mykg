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


@pytest.fixture(scope="session")
def openrouter_api_key():
    key = provider_key("openrouter-free")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def gemini_api_key():
    key = provider_key("gemini")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def anthropic_api_key():
    key = provider_key("anthropic-claude")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def openai_api_key():
    key = provider_key("openai")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return key


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
