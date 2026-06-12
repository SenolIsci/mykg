from __future__ import annotations


def test_fetch_config_constants_exist_with_defaults() -> None:
    from mykg import config
    # Constants exist and have the documented default types/values.
    assert isinstance(config.FETCH_ENABLED, bool)
    assert config.FETCH_STRATEGY in ("same-domain", "same-origin", "all")
    assert isinstance(config.FETCH_MAX_PAGES, int) and config.FETCH_MAX_PAGES > 0
    assert isinstance(config.FETCH_MAX_DEPTH, int)
    assert isinstance(config.FETCH_RESPECT_ROBOTS, bool)
    assert isinstance(config.FETCH_REQUEST_DELAY_SECONDS, float)
    assert isinstance(config.FETCH_CONCURRENCY, int)
    assert isinstance(config.FETCH_DOWNLOAD_ASSETS, bool)
    assert isinstance(config.FETCH_TIMEOUT_SECONDS, int)
    assert isinstance(config.FETCH_UV_PATH, str)
    assert isinstance(config.FETCH_UV_PYTHON_VERSION, str)
    assert "crawlee" in config.FETCH_CRAWLEE_SPEC
    assert isinstance(config.FETCH_INSTALL_TIMEOUT_SECONDS, int)
