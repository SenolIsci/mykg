from __future__ import annotations

import click
import pytest


def test_fetch_config_constants_exist_with_defaults() -> None:
    from mykg import config
    # Constants exist and have the documented default types/values.
    assert isinstance(config.FETCH_ENABLED, bool)
    assert config.FETCH_OUTPUT_DIR == "mykg_web_fetch"
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
    assert isinstance(config.FETCH_GITHUB_CLONE_ENABLED, bool)
    assert isinstance(config.FETCH_GITHUB_CLONE_DEPTH, int) and config.FETCH_GITHUB_CLONE_DEPTH > 0
    assert isinstance(config.FETCH_GITHUB_CLONE_TIMEOUT_SECONDS, int)
    assert config.FETCH_MAX_WORKERS == 2


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
            for key in ("enabled", "output_dir", "strategy", "max_pages", "max_depth",
                        "respect_robots", "request_delay_seconds", "concurrency",
                        "download_assets", "timeout_seconds", "uv_path",
                        "uv_python_version", "crawlee_spec", "install_timeout_seconds",
                        "github_clone_enabled", "github_clone_depth",
                        "github_clone_timeout_seconds", "max_workers"):
                assert key in fetch, f"fetch.{key} missing in {cfg_path} profile {name}"


def test_default_output_dir_uses_seed_domain(tmp_path) -> None:
    from mykg.fetch_web import default_output_dir
    out = default_output_dir("https://example.com/docs/guide", "mykg_web_fetch", base=tmp_path)
    assert out == tmp_path / "mykg_web_fetch" / "example.com"


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
    out = default_output_dir("https://a@b:8080/", "mykg_web_fetch", base=tmp_path)
    assert out == tmp_path / "mykg_web_fetch" / "b_8080"


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


def test_fetch_web_command_disabled_short_circuits(tmp_path, monkeypatch) -> None:
    """When fetch.enabled is false, the command exits with an error before
    creating the output directory or touching the ephemeral venv."""
    from click.testing import CliRunner
    from mykg import config as _cfg
    from mykg.cli import cli

    monkeypatch.setattr(_cfg, "FETCH_ENABLED", False)

    out = tmp_path / "fw"
    result = CliRunner().invoke(
        cli, ["fetch-web", "https://example.com", "--output", str(out)],
    )

    assert result.exit_code != 0
    assert "disabled" in result.output.lower()
    assert not out.exists()


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


def test_crawl_runner_asset_allowed_predicate() -> None:
    """Pure asset-allowlist decision: suffix in allowed → True; not in → False;
    empty allowed → always False (download_assets off skips everything)."""
    mod = _load_runner_module()
    allowed = {".pdf", ".png"}
    assert mod._asset_allowed("https://x.com/doc.pdf", allowed) is True
    assert mod._asset_allowed("https://x.com/path/IMG.PNG", allowed) is True  # case-insensitive
    assert mod._asset_allowed("https://x.com/style.css", allowed) is False
    assert mod._asset_allowed("https://x.com/doc.pdf?v=1", allowed) is True
    # Empty allowlist → nothing is allowed, regardless of suffix.
    assert mod._asset_allowed("https://x.com/doc.pdf", set()) is False
    # No extension at all → not in any allowlist.
    assert mod._asset_allowed("https://x.com/page", allowed) is False


def test_crawl_runner_should_skip_predicate() -> None:
    """Pure dedup/resume decision: url previously fetched AND content sha256
    unchanged → skip (True); new url, or unchanged url with a different sha
    (content changed since prior crawl) → process (False)."""
    mod = _load_runner_module()
    already = {"https://x.com/a": "deadbeef", "https://x.com/b": "cafef00d"}
    assert mod._should_skip("https://x.com/a", "deadbeef", already) is True
    assert mod._should_skip("https://x.com/b", "cafef00d", already) is True
    # Content changed since prior crawl → reprocess despite being "known".
    assert mod._should_skip("https://x.com/a", "newhash01", already) is False
    # New URL, not in the prior manifest at all.
    assert mod._should_skip("https://x.com/c", "deadbeef", already) is False
    assert mod._should_skip("https://x.com/a", "deadbeef", {}) is False


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


# --- D51: GitHub repo scraping + --url-list -------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/SenolIsci/mykg", ("SenolIsci", "mykg")),
        ("https://github.com/SenolIsci/mykg/", ("SenolIsci", "mykg")),
        ("https://github.com/SenolIsci/mykg.git", ("SenolIsci", "mykg")),
        ("https://github.com/SenolIsci/mykg/tree/main/docs", ("SenolIsci", "mykg")),
        ("https://github.com/orgs/SenolIsci/repositories", None),
        ("https://github.com/search?q=mykg", None),
        ("https://github.com", None),
        ("https://github.com/SenolIsci", None),
        ("https://example.com/SenolIsci/mykg", None),
    ],
)
def test_is_github_repo_url(url, expected) -> None:
    from mykg.fetch_web import is_github_repo_url
    assert is_github_repo_url(url) == expected


def test_seed_subdir_name_github_vs_plain() -> None:
    from mykg.fetch_web import seed_subdir_name
    assert seed_subdir_name("https://github.com/SenolIsci/mykg") == "github.com_SenolIsci_mykg"
    assert seed_subdir_name("https://example.com/docs/guide") == "example.com"


def test_default_output_dir_github_repo(tmp_path) -> None:
    from mykg.fetch_web import default_output_dir
    out = default_output_dir("https://github.com/SenolIsci/mykg", "mykg_web_fetch", base=tmp_path)
    assert out == tmp_path / "mykg_web_fetch" / "github.com_SenolIsci_mykg"


@pytest.mark.parametrize(
    ("url", "expected_depth"),
    [
        ("https://example.com", "default"),
        ("https://example.com/", "default"),
        ("https://example.com/blog/post-1", 0),
        ("https://example.com/blog/post-1/", 0),
    ],
)
def test_infer_max_depth(url, expected_depth) -> None:
    from mykg.fetch_web import infer_max_depth
    configured_default = 3
    expected = configured_default if expected_depth == "default" else expected_depth
    assert infer_max_depth(url, configured_default) == expected


def test_parse_url_list(tmp_path) -> None:
    from mykg.fetch_web import parse_url_list
    f = tmp_path / "urls.txt"
    f.write_text(
        "\n".join([
            "# a comment",
            "",
            "https://example.com",
            "  # indented comment",
            "https://github.com/SenolIsci/mykg  ",
            "",
            "https://example.org/page",
        ]),
        encoding="utf-8",
    )
    assert parse_url_list(f) == [
        "https://example.com",
        "https://github.com/SenolIsci/mykg",
        "https://example.org/page",
    ]


def test_filter_repo_files(tmp_path) -> None:
    from mykg.fetch_web import filter_repo_files

    repo = tmp_path / "_repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "config").write_text("git config")
    (repo / "README.md").write_text("# readme")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hi')")
    (repo / "docs").mkdir()
    (repo / "docs" / "guide.md").write_text("# guide")
    (repo / "assets").mkdir()
    (repo / "assets" / "logo.png").write_bytes(b"\x89PNG")

    input_dir = tmp_path / "input"
    allowed = frozenset({".png", ".pdf"})
    result = filter_repo_files(repo, input_dir, allowed)

    assert sorted(result["copied"]) == sorted([
        "README.md", "docs/guide.md", "assets/logo.png",
    ])
    assert result["skipped"] == [{"path": "src/main.py", "ext": ".py"}]
    assert result["total_files"] == 4  # .git/config excluded entirely
    assert result["copied_count"] == 3

    assert (input_dir / "README.md").exists()
    assert (input_dir / "docs" / "guide.md").exists()
    assert (input_dir / "assets" / "logo.png").exists()
    assert not (input_dir / "src" / "main.py").exists()
    assert not (input_dir / ".git").exists()


def test_clone_github_repo_command_shape(tmp_path) -> None:
    from unittest.mock import patch, MagicMock
    from mykg.fetch_web import clone_github_repo

    dest = tmp_path / "_repo"
    proc = MagicMock()
    proc.returncode = 0
    with (
        patch("mykg.fetch_web.shutil.which", return_value="/usr/bin/git"),
        patch("mykg.fetch_web.subprocess.run", return_value=proc) as mock_run,
    ):
        clone_github_repo("SenolIsci", "mykg", dest, depth=1, timeout_seconds=60)

    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd == [
        "git", "clone", "--depth", "1",
        "https://github.com/SenolIsci/mykg.git", str(dest),
    ]
    assert kwargs["timeout"] == 60
    assert kwargs["check"] is True


def test_clone_github_repo_missing_git(tmp_path) -> None:
    from unittest.mock import patch
    from mykg.fetch_web import clone_github_repo

    with patch("mykg.fetch_web.shutil.which", return_value=None):
        with pytest.raises(click.ClickException, match="git"):
            clone_github_repo("SenolIsci", "mykg", tmp_path / "_repo", depth=1, timeout_seconds=60)


def test_clone_github_repo_failure(tmp_path) -> None:
    import subprocess
    from unittest.mock import patch
    from mykg.fetch_web import clone_github_repo

    with (
        patch("mykg.fetch_web.shutil.which", return_value="/usr/bin/git"),
        patch(
            "mykg.fetch_web.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, ["git"], stderr=b"fatal: not found"),
        ),
    ):
        with pytest.raises(click.ClickException, match="git clone failed"):
            clone_github_repo("SenolIsci", "mykg", tmp_path / "_repo", depth=1, timeout_seconds=60)


def test_clone_github_repo_timeout(tmp_path) -> None:
    import subprocess
    from unittest.mock import patch
    from mykg.fetch_web import clone_github_repo

    with (
        patch("mykg.fetch_web.shutil.which", return_value="/usr/bin/git"),
        patch(
            "mykg.fetch_web.subprocess.run",
            side_effect=subprocess.TimeoutExpired(["git"], 60),
        ),
    ):
        with pytest.raises(click.ClickException, match="timed out"):
            clone_github_repo("SenolIsci", "mykg", tmp_path / "_repo", depth=1, timeout_seconds=60)


def test_fetch_web_github_url_skips_crawlee(tmp_path) -> None:
    """A github.com/<owner>/<repo> URL is cloned+filtered; Crawlee/venv path
    is never entered."""
    import json
    from unittest.mock import patch
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"

    def fake_clone(owner, repo, dest, *, depth, timeout_seconds):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("# hi")
        (dest / ".git").mkdir()

    with (
        patch("mykg.cli.ephemeral_venv") as mock_venv,
        patch("mykg.cli.subprocess.run") as mock_run,
        patch("mykg.fetch_web.clone_github_repo", side_effect=fake_clone),
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "https://github.com/SenolIsci/mykg", "--output", str(out)],
        )

    assert result.exit_code == 0, result.output
    mock_venv.assert_not_called()
    mock_run.assert_not_called()

    manifest = json.loads((out / "fetch_manifest.json").read_text())
    assert manifest["seed_url"] == "https://github.com/SenolIsci/mykg"
    assert manifest["strategy"] == "github_clone"
    assert manifest["stats"]["files_total"] == 1
    assert manifest["stats"]["files_copied"] == 1
    assert (out / "input" / "README.md").exists()
    assert not (out / "input" / ".git").exists()


def test_fetch_web_url_list_requires_output(tmp_path) -> None:
    from click.testing import CliRunner
    from mykg.cli import cli

    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://example.com\n")

    result = CliRunner().invoke(cli, ["fetch-web", "--url-list", str(url_list)])
    assert result.exit_code != 0
    assert "--output" in result.output


def test_fetch_web_url_and_url_list_mutually_exclusive(tmp_path) -> None:
    from click.testing import CliRunner
    from mykg.cli import cli

    url_list = tmp_path / "urls.txt"
    url_list.write_text("https://example.com\n")
    out = tmp_path / "fw"

    result = CliRunner().invoke(
        cli,
        ["fetch-web", "https://example.com", "--url-list", str(url_list), "--output", str(out)],
    )
    assert result.exit_code != 0
    assert "--url-list" in result.output


def test_fetch_web_url_list_mixed_seeds(tmp_path) -> None:
    """1 plain URL + 1 GitHub URL: single shared venv/subprocess for the
    Crawlee seed, GitHub seed cloned separately; aggregated manifest."""
    import json
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"

    url_list = tmp_path / "urls.txt"
    url_list.write_text(
        "https://example.com\nhttps://github.com/SenolIsci/mykg\n", encoding="utf-8"
    )

    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_run(cmd, **kwargs):
        config_path = Path(cmd[-1])
        cfg = json.loads(config_path.read_text())
        captured["cfg"] = cfg
        results = {
            "seeds": [
                {
                    "pages": {
                        "https://example.com/": {
                            "local_file": "index.html", "sha256": "abc",
                            "content_type": "text/html", "status": 200, "depth": 0,
                            "fetched_at": "2026-06-12T00:00:00Z",
                        }
                    },
                    "stats": {"pages": 1, "assets": 0, "skipped_robots": 0, "errors": 0},
                    "crawlee_version": "1.0.0",
                }
            ],
            "crawlee_version": "1.0.0",
        }
        (Path(cfg["output_dir"]) / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock()
        proc.returncode = 0
        return proc

    def fake_clone(owner, repo, dest, *, depth, timeout_seconds):
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "README.md").write_text("# hi")

    from pathlib import Path

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()) as mock_venv,
        patch("mykg.cli.subprocess.run", side_effect=fake_run) as mock_subproc,
        patch("mykg.fetch_web.clone_github_repo", side_effect=fake_clone),
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "--url-list", str(url_list), "--output", str(out)],
        )

    assert result.exit_code == 0, result.output
    mock_venv.assert_called_once()
    mock_subproc.assert_called_once()
    assert len(captured["cfg"]["seeds"]) == 1

    manifest = json.loads((out / "fetch_manifest.json").read_text())
    assert manifest["seed_url"] is None
    assert manifest["strategy"] is None
    assert len(manifest["seeds"]) == 2
    strategies = {s["seed_url"]: s["strategy"] for s in manifest["seeds"]}
    assert strategies["https://example.com"] == "same-domain"
    assert strategies["https://github.com/SenolIsci/mykg"] == "github_clone"

    subdirs = {p.name for p in out.iterdir()}
    assert "example.com" in subdirs
    assert "github.com_SenolIsci_mykg" in subdirs
    assert (out / "github.com_SenolIsci_mykg" / "input" / "README.md").exists()


def test_fetch_web_url_list_single_shared_venv_for_plain_urls(tmp_path) -> None:
    """3 plain URLs: exactly one ephemeral_venv + one subprocess.run, with all
    3 seed configs in a single combined config file."""
    import json
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"

    url_list = tmp_path / "urls.txt"
    url_list.write_text(
        "https://a.example.com\nhttps://b.example.com\nhttps://c.example.com\n",
        encoding="utf-8",
    )

    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_run(cmd, **kwargs):
        config_path = Path(cmd[-1])
        cfg = json.loads(config_path.read_text())
        captured["cfg"] = cfg
        seeds = cfg["seeds"]
        results = {
            "seeds": [
                {"pages": {}, "stats": {"pages": 0, "assets": 0, "skipped_robots": 0, "errors": 0},
                 "crawlee_version": "1.0.0"}
                for _ in seeds
            ],
            "crawlee_version": "1.0.0",
        }
        (Path(cfg["output_dir"]) / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock()
        proc.returncode = 0
        return proc

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()) as mock_venv,
        patch("mykg.cli.subprocess.run", side_effect=fake_run) as mock_subproc,
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "--url-list", str(url_list), "--output", str(out)],
        )

    assert result.exit_code == 0, result.output
    mock_venv.assert_called_once()
    mock_subproc.assert_called_once()
    assert len(captured["cfg"]["seeds"]) == 3
    assert captured["cfg"]["max_workers"] == 2

    manifest = json.loads((out / "fetch_manifest.json").read_text())
    assert len(manifest["seeds"]) == 3


def test_fetch_web_url_list_per_seed_depth_inference(tmp_path) -> None:
    """Bare-domain seed → fetch.max_depth; specific-page seed → 0; both when
    --max-depth is not passed."""
    import json
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli
    from mykg import config as _cfg

    out = tmp_path / "fw"

    url_list = tmp_path / "urls.txt"
    url_list.write_text(
        "https://a.example.com\nhttps://b.example.com/blog/post-1\n", encoding="utf-8"
    )

    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_run(cmd, **kwargs):
        config_path = Path(cmd[-1])
        cfg = json.loads(config_path.read_text())
        captured["cfg"] = cfg
        seeds = cfg["seeds"]
        results = {
            "seeds": [
                {"pages": {}, "stats": {"pages": 0, "assets": 0, "skipped_robots": 0, "errors": 0},
                 "crawlee_version": "1.0.0"}
                for _ in seeds
            ],
            "crawlee_version": "1.0.0",
        }
        (Path(cfg["output_dir"]) / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock()
        proc.returncode = 0
        return proc

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "--url-list", str(url_list), "--output", str(out)],
        )

    assert result.exit_code == 0, result.output
    by_url = {c["seed_url"]: c for c in captured["cfg"]["seeds"]}
    assert by_url["https://a.example.com"]["max_depth"] == _cfg.FETCH_MAX_DEPTH
    assert by_url["https://b.example.com/blog/post-1"]["max_depth"] == 0


def test_fetch_web_url_list_explicit_max_depth_overrides_inference(tmp_path) -> None:
    """An explicit --max-depth applies uniformly to all seeds, bypassing
    infer_max_depth."""
    import json
    from pathlib import Path
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli

    out = tmp_path / "fw"

    url_list = tmp_path / "urls.txt"
    url_list.write_text(
        "https://a.example.com\nhttps://b.example.com/blog/post-1\n", encoding="utf-8"
    )

    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_run(cmd, **kwargs):
        config_path = Path(cmd[-1])
        cfg = json.loads(config_path.read_text())
        captured["cfg"] = cfg
        seeds = cfg["seeds"]
        results = {
            "seeds": [
                {"pages": {}, "stats": {"pages": 0, "assets": 0, "skipped_robots": 0, "errors": 0},
                 "crawlee_version": "1.0.0"}
                for _ in seeds
            ],
            "crawlee_version": "1.0.0",
        }
        (Path(cfg["output_dir"]) / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock()
        proc.returncode = 0
        return proc

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli,
            ["fetch-web", "--url-list", str(url_list), "--output", str(out), "--max-depth", "5"],
        )

    assert result.exit_code == 0, result.output
    by_url = {c["seed_url"]: c for c in captured["cfg"]["seeds"]}
    assert by_url["https://a.example.com"]["max_depth"] == 5
    assert by_url["https://b.example.com/blog/post-1"]["max_depth"] == 5


def test_fetch_web_single_url_depth_inference(tmp_path) -> None:
    """Single-URL invocation without --max-depth: bare domain → fetch.max_depth
    via infer_max_depth (refines the existing single-seed default)."""
    import json
    from unittest.mock import patch, MagicMock
    from click.testing import CliRunner
    from mykg.cli import cli
    from mykg import config as _cfg

    out = tmp_path / "fw"

    class _FakeVenv:
        def __enter__(self):
            return tmp_path / "venv" / "bin" / "python"

        def __exit__(self, *a):
            return False

    captured = {}

    def fake_run(cmd, **kwargs):
        config_path = Path(cmd[-1])
        cfg = json.loads(config_path.read_text())
        captured["cfg"] = cfg
        results = {"pages": {}, "stats": {"pages": 0, "assets": 0, "skipped_robots": 0, "errors": 0}}
        (out / ".fetch_results.json").write_text(json.dumps(results))
        proc = MagicMock()
        proc.returncode = 0
        return proc

    from pathlib import Path

    with (
        patch("mykg.cli.ephemeral_venv", return_value=_FakeVenv()),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli, ["fetch-web", "https://example.com/docs/guide", "--output", str(out)],
        )

    assert result.exit_code == 0, result.output
    # Specific page (non-empty path) → max_depth=0 via infer_max_depth.
    assert captured["cfg"]["max_depth"] == 0


def test_crawl_runner_multi_seed(tmp_path) -> None:
    """{"seeds": [cfg1, cfg2]} → main() writes {"seeds": [...]} results;
    single-cfg (no "seeds" key) stays backward compatible."""
    import json
    from unittest.mock import patch

    mod = _load_runner_module()

    seeds = [
        {"output_dir": str(tmp_path), "seed_url": "https://a.example.com"},
        {"output_dir": str(tmp_path), "seed_url": "https://b.example.com"},
    ]
    combined = {"seeds": seeds, "max_workers": 2, "output_dir": str(tmp_path)}
    config_path = tmp_path / "cfg.json"
    config_path.write_text(json.dumps(combined))

    async def fake_crawl(cfg):
        return {"pages": {cfg["seed_url"]: {}}, "stats": {"pages": 1}}

    with patch.object(mod, "crawl", side_effect=fake_crawl):
        rc = mod.main(["_crawl_runner.py", str(config_path)])

    assert rc == 0
    results = json.loads((tmp_path / ".fetch_results.json").read_text())
    assert "seeds" in results
    assert len(results["seeds"]) == 2
    assert results["seeds"][0]["pages"] == {"https://a.example.com": {}}
    assert results["seeds"][1]["pages"] == {"https://b.example.com": {}}


def test_crawl_runner_single_seed_backward_compatible(tmp_path) -> None:
    import json
    from unittest.mock import patch

    mod = _load_runner_module()

    cfg = {"output_dir": str(tmp_path), "seed_url": "https://example.com"}
    config_path = tmp_path / "cfg.json"
    config_path.write_text(json.dumps(cfg))

    async def fake_crawl(cfg):
        return {"pages": {"https://example.com": {}}, "stats": {"pages": 1}}

    with patch.object(mod, "crawl", side_effect=fake_crawl):
        rc = mod.main(["_crawl_runner.py", str(config_path)])

    assert rc == 0
    results = json.loads((tmp_path / ".fetch_results.json").read_text())
    assert "seeds" not in results
    assert results["pages"] == {"https://example.com": {}}


def test_crawl_runner_concurrency_bound(tmp_path) -> None:
    """asyncio.Semaphore(max_workers) caps in-flight crawl() calls."""
    import asyncio

    mod = _load_runner_module()

    seeds = [{"output_dir": str(tmp_path), "seed_url": f"https://s{i}.example.com"} for i in range(4)]

    async def run_with_max_workers(max_workers):
        in_flight = 0
        max_in_flight = 0
        lock = asyncio.Lock()

        async def fake_crawl(cfg):
            nonlocal in_flight, max_in_flight
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            async with lock:
                in_flight -= 1
            return {"pages": {}, "stats": {}, "seed_url": cfg["seed_url"]}

        from unittest.mock import patch
        with patch.object(mod, "crawl", side_effect=fake_crawl):
            results = await mod._crawl_many(seeds, max_workers)
        return results, max_in_flight

    results, max_in_flight = asyncio.run(run_with_max_workers(2))
    assert len(results) == 4
    assert max_in_flight <= 2

    _, max_in_flight_1 = asyncio.run(run_with_max_workers(1))
    assert max_in_flight_1 == 1
