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


def test_fetch_block_present_in_both_yaml_files() -> None:
    """Invariant 17: the fetch: block exists in every profile of both YAMLs."""
    import yaml
    from pathlib import Path
    import mykg

    pkg_dir = Path(mykg.__file__).parent
    repo_root = pkg_dir.parent.parent
    runtime = repo_root / "mykg_config.yaml"
    packaged = pkg_dir / "data" / "mykg_config.yaml"

    for cfg_path in (runtime, packaged):
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        profiles = raw.get("profiles", {})
        assert profiles, f"no profiles in {cfg_path}"
        for name, prof in profiles.items():
            pipeline = prof.get("pipeline", {})
            assert "fetch" in pipeline, f"fetch block missing in {cfg_path} profile {name}"
            fetch = pipeline["fetch"]
            for key in ("enabled", "strategy", "max_pages", "max_depth",
                        "respect_robots", "request_delay_seconds", "concurrency",
                        "download_assets", "timeout_seconds", "uv_path",
                        "uv_python_version", "crawlee_spec", "install_timeout_seconds"):
                assert key in fetch, f"fetch.{key} missing in {cfg_path} profile {name}"
