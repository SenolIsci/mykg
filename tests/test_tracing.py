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


def test_setup_tracing_enabled_exports_spans(span_exporter):
    from mykg.tracing import get_tracer

    tracer = get_tracer()
    with tracer.start_as_current_span("test-span") as span:
        span.set_attribute("mykg.test", "value")

    spans = span_exporter.get_finished_spans()
    assert len(spans) == 1
    assert spans[0].name == "test-span"
    assert spans[0].attributes["mykg.test"] == "value"


def test_submit_with_context_propagates_span_parent(span_exporter):
    from concurrent.futures import ThreadPoolExecutor

    from mykg.tracing import get_tracer, submit_with_context

    tracer = get_tracer()

    def worker():
        with tracer.start_as_current_span("child-span"):
            pass

    with tracer.start_as_current_span("parent-span"):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = submit_with_context(executor, worker)
            future.result()

    spans = span_exporter.get_finished_spans()
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


def test_otel_span_log_handler_adds_event_to_active_span(span_exporter):
    import logging

    from mykg.tracing import OtelSpanLogHandler, get_tracer

    logger = logging.getLogger("mykg.test.otel_span_log_handler")
    logger.setLevel(logging.WARNING)
    handler = OtelSpanLogHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("traced-step"):
            logger.warning("something looked off in chunk 3")
    finally:
        logger.removeHandler(handler)

    spans = span_exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "traced-step")
    log_events = [e for e in step_span.events if e.name == "log"]
    assert len(log_events) == 1
    assert log_events[0].attributes["log.level"] == "WARNING"
    assert log_events[0].attributes["log.logger"] == "mykg.test.otel_span_log_handler"
    assert "something looked off in chunk 3" in log_events[0].attributes["log.message"]


def test_otel_span_log_handler_records_exception(span_exporter):
    import logging

    from mykg.tracing import OtelSpanLogHandler, get_tracer

    logger = logging.getLogger("mykg.test.otel_span_log_handler_exc")
    logger.setLevel(logging.WARNING)
    handler = OtelSpanLogHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        tracer = get_tracer()
        with tracer.start_as_current_span("traced-step-with-error"):
            try:
                raise ValueError("boom")
            except ValueError:
                logger.exception("chunk extraction blew up")
    finally:
        logger.removeHandler(handler)

    spans = span_exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "traced-step-with-error")
    exc_events = [e for e in step_span.events if e.name == "exception"]
    assert len(exc_events) == 1
    assert exc_events[0].attributes["exception.type"] == "ValueError"
    assert exc_events[0].attributes["exception.message"] == "boom"


def test_otel_span_log_handler_noop_without_active_span():
    import logging

    from mykg.tracing import OtelSpanLogHandler

    logger = logging.getLogger("mykg.test.otel_span_log_handler_no_span")
    logger.setLevel(logging.WARNING)
    handler = OtelSpanLogHandler(level=logging.WARNING)
    logger.addHandler(handler)
    try:
        # No active span (or a no-op provider) — must not raise.
        logger.warning("this has nowhere to attach")
    finally:
        logger.removeHandler(handler)


def test_setup_tracing_attaches_log_handler_when_enabled(monkeypatch, span_exporter):
    import logging

    import mykg.config as config
    from mykg.tracing import OtelSpanLogHandler, setup_tracing

    monkeypatch.setattr(config, "OTEL_ENABLED", True)
    monkeypatch.setattr(config, "OTEL_LOG_TO_SPAN_EVENTS", True)
    root = logging.getLogger()
    before = [h for h in root.handlers if isinstance(h, OtelSpanLogHandler)]
    for h in before:
        root.removeHandler(h)

    setup_tracing(session_name="test-session", profile="openai")

    after = [h for h in root.handlers if isinstance(h, OtelSpanLogHandler)]
    assert len(after) == 1
    root.removeHandler(after[0])


def test_setup_tracing_skips_log_handler_when_disabled(monkeypatch):
    import logging

    import mykg.config as config
    from mykg.tracing import OtelSpanLogHandler, setup_tracing

    monkeypatch.setattr(config, "OTEL_ENABLED", True)
    monkeypatch.setattr(config, "OTEL_LOG_TO_SPAN_EVENTS", False)
    root = logging.getLogger()
    before = [h for h in root.handlers if isinstance(h, OtelSpanLogHandler)]
    for h in before:
        root.removeHandler(h)

    setup_tracing(session_name="test-session", profile="openai")

    after = [h for h in root.handlers if isinstance(h, OtelSpanLogHandler)]
    assert len(after) == 0


def test_setup_tracing_uses_simple_span_processor_when_sync_export(monkeypatch):
    import mykg.config as config
    from mykg.tracing import setup_tracing

    monkeypatch.setattr(config, "OTEL_ENABLED", True)
    monkeypatch.setattr(config, "OTEL_SYNC_EXPORT", True)
    monkeypatch.setattr(config, "OTEL_LOG_TO_SPAN_EVENTS", False)

    # Must not raise — proves the SimpleSpanProcessor branch is reachable
    # and constructs cleanly. set_tracer_provider() is process-wide
    # set-once, so this doesn't assert which processor ends up active
    # (another test may have already installed a provider); it exists to
    # catch an import/argument error in that branch specifically.
    setup_tracing(session_name="test-session", profile="openai")
