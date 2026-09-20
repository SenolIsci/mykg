# OpenTelemetry Tracing for `mykg extract-graph` — Design

Status: proposed, pending review
Date: 2026-09-20

## 1. Problem

`extract-graph` runs a 12-step pipeline (D4/D38 in `CLAUDE.md`) with heavy
parallelism (8 distinct `ThreadPoolExecutor` sites) and dozens to thousands of
LLM calls per run. Today the only execution-time visibility is:

- `run.log` — free-text log lines, one logger per module, no timing structure.
- `llm.log` — one JSON line per LLM call (provider, model, tokens, duration),
  but no start timestamp, no parent/child linkage, and it's a flat file you
  have to grep after the fact.
- `pipeline_state.json` — per-step status (`pending`/`running`/`done`/`failed`)
  with a completion timestamp but no start timestamp or duration.
- Various D16 intermediate shards (`pass1_batch_proposals/`,
  `pass2_raw_batches/`) — per-unit-of-work status for *resumability*, not
  timing.

None of these compose into a single picture of "where did the last 40 minutes
go, and which of the 8 parallel workers is stuck." The D57 incident (a
production session found stuck at `pass2: running` with 73/3002 batches done
and no visibility into why) is a concrete example of the gap this closes.

## 2. Goals

- See where time goes across steps, batches, and individual LLM calls — a
  waterfall view of one `extract-graph` run.
- Token/cost visibility per run, per step, per provider — richer and more
  queryable than grepping `llm.log`.
- A foundation that can later point at a real backend (Honeycomb, Datadog,
  a hosted OTel collector) with no code changes, only config.
- Zero cost/risk for users who don't opt in.

## 3. Non-goals

- Replacing `run.log`, `llm.log`, or any D16 intermediate file. All existing
  audit/resumability files are unchanged; tracing is additive, emitted
  alongside them from the same call sites.
- Metrics or logs signals (OTel also defines these). This design is traces
  only — spans. Metrics can be layered on later using the same
  `TracerProvider`-adjacent `MeterProvider` setup if wanted.
- Distributed tracing across multiple `mykg` processes (e.g. correlating a
  `merge-graphs` run with the two `extract-graph` runs that produced its
  inputs). One run = one trace, full stop, for v1.
- Auto-instrumenting the LLM SDKs' retry/backoff internals — `mykg` already
  owns retry logic (`retry.py`); we trace mykg's retry loop, not the SDK's.

## 4. Prior art in the codebase (what this complements)

Research into the current pipeline turned up several files whose shape
already overlaps with what a span records, summarized here so the new design
is legible against what exists:

| File | What it has | What it lacks vs. a span |
|---|---|---|
| `pipeline_state.json` | per-step status + completion time | no start time, no duration, no nesting |
| `llm.log` | per-call provider/model/tokens/duration | no start time (only end), no trace/span id, no parent step |
| `pass1_batch_proposals/*.json`, `pass2_raw_batches/*.json` | per-batch status, written incrementally (D55/D57) | no timing at all — pure resumability cache |
| `schema_history/*.json`, `merge_log.json` | structured *decision* events | no timing — good material for span **events**, not spans themselves |

The design below emits spans **alongside** these writes; none of them are
restructured. Schema-history and merge-log entries become span events
attached to the relevant step span, not new spans of their own.

## 5. Architecture

### 5.1 New module: `src/mykg/tracing.py`

Single place OTel setup lives, mirroring how `src/mykg/logging.py` centralizes
logging setup today (module-level singleton, configured once per process).

```python
def setup_tracing() -> None:
    """Called once from cli.py, immediately after logging.setup().
    No-op when config.OTEL_ENABLED is false."""

def get_tracer() -> trace.Tracer:
    """Returns trace.get_tracer('mykg'). Safe to call even when tracing
    is disabled — returns a tracer backed by OTel's no-op provider."""

def submit_with_context(executor, fn, *args, **kwargs) -> Future:
    """Drop-in replacement for executor.submit(fn, *args, **kwargs) that
    propagates the calling thread's OTel context (and any other
    contextvars) into the worker thread."""
```

`setup_tracing()`:
1. Builds a `Resource` with `service.name=mykg`, `session.name=<session>`,
   `mykg.profile=<active profile>`.
2. Builds a `TracerProvider(resource=resource)`.
3. Adds a `BatchSpanProcessor(OTLPSpanExporter(endpoint=config.OTEL_EXPORTER_OTLP_ENDPOINT))`.
4. Calls `trace.set_tracer_provider(provider)`.
5. If `opentelemetry-instrumentation-httpx` is installed, calls
   `HTTPXClientInstrumentor().instrument()` — covers the 5 HTTP-based
   adapters (anthropic/openai/gemini/ollama/openrouter) for free.
6. When `config.OTEL_ENABLED` is false, does nothing. `trace.get_tracer(...)`
   then returns spans backed by OTel's built-in `INVALID_SPAN` /
   `NoOpTracer` — every `tracer.start_as_current_span(...)` call downstream
   becomes a cheap no-op automatically. **No `if config.OTEL_ENABLED` branch
   is needed anywhere outside `tracing.py` itself.**

### 5.2 Context propagation across `ThreadPoolExecutor`

Confirmed during research: all 8 executor call sites use bare
`executor.submit(fn, *args)`, and `contextvars` is not used anywhere in the
codebase today. OTel's `Context` is `contextvars`-based and does **not**
auto-propagate into a `ThreadPoolExecutor` worker (unlike `asyncio.create_task`,
which does this for you). Without a fix, every span created inside a worker
thread would be parentless — batches would not nest under their step, LLM
calls would not nest under their batch.

Fix: the shared `submit_with_context()` helper (5.1), swapped in at all 8
sites:

| File:line | Pool | Call site to change |
|---|---|---|
| `pass1.py:290-292` | Pass 1 batch dispatch | `executor.submit(_process_batch, i, batch)` |
| `pass2.py:544-549` | Pass 2 `per_file`/`concat` | `executor.submit(...)` |
| `pass2.py:827-829` | Pass 2 `batch_chunks` dispatch | `executor.submit(...)` |
| `pass2.py:880-884` | Pass 2 `batch_chunks` retry round | `executor.submit(...)` |
| `orphan_connector.py:715-719` | Stage 2 per-candidate | `executor.submit(...)` |
| `orphan_connector.py:929-931` | Stage 2 per-chunk-group | `executor.submit(...)` |
| `step_ingest.py:53-57` | file read/hash/chunk | `executor.submit(...)` |
| `step_preprocess.py:64-66` | non-md source hashing | `executor.submit(...)` |

One helper, one behavior, tested once — rather than duplicating
`contextvars.copy_context().run(...)` at 8 sites by hand.

### 5.3 Span levels

Four levels, matching the pipeline's own structure exactly (no new
abstraction invented — spans follow existing boundaries):

**1. Run span** — wraps the single `run(STEPS, ctx)` call at `cli.py:1153`.
One per `mykg extract-graph` (or `merge-graphs`) invocation.
Attributes: `mykg.session`, `mykg.profile`, `llm.provider`, `llm.model`,
`mykg.append`, `mykg.sync`, `mykg.grow_schema`, `mykg.pass2_only`.

**2. Step span** — one per `Step` in `STEPS`. Opened where
`state.mark_running(step.name)` fires (`orchestrator.py:425`), closed at the
matching `mark_done`/`mark_failed` (lines 572/549). Attributes:
`mykg.step.name`, `mykg.step.is_llm_step`, `mykg.step.blocking`.

- Each of the up to 3 attempts inside `_try_run` (`orchestrator.py:213`,
  `531`, `540`) becomes a **child span** (`attempt-1`, `attempt-2`,
  `attempt-3-with-feedback`), so a step that needed the LLM feedback loop
  (D31) is visible as "2 failed attempts, 1 succeeded" rather than a single
  opaque step duration.
- `SchemaUpdatedError` (the automated Re-entry A restart, D31 Tier 2) is
  recorded as a span **event** `schema.updated_restart` on the step span, not
  an error status — it is a control-flow signal, not a failure. The
  subsequent full-loop restart starts a **new** run span iteration is *not*
  introduced; the existing run span simply spans the whole
  `while True` orchestrator loop (`orchestrator.py:349`), restart included,
  since from the outside it is still "one `extract-graph` invocation."

**3. Batch/file/chunk span** — one per unit of work dispatched into a thread
pool: `_process_batch` (Pass 1), `_process_file`/batch worker (Pass 2),
`_confirm_one`/`_process_group` (orphan connect). Parented via
`submit_with_context` (5.2) to the enclosing step span. Attributes drawn from
data the code already computes for the D55/D57 shard files —
`mykg.batch.index`, `mykg.batch.chunk_count`, `mykg.batch.source_files` — so
no new computation, just reuse.

**4. LLM-call span** — wraps `llm_complete_with_retry()`
(`src/mykg/llm/retry.py:87-127`), the single choke point every Pass 1/Pass
2/orphan/feedback/normalize-names call site already goes through. Populated
from the same data `record_llm_call()` (`logging.py:120-186`) already
gathers — no duplicate token/latency computation. Named and tagged per
[OpenTelemetry's GenAI semantic conventions](https://github.com/open-telemetry/semantic-conventions-genai)
(these are still evolving upstream — verify attribute names at
implementation time rather than trusting this doc as the final word):

```
gen_ai.system            = provider (anthropic|openai|gemini|ollama|openrouter|claude_cli|agent)
gen_ai.request.model     = model
gen_ai.usage.input_tokens
gen_ai.usage.output_tokens
mykg.llm.context_label   = the existing context_label string (e.g. "pass1 batch 3/12")
mykg.llm.cache_read_tokens / mykg.llm.cache_creation_tokens
```

On failure (context-overflow, rate-limit exhaustion), `span.record_exception(e)`
+ `span.set_status(Status(StatusCode.ERROR))`, mirroring the existing
`status_code`/`error` fields already written to `llm.log`.

### 5.4 HTTP auto-instrumentation (optional layer)

`opentelemetry-instrumentation-httpx`, instrumented conditionally in
`setup_tracing()` only when `OTEL_ENABLED` and the package is importable.
Covers the 5 HTTP/SDK-based adapters (anthropic, openai, gemini, ollama,
openrouter — all transitively use `httpx`/`httpcore`, already log-silenced in
`logging.py:61`). Gives DNS/TLS/request-response spans nested under the
manual LLM-call span, for free, no adapter code changes.

`claude_cli` (a `claude -p` subprocess) and `agent` adapters are not HTTP
calls — no auto-instrumentation applies. They still get the manual LLM-call
span from 5.3; that span simply has no HTTP child.

### 5.5 Configuration

New `otel:` block, added to **both** `mykg_config.yaml` (repo root) and
`src/mykg/data/mykg_config.yaml` (packaging template) per Invariant 17:

```yaml
otel:
  enabled: false                              # master toggle
  exporter_endpoint: "http://localhost:4317"  # OTLP gRPC endpoint
  service_name: mykg
```

Exposed in `config.py` following the exact `LOG_CAPTURE_PROMPTS` /
`ERROR_GATE_ENABLED` pattern (`_get_opt("otel", "enabled", False)`, etc.) —
named constants, no inline literals downstream (Invariant 7):

```python
OTEL_ENABLED: bool
OTEL_EXPORTER_OTLP_ENDPOINT: str
OTEL_SERVICE_NAME: str
```

CLI gets a `--otel` flag on `extract-graph` (and `merge-graphs`), mirroring
the existing `--obsidian-vault`/`--neo4j-csv` runtime-toggle pattern
(`cli.py:1073-1081`):

```python
if otel:
    import mykg.config as _config_mod
    _config_mod.OTEL_ENABLED = True
```

`setup_tracing()` is called once, immediately after `logging.setup()`, in
`extract_graph()`/`merge_graphs()` — same call-site shape as today's logging
setup.

### 5.6 Dependencies

New **optional** extras group in `pyproject.toml` — not a core dependency,
since tracing is opt-in and the SDK/exporter packages (~a few MB, no heavy
transitive deps like MinerU's venv) shouldn't burden users who never enable
it:

```toml
[project.optional-dependencies]
otel = [
    "opentelemetry-api>=1.27",
    "opentelemetry-sdk>=1.27",
    "opentelemetry-exporter-otlp-proto-grpc>=1.27",
    "opentelemetry-instrumentation-httpx>=0.48b0",
]
```

`tracing.py` imports these lazily (inside `setup_tracing()`, guarded by
`try/except ImportError` with a clear error message pointing at
`pip install mykg[otel]`) so importing `mykg.tracing` itself never fails for
users who haven't installed the extra — mirroring how `mineru`/MinerU support
is fully decoupled (D48) rather than a hard dependency.

### 5.7 Local dev stack

A `docker-compose.otel.yml` at the repo root running Jaeger's all-in-one
image:

```yaml
services:
  jaeger:
    image: jaegertracing/all-in-one:1.60
    ports:
      - "4317:4317"   # OTLP gRPC receiver
      - "16686:16686" # Jaeger UI
```

Workflow: `docker compose -f docker-compose.otel.yml up -d`, then
`mykg extract-graph <dir> --otel`, then open `http://localhost:16686` and
search for the `mykg` service to see the run's waterfall.

## 6. `PipelineContext` impact

**No new required field.** Spans are tracked via OTel's own
context-propagation machinery (`contextvars`, transparently managed by
`start_as_current_span`), not by threading a span object through `ctx`
manually. This avoids adding another `Any`-typed field to the Pydantic
`PipelineContext` model (which already has to special-case `adapter: Any` and
`error_gate: Any = None` to dodge circular imports, `orchestrator.py:53-54`)
and keeps tracing fully orthogonal to pipeline state — a step function does
not need `ctx` to know what span it's in; `tracer.start_as_current_span(...)`
inside that function attaches to whatever the ambient context already is.

## 7. Failure modes

- **Collector unreachable** (Jaeger not running, wrong endpoint): the
  `BatchSpanProcessor` exporter fails silently in the background per OTel SDK
  default behavior (logs a one-line warning via the `opentelemetry` logger,
  already suppressed the same way `httpx` is in `logging.py:61` if desired) —
  it never raises into pipeline code and never blocks a step. This must be
  verified in testing (§9) since a badly-behaved exporter blocking the
  critical path would be worse than no tracing at all.
- **`OTEL_ENABLED=false`**: `tracing.py` skips SDK setup entirely; every
  `get_tracer()` call returns OTel's default no-op tracer. Zero dependency
  import, zero background thread, zero measurable overhead.
- **`mykg[otel]` extras not installed but `--otel` passed**: `setup_tracing()`
  raises a `ClickException` with the `pip install mykg[otel]` remediation,
  caught at the same level `cli.py` already handles other precondition
  errors (e.g. missing `--base-schema` file).

## 8. What this does *not* change

- `orchestrator.py`'s retry/feedback control flow — spans observe it, they
  don't alter attempt counts, timing, or the `SchemaUpdatedError` restart
  behavior.
- Any of the 7 adapters' `complete()` implementations, beyond adding the
  LLM-call span wrapper at the `llm_complete_with_retry` choke point (5.3) —
  no per-adapter code duplication.
- `llm.log`, `run.log`, or any D16 intermediate file format.
- Any existing config key, CLI flag, or output file.

## 9. Testing approach

- Unit test `submit_with_context()` in isolation: assert a span started in
  the main thread is the parent of a span started inside the submitted
  function (using an in-memory `InMemorySpanExporter` from
  `opentelemetry-sdk`'s test utilities — no real collector needed).
- Unit test `setup_tracing()` no-op path: `OTEL_ENABLED=false` → confirm no
  `opentelemetry.sdk` import side effects occur and `get_tracer()` doesn't
  raise.
- Integration test: run a tiny fixture corpus through `extract-graph --otel`
  against an `InMemorySpanExporter` swapped in via a test-only config
  override; assert the expected span tree shape (1 run span → 12 step spans
  → N batch spans → M LLM-call spans) and that `SchemaUpdatedError` produces
  an event, not an error span, on a fixture designed to trigger it.
- Manual e2e: `docker compose -f docker-compose.otel.yml up -d`, run a real
  small corpus with `--otel`, visually confirm the waterfall in Jaeger's UI
  looks like the pipeline's actual structure (steps in order, batches
  parallel within a step, LLM calls parallel within a batch).

## 10. Rollout scope (v1)

Full instrumentation from the start, per user decision: run + step +
batch/chunk + LLM-call spans, context propagation applied at all 8 executor
sites, HTTP auto-instrumentation for the 5 SDK-based adapters. No phased
fast-follow — the four span levels are cheap to add together since they all
reuse the same `submit_with_context`/`get_tracer` primitives, and a
half-instrumented pipeline (e.g. steps but no LLM calls) would hide exactly
the kind of stuck-batch scenario (D57) that motivated this work.

## 11. Open questions for reviewer

1. **GenAI semantic convention names** — flagged in §5.3 as "verify at
   implementation time." The upstream spec has moved repos recently; worth a
   final check against `open-telemetry/semantic-conventions-genai` before
   writing the attribute-setting code, not before final review of this doc.
2. **Retention/volume** — no sampling is proposed for v1 (every span is
   exported). For a 3000-batch Pass 2 run (the D57 production case), this is
   ~3000+ batch spans and however many thousand LLM-call spans in one trace.
   Confirm this is acceptable for the intended Jaeger-via-Docker local setup,
   or whether a `BatchSpanProcessor` queue-size/export-batch-size tuning note
   belongs in the config block. Sampling can be added later without
   restructuring anything above.
3. **`merge-graphs`** — this design covers `extract-graph` fully; the same
   `run(MERGE_STEPS, ctx)` wrapping applies directly to `merge-graphs` (same
   orchestrator, different step list) with no additional design needed, but
   confirm that's an acceptable "covered by extension" rather than requiring
   its own section.
