# OpenTelemetry Tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in OpenTelemetry tracing to `mykg extract-graph`, with spans at 4 levels (run → pipeline step → batch/chunk → LLM call), exported via OTLP to a local Jaeger instance for debugging slow/stuck runs and token/cost visibility.

**Architecture:** A new `src/mykg/tracing.py` module centralizes OTel SDK setup (mirroring `logging.py`'s pattern) and exposes a `get_tracer()` used at each of the 4 span levels, plus a `submit_with_context()` helper that fixes the `contextvars` propagation gap across all 8 `ThreadPoolExecutor` sites in the codebase. Tracing is off by default (`otel.enabled: false`); a `--otel` CLI flag flips it on for one invocation, following the exact runtime-toggle pattern already used by `--obsidian-vault`/`--neo4j-csv`.

**Tech Stack:** `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-grpc`, `opentelemetry-instrumentation-httpx` (all new, added as an optional `otel` extras group). Jaeger via Docker Compose for local trace viewing. pytest with `opentelemetry-sdk`'s `InMemorySpanExporter` test utility for assertions.

**Spec:** `docs/superpowers/specs/2026-09-20-opentelemetry-tracing-design.md`

## Global Constraints

- **Python floor:** `>=3.11` (`pyproject.toml:22`) — all code must run on 3.11.
- **No hardcoded values (CLAUDE.md Invariant 7):** every OTel knob (enabled flag, exporter endpoint, service name) is a named constant in `config.py`, sourced from `mykg_config.yaml`, never an inline literal in `tracing.py` or elsewhere.
- **Pydantic for structured data (Invariant 8):** does not apply to raw OTel SDK objects (`Tracer`, `Span`, `TracerProvider`) — these stay plain SDK types, consistent with how `PipelineContext.adapter`/`error_gate` are already typed `Any` to dodge circular imports.
- **Dual-file YAML sync (Invariant 17):** any new key under a profile's `otel:` block must be added to **both** `mykg_config.yaml` (repo root) and `src/mykg/data/mykg_config.yaml` (packaging template), and — this repo's `logging:`/`error_gate:` blocks are repeated **once per profile** (7 profiles), so a new `otel:` block needs **14 total insertions** (7 profiles × 2 files), not one.
- **UTF-8 everywhere (Invariant 20):** any new `open()`/`read_text()`/`write_text()` call must pass `encoding="utf-8"` explicitly. (Not expected to be needed in this plan — no new file I/O beyond YAML/TOML edits done via the Edit tool — but keep in mind if a task adds one.)
- **Streaming I/O (Invariant 19):** not applicable — no new large file reads/writes introduced by this plan.
- **Never mutate `run.log`/`llm.log`/D16 intermediate files:** tracing is additive only (per spec §3, §8). No task in this plan touches `logging.py`'s existing behavior, `record_llm_call()`'s existing fields, or any D16 file format.
- **Test conventions:** flat `tests/` directory (no subpackages — confirmed `tests/llm/` does **not** exist), plain function-based pytest tests, `tmp_path` fixture, minimal-field Pydantic construction. New tests go directly under `tests/`, e.g. `tests/test_tracing.py`.
- **No existing `[project.optional-dependencies]` table** — `pyproject.toml` has none today; this plan creates it from scratch.
- **`logging.setup()` is called from 4 CLI command sites** (`cli.py:1041` `extract_graph`, `:1173` `approve_schema`, `:1298` `merge_graphs`, `:1728` a 4th command) — this plan wires `setup_tracing()` into `extract_graph` only (per user decision: merge-graphs and other commands are out of scope for this plan). Do not add tracing calls to the other 3 sites.
- **No sampling in v1** — every span is exported unconditionally (per user decision). Do not add a `trace_sample_ratio` config key or `TraceIdRatioBased` sampler.

---

## Task 1: `otel` extras group + core dependency scaffolding

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: an installable `mykg[otel]` extra providing `opentelemetry.trace`, `opentelemetry.sdk.trace.TracerProvider`, `opentelemetry.sdk.trace.export.BatchSpanProcessor`, `opentelemetry.exporter.otlp.proto.grpc.trace_exporter.OTLPSpanExporter`, and `opentelemetry.instrumentation.httpx.HTTPXClientInstrumentor`, importable when the extra is installed.

- [ ] **Step 1: Add the `[project.optional-dependencies]` table**

There is no existing `[project.optional-dependencies]` table in `pyproject.toml` — it must be created. Insert it immediately after the closing `]` of the `dependencies = [...]` list (which ends at line 36) and before `[project.scripts]` (line 38):

```toml
[project.optional-dependencies]
otel = [
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
    "opentelemetry-instrumentation-httpx>=0.48b0",
]
```

- [ ] **Step 2: Install the extra locally and verify imports**

Run: `uv pip install -e ".[otel]"`
Expected: install succeeds with no dependency conflicts against existing pins (`anthropic>=0.28`, `openai>=1.30`, `google-genai>=2.18`, `mcp>=1.0`).

Then verify the imports resolve:
```bash
python -c "
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
print('ok')
"
```
Expected: prints `ok` with no `ImportError`.

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
build: add optional otel extras group

Adds opentelemetry-api/sdk/exporter-otlp-proto-grpc/instrumentation-httpx
as an opt-in [otel] extra. No core dependency changes.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `otel:` YAML config block (both files, all 7 profiles)

**Files:**
- Modify: `mykg_config.yaml`
- Modify: `src/mykg/data/mykg_config.yaml`

**Interfaces:**
- Produces: an `otel:` YAML block with keys `enabled` (bool), `exporter_endpoint` (str), `service_name` (str), present identically in all 7 profile blocks of both files.

- [ ] **Step 1: Locate all 7 `logging:` block occurrences in `mykg_config.yaml`**

Run: `grep -n "^      logging:" "mykg_config.yaml"`
Expected output (7 lines): line numbers `176, 352, 527, 709, 904, 1082, 1250` (the `openai` profile's block is at `709` — this is the currently active profile per `profile: openai` at line 8, but all 7 must be edited).

- [ ] **Step 2: Insert `otel:` block after each `logging:` block in `mykg_config.yaml`**

For **each** of the 7 locations found in Step 1, insert a new `otel:` block immediately after that profile's `logging:` block (i.e. after its 5 keys: `max_bytes`, `backup_count`, `llm_log`, `capture_prompts`, `error_output_max_chars`), before the next key (`report:`). Use this exact block, matching the existing 6-space indentation used by sibling keys like `logging:`/`report:`:

```yaml
      otel:
        enabled: false
        exporter_endpoint: "http://localhost:4317"
        service_name: mykg
```

Do this for all 7 profiles. Use the Edit tool once per profile (7 edits total in this file), anchoring each edit on the unique 5-line `logging:` block content immediately preceding it so each edit is unambiguous (the `error_output_max_chars` value may differ slightly between profiles — read each block first before editing).

- [ ] **Step 3: Verify insertion count in `mykg_config.yaml`**

Run: `grep -c "^      otel:" "mykg_config.yaml"`
Expected: `7`

- [ ] **Step 4: Repeat Steps 1–3 for `src/mykg/data/mykg_config.yaml`**

Run: `grep -n "^      logging:" "src/mykg/data/mykg_config.yaml"`
Expected: same 7 line numbers as Step 1 (this file is structurally identical to the repo-root file).

Insert the identical `otel:` block after each of the 7 `logging:` blocks, same as Step 2.

Run: `grep -c "^      otel:" "src/mykg/data/mykg_config.yaml"`
Expected: `7`

- [ ] **Step 5: Diff the two files to confirm structural parity**

Run: `diff <(grep -A3 "^      otel:" "mykg_config.yaml") <(grep -A3 "^      otel:" "src/mykg/data/mykg_config.yaml")`
Expected: no output (files are identical at every `otel:` block).

- [ ] **Step 6: Validate YAML syntax**

Run: `python -c "import yaml; yaml.safe_load(open('mykg_config.yaml', encoding='utf-8')); yaml.safe_load(open('src/mykg/data/mykg_config.yaml', encoding='utf-8')); print('valid')"`
Expected: prints `valid` with no `yaml.YAMLError`.

- [ ] **Step 7: Commit**

```bash
git add mykg_config.yaml src/mykg/data/mykg_config.yaml
git commit -m "$(cat <<'EOF'
config: add otel: block to all 7 profiles in both config files

Master toggle (enabled: false by default), OTLP exporter endpoint,
and service name. Mirrors the logging:/error_gate: per-profile
block structure. Satisfies Invariant 17 (dual-file key parity).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `config.py` constants for OTel

**Files:**
- Modify: `src/mykg/config.py`
- Test: `tests/test_config.py` (create if it does not already exist — check first with `ls tests/test_config.py`)

**Interfaces:**
- Consumes: `_get_opt(section, key, default)` at `config.py:148-149` — `def _get_opt(section: str, key: str, default): return _p.get(section, {}).get(key, default)`, and `_p = RAW.get("pipeline", {})` at `config.py:141`.
- Produces: module-level constants `OTEL_ENABLED: bool`, `OTEL_EXPORTER_OTLP_ENDPOINT: str`, `OTEL_SERVICE_NAME: str`, readable as `config.OTEL_ENABLED` etc. by any other module.

- [ ] **Step 1: Write the failing test**

Create `tests/test_config.py` if it doesn't exist, or add to it if it does (check first). Add:

```python
def test_otel_config_constants_exist():
    import mykg.config as config

    assert isinstance(config.OTEL_ENABLED, bool)
    assert isinstance(config.OTEL_EXPORTER_OTLP_ENDPOINT, str)
    assert isinstance(config.OTEL_SERVICE_NAME, str)
    assert config.OTEL_ENABLED is False  # shipped default
    assert config.OTEL_EXPORTER_OTLP_ENDPOINT == "http://localhost:4317"
    assert config.OTEL_SERVICE_NAME == "mykg"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_otel_config_constants_exist -v`
Expected: FAIL with `AttributeError: module 'mykg.config' has no attribute 'OTEL_ENABLED'`

- [ ] **Step 3: Add the constants to `config.py`**

Add immediately after the `LOG_CAPTURE_PROMPTS` line (`config.py:264`), following the exact `_get_opt` pattern used by `LOG_LLM_LOG`/`LOG_CAPTURE_PROMPTS` (lines 263-264) rather than the manual-dict pattern used by `ERROR_GATE_*` (lines 336-338) — `_get_opt` is the more idiomatic match for a 3-key block like this:

```python
OTEL_ENABLED: bool = bool(_get_opt("otel", "enabled", False))
OTEL_EXPORTER_OTLP_ENDPOINT: str = str(
    _get_opt("otel", "exporter_endpoint", "http://localhost:4317")
)
OTEL_SERVICE_NAME: str = str(_get_opt("otel", "service_name", "mykg"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py::test_otel_config_constants_exist -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/mykg/config.py tests/test_config.py
git commit -m "$(cat <<'EOF'
feat(config): expose OTEL_ENABLED/OTEL_EXPORTER_OTLP_ENDPOINT/OTEL_SERVICE_NAME

Follows the existing _get_opt("logging", ...) pattern (LOG_LLM_LOG,
LOG_CAPTURE_PROMPTS). Defaults match the shipped otel: YAML block
added in the previous commit (enabled: false).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `src/mykg/tracing.py` — `setup_tracing()` and `get_tracer()`

**Files:**
- Create: `src/mykg/tracing.py`
- Test: `tests/test_tracing.py`

**Interfaces:**
- Consumes: `config.OTEL_ENABLED`, `config.OTEL_EXPORTER_OTLP_ENDPOINT`, `config.OTEL_SERVICE_NAME` (Task 3).
- Produces:
  - `setup_tracing(session_name: str, profile: str) -> None` — idempotent-safe module-level setup call.
  - `get_tracer() -> opentelemetry.trace.Tracer` — returns `trace.get_tracer("mykg")`; safe to call whether or not `setup_tracing()` ran or `OTEL_ENABLED` is true.
  - Both names importable as `from mykg.tracing import setup_tracing, get_tracer`.

This task does **not** yet include `submit_with_context()` (that's Task 5) or the HTTPX auto-instrumentation call (that's folded into Step 3 below since it's part of `setup_tracing()`'s body per spec §5.1 item 5, but gated behind an `ImportError`-safe check).

- [ ] **Step 1: Write the failing test for the disabled (no-op) path**

Create `tests/test_tracing.py`:

```python
import pytest


def test_get_tracer_works_without_setup():
    from mykg.tracing import get_tracer

    tracer = get_tracer()
    # Must not raise even though setup_tracing() was never called.
    with tracer.start_as_current_span("test-span"):
        pass


def test_setup_tracing_noop_when_disabled(monkeypatch):
    import mykg.config as config
    from mykg.tracing import setup_tracing

    monkeypatch.setattr(config, "OTEL_ENABLED", False)

    # Must not raise, must not require opentelemetry-sdk to be doing
    # anything beyond the no-op default tracer provider.
    setup_tracing(session_name="test-session", profile="openai")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'mykg.tracing'`

- [ ] **Step 3: Write `src/mykg/tracing.py`**

```python
"""OpenTelemetry tracing setup for mykg pipeline runs.

Centralizes OTel SDK configuration, mirroring how logging.py centralizes
logging setup: a module-level singleton, configured once per process via
setup_tracing(), read thereafter via get_tracer().

Tracing is fully opt-in (config.OTEL_ENABLED). When disabled, get_tracer()
still works — it returns a tracer backed by OTel's built-in no-op provider,
so callers never need to branch on whether tracing is on.
"""

from __future__ import annotations

import logging as _stdlib_logging

import mykg.config as config

_log = _stdlib_logging.getLogger("mykg.tracing")

_TRACER_NAME = "mykg"


def get_tracer():
    """Return the mykg tracer. Safe to call whether or not setup_tracing()
    has run, and whether or not tracing is enabled — returns a no-op
    tracer in both of those cases."""
    from opentelemetry import trace

    return trace.get_tracer(_TRACER_NAME)


def setup_tracing(session_name: str, profile: str) -> None:
    """Configure the global OTel TracerProvider for this process.

    No-op when config.OTEL_ENABLED is false. Call once, immediately after
    logging.setup(), before the pipeline orchestrator runs.

    Raises RuntimeError if config.OTEL_ENABLED is true but the optional
    `mykg[otel]` dependencies are not installed.
    """
    if not config.OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError as exc:
        raise RuntimeError(
            "otel.enabled is true (or --otel was passed) but the optional "
            "OpenTelemetry dependencies are not installed. Install them with: "
            "pip install 'mykg[otel]'"
        ) from exc

    resource = Resource.create(
        {
            "service.name": config.OTEL_SERVICE_NAME,
            "session.name": session_name,
            "mykg.profile": profile,
        }
    )
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=config.OTEL_EXPORTER_OTLP_ENDPOINT)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        _log.debug(
            "opentelemetry-instrumentation-httpx not installed; "
            "HTTP-level auto-instrumentation skipped."
        )

    _log.info(
        "OTel tracing enabled: exporting to %s", config.OTEL_EXPORTER_OTLP_ENDPOINT
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracing.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Write the failing test for the enabled path (using `InMemorySpanExporter`)**

Add to `tests/test_tracing.py`:

```python
def test_setup_tracing_enabled_exports_spans(monkeypatch):
    import mykg.config as config

    monkeypatch.setattr(config, "OTEL_ENABLED", True)
    monkeypatch.setattr(config, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")

    # Reset the global tracer provider so this test doesn't leak state
    # into others, and swap in an in-memory exporter instead of the real
    # OTLP one so this test needs no running collector.
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "mykg-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    tracer = trace.get_tracer("mykg")
    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("mykg.test", "value")

    spans = exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"
    assert spans[0].attributes["mykg.test"] == "value"
```

- [ ] **Step 6: Run test to verify it fails initially, then passes**

Run: `pytest tests/test_tracing.py::test_setup_tracing_enabled_exports_spans -v`
Expected: this test does not depend on new production code (it directly exercises the OTel SDK to prove the test pattern works) — it should PASS immediately since `opentelemetry-sdk` is installed via Task 1. If it fails with an import error, re-verify Task 1's Step 2 succeeded in this environment.

- [ ] **Step 7: Run the full test file**

Run: `pytest tests/test_tracing.py -v`
Expected: PASS (all 3 tests)

- [ ] **Step 8: Commit**

```bash
git add src/mykg/tracing.py tests/test_tracing.py
git commit -m "$(cat <<'EOF'
feat(tracing): add setup_tracing() and get_tracer()

New src/mykg/tracing.py, mirroring logging.py's module-level-singleton
setup pattern. No-op when config.OTEL_ENABLED is false. Raises a clear
RuntimeError if enabled without the optional mykg[otel] extra installed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `submit_with_context()` — ThreadPoolExecutor context propagation helper

**Files:**
- Modify: `src/mykg/tracing.py`
- Test: `tests/test_tracing.py`

**Interfaces:**
- Consumes: nothing new from other tasks — uses only `contextvars` (stdlib) and `concurrent.futures.ThreadPoolExecutor`.
- Produces: `submit_with_context(executor: ThreadPoolExecutor, fn: Callable, *args, **kwargs) -> Future` — importable as `from mykg.tracing import submit_with_context`. Drop-in replacement for `executor.submit(fn, *args, **kwargs)`.

- [ ] **Step 1: Write the failing test proving the propagation gap exists, then that the helper fixes it**

Add to `tests/test_tracing.py`:

```python
def test_submit_with_context_propagates_span_parent():
    from concurrent.futures import ThreadPoolExecutor

    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from mykg.tracing import submit_with_context

    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "mykg-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("mykg")

    def worker():
        with tracer.start_as_current_span("child-span"):
            pass

    with tracer.start_as_current_span("parent-span"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_with_context(executor, worker)
            future.result()

    spans = exporter.get_finished_spans()
    assert len(spans) == 2
    by_name = {s.name: s for s in spans}
    parent_span_id = by_name["parent-span"].context.span_id
    child_parent_id = by_name["child-span"].parent.span_id
    assert child_parent_id == parent_span_id, (
        "child-span's parent must be parent-span's span_id — "
        "context did not propagate into the worker thread"
    )


def test_submit_with_context_passes_args_and_kwargs():
    from concurrent.futures import ThreadPoolExecutor

    from mykg.tracing import submit_with_context

    def add(a, b, c=0):
        return a + b + c

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = submit_with_context(executor, add, 1, 2, c=3)
        assert future.result() == 6
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tracing.py::test_submit_with_context_propagates_span_parent tests/test_tracing.py::test_submit_with_context_passes_args_and_kwargs -v`
Expected: FAIL with `ImportError: cannot import name 'submit_with_context' from 'mykg.tracing'`

- [ ] **Step 3: Add `submit_with_context()` to `src/mykg/tracing.py`**

Add near the top of the file (after imports, before `get_tracer`):

```python
import contextvars
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

_T = TypeVar("_T")


def submit_with_context(
    executor: ThreadPoolExecutor, fn: Callable[..., _T], *args: Any, **kwargs: Any
) -> "Future[_T]":
    """Drop-in replacement for executor.submit(fn, *args, **kwargs) that
    propagates the calling thread's contextvars.Context — including the
    active OTel span context — into the worker thread.

    ThreadPoolExecutor.submit() does not snapshot/restore contextvars for
    you (unlike asyncio.create_task, which does). Without this, every span
    started inside a worker thread would be parentless.
    """
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tracing.py -v`
Expected: PASS (all 5 tests in the file now)

- [ ] **Step 5: Commit**

```bash
git add src/mykg/tracing.py tests/test_tracing.py
git commit -m "$(cat <<'EOF'
feat(tracing): add submit_with_context() for ThreadPoolExecutor propagation

contextvars (and therefore OTel span context) does not auto-propagate
into ThreadPoolExecutor workers. This helper captures the caller's
context via contextvars.copy_context() and runs the submitted callable
inside it, so a span started in a worker thread correctly nests under
whatever span was active on the submitting thread.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Wire `submit_with_context` into all 8 `ThreadPoolExecutor` call sites

**Files:**
- Modify: `src/mykg/pass1.py:290-292`
- Modify: `src/mykg/pass2.py:544-549`
- Modify: `src/mykg/pass2.py:827-829`
- Modify: `src/mykg/pass2.py:880-884`
- Modify: `src/mykg/orphan_connector.py:715-719`
- Modify: `src/mykg/orphan_connector.py:929-931`
- Modify: `src/mykg/steps/step_ingest.py:53-57`
- Modify: `src/mykg/steps/step_preprocess.py:64-66`
- Test: `tests/test_thread_pool_context_propagation.py`

**Interfaces:**
- Consumes: `submit_with_context(executor, fn, *args, **kwargs)` from Task 5.
- Produces: no new public interface — this task is a mechanical swap at 8 call sites. After this task, every `ThreadPoolExecutor.submit(...)` call in the codebase (verify via grep in Step 6) goes through `submit_with_context` instead.

**Note on exact current code** (verified against the live files, not the spec's approximate line numbers — these are exact):

- `pass1.py:290-292`:
  ```python
  with ThreadPoolExecutor(max_workers=_cfg.PASS1_MAX_WORKERS) as executor:
      futures = [executor.submit(_process_batch, i, batch) for i, batch in to_dispatch]
  ```
- `pass2.py:544-549`:
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
      futures = {executor.submit(_process_file, fname, content): fname for fname, content in files.items()}
  ```
- `pass2.py:827-829`:
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
      futures = {executor.submit(_process_batch, i, batch): i for i, batch in to_dispatch}
  ```
- `pass2.py:880-884`:
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as retry_executor:
      retry_futures = {retry_executor.submit(_process_batch, bi, b): bi for bi, b in failed_items}
  ```
- `orphan_connector.py:715-719`:
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
      futures: dict[Any, OrphanCandidate] = {executor.submit(_confirm_one, c, schema, adapter, chunk_texts): c for c in candidates}
  ```
- `orphan_connector.py:929-931`:
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
      futures = {executor.submit(_process_group, g): g for g in groups}
  ```
- `step_ingest.py:53-57` (inside `_run_parallel`, def at line 41):
  ```python
  with ThreadPoolExecutor(max_workers=max_workers) as executor:
      future_to_file = {executor.submit(worker, md_file, input_dir): md_file for md_file in md_files}
  ```
- `step_preprocess.py:64-66` (inside `_hash_files_parallel`, def at line 59):
  ```python
  with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
      future_to_path = {pool.submit(_sha256_path, p): p for p in files}
  ```

- [ ] **Step 1: Write a regression test asserting no bare `executor.submit`/`pool.submit` remains at these 8 sites**

Create `tests/test_thread_pool_context_propagation.py`:

```python
"""Guards against regressing on OTel context propagation: every
ThreadPoolExecutor.submit() call in the pipeline's parallel-dispatch code
must go through mykg.tracing.submit_with_context(), not be called bare,
or spans created inside worker threads will be parentless."""

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "mykg"

_SITES = [
    _SRC / "pass1.py",
    _SRC / "pass2.py",
    _SRC / "orphan_connector.py",
    _SRC / "steps" / "step_ingest.py",
    _SRC / "steps" / "step_preprocess.py",
]

_BARE_SUBMIT_RE = re.compile(r"(?<!submit_with_context\()\b\w+\.submit\(")


def test_no_bare_executor_submit_in_parallel_dispatch_files():
    offenders = []
    for path in _SITES:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ".submit(" in line and "submit_with_context" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Found bare .submit( calls that bypass submit_with_context "
        "(breaks OTel span parenting across threads):\n" + "\n".join(offenders)
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_thread_pool_context_propagation.py -v`
Expected: FAIL — lists all 8 (or more, if `step_ingest.py`/`step_preprocess.py` have additional unrelated `.submit(` calls — read each file to confirm before treating extra hits as a problem) bare `.submit(` call sites.

- [ ] **Step 3: Add the import and swap each call site**

For each of the 8 files, add `from mykg.tracing import submit_with_context` to the imports (near other `from mykg...` imports), then replace each bare `executor.submit(...)`/`pool.submit(...)`/`retry_executor.submit(...)` with the equivalent `submit_with_context(executor, ...)` call. Example for `pass1.py:290-292`:

```python
with ThreadPoolExecutor(max_workers=_cfg.PASS1_MAX_WORKERS) as executor:
    futures = [
        submit_with_context(executor, _process_batch, i, batch) for i, batch in to_dispatch
    ]
```

Apply the same transformation shape to all 7 remaining sites listed above — replace `<executor_var>.submit(fn, args...)` with `submit_with_context(<executor_var>, fn, args...)`, preserving every existing argument exactly.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_thread_pool_context_propagation.py -v`
Expected: PASS

- [ ] **Step 5: Run the existing test suite for the 5 modified modules to check for regressions**

Run: `pytest tests/ -v -k "pass1 or pass2 or orphan or ingest or preprocess" -m "not live and not mineru"`
Expected: PASS (no behavior change — `submit_with_context` calls `fn` with the identical args, just inside a copied context; all existing assertions about return values/results must still hold)

- [ ] **Step 6: Grep-verify no bare submit remains anywhere the plan intended to change**

Run: `grep -rn "\.submit(" src/mykg/pass1.py src/mykg/pass2.py src/mykg/orphan_connector.py src/mykg/steps/step_ingest.py src/mykg/steps/step_preprocess.py | grep -v submit_with_context`
Expected: no output (empty)

- [ ] **Step 7: Commit**

```bash
git add src/mykg/pass1.py src/mykg/pass2.py src/mykg/orphan_connector.py \
        src/mykg/steps/step_ingest.py src/mykg/steps/step_preprocess.py \
        tests/test_thread_pool_context_propagation.py
git commit -m "$(cat <<'EOF'
fix(tracing): propagate context across all 8 ThreadPoolExecutor sites

Swaps bare executor.submit(...) for tracing.submit_with_context(...)
at every parallel-dispatch call site (Pass 1 batches, Pass 2 per-file/
batch_chunks/retry-round, orphan Stage 2 per-candidate/per-group,
ingest file workers, preprocess source hashing). No behavior change —
submit_with_context runs the same callable with the same args inside
a copied contextvars.Context, which OTel spans rely on for correct
parent/child nesting once spans are added inside these workers.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Run span + `--otel` CLI flag

**Files:**
- Modify: `src/mykg/cli.py`
- Test: `tests/test_cli_otel_flag.py`

**Interfaces:**
- Consumes: `config.OTEL_ENABLED` (Task 3), `setup_tracing(session_name, profile)` and `get_tracer()` (Task 4).
- Produces: `--otel` CLI flag on `extract-graph`; a run span wrapping the `run(STEPS, ctx)` call at `cli.py:1153`, with attributes `mykg.session`, `mykg.profile`, `llm.provider`, `llm.model`, `mykg.append`, `mykg.sync`, `mykg.grow_schema`, `mykg.pass2_only`.

- [ ] **Step 1: Write the failing test for the `--otel` flag flipping config**

Create `tests/test_cli_otel_flag.py`:

```python
def test_otel_flag_sets_config(monkeypatch, tmp_path):
    """--otel should flip config.OTEL_ENABLED to True at runtime, exactly
    like the existing --obsidian-vault/--neo4j-csv pattern."""
    import mykg.config as config

    monkeypatch.setattr(config, "OTEL_ENABLED", False)

    # Mirror the exact runtime-toggle body used for obsidian_vault/neo4j_csv
    # at cli.py:1073-1081 — this test documents the expected shape without
    # invoking the full CLI (which needs a real corpus/adapter); the full
    # behavior is exercised end-to-end in Task 9.
    otel = True
    if otel:
        import mykg.config as _config_mod

        _config_mod.OTEL_ENABLED = True

    assert config.OTEL_ENABLED is True
```

- [ ] **Step 2: Run test to verify it passes trivially (documents intended shape)**

Run: `pytest tests/test_cli_otel_flag.py -v`
Expected: PASS (this test doesn't yet touch `cli.py` — it's a shape-lock test; the real wiring is verified in Steps 3-6 below via direct inspection, since exercising the full `extract_graph` Click command requires a live adapter/corpus, covered by Task 9's e2e test instead)

- [ ] **Step 3: Add the `--otel` Click option**

In `cli.py`, near the existing `--obsidian-vault`/`--neo4j-csv` options (lines 865-876), add:

```python
@click.option(
    "--otel",
    is_flag=True,
    default=False,
    help="Enable OpenTelemetry tracing for this run (overrides config otel.enabled)",
)
```

Add `otel` to the `extract_graph(...)` function's parameter list (matching how `obsidian_vault`/`neo4j_csv` are already parameters).

- [ ] **Step 4: Add the runtime-toggle body and `setup_tracing()` call**

Immediately after the existing block at `cli.py:1073-1081`:

```python
    if obsidian_vault:
        import mykg.config as _config_mod

        _config_mod.OBSIDIAN_ENABLED = True

    if neo4j_csv:
        import mykg.config as _config_mod

        _config_mod.NEO4J_CSV_ENABLED = True
```

add:

```python
    if otel:
        import mykg.config as _config_mod

        _config_mod.OTEL_ENABLED = True

    from mykg.tracing import setup_tracing

    setup_tracing(session_name=session_name, profile=_cfg().PROFILE)
```

Read the surrounding code first to confirm the exact variable names in scope at this point for `session_name` and the active profile (the profile constant's exact name — likely `PROFILE` or similar on the `_cfg()` accessor — must be verified by reading `config.py`'s module-level constants near where `RAW`/`_apply_profile` are defined; if no such constant exists, use the `--profile` CLI option's own local variable instead, whichever is already in scope at this point in `extract_graph`).

- [ ] **Step 5: Wrap `run(STEPS, ctx)` in a run span**

At `cli.py:1153`, change:

```python
run(STEPS, ctx)
```

to:

```python
    from mykg.tracing import get_tracer

    tracer = get_tracer()
    with tracer.start_as_current_span("mykg.extract_graph.run") as run_span:
        run_span.set_attribute("mykg.session", session_name)
        run_span.set_attribute("mykg.profile", _cfg().PROFILE)
        run_span.set_attribute("llm.provider", adapter.endpoint_label())
        run_span.set_attribute("mykg.append", bool(append))
        run_span.set_attribute("mykg.sync", bool(sync))
        run_span.set_attribute("mykg.grow_schema", bool(grow_schema))
        run_span.set_attribute("mykg.pass2_only", bool(pass2_only))
        run(STEPS, ctx)
```

(Read the surrounding code to confirm the exact local variable names for `append`, `sync`, `grow_schema`, `pass2_only` match the `extract_graph` function signature — these are the CLI option variables, not `ctx` fields, unless `ctx` is simpler to read from at this point; prefer whichever is already in scope and correct at line 1153 without needing to look ahead in the function.)

When `config.OTEL_ENABLED` is false, `get_tracer()` returns a no-op tracer (Task 4), so `start_as_current_span` and `set_attribute` are cheap no-ops — no `if config.OTEL_ENABLED:` branch is needed here, per spec §5.1.

- [ ] **Step 6: Manually verify the flag parses**

Run: `mykg extract-graph --help`
Expected: output includes a `--otel` line with the help text "Enable OpenTelemetry tracing for this run (overrides config otel.enabled)"

- [ ] **Step 7: Run the full existing extract-graph CLI test coverage to check for regressions**

Run: `pytest tests/ -v -k "cli" -m "not live and not mineru"`
Expected: PASS — no existing test should reference call-site line numbers, so adding the flag/span-wrap should not break anything already passing.

- [ ] **Step 8: Commit**

```bash
git add src/mykg/cli.py tests/test_cli_otel_flag.py
git commit -m "$(cat <<'EOF'
feat(cli): add --otel flag and wrap run(STEPS, ctx) in a run span

Mirrors the --obsidian-vault/--neo4j-csv runtime-toggle pattern.
setup_tracing() is called once per extract-graph invocation; the run
span carries session/profile/provider/mode-flag attributes. No-op
when otel.enabled is false and --otel is not passed.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Step spans + attempt child spans in the orchestrator

**Files:**
- Modify: `src/mykg/orchestrator.py`
- Test: `tests/test_orchestrator_tracing.py`

**Interfaces:**
- Consumes: `get_tracer()` from Task 4.
- Produces: one span per `Step` execution (name `f"mykg.step.{step.name}"`), attributes `mykg.step.name`, `mykg.step.is_llm_step`, `mykg.step.blocking`; child spans `attempt-1`/`attempt-2`/`attempt-3-with-feedback` for each `_try_run` invocation; a span event `schema.updated_restart` when `SchemaUpdatedError` fires.

- [ ] **Step 1: Write the failing test using `InMemorySpanExporter`**

Create `tests/test_orchestrator_tracing.py`. This test constructs a minimal 2-step pipeline (one always-succeeding step, one that fails twice then succeeds) and asserts the resulting span tree shape:

```python
import pytest
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)

from mykg.orchestrator import PipelineContext, PipelineState, Step, run


@pytest.fixture
def span_exporter():
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": "mykg-test"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    yield exporter
    exporter.clear()


def test_step_span_created_for_successful_step(tmp_path, span_exporter):
    calls = []

    def ok_step(ctx):
        calls.append(1)

    steps = [
        Step(name="ok_step", fn=ok_step, outputs=[], is_llm_step=False, blocking=True)
    ]
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    (tmp_path / "intermediate").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    state = PipelineState(intermediate_dir=ctx.intermediate_dir)

    run(steps, ctx, state=state)

    spans = span_exporter.get_finished_spans()
    step_spans = [s for s in spans if s.name == "mykg.step.ok_step"]
    assert len(step_spans) == 1
    assert step_spans[0].attributes["mykg.step.name"] == "ok_step"
    assert step_spans[0].attributes["mykg.step.is_llm_step"] is False
```

**Before writing this test file for real, first read `orchestrator.py`'s `run()` function signature exactly** (verify whether `state` is a required positional/keyword argument or constructed internally — the plan's Task 4 research found `run(steps, ctx)` as the signature at line 328, with no visible `state` parameter, meaning `PipelineState` may be constructed inside `run()` itself from `ctx.intermediate_dir`). **Adjust the test's call to `run(...)` to match the actual signature** — read `orchestrator.py:328-360` before finalizing this test, since calling `run()` incorrectly will produce a misleading test failure unrelated to tracing.

- [ ] **Step 2: Run test to verify it fails for the right reason**

Run: `pytest tests/test_orchestrator_tracing.py -v`
Expected: FAIL because no spans are produced yet (`step_spans` is empty) — not because of a `TypeError` on the `run()` call signature. If it fails with a `TypeError`, fix the test's call to `run(...)` first (per the note in Step 1) before treating this as the tracing gap.

- [ ] **Step 3: Add step spans and attempt child spans in `orchestrator.py`**

Read `orchestrator.py:328-583` in full before editing (the plan's earlier research summarized it, but re-read the live file to get exact current variable names before editing, since this is the most control-flow-sensitive file in the plan).

At the point `state.mark_running(step.name)` is called (line 425), open a step span and keep it current for the duration of that step's attempts:

```python
from mykg.tracing import get_tracer

_tracer = get_tracer()
```

(add this near the top of `orchestrator.py`, with the other imports)

Wrap the per-step body (the code between `state.mark_running(step.name)` at line 425 and the final `mark_done`/`mark_failed` calls at lines 572/549) in:

```python
with _tracer.start_as_current_span(f"mykg.step.{step.name}") as step_span:
    step_span.set_attribute("mykg.step.name", step.name)
    step_span.set_attribute("mykg.step.is_llm_step", step.is_llm_step)
    step_span.set_attribute("mykg.step.blocking", step.blocking)
    # ... existing per-step body, unchanged ...
```

Wrap each of the 3 `_try_run` call sites (lines 213, 531, 540 per the plan's verified research) in its own child span:

```python
with _tracer.start_as_current_span("attempt-1"):
    error = _try_run(step, ctx)
```

```python
with _tracer.start_as_current_span("attempt-2"):
    error = _try_run(step, ctx)
```

```python
with _tracer.start_as_current_span("attempt-3-with-feedback"):
    error = _try_run(step, ctx)
```

(Match these to whatever the actual retry-loop variable names/structure are once you've re-read the live file in this step — the goal is one child span per `_try_run` invocation, named to distinguish the bare retry from the feedback-corrected retry, without changing any existing control flow, error handling, or `mark_done`/`mark_failed`/`state.save()` calls.)

At the `SchemaUpdatedError` catch site (line 437 per research), add a span event on the step span rather than an error status:

```python
except SchemaUpdatedError as schema_exc:
    step_span.add_event(
        "schema.updated_restart",
        attributes={"mykg.restart_count": ctx.schema_restart_count},
    )
    # ... existing handling, unchanged ...
```

On the failure path (where `mark_failed` is called, line 549), before or after that call, set the step span's error status:

```python
if error:
    step_span.record_exception(error)
    step_span.set_status(trace.Status(trace.StatusCode.ERROR))
    # ... existing state.mark_failed(...) call, unchanged ...
```

(`from opentelemetry import trace` needed for `trace.Status`/`trace.StatusCode` — add to the top-level imports guarded the same way `get_tracer` is, i.e. these are only ever invoked when a span is active, which is always safe since `get_tracer()` never raises.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_orchestrator_tracing.py -v`
Expected: PASS

- [ ] **Step 5: Add and run a second test for the retry-attempt span count**

Add to `tests/test_orchestrator_tracing.py`:

```python
def test_attempt_spans_created_on_retry(tmp_path, span_exporter):
    attempt_count = {"n": 0}

    def flaky_step(ctx):
        attempt_count["n"] += 1
        if attempt_count["n"] < 2:
            raise RuntimeError("transient failure")

    steps = [
        Step(
            name="flaky_step", fn=flaky_step, outputs=[], is_llm_step=False, blocking=True
        )
    ]
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    (tmp_path / "intermediate").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)

    run(steps, ctx)

    spans = span_exporter.get_finished_spans()
    attempt_spans = [s for s in spans if s.name == "attempt-1"]
    assert len(attempt_spans) == 1, "expected exactly one attempt-1 span"
```

Run: `pytest tests/test_orchestrator_tracing.py -v`
Expected: PASS. If `flaky_step` isn't actually retried the way this test assumes (e.g. `is_llm_step=False` steps might not get a feedback retry, only a bare one — re-check the orchestrator's actual retry-gating logic from Step 3's re-read), adjust the test to match real behavior rather than forcing a false assumption.

- [ ] **Step 6: Run the full orchestrator test suite for regressions**

Run: `pytest tests/test_orchestrator.py tests/test_orchestrator_tracing.py -v`
Expected: PASS (all tests, old and new)

- [ ] **Step 7: Commit**

```bash
git add src/mykg/orchestrator.py tests/test_orchestrator_tracing.py
git commit -m "$(cat <<'EOF'
feat(tracing): add step spans + attempt child spans to the orchestrator

One span per Step execution, named mykg.step.<name>, with a child span
per _try_run attempt (bare retry and feedback-corrected retry get
distinct names). SchemaUpdatedError is recorded as a span event
(schema.updated_restart), not an error status, since it's a
control-flow signal rather than a failure. No change to retry counts,
timing, or the automated Re-entry A restart behavior.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Batch/file/chunk spans (Pass 1 + Pass 2 + orphan connect)

**Files:**
- Modify: `src/mykg/pass1.py` (`_process_batch`)
- Modify: `src/mykg/pass2.py` (`_process_file` and/or per-batch worker function used by `batch_chunks` mode — verify exact function name(s) by reading the file)
- Modify: `src/mykg/orphan_connector.py` (`_confirm_one`, `_process_group`)
- Test: `tests/test_batch_spans.py`

**Interfaces:**
- Consumes: `get_tracer()` (Task 4), `submit_with_context()` (Task 5, already wired in Task 6 — this task adds spans *inside* the functions those sites dispatch, not the dispatch itself).
- Produces: one span per unit of work, named to match its kind (e.g. `mykg.pass1.batch`, `mykg.pass2.file`, `mykg.pass2.batch`, `mykg.orphan.confirm`, `mykg.orphan.group`), attributes drawn from data already in scope at each call site (batch index, chunk count, source files, file name, orphan/candidate IDs).

- [ ] **Step 1: Read the exact current bodies of the 5 target functions**

Before writing any span code, read:
- `pass1.py` — the `_process_batch(i, batch)` function body in full.
- `pass2.py` — `_process_file(fname, content)` and the `batch_chunks`-mode worker function dispatched at lines 827/880 (confirm its exact name — the plan's research called it `_process_batch` by inference but did not read its body; verify before editing).
- `orphan_connector.py` — `_confirm_one(candidate, schema, adapter, chunk_texts)` and `_process_group(group)`.

Confirm each function's parameters give enough information to set meaningful span attributes without adding new parameters (per spec §5.3 item 3 — "no new computation, just reuse").

- [ ] **Step 2: Write failing tests asserting each function creates a span with the expected name/attributes**

Create `tests/test_batch_spans.py`. Structure each test the same way: set up an `InMemorySpanExporter`, call the target function directly (not through the full pipeline — these are unit-level tests of one function each) with minimal fixture data, assert on `exporter.get_finished_spans()`. Example shape for `_process_batch` in `pass1.py` (adapt exact fixture construction — `Chunk`, schema proposal shape, etc. — to match what `_process_batch` actually requires, read from Step 1):

```python
def test_pass1_process_batch_creates_span(span_exporter, monkeypatch):
    from mykg import pass1

    # Fixture setup here must match _process_batch's actual signature and
    # any module-level dependencies it reads (e.g. a mock adapter returning
    # a canned schema proposal) — read pass1.py fully before writing this,
    # per Step 1, and construct the minimal fixture that lets the function
    # run to completion without a real LLM call.
    ...

    spans = span_exporter.get_finished_spans()
    batch_spans = [s for s in spans if s.name == "mykg.pass1.batch"]
    assert len(batch_spans) == 1
    assert "mykg.batch.index" in batch_spans[0].attributes
```

Write the equivalent test for each of the other 4 functions, following the exact same `span_exporter` fixture pattern established in `tests/test_orchestrator_tracing.py` (Task 8) — reuse that fixture via a shared `conftest.py` addition if convenient (add a `span_exporter` fixture to `tests/conftest.py` if it will be reused across 2+ test files, to avoid duplicating the `InMemorySpanExporter`/`TracerProvider` setup boilerplate).

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_batch_spans.py -v`
Expected: FAIL — no spans produced yet by any of the 5 functions.

- [ ] **Step 4: Add a span to each of the 5 functions**

For each function, wrap its existing body in a span, using the tracer obtained via `from mykg.tracing import get_tracer` at module level (same pattern as Task 8). Example for `pass1.py`'s `_process_batch`:

```python
_tracer = get_tracer()  # module-level, added once near other imports

def _process_batch(i, batch):
    with _tracer.start_as_current_span("mykg.pass1.batch") as span:
        span.set_attribute("mykg.batch.index", i)
        span.set_attribute("mykg.batch.chunk_count", len(batch))
        # ... existing function body, unchanged ...
```

Apply the equivalent wrap to `pass2.py`'s `_process_file` (attributes: `mykg.file.name` = `fname`) and the `batch_chunks`-mode batch worker (attributes: `mykg.batch.index`, `mykg.batch.chunk_count`, and `mykg.batch.source_files` if cheaply available at that point — check `batch_map[f"batch_{i:04d}"]` per the plan's research), `orphan_connector.py`'s `_confirm_one` (attributes: `mykg.orphan.orphan_id` = `candidate.orphan_id`, `mykg.orphan.candidate_id` = `candidate.candidate_id`) and `_process_group` (attributes: `mykg.orphan.chunk_key` = `group.chunk_key`, `mykg.orphan.count` = `len(group.orphan_ids)`).

On failure inside any of these functions (if the function catches its own exceptions internally rather than letting them propagate — check during Step 1's read), record the exception on the span before any existing error handling: `span.record_exception(exc); span.set_status(trace.Status(trace.StatusCode.ERROR))`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_batch_spans.py -v`
Expected: PASS

- [ ] **Step 6: Run the existing Pass 1 / Pass 2 / orphan test suites for regressions**

Run: `pytest tests/ -v -k "pass1 or pass2 or orphan" -m "not live and not mineru"`
Expected: PASS — wrapping a function body in a `with` block must not change its return value, side effects, or exception propagation.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/pass1.py src/mykg/pass2.py src/mykg/orphan_connector.py \
        tests/test_batch_spans.py
git commit -m "$(cat <<'EOF'
feat(tracing): add batch/file/chunk spans to Pass 1, Pass 2, orphan connect

One span per unit of work dispatched into a thread pool: Pass 1 batch,
Pass 2 file/batch, orphan Stage 2 candidate/group. Attributes reuse
data already computed at each call site (batch index, chunk count,
file name, orphan/candidate IDs) — no new computation. Relies on the
context propagation wired in the ThreadPoolExecutor task so these
spans correctly nest under their enclosing step span.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: LLM-call spans around `llm_complete_with_retry`

**Files:**
- Modify: `src/mykg/llm/retry.py`
- Test: `tests/test_retry.py` (add to existing file)

**Interfaces:**
- Consumes: `get_tracer()` (Task 4).
- Produces: one span per `llm_complete_with_retry(...)` call, named `mykg.llm.call`, with attributes `gen_ai.system` (adapter's provider — read from `adapter.endpoint_label()` or an equivalent provider-name accessor, verify exact source during implementation), `gen_ai.request.model` (if obtainable from the adapter without new plumbing — otherwise omit and note as a follow-up, since spec §5.3 says reuse existing data only), `mykg.llm.context_label` (the existing `context_label` parameter, verbatim).

- [ ] **Step 1: Read `retry.py`'s full current body**

Read `src/mykg/llm/retry.py` in full (172 lines) before editing — the plan's research read only the signature (lines 87-96); confirm the exact body structure of `llm_complete_with_retry` (its retry loop, how it calls `adapter.complete(...)`, what it returns/raises) before wrapping it in a span, since this function's own retry loop means a span here covers potentially multiple underlying `adapter.complete()` calls (empty-response retries) — decide during this read whether that's one span per `llm_complete_with_retry` call (covering all its internal retries) or one span per internal attempt, and default to **one span per `llm_complete_with_retry` call** (matching spec §5.3's stated choke point) unless the function's structure makes that clearly wrong.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_retry.py` (read the existing file first to match its fixture/mocking conventions for `adapter`):

```python
def test_llm_complete_with_retry_creates_span(span_exporter, monkeypatch):
    from mykg.llm.retry import llm_complete_with_retry

    class _FakeAdapter:
        def complete(self, system, user, context_label="", max_tokens=None,
                     timeout=None, temperature=None):
            return "fake response"

        def endpoint_label(self):
            return "fake-provider/fake-model"

    result = llm_complete_with_retry(
        _FakeAdapter(), "system prompt", "user prompt", context_label="test-call"
    )

    assert result == "fake response"
    spans = span_exporter.get_finished_spans()
    call_spans = [s for s in spans if s.name == "mykg.llm.call"]
    assert len(call_spans) == 1
    assert call_spans[0].attributes["mykg.llm.context_label"] == "test-call"
```

(Use the shared `span_exporter` fixture from `tests/conftest.py` if added in Task 9, or the inline pattern from Task 8/9 otherwise — match whichever exists by the time this task runs.)

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_retry.py::test_llm_complete_with_retry_creates_span -v`
Expected: FAIL — no span produced yet.

- [ ] **Step 4: Wrap `llm_complete_with_retry` in a span**

Based on the Step 1 read, wrap the function body (or, if the function is short enough, its single call-out to the adapter) in:

```python
from mykg.tracing import get_tracer

_tracer = get_tracer()

def llm_complete_with_retry(adapter, system, user, context_label="", max_tokens=None, timeout=None, temperature=None):
    with _tracer.start_as_current_span("mykg.llm.call") as span:
        span.set_attribute("mykg.llm.context_label", context_label)
        try:
            span.set_attribute("gen_ai.system", adapter.endpoint_label())
        except Exception:
            pass  # endpoint_label() must never fail a real LLM call over a span attribute
        # ... existing function body, unchanged ...
```

(Match indentation/structure to the function's actual current body from Step 1 — this snippet shows the wrapping shape, not a literal diff, since the exact body wasn't read at plan-writing time.)

On failure (the function's existing exception path, whatever it is per Step 1's read), add `span.record_exception(exc)` and `span.set_status(trace.Status(trace.StatusCode.ERROR))` before re-raising, without changing what is raised or when.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_retry.py::test_llm_complete_with_retry_creates_span -v`
Expected: PASS

- [ ] **Step 6: Run the full existing retry test suite for regressions**

Run: `pytest tests/test_retry.py -v`
Expected: PASS (all tests, old and new) — confirms the span wrapper doesn't change retry counts, return values, or exception types.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/llm/retry.py tests/test_retry.py
git commit -m "$(cat <<'EOF'
feat(tracing): add LLM-call span around llm_complete_with_retry()

Single choke point every Pass 1/Pass 2/orphan/feedback/normalize-names
call site already goes through. One span per call (covering internal
empty-response retries), tagged with gen_ai.system and the existing
context_label string. No change to retry behavior or return values.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Local Jaeger Docker Compose + README section

**Files:**
- Create: `docker-compose.otel.yml`
- Modify: `README.md` (add a short "Tracing" section — check existing structure/heading levels first)

**Interfaces:**
- Produces: a `docker compose -f docker-compose.otel.yml up -d` workflow that stands up Jaeger's all-in-one image with an OTLP gRPC receiver on 4317 and UI on 16686.

- [ ] **Step 1: Create `docker-compose.otel.yml`**

```yaml
services:
  jaeger:
    image: jaegertracing/all-in-one:1.60
    ports:
      - "4317:4317"   # OTLP gRPC receiver
      - "16686:16686" # Jaeger UI
```

- [ ] **Step 2: Verify the compose file is syntactically valid**

Run: `docker compose -f docker-compose.otel.yml config`
Expected: prints the resolved compose config with no errors. (If `docker` is not available in this environment, skip actually running it and just visually confirm the YAML parses: `python -c "import yaml; yaml.safe_load(open('docker-compose.otel.yml', encoding='utf-8')); print('valid')"`.)

- [ ] **Step 3: If Docker is available, start Jaeger and confirm the UI responds**

Run: `docker compose -f docker-compose.otel.yml up -d`
Then: `curl -s -o /dev/null -w "%{http_code}" http://localhost:16686`
Expected: `200`

Run: `docker compose -f docker-compose.otel.yml down`
(Clean up after verifying — don't leave the container running for later tasks unless Task 12 needs it immediately after.)

- [ ] **Step 4: Add a short "Tracing" section to `README.md`**

Read the existing `README.md` structure first (heading levels, existing sections like installation/usage) to match style. Add a section along these lines, placed near other optional-feature documentation (e.g. near Neo4j/Obsidian export docs if they exist as README sections):

```markdown
## Tracing (OpenTelemetry)

`mykg extract-graph` can emit OpenTelemetry traces for debugging slow or
stuck runs and for token/cost visibility across steps and LLM calls.

1. Install the optional extra: `pip install 'mykg[otel]'`
2. Start a local Jaeger instance: `docker compose -f docker-compose.otel.yml up -d`
3. Run with tracing enabled: `mykg extract-graph <dir> --otel`
4. Open `http://localhost:16686`, select the `mykg` service, and view the run's trace.

Tracing is off by default and adds no overhead unless `--otel` is passed or
`otel.enabled: true` is set in `mykg_config.yaml`.
```

- [ ] **Step 5: Commit**

```bash
git add docker-compose.otel.yml README.md
git commit -m "$(cat <<'EOF'
docs: add local Jaeger docker-compose + README tracing section

docker compose -f docker-compose.otel.yml up -d gives an immediate
OTLP receiver + trace-viewer UI for local --otel runs.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: End-to-end verification against a real fixture corpus

**Files:**
- No new source files — this task runs the full pipeline with `--otel` against a small real corpus and manually verifies the resulting trace, then adds one integration test asserting the overall span-tree shape.
- Test: `tests/test_otel_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1–10.

- [ ] **Step 1: Write the integration test**

Create `tests/test_otel_integration.py`. This exercises the pipeline against a tiny fixture corpus (2-3 short markdown files) using the `live_corpus` fixture pattern already established in `tests/conftest.py` (read `conftest.py` first to reuse its exact fixture, rather than duplicating corpus-building logic) — but since a real LLM call is expensive/slow/non-deterministic for a unit test, this test should use whichever mocking approach `tests/test_orchestrator.py` or similar already use for a full-pipeline run without live API calls. If no such mock-adapter pattern exists in the test suite, mark this test `@pytest.mark.live` (per the existing marker registered in `pyproject.toml:57-63`) so it only runs when API keys are present, and structure it as:

```python
import pytest


@pytest.mark.live
def test_extract_graph_with_otel_produces_expected_span_tree(
    tmp_path, live_corpus, anthropic_api_key, span_exporter
):
    """Full pipeline run with --otel enabled, asserting the span tree has
    the shape: 1 run span containing N step spans, each LLM step containing
    at least 1 LLM-call span."""
    import mykg.config as config

    monkeypatch_otel_enabled = True  # set via the same pattern as other tests
    # ... invoke extract-graph against live_corpus, following whatever
    # existing live-corpus test in tests/ (e.g. one exercising the full
    # pipeline end-to-end already) does for CLI invocation — read that
    # test first and mirror its setup/teardown exactly ...

    spans = span_exporter.get_finished_spans()
    run_spans = [s for s in spans if s.name == "mykg.extract_graph.run"]
    assert len(run_spans) == 1

    step_spans = [s for s in spans if s.name.startswith("mykg.step.")]
    assert len(step_spans) >= 10  # pipeline has 12 steps; some may be skipped

    llm_call_spans = [s for s in spans if s.name == "mykg.llm.call"]
    assert len(llm_call_spans) >= 1
```

Before finalizing this test, find an existing full-pipeline live test in `tests/` (search: `grep -l "live_corpus" tests/*.py`) and copy its exact invocation pattern for running `extract-graph` against a fixture corpus, rather than inventing a new one — the goal is to add `--otel`/`InMemorySpanExporter` assertions on top of an already-proven pipeline invocation, not to write a new one from scratch.

- [ ] **Step 2: Run the test if API keys are available**

Run: `pytest tests/test_otel_integration.py -v -m live`
Expected: PASS if an API key is configured in the environment (per `conftest.py`'s skip-if-unset fixtures); SKIPPED otherwise — either outcome is acceptable, this is not a required gate for the plan's other tasks.

- [ ] **Step 3: Manual e2e verification (requires Docker + a real API key)**

If Docker and an API key are both available in this environment:

```bash
docker compose -f docker-compose.otel.yml up -d
mykg extract-graph tests/fixtures/<some small existing fixture dir> --otel --session otel-e2e-test
```

(Find an existing small fixture corpus under `tests/` via `find tests -name "*.md" | head -5` rather than inventing new fixture files.)

Then open `http://localhost:16686` in a browser, search for service `mykg`, and confirm:
- Exactly one trace appears for the run.
- The trace's root span is `mykg.extract_graph.run`.
- Step spans appear in pipeline order as children.
- Steps with parallel work (pass1, pass2) show multiple concurrent batch/file child spans.
- LLM-call spans appear nested under their batch/file span, each tagged with `gen_ai.system` and `mykg.llm.context_label`.

Report what was observed (or note "skipped — no Docker/API key in this environment") rather than asserting success without having looked.

```bash
docker compose -f docker-compose.otel.yml down
```

- [ ] **Step 4: Run the full test suite one final time**

Run: `pytest tests/ -v -m "not live and not mineru"`
Expected: PASS — this is the final regression gate confirming nothing in Tasks 1-11 broke any existing non-live test.

- [ ] **Step 5: Commit**

```bash
git add tests/test_otel_integration.py
git commit -m "$(cat <<'EOF'
test: add end-to-end OTel span-tree integration test

Marked @pytest.mark.live since it exercises a real LLM call against a
fixture corpus. Asserts the full span tree shape: one run span, step
spans for each pipeline stage, at least one LLM-call span.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Summary of what this plan does NOT do (explicitly out of scope, per spec + user decisions)

- No changes to `merge-graphs`, `approve-schema`, or `parse-docs`/`fetch-web` CLI commands — tracing is wired into `extract-graph` only.
- No sampling/`TraceIdRatioBased` config — every span is exported unconditionally in v1.
- No metrics or logs signals — traces (spans) only.
- No changes to `llm.log`, `run.log`, or any D16 intermediate JSON file format.
- No new required `PipelineContext` field — tracing rides on OTel's own `contextvars`-based context propagation, not manual threading through `ctx`.
