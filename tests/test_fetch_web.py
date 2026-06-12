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


def test_default_output_dir_uses_seed_domain(tmp_path) -> None:
    from mykg.fetch_web import default_output_dir
    out = default_output_dir("https://example.com/docs/guide", base=tmp_path)
    assert out == tmp_path / "fetched_web" / "example.com"


def test_build_crawl_config_reflects_overrides() -> None:
    from mykg.fetch_web import build_crawl_config
    cfg = build_crawl_config(
        seed_url="https://example.com",
        output_dir="/tmp/fw",
        strategy="same-origin",
        max_pages=42,
        max_depth=3,
        respect_robots=False,
        request_delay_seconds=1.0,
        concurrency=2,
        allowed_asset_exts=[".pdf"],
    )
    assert cfg["seed_url"] == "https://example.com"
    assert cfg["strategy"] == "same-origin"
    assert cfg["max_pages"] == 42
    assert cfg["respect_robots"] is False
    assert cfg["allowed_asset_exts"] == [".pdf"]


def test_local_path_for_url_html_and_query() -> None:
    from mykg.fetch_web import local_path_for_url
    # Trailing-slash path → index.html
    assert local_path_for_url("https://example.com/", "text/html") == "index.html"
    # Nested path preserved
    assert local_path_for_url("https://example.com/a/b", "text/html") == "a/b.html"
    # Query string is hashed into the name (deterministic, collision-safe)
    p = local_path_for_url("https://example.com/a?x=1", "text/html")
    assert p.startswith("a") and p.endswith(".html") and p != "a.html"
    # Non-html keeps its own extension
    assert local_path_for_url("https://example.com/g.pdf", "application/pdf") == "g.pdf"


def test_manifest_merge_and_atomic_write(tmp_path) -> None:
    from mykg.fetch_web import load_manifest, write_manifest
    out = tmp_path / "fw"
    out.mkdir()
    # No prior manifest → empty pages
    assert load_manifest(out) == {}
    rows = {
        "https://example.com/": {
            "local_file": "index.html", "sha256": "abc",
            "content_type": "text/html", "status": 200, "depth": 0,
            "fetched_at": "2026-06-12T00:00:00Z",
        }
    }
    write_manifest(out, seed_url="https://example.com", strategy="same-domain",
                   pages=rows, stats={"pages": 1, "assets": 0,
                                      "skipped_robots": 0, "errors": 0})
    loaded = load_manifest(out)
    assert "https://example.com/" in loaded
    assert (out / "fetch_manifest.json").exists()


def test_already_fetched_skips_matching_sha() -> None:
    from mykg.fetch_web import is_already_fetched
    prior = {"https://example.com/": {"sha256": "abc"}}
    assert is_already_fetched(prior, "https://example.com/", "abc") is True
    assert is_already_fetched(prior, "https://example.com/", "xyz") is False
    assert is_already_fetched(prior, "https://example.com/new", "abc") is False
