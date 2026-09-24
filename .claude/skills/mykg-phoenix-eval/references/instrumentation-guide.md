# Writing OTel instrumentation into a project that has none (or partial)

Read this only after the Phase A plan (SKILL.md) has been presented to the
user and approved. This is the "how to actually write it" mechanics —
Phase A's job was deciding *what* spans to add; this file is about
implementing that decision correctly, using patterns already proven working
in mykg's own `src/mykg/tracing.py` (verified live against a real Phoenix
instance — this isn't theoretical).

## Follow the target project's own conventions first

Before writing anything, check what the project already does for
comparable cross-cutting concerns — logging setup is the closest analog to
tracing setup, and usually already exists. If there's a `logging.py` with a
`setup()` function and a `get(name)` factory, mirror that shape for
`tracing.py` (a `setup_tracing()` + `get_tracer()` pair, called from the
same place logging setup is called). If nothing comparable exists, keep the
new module self-contained rather than inventing a project-wide convention
nobody asked for.

## The module template (`tracing.py`)

```python
"""OTel tracing setup, mirroring how logging.py centralizes logging setup:
a module-level singleton, configured once per process via setup_tracing(),
read thereafter via get_tracer()."""

from __future__ import annotations

import contextvars
import logging as _stdlib_logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

import myproject.config as config  # however this project reads its own config

_log = _stdlib_logging.getLogger("myproject.tracing")
_TRACER_NAME = "myproject"
_T = TypeVar("_T")


def submit_with_context(
    executor: ThreadPoolExecutor, fn: Callable[..., _T], *args: Any, **kwargs: Any
) -> "Future[_T]":
    """Drop-in replacement for executor.submit(fn, *args, **kwargs) that
    propagates the calling thread's contextvars.Context -- including the
    active OTel span context -- into the worker thread. ThreadPoolExecutor
    does not do this for you (unlike asyncio.create_task)."""
    ctx = contextvars.copy_context()
    return executor.submit(ctx.run, fn, *args, **kwargs)


def mark_span_error(span, message: str | None = None) -> None:
    """Set ERROR status on a span, optionally recording a message."""
    from opentelemetry.trace import Status, StatusCode
    span.set_status(Status(StatusCode.ERROR))
    if message is not None:
        span.set_attribute("myproject.error", message)


def get_tracer():
    """Safe to call whether or not setup_tracing() has run -- returns a
    no-op tracer in that case, via OTel's own default provider."""
    from opentelemetry import trace
    return trace.get_tracer(_TRACER_NAME)


class OtelSpanLogHandler(_stdlib_logging.Handler):
    """Bridges standard-library `logging` WARNING+/exception records onto
    the currently active OTel span, as span events.

    Phoenix (and most trace backends) ingest traces only, not a separate
    OTel *logs* signal -- confirmed for Phoenix specifically via its own
    open GitHub issue (Arize-ai/phoenix#10624). opentelemetry-instrumentation-
    logging's LoggingInstrumentor does NOT solve this even though it sounds
    like it should: its set_logging_format/inject_trace_context options only
    stamp trace_id/span_id text into the log record for correlation with an
    *external* log store, and its log_hook extension point only fires once a
    full OTel Logs SDK pipeline (a separate LoggerProvider) is configured --
    which most projects, including this pattern, deliberately skip, since
    Phoenix couldn't read it anyway. So getting a log line to show up next
    to the span that produced it requires this: a plain logging.Handler that
    calls span.add_event()/span.record_exception() directly.

    Filtered to WARNING+ at attach time -- mirroring every INFO-level
    progress line onto spans buries the signal (retries, validation
    failures, degraded-mode fallbacks) under routine noise.
    """

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            return  # no active span, or a no-op provider -- nothing to attach to
        try:
            if record.exc_info:
                span.record_exception(record.exc_info[1] or Exception(record.getMessage()))
            span.add_event(
                "log",
                attributes={
                    "log.level": record.levelname,
                    "log.logger": record.name,
                    "log.message": record.getMessage(),
                },
            )
        except Exception:
            # A logging handler must never raise -- that breaks logging
            # itself for the rest of the process, not just tracing.
            self.handleError(record)


def setup_tracing(**resource_attrs) -> None:
    """Configure the global TracerProvider. No-op when tracing is disabled
    in config. Call exactly once, at the real entry point, before the
    orchestrator/pipeline runs."""
    if not config.OTEL_ENABLED:
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Tracing is enabled but the optional OTel SDK/exporter packages "
            "are not installed. Install the project's [otel] extra."
        ) from exc

    resource = Resource.create({"service.name": config.OTEL_SERVICE_NAME, **resource_attrs})
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=config.OTEL_EXPORTER_OTLP_ENDPOINT)
    if config.OTEL_SYNC_EXPORT:
        # Blocking -- every span exports synchronously the instant it
        # closes. Local debugging only; adds real network latency to every
        # traced call. Never the default for a run whose wall-clock time
        # matters (Phoenix's own docs make the same recommendation).
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        # Async, non-blocking -- the correct default. Tuned below OTel's own
        # defaults (5000ms schedule delay, 512-span batch) so short-lived
        # spans reach the collector within ~1s of finishing rather than up
        # to 5s, without giving up the non-blocking guarantee. This does NOT
        # make long-running spans (a whole pipeline run, a whole step)
        # appear before they finish -- see the "streaming" note below.
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                schedule_delay_millis=config.OTEL_SCHEDULE_DELAY_MILLIS,
                max_export_batch_size=config.OTEL_MAX_EXPORT_BATCH_SIZE,
            )
        )
    trace.set_tracer_provider(provider)

    # Optional: auto-instrument HTTP/provider SDKs if their packages are
    # present -- e.g. opentelemetry-instrumentation-httpx for generic HTTP,
    # openinference-instrumentation-openai for prompt/completion capture on
    # OpenAI calls specifically. Each is independently optional -- try/except
    # ImportError per instrumentor, don't let a missing one block the rest.

    if config.OTEL_LOG_TO_SPAN_EVENTS:
        _stdlib_logging.getLogger().addHandler(
            OtelSpanLogHandler(level=_stdlib_logging.WARNING)
        )

    _log.info("OTel tracing enabled: exporting to %s", config.OTEL_EXPORTER_OTLP_ENDPOINT)
```

## Streaming spans live, not just at the end of the run

A natural first request once tracing exists is "I want to see spans in the
UI as they happen, not wait for the whole run to finish." Two separate
things determine that, and only one of them is a processor setting:

1. **Export scheduling** -- `BatchSpanProcessor` queues finished spans and
   flushes on a timer (`schedule_delay_millis`) or when the queue fills
   (`max_export_batch_size`). Lowering both (as above) gets a *finished*
   span to the collector faster. `SimpleSpanProcessor` exports every span
   the instant it finishes, synchronously -- fastest possible, but blocks
   the traced code path on network I/O, so it's a debug-only trade, never a
   production default.
2. **When a span finishes at all** -- this is the part export-tuning cannot
   touch. A span is one record spanning `[start_time, end_time]`; nothing
   goes to any exporter until the `with tracer.start_as_current_span(...):`
   block that owns it exits. A span wrapping an entire pipeline run, or an
   entire multi-minute step, will only ever appear once that run or step
   finishes -- full stop, regardless of processor. If "I want to see it as
   it happens" is the actual goal, the answer is architectural, not a
   config knob: make sure there's a *unit-of-work* span layer underneath
   the long-running one (see Step 2 in SKILL.md's Phase A -- "a
   unit-of-work span inside any parallelized/looped stage") and point the
   user at watching *those* in the live trace view, since each one closes
   (and therefore can stream) as soon as its single item of work is done,
   well before the parent step/run span does. Say this explicitly when
   proposing spans for a new project -- a plan with only a run-level and a
   step-level span, no unit-of-work layer, will look "silent" in Phoenix's
   UI for the entire duration of a long step even with the fastest
   possible export settings, and that's worth flagging as a gap in the
   proposal itself rather than something to discover after the user asks
   why nothing is showing up.

## The core-dependency trap (verified real bug, not hypothetical)

`opentelemetry-api` ships built-in no-op implementations by design — it's
meant to be always importable, even when nothing is actually configured to
export anywhere. If `get_tracer()` (or anything importing `opentelemetry`)
is only reachable when the optional SDK/exporter extras are installed, then
importing the module that calls `get_tracer()` at module load time (a very
natural pattern — see below) breaks the **entire project**, not just
tracing, for anyone who hasn't installed the heavier optional pieces.

This is exactly what happened building mykg's own tracing: `orchestrator.py`
(imported by every single CLI command) did `_tracer = get_tracer()` at
module level, and `get_tracer()` unconditionally did `from opentelemetry
import trace` inside its body — fine as long as `opentelemetry-api` was
installed, but there was no guarantee of that since the plan had put it in
the same optional extras group as the heavier `opentelemetry-sdk`/exporter
packages. **The fix: put `opentelemetry-api` itself in the project's core
dependencies, not the optional extras group** — it's tiny, adds no real
weight, and its whole purpose is safe unconditional importability. Keep
only `opentelemetry-sdk`, the exporter, and any auto-instrumentation
packages (the things that actually *do* something with the API, and pull in
real weight) in the optional extras.

**Verify this, don't just implement it and assume it's fine**: simulate the
"extras not installed" case before calling the work done —

```python
import builtins
_orig_import = builtins.__import__
def blocked(name, *a, **k):
    if name.startswith("opentelemetry.sdk") or name.startswith("opentelemetry.exporter"):
        raise ImportError(f"simulated: {name} not installed")
    return _orig_import(name, *a, **k)
builtins.__import__ = blocked

import myproject.orchestrator  # or whatever imports tracing.py at module load
print("still imports fine without the SDK/exporter extras")
```
If this raises, the module boundary is wrong — `opentelemetry-api` needs to
move (or the offending module needs to defer its `get_tracer()` call past
import time).

## Context propagation across thread pools — the second real bug class

Every `ThreadPoolExecutor.submit(fn, *args)` call site in the pipeline that
does parallel work needs `submit_with_context(executor, fn, *args)` instead
— found and fixed at all such sites in mykg by grepping
`\.submit\(` across the codebase and checking each one. Add a regression
test that greps for bare `.submit(` calls outside `submit_with_context` in
the relevant files, so a *future* parallel-dispatch site added without this
doesn't silently reintroduce the bug:

```python
def test_no_bare_executor_submit():
    import re
    from pathlib import Path
    offenders = []
    for path in PARALLEL_DISPATCH_FILES:  # the files with .submit( calls
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if ".submit(" in line and "submit_with_context" not in line:
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "\n".join(offenders)
```

## Testing what you built

Use an in-memory span exporter, not "ran without crashing," as the bar for
done. The one non-obvious wrinkle: `opentelemetry.trace.set_tracer_provider()`
is a **process-wide set-once operation** — every call after the first is
silently ignored, which breaks naive per-test isolation if each test tries
to install its own `TracerProvider`. The working pattern (verified,
used throughout mykg's own test suite):

```python
import pytest

@pytest.fixture
def span_exporter():
    """Install exactly one real TracerProvider the first time this fixture
    runs (every already-cached tracer in the process forwards to it, since
    get_tracer() returns a ProxyTracer resolved at span-creation time, not
    at import time). On every test, swap in a fresh InMemorySpanExporter as
    that provider's only processor, so tests don't see each other's spans."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider(resource=Resource.create({"service.name": "test"}))
        trace.set_tracer_provider(provider)

    exporter = InMemorySpanExporter()
    old = list(provider._active_span_processor._span_processors)
    provider._active_span_processor._span_processors = (SimpleSpanProcessor(exporter),)
    yield exporter
    provider._active_span_processor._span_processors = tuple(old)
    exporter.clear()
```
This reaches into a private attribute (`_active_span_processor`) — there is
no public API for swapping processors on an existing provider, and this is
the standard workaround. Verified working across dozens of tests in mykg's
own suite, in any order, with zero cross-test contamination.

Then assert real structure, not just "no exception":
```python
def test_step_span_created_for_successful_step(span_exporter):
    run_the_pipeline_step()
    spans = span_exporter.get_finished_spans()
    step_spans = [s for s in spans if s.name == "myproject.step.whatever"]
    assert len(step_spans) == 1
    assert step_spans[0].attributes["myproject.step.name"] == "whatever"
```
And for the propagation fix specifically, prove nesting, not just presence:
```python
def test_submit_with_context_propagates_span_parent(span_exporter):
    tracer = get_tracer()
    def worker():
        with tracer.start_as_current_span("child"):
            pass
    with tracer.start_as_current_span("parent"):
        with ThreadPoolExecutor(max_workers=1) as ex:
            submit_with_context(ex, worker).result()
    spans = {s.name: s for s in span_exporter.get_finished_spans()}
    assert spans["child"].parent.span_id == spans["parent"].context.span_id
```
This is the one test that actually distinguishes "the propagation fix
works" from "it looks like it should work" — a broken version of
`submit_with_context` produces spans with no visible error, just a wrong
(or missing) parent, so this assertion is the only thing standing between
"looks done" and "is done."

Test the log-bridge handler the same way — attach it directly to a throwaway
logger rather than going through the real `logging.setup()`/`setup_tracing()`
call chain, so the test doesn't depend on the target project's own logging
config:
```python
def test_otel_span_log_handler_adds_event_to_active_span(span_exporter):
    import logging
    logger = logging.getLogger("test.otel_span_log_handler")
    logger.setLevel(logging.WARNING)
    handler = OtelSpanLogHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("traced-step"):
            logger.warning("something looked off")
    finally:
        logger.removeHandler(handler)

    spans = span_exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "traced-step")
    log_events = [e for e in step_span.events if e.name == "log"]
    assert len(log_events) == 1
    assert log_events[0].attributes["log.level"] == "WARNING"
```
And that `logger.exception(...)` produces a `record_exception`-shaped event,
not just a `log` one — this is the assertion that actually distinguishes
"exceptions get the richer OTel exception semantic-convention attributes"
from "exceptions just look like any other warning":
```python
def test_otel_span_log_handler_records_exception(span_exporter):
    import logging
    logger = logging.getLogger("test.otel_span_log_handler_exc")
    logger.setLevel(logging.WARNING)
    handler = OtelSpanLogHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("traced-step-with-error"):
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("blew up")
    finally:
        logger.removeHandler(handler)

    spans = span_exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "traced-step-with-error")
    exc_events = [e for e in step_span.events if e.name == "exception"]
    assert exc_events[0].attributes["exception.type"] == "ValueError"
```

For the processor-selection branch in `setup_tracing()`, a test only needs
to prove the `sync_export: true` path constructs without raising (the
in-memory `span_exporter` fixture above already forces a specific processor
for test isolation, so asserting *which* processor `setup_tracing()`
installed in production would require reaching into the same private
`_active_span_processor` attribute for no real benefit) — the goal is
catching an import or argument-shape error in the branch, not re-testing
`SimpleSpanProcessor` itself.
