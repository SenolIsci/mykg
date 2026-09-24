"""OpenTelemetry tracing setup for mykg pipeline runs.

Centralizes OTel SDK configuration, mirroring how logging.py centralizes
logging setup: a module-level singleton, configured once per process via
setup_tracing(), read thereafter via get_tracer().

Tracing is fully opt-in (config.OTEL_ENABLED). When disabled, get_tracer()
still works — it returns a tracer backed by OTel's built-in no-op provider,
so callers never need to branch on whether tracing is on.
"""

from __future__ import annotations

import contextvars
import logging as _stdlib_logging
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable, TypeVar

import mykg.config as config

_log = _stdlib_logging.getLogger("mykg.tracing")

_TRACER_NAME = "mykg"

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


def mark_span_error(span, message: str | None = None) -> None:
    """Set ERROR status on a span, optionally recording a message attribute.

    opentelemetry-api is a core mykg dependency (it ships built-in no-op
    implementations and adds no real weight), so Status/StatusCode are
    always importable here regardless of whether the mykg[otel] extra
    (the SDK/exporter packages that do something with the API) is
    installed.
    """
    from opentelemetry.trace import Status, StatusCode

    span.set_status(Status(StatusCode.ERROR))
    if message is not None:
        span.set_attribute("mykg.error", message)


def get_tracer():
    """Return the mykg tracer. Safe to call whether or not setup_tracing()
    has run, and whether or not tracing is enabled — returns a no-op
    tracer in both of those cases."""
    from opentelemetry import trace

    return trace.get_tracer(_TRACER_NAME)


class OtelSpanLogHandler(_stdlib_logging.Handler):
    """Bridges standard-library `logging` records onto the currently active
    OTel span, as span events (or recorded exceptions).

    Phoenix has no native OTel-logs ingestion — it accepts traces (OTLP)
    only, confirmed via Phoenix's own open GitHub issue (Arize-ai/phoenix
    #10624, "OTEL Logging Instrumentation support"), which is still
    unresolved. `opentelemetry-instrumentation-logging`'s LoggingInstrumentor
    (already wired below, see set_logging_format=False/
    inject_trace_context=True) only stamps otelTraceID/otelSpanID text into
    the log record for correlation in an external log store — it does not
    attach anything to the span itself, and its `log_hook` extension point
    only fires when a full OTel *Logs* SDK pipeline (a separate
    LoggerProvider) is configured, which mykg deliberately doesn't set up
    (a second signal pipeline Phoenix couldn't read anyway). So a log line
    showing up next to the span that produced it requires this: a plain
    logging.Handler that calls span.add_event()/span.record_exception()
    directly on whatever span is active when the record is emitted.

    Filtered to WARNING+ by the level passed at attach time — every step
    already logs INFO-level progress lines, and mirroring all of those onto
    spans would bury the signal (retries, validation errors, schema-gap
    restarts) this exists to surface under noise.
    """

    def emit(self, record: _stdlib_logging.LogRecord) -> None:
        from opentelemetry import trace

        span = trace.get_current_span()
        if span is None or not span.is_recording():
            # No active span (e.g. a log line outside any traced step), or
            # tracing is a no-op provider — nothing to attach to.
            return
        try:
            if record.exc_info:
                # record_exception captures type/message/stacktrace as a
                # single structured event, following OTel's own exception
                # semantic conventions — richer than a plain add_event for
                # anything logged via logger.exception()/logger.error(exc_info=True).
                span.record_exception(record.exc_info[1] or Exception(record.getMessage()))
            span.add_event(
                "log",
                attributes={
                    "log.level": record.levelname,
                    "log.logger": record.name,
                    "log.message": self.format(record) if self.formatter else record.getMessage(),
                },
            )
        except Exception:
            # A logging handler must never raise — that would break logging
            # itself for the rest of the process. Silently drop; this is a
            # secondary observability channel, not the log's primary sink
            # (the stdout/file handlers logging.setup() already installed).
            self.handleError(record)


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
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
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
    if config.OTEL_SYNC_EXPORT:
        # Blocking: exports each span synchronously the instant it closes.
        # Every traced call (LLM call, batch, file) pays network latency to
        # the collector inline — only for local debugging sessions where
        # seeing a span the moment it ends matters more than pipeline speed.
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    else:
        # Async, non-blocking (production-safe per OTel/Phoenix's own
        # guidance). Tuned below OTel's defaults (5000ms delay, 512-span
        # batch) so short-lived spans — mykg.pass1.batch, mykg.pass2.batch,
        # mykg.llm.call, and their ChatCompletion children — land in Phoenix
        # within ~1s of completing instead of ~5s, without giving up the
        # non-blocking guarantee. This does NOT make long-running spans
        # (mykg.step.pass1, mykg.extract_graph.run) appear before they
        # finish — a span is a single record covering [start, end], and
        # nothing is sent to the exporter until end_span() closes it,
        # regardless of processor. Only child spans that finish earlier
        # (batches, files, LLM calls) benefit from faster scheduling.
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                schedule_delay_millis=config.OTEL_SCHEDULE_DELAY_MILLIS,
                max_export_batch_size=config.OTEL_MAX_EXPORT_BATCH_SIZE,
            )
        )
    trace.set_tracer_provider(provider)

    if config.OTEL_LOG_TO_SPAN_EVENTS:
        root = _stdlib_logging.getLogger()
        handler = OtelSpanLogHandler(level=_stdlib_logging.WARNING)
        root.addHandler(handler)

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        HTTPXClientInstrumentor().instrument()
    except ImportError:
        _log.debug(
            "opentelemetry-instrumentation-httpx not installed; "
            "HTTP-level auto-instrumentation skipped."
        )

    try:
        from openinference.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
    except ImportError:
        _log.debug(
            "openinference-instrumentation-openai not installed; "
            "OpenAI prompt/completion capture skipped."
        )

    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        # set_logging_format=False + inject_trace_context=True: attach
        # otelTraceID/otelSpanID/otelServiceName/otelTraceSampled to every
        # LogRecord without touching mykg.logging's own format string or
        # handlers. set_logging_format=True (the instrumentor's default when
        # inject_trace_context is left unset) calls logging.basicConfig(),
        # which would silently override the colorized stdout + rotating
        # file handlers logging.setup() already installed.
        LoggingInstrumentor().instrument(
            set_logging_format=False, inject_trace_context=True
        )
    except ImportError:
        _log.debug(
            "opentelemetry-instrumentation-logging not installed; "
            "log records will not carry trace/span IDs."
        )

    _log.info(
        "OTel tracing enabled: exporting to %s", config.OTEL_EXPORTER_OTLP_ENDPOINT
    )
