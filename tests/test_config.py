def test_otel_config_constants_exist():
    import mykg.config as config

    assert isinstance(config.OTEL_ENABLED, bool)
    assert isinstance(config.OTEL_EXPORTER_OTLP_ENDPOINT, str)
    assert isinstance(config.OTEL_SERVICE_NAME, str)
    assert isinstance(config.OTEL_PROJECT_NAME, str)
    assert config.OTEL_ENABLED is False  # shipped default
    assert config.OTEL_EXPORTER_OTLP_ENDPOINT == "http://localhost:4317"
    assert config.OTEL_SERVICE_NAME == "mykg"
    assert config.OTEL_PROJECT_NAME == "mykg"  # defaults to OTEL_SERVICE_NAME

    assert isinstance(config.OTEL_SYNC_EXPORT, bool)
    assert isinstance(config.OTEL_SCHEDULE_DELAY_MILLIS, int)
    assert isinstance(config.OTEL_MAX_EXPORT_BATCH_SIZE, int)
    assert isinstance(config.OTEL_LOG_TO_SPAN_EVENTS, bool)
    assert config.OTEL_SYNC_EXPORT is False  # shipped default — async BatchSpanProcessor
    assert config.OTEL_SCHEDULE_DELAY_MILLIS == 1000  # tuned below OTel's 5000ms default
    assert config.OTEL_MAX_EXPORT_BATCH_SIZE == 64  # tuned below OTel's 512 default
    assert config.OTEL_LOG_TO_SPAN_EVENTS is True  # shipped default — log->span bridge on
