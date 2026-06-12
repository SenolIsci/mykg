from __future__ import annotations

import pytest


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


def test_local_path_for_url_rejects_path_traversal() -> None:
    """CRITICAL: a hostile URL path must never escape the output dir."""
    from mykg.fetch_web import local_path_for_url
    # `..` segments are stripped; result stays inside output_dir.
    p = local_path_for_url("https://evil.com/../etc/passwd", "text/html")
    assert not p.startswith("..")
    assert "/../" not in p
    assert ".." not in p.split("/")
    assert p == "etc/passwd.html"


def test_local_path_for_url_strips_interior_dotdot() -> None:
    from mykg.fetch_web import local_path_for_url
    p = local_path_for_url("https://evil.com/a/../../b", "text/html")
    assert ".." not in p.split("/")
    assert not p.startswith("/")
    assert p == "a/b.html"


def test_local_path_for_url_only_dot_segments_falls_back_to_index() -> None:
    from mykg.fetch_web import local_path_for_url
    p = local_path_for_url("https://evil.com/../..", "text/html")
    assert ".." not in p.split("/")
    assert p == "index.html"


def test_local_path_for_url_no_silent_collision_on_stem_strip() -> None:
    """IMPORTANT: /foo and /foo.html must not map to the same file."""
    from mykg.fetch_web import local_path_for_url
    a = local_path_for_url("https://example.com/foo", "text/html")
    b = local_path_for_url("https://example.com/foo.html", "text/html")
    assert a != b
    assert a == "foo.html"


def test_local_path_for_url_plain_path_unchanged_by_collision_fix() -> None:
    """No dot in basename → no disambiguator fires (no regression)."""
    from mykg.fetch_web import local_path_for_url
    assert local_path_for_url("https://example.com/a/b", "text/html") == "a/b.html"


def test_default_output_dir_sanitizes_netloc(tmp_path) -> None:
    from mykg.fetch_web import default_output_dir
    out = default_output_dir("https://a@b:8080/", base=tmp_path)
    assert out == tmp_path / "fetched_web" / "b_8080"


def _load_runner_module():
    """Load data/_crawl_runner.py via importlib without importing crawlee."""
    import importlib.util
    from pathlib import Path
    import mykg

    runner = Path(mykg.__file__).parent / "data" / "_crawl_runner.py"
    spec = importlib.util.spec_from_file_location("_crawl_runner", runner)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_crawl_runner_module_imports_without_crawlee() -> None:
    """The runner must import cleanly even when crawlee is absent — crawlee
    is imported lazily inside the async crawl body, not at module top level."""
    import importlib.util
    from pathlib import Path
    import mykg

    runner = Path(mykg.__file__).parent / "data" / "_crawl_runner.py"
    spec = importlib.util.spec_from_file_location("_crawl_runner", runner)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # must not raise (no crawlee import at top)
    # Pure helper: sha256 of bytes
    assert mod.sha256_bytes(b"abc") == __import__("hashlib").sha256(b"abc").hexdigest()
    # Pure helper: write a page and return its row
    assert hasattr(mod, "save_page")


def test_crawl_runner_save_page_refuses_traversal_escape(tmp_path) -> None:
    """save_page must never write outside output_dir, even for a hostile URL."""
    mod = _load_runner_module()
    row = mod.save_page(
        tmp_path, "https://evil.com/../../etc/passwd", "text/html", b"x"
    )
    from pathlib import Path

    # The mirror strips ".." so the local_file is a contained relative path.
    assert ".." not in row["local_file"].split("/")
    written = (Path(tmp_path) / row["local_file"]).resolve()
    root = Path(tmp_path).resolve()
    # The file must exist and live strictly under tmp_path.
    assert written.exists()
    assert root == written or root in written.parents
    assert row["local_file"] == "etc/passwd.html"


def test_crawl_runner_local_path_parity_with_fetch_web() -> None:
    """The runner's mirror must match fetch_web.local_path_for_url exactly —
    parity guard so the duplicated logic can't silently drift."""
    mod = _load_runner_module()
    from mykg.fetch_web import local_path_for_url

    cases = [
        ("https://example.com/", "text/html"),
        ("https://example.com/a/b", "text/html"),
        ("https://example.com/g.pdf", "application/pdf"),
        ("https://example.com/foo.html", "text/html"),
        ("https://evil.com/../etc/passwd", "text/html"),
    ]
    for url, ctype in cases:
        assert mod._local_path_for_url(url, ctype) == local_path_for_url(
            url, ctype
        ), f"mirror drift for {url!r} ({ctype})"


def test_fetch_web_command_runs_runner_and_writes_manifest(tmp_path, monkeypatch) -> None:
    import json
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"

    # Fake the ephemeral venv: yield a fake python path without building anything.
    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"
        def __exit__(self, *a):
            return False

    # Fake subprocess.run for the runner: simulate the runner writing results.
    def fake_run(cmd, **kwargs):
        results = {
            "pages": {
                "https://example.com/": {
                    "local_file": "index.html", "sha256": "abc",
                    "content_type": "text/html", "status": 200, "depth": 0,
                    "fetched_at": "2026-06-12T00:00:00Z",
                }
            },
            "stats": {"pages": 1, "assets": 0, "skipped_robots": 0, "errors": 0},
        }
        (out / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock(); proc.returncode = 0
        return proc

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "https://example.com", "--output", str(out),
                  "--max-pages", "5"],
        )

    assert result.exit_code == 0, result.output
    manifest = json.loads((out / "fetch_manifest.json").read_text())
    assert "https://example.com/" in manifest["pages"]
    assert manifest["seed_url"] == "https://example.com"
    # Durable artifact stays; transient runner I/O files are cleaned up.
    assert (out / "fetch_manifest.json").exists()
    assert not (out / ".fetch_results.json").exists()
    assert not (out / ".fetch_config.json").exists()


def _fake_venv_and_run(out):
    """Shared mocks: a no-op ephemeral venv + a runner that writes results."""
    import json
    from unittest.mock import MagicMock

    class _FakeVenv:
        def __enter__(self):
            return out / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    def fake_run(cmd, **kwargs):
        results = {
            "pages": {
                "https://example.com/": {
                    "local_file": "index.html", "sha256": "abc",
                    "content_type": "text/html", "status": 200, "depth": 0,
                    "fetched_at": "2026-06-12T00:00:00Z",
                }
            },
            "stats": {"pages": 1, "assets": 0, "skipped_robots": 0, "errors": 0},
        }
        (out / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock(); proc.returncode = 0
        return proc

    return _FakeVenv(), fake_run


def test_fetch_web_verbose_flag_is_wired_and_succeeds(tmp_path) -> None:
    """Smoke test: -v enables DEBUG logging via setup() without crashing."""
    import json
    from unittest.mock import patch
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"
    fake_venv, fake_run = _fake_venv_and_run(out)

    with (
        patch("mykg.cli.ephemeral_venv", return_value=fake_venv),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
        patch("mykg.logging.setup") as mock_setup,
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "https://example.com", "--output", str(out),
                  "--max-pages", "5", "--verbose"],
        )

    assert result.exit_code == 0, result.output
    # setup() was invoked with verbose=True (parent-process DEBUG logging).
    mock_setup.assert_called_once()
    _, kwargs = mock_setup.call_args
    assert kwargs.get("verbose") is True
    assert (out / "fetch_manifest.json").exists()


@pytest.mark.live
def test_fetch_web_e2e_local_site(tmp_path) -> None:
    """End-to-end: serve a tiny 2-page site, crawl it for real (builds the
    crawlee venv), assert pages + manifest. Deselect with -m 'not live'."""
    import http.server, socketserver, threading, functools, json
    from click.testing import CliRunner
    from mykg.cli import cli

    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text(
        '<html><body><a href="/a.html">A</a></body></html>')
    (site / "a.html").write_text("<html><body><p>page a</p></body></html>")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as httpd:
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            out = tmp_path / "fw"
            result = CliRunner().invoke(cli, [
                "fetch-web", f"http://127.0.0.1:{port}/",
                "--output", str(out), "--max-pages", "10", "--no-robots",
            ])
            assert result.exit_code == 0, result.output
            manifest = json.loads((out / "fetch_manifest.json").read_text())
            assert manifest["stats"]["pages"] >= 1
            assert (out / "index.html").exists()
        finally:
            httpd.shutdown()
