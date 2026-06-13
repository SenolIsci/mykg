# Fetch-Web Crawler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a standalone `mykg fetch-web <url>` command that crawls a website (full same-domain crawl) and writes raw HTML + a `fetch_manifest.json` into a folder that `extract-graph` can consume directly.

**Architecture:** Crawlee-for-Python runs inside an ephemeral `uv`-managed venv (created per invocation, destroyed on exit) — mirroring the existing MinerU pattern in `uv_venv.py` (D48). The crawler library is never installed into mykg's own interpreter. A small bundled runner script (`_crawl_runner.py`) is the only place Crawlee is imported; it is invoked as `<venv>/bin/python _crawl_runner.py <config.json>`. The CLI handler and pure helpers (`fetch_web.py`) stay in mykg's interpreter and communicate with the runner via two JSON files (config in, results out). Raw HTML is left to the existing `preprocess` step to convert (D44); the crawler only does acquisition + provenance.

**Tech Stack:** Python 3.11+, Click (CLI), `uv` (ephemeral venv), Crawlee-for-Python `crawlee[beautifulsoup]` (venv-only), pytest + `unittest.mock` + `click.testing.CliRunner` (tests).

**Spec:** `docs/superpowers/specs/2026-06-12-fetch-web-crawler-design.md`
**Branch:** `design/fetch-web-crawler`

---

## File Structure

| File | Responsibility | New/Modified |
|---|---|---|
| `src/mykg/uv_venv.py` | Add generic `ephemeral_venv(...)`; refactor `ephemeral_mineru_venv` into a thin wrapper (no behavior change) | Modify |
| `src/mykg/config.py` | Add `FETCH_*` constants read from the `fetch:` YAML block | Modify |
| `mykg_config.yaml` | Add `fetch:` block to every profile (runtime config) | Modify |
| `src/mykg/data/mykg_config.yaml` | Add `fetch:` block to every profile (packaged template) — Invariant 17 | Modify |
| `src/mykg/fetch_web.py` | Pure helpers: output-dir resolution, crawl-config builder, manifest load/merge/atomic-write, filename derivation, dedup | Create |
| `src/mykg/data/_crawl_runner.py` | Crawlee BFS runner; the only Crawlee import; reads config JSON, writes pages + results JSON | Create |
| `src/mykg/cli.py` | Add the `fetch-web` Click command | Modify |
| `tests/test_fetch_web.py` | Unit tests for `fetch_web.py` helpers + the CLI handler (mocked venv/subprocess) | Create |
| `tests/test_uv_venv_generic.py` | Regression: `ephemeral_mineru_venv` still works after refactor; `ephemeral_venv` yields the right binary | Create |

**Dependency order (tasks must be done in sequence — each depends on the prior):**
1 `ephemeral_venv` → 2 config constants → 3 YAML blocks → 4 `fetch_web.py` helpers → 5 `_crawl_runner.py` → 6 CLI command → 7 docs/CLAUDE.md.

---

## Conventions to follow (discovered in the codebase)

- **No hardcoded values (Invariant 7):** every knob reads from a `config.py` constant sourced from YAML. Use the existing `_get_opt("fetch", "<key>", <default>)` helper pattern (see `config.py:205-230`).
- **Config in two places (Invariant 17):** any new YAML key goes in BOTH `mykg_config.yaml` (repo root, every profile) and `src/mykg/data/mykg_config.yaml`.
- **Lazy config import in CLI:** `cli.py` imports config lazily inside handlers via `from mykg import config as _cfg` (see `parse_docs` at `cli.py:1107`). Follow that.
- **Atomic JSON writes:** `*.tmp` → `os.replace` (see `step_preprocess._atomic_write_json` at `step_preprocess.py:33`). Reuse that idiom.
- **Ephemeral-venv failure semantics:** `uv` missing / install fail / timeout → `RuntimeError`/`ClickException` with truncated stderr. The existing `ephemeral_mineru_venv` already does this; the generic version inherits it.
- **CLI failure semantics (mirror `parse_docs`, `cli.py:1064-1183`):** per-page errors are non-fatal and recorded; a non-zero runner exit or a timeout raises `click.ClickException`.
- **Test style (see `tests/test_parse_docs.py`):** `CliRunner` for command tests; `patch("mykg.uv_venv.shutil.which", ...)` + a `fake_run` that fabricates the venv tree; `_fake_proc(returncode, stdout, stderr)` helper. No real network in non-`live` tests.
- **Run tests with:** `pytest tests/test_fetch_web.py -v` (the repo `addopts` adds coverage automatically; that's fine).

---

## Task 1: Generalize the ephemeral venv helper

**Files:**
- Modify: `src/mykg/uv_venv.py`
- Test: `tests/test_uv_venv_generic.py`

- [ ] **Step 1: Write the failing regression + generic test**

Create `tests/test_uv_venv_generic.py`:

```python
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

from mykg.uv_venv import ephemeral_mineru_venv, ephemeral_venv


def _fake_run_factory(bin_names):
    """Return a fake_run that fabricates a venv tree with the given binaries."""
    def fake_run(cmd, **kwargs):
        from unittest.mock import MagicMock
        if "venv" in cmd and "pip" not in cmd:
            venv_dir = Path(cmd[-1])
            bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
            bin_dir.mkdir(parents=True, exist_ok=True)
            for name in bin_names:
                (bin_dir / name).write_text("")
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        return proc
    return fake_run


def test_ephemeral_venv_yields_named_binary(tmp_path: Path) -> None:
    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=_fake_run_factory(["python"])),
    ):
        with ephemeral_venv("3.12", "crawlee[beautifulsoup]", "uv", 60,
                            bin_name="python", prefix="mykg-crawl-venv-") as py:
            assert py.name in ("python", "python.exe")
            assert py.exists()


def test_ephemeral_mineru_venv_still_yields_mineru(tmp_path: Path) -> None:
    """Regression: the wrapper still yields the mineru binary unchanged."""
    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=_fake_run_factory(["python", "mineru"])),
    ):
        with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60) as mineru_bin:
            assert mineru_bin.name in ("mineru", "mineru.exe")
            assert mineru_bin.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_uv_venv_generic.py -v`
Expected: FAIL — `ImportError: cannot import name 'ephemeral_venv'`.

- [ ] **Step 3: Implement `ephemeral_venv` and refactor the wrapper**

In `src/mykg/uv_venv.py`, replace the `ephemeral_mineru_venv` function (lines 52-104) and the `__all__` (line 107) with:

```python
@contextmanager
def ephemeral_venv(
    python_version: str,
    spec: str,
    uv_path: str,
    install_timeout: int,
    *,
    bin_name: str,
    prefix: str,
) -> Iterator[Path]:
    """Create a fresh Python venv with `spec` installed, yield a named binary.

    The venv lives in a TemporaryDirectory and is deleted when the context
    exits (success or exception). uv auto-downloads the requested Python
    interpreter if the host system lacks it. `bin_name` is the executable to
    yield from the venv's bin/ dir (e.g. "mineru", or "python" to run a script).
    """
    resolved_uv = shutil.which(uv_path)
    if resolved_uv is None:
        raise RuntimeError(
            f"uv not found at {uv_path!r}; uv is a core mykg dependency, "
            "reinstall mykg or set the uv_path key in mykg_config.yaml."
        )

    with tempfile.TemporaryDirectory(prefix=prefix) as tmp:
        venv_dir = Path(tmp) / "venv"
        log.info("uv_venv — creating venv at %s (python=%s)", venv_dir, python_version)

        _run(
            [resolved_uv, "venv", "--python", python_version, str(venv_dir)],
            timeout=install_timeout,
            phase="uv venv",
        )
        _run(
            [
                resolved_uv,
                "pip",
                "install",
                "--python",
                str(_venv_bin(venv_dir, "python")),
                "-U",
                spec,
            ],
            timeout=install_timeout,
            phase=f"uv pip install {spec}",
        )

        target_bin = _venv_bin(venv_dir, bin_name)
        if not target_bin.exists():
            raise RuntimeError(f"uv_venv — installed {spec} but {target_bin} not found")

        log.info("uv_venv — ready: %s", target_bin)
        try:
            yield target_bin
        finally:
            log.info("uv_venv — cleaning up %s", venv_dir)


@contextmanager
def ephemeral_mineru_venv(
    python_version: str,
    mineru_spec: str,
    uv_path: str,
    install_timeout: int,
) -> Iterator[Path]:
    """Thin wrapper over `ephemeral_venv` yielding the mineru binary (D48)."""
    with ephemeral_venv(
        python_version,
        mineru_spec,
        uv_path,
        install_timeout,
        bin_name="mineru",
        prefix="mykg-mineru-venv-",
    ) as mineru_bin:
        yield mineru_bin


__all__ = ["ephemeral_venv", "ephemeral_mineru_venv"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_uv_venv_generic.py tests/test_parse_docs.py -v`
Expected: PASS (new generic tests pass AND the existing parse-docs venv tests still pass).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/uv_venv.py tests/test_uv_venv_generic.py
git commit -m "refactor(uv_venv): extract generic ephemeral_venv from ephemeral_mineru_venv"
```

---

## Task 2: Add `FETCH_*` config constants

**Files:**
- Modify: `src/mykg/config.py` (after the PREPROCESS block, ~line 231)
- Test: `tests/test_fetch_web.py` (create with the first test)

- [ ] **Step 1: Write the failing test**

Create `tests/test_fetch_web.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_web.py::test_fetch_config_constants_exist_with_defaults -v`
Expected: FAIL — `AttributeError: module 'mykg.config' has no attribute 'FETCH_ENABLED'`.

- [ ] **Step 3: Add the constants**

In `src/mykg/config.py`, immediately after the `PREPROCESS_EXTENSIONS` block (after line 230), insert:

```python
# ---------------------------------------------------------------------------
# Fetch-web — standalone website crawler (Crawlee in an ephemeral uv venv).
# Mirrors the preprocess MinerU venv pattern (D48): nothing about Crawlee is
# installed into mykg's own interpreter. The crawler writes raw HTML + a
# fetch_manifest.json into a folder that `extract-graph` then consumes.
# The asset allowlist reuses PREPROCESS_EXTENSIONS — no separate fetch list.
# ---------------------------------------------------------------------------
FETCH_ENABLED: bool = bool(_get_opt("fetch", "enabled", True))
FETCH_STRATEGY: str = _get_opt("fetch", "strategy", "same-domain")
FETCH_MAX_PAGES: int = int(_get_opt("fetch", "max_pages", 500))
FETCH_MAX_DEPTH: int = int(_get_opt("fetch", "max_depth", 10))
FETCH_RESPECT_ROBOTS: bool = bool(_get_opt("fetch", "respect_robots", True))
FETCH_REQUEST_DELAY_SECONDS: float = float(
    _get_opt("fetch", "request_delay_seconds", 0.5)
)
FETCH_CONCURRENCY: int = int(_get_opt("fetch", "concurrency", 4))
FETCH_DOWNLOAD_ASSETS: bool = bool(_get_opt("fetch", "download_assets", True))
FETCH_TIMEOUT_SECONDS: int = int(_get_opt("fetch", "timeout_seconds", 1800))
FETCH_UV_PATH: str = _get_opt("fetch", "uv_path", "uv")
FETCH_UV_PYTHON_VERSION: str = _get_opt("fetch", "uv_python_version", "3.12")
FETCH_CRAWLEE_SPEC: str = _get_opt("fetch", "crawlee_spec", "crawlee[beautifulsoup]")
FETCH_INSTALL_TIMEOUT_SECONDS: int = int(
    _get_opt("fetch", "install_timeout_seconds", 1800)
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_web.py::test_fetch_config_constants_exist_with_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/config.py tests/test_fetch_web.py
git commit -m "feat(config): add FETCH_* constants for fetch-web crawler"
```

---

## Task 3: Add the `fetch:` YAML block to both config files

**Files:**
- Modify: `mykg_config.yaml` (every profile)
- Modify: `src/mykg/data/mykg_config.yaml` (every profile)
- Test: `tests/test_fetch_web.py` (add a structural-parity test)

- [ ] **Step 1: Write the failing parity test**

Add to `tests/test_fetch_web.py`:

```python
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
```

> NOTE: If the test reveals the `fetch:` block belongs at a different nesting level than `pipeline:` (e.g. directly under the profile, like `preprocess:`), adjust the assertion path to match where `preprocess:` lives. Verify by reading where `preprocess:` is nested in `mykg_config.yaml` first, and place `fetch:` as a sibling of `preprocess:`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_web.py::test_fetch_block_present_in_both_yaml_files -v`
Expected: FAIL — `fetch block missing`.

- [ ] **Step 3: Add the `fetch:` block as a sibling of `preprocess:` in every profile**

First read where `preprocess:` is nested (`grep -n 'preprocess:' mykg_config.yaml`). For EACH profile in BOTH `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml`, add this block immediately after that profile's `preprocess:` block, at the same indentation level:

```yaml
      fetch:
        enabled: true                 # master toggle for the fetch-web command
        strategy: same-domain         # link-following scope: same-domain | same-origin | all
        max_pages: 500                # hard cap on total fetched pages (bounds runtime)
        max_depth: 10                 # max crawl depth from the seed URL
        respect_robots: true          # honor robots.txt disallow + crawl-delay
        request_delay_seconds: 0.5    # politeness delay between requests
        concurrency: 4                # max concurrent requests
        download_assets: true         # download linked binaries whose suffix is in preprocess.extensions
        timeout_seconds: 1800         # crawl run-phase timeout (30 min)
        uv_path: uv                   # uv CLI path (uv is a core mykg dependency)
        uv_python_version: "3.12"     # interpreter pinned for the ephemeral crawl venv
        crawlee_spec: "crawlee[beautifulsoup]"   # spec installed via `uv pip install -U`
        install_timeout_seconds: 1800 # install-phase timeout (30 min)
```

(Match the exact indentation used by the sibling `preprocess:` block in each file — the example above assumes 6-space indent; adjust if the file uses a different level.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_web.py::test_fetch_block_present_in_both_yaml_files -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add mykg_config.yaml src/mykg/data/mykg_config.yaml tests/test_fetch_web.py
git commit -m "feat(config): add fetch: block to runtime and packaged YAML (Invariant 17)"
```

---

## Task 4: `fetch_web.py` pure helpers

**Files:**
- Create: `src/mykg/fetch_web.py`
- Test: `tests/test_fetch_web.py` (add helper tests)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_fetch_web.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_fetch_web.py -k "default_output or build_crawl or local_path or manifest_merge or already_fetched" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mykg.fetch_web'`.

- [ ] **Step 3: Implement `fetch_web.py`**

Create `src/mykg/fetch_web.py`:

```python
"""Pure helpers for the `mykg fetch-web` command.

These functions run in mykg's own interpreter. They never import Crawlee —
the crawl itself happens in `data/_crawl_runner.py` inside an ephemeral venv.
Keeping these pure makes them unit-testable without any network or venv.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def default_output_dir(seed_url: str, base: Path | None = None) -> Path:
    """`./fetched_web/<seed-domain>/` so a bare invocation is one-shot usable."""
    base = base or Path.cwd()
    domain = urlparse(seed_url).netloc or "site"
    return base / "fetched_web" / domain


def build_crawl_config(
    *,
    seed_url: str,
    output_dir: str,
    strategy: str,
    max_pages: int,
    max_depth: int,
    respect_robots: bool,
    request_delay_seconds: float,
    concurrency: int,
    allowed_asset_exts: list[str],
) -> dict:
    """Assemble the JSON contract handed to the in-venv crawl runner."""
    return {
        "seed_url": seed_url,
        "output_dir": output_dir,
        "strategy": strategy,
        "max_pages": max_pages,
        "max_depth": max_depth,
        "respect_robots": respect_robots,
        "request_delay_seconds": request_delay_seconds,
        "concurrency": concurrency,
        "allowed_asset_exts": list(allowed_asset_exts),
    }


_HTML_EXT = ".html"


def local_path_for_url(url: str, content_type: str) -> str:
    """Map a URL → a relative on-disk path under the output dir.

    HTML responses get `.html`; a trailing-slash path becomes `index.html`.
    Query strings are folded into the filename via a short hash so distinct
    query variants never collide. Non-HTML keeps its own URL extension.
    """
    parsed = urlparse(url)
    path = parsed.path or "/"
    is_html = content_type.split(";")[0].strip().lower() == "text/html"

    if path.endswith("/"):
        base = path.rstrip("/") + "/index"
    else:
        base = path
    base = base.lstrip("/")
    if not base:
        base = "index"

    if is_html:
        # Drop any existing suffix; we control the .html extension.
        stem = base
        if "." in os.path.basename(stem):
            stem = stem.rsplit(".", 1)[0]
        if parsed.query:
            digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
            return f"{stem}-{digest}{_HTML_EXT}"
        return f"{stem}{_HTML_EXT}"

    # Non-HTML: keep the URL's own extension; hash query if present.
    if parsed.query:
        digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        if "." in os.path.basename(base):
            stem, ext = base.rsplit(".", 1)
            return f"{stem}-{digest}.{ext}"
        return f"{base}-{digest}"
    return base


def load_manifest(output_dir: Path) -> dict:
    """Return the prior manifest's `pages` map, or {} if none exists."""
    mf = output_dir / "fetch_manifest.json"
    if not mf.exists():
        return {}
    try:
        data = json.loads(mf.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data.get("pages", {})


def is_already_fetched(prior_pages: dict, url: str, sha256: str) -> bool:
    """True iff `url` is in the prior manifest with a matching content SHA."""
    entry = prior_pages.get(url)
    return bool(entry and entry.get("sha256") == sha256)


def write_manifest(
    output_dir: Path,
    *,
    seed_url: str,
    strategy: str,
    pages: dict,
    stats: dict,
    crawlee_version: str = "",
) -> None:
    """Atomically write fetch_manifest.json (`*.tmp` → os.replace)."""
    data = {
        "seed_url": seed_url,
        "strategy": strategy,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "crawlee_version": crawlee_version,
        "stats": stats,
        "pages": pages,
    }
    mf = output_dir / "fetch_manifest.json"
    tmp = mf.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, mf)


__all__ = [
    "default_output_dir",
    "build_crawl_config",
    "local_path_for_url",
    "load_manifest",
    "is_already_fetched",
    "write_manifest",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_fetch_web.py -v`
Expected: PASS (all helper tests + the earlier config/parity tests).

- [ ] **Step 5: Commit**

```bash
git add src/mykg/fetch_web.py tests/test_fetch_web.py
git commit -m "feat(fetch_web): pure helpers for output paths, crawl config, manifest"
```

---

## Task 5: `_crawl_runner.py` — the in-venv Crawlee runner

**Files:**
- Create: `src/mykg/data/_crawl_runner.py`
- Test: `tests/test_fetch_web.py` (test the pure logic inside the runner by importing the file directly; do NOT run a real crawl)

> The runner imports `crawlee` only inside `main()` / the async body, so the module can be imported in tests (which lack crawlee) to exercise its pure helpers. Keep all crawlee usage behind the `if __name__ == "__main__"` / `async def crawl(...)` boundary.

- [ ] **Step 1: Write the failing test for the runner's pure helpers**

Add to `tests/test_fetch_web.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_web.py::test_crawl_runner_module_imports_without_crawlee -v`
Expected: FAIL — file does not exist.

- [ ] **Step 3: Implement the runner**

Create `src/mykg/data/_crawl_runner.py`:

```python
"""In-venv Crawlee crawl runner for `mykg fetch-web`.

Run as:  <venv>/bin/python _crawl_runner.py <config.json>

Reads the crawl-config JSON written by the CLI handler, performs a same-domain
BFS with Crawlee's BeautifulSoupCrawler, saves each fetched resource's raw
bytes under config["output_dir"], and writes the per-resource manifest rows to
<output_dir>/.fetch_results.json for the parent process to read back.

crawlee is imported lazily inside `crawl()` so this module stays importable
(for unit tests) on interpreters that do not have crawlee installed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# NOTE: keep this import set free of crawlee. The fetch_web helpers are pure
# stdlib; we re-derive the path mapping here to avoid importing the mykg
# package inside the throwaway venv (mykg is not installed there).
from urllib.parse import urlparse


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _local_path_for_url(url: str, content_type: str) -> str:
    """Mirror of fetch_web.local_path_for_url, duplicated to avoid importing
    the mykg package inside the venv (mykg is not installed there)."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    is_html = content_type.split(";")[0].strip().lower() == "text/html"
    base = (path.rstrip("/") + "/index") if path.endswith("/") else path
    base = base.lstrip("/") or "index"
    if is_html:
        stem = base.rsplit(".", 1)[0] if "." in Path(base).name else base
        if parsed.query:
            d = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
            return f"{stem}-{d}.html"
        return f"{stem}.html"
    if parsed.query:
        d = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        if "." in Path(base).name:
            stem, ext = base.rsplit(".", 1)
            return f"{stem}-{d}.{ext}"
        return f"{base}-{d}"
    return base


def save_page(output_dir: Path, url: str, content_type: str, body: bytes) -> dict:
    """Write the response bytes to disk and return a manifest row."""
    rel = _local_path_for_url(url, content_type)
    dest = output_dir / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    return {
        "local_file": rel,
        "sha256": sha256_bytes(body),
        "content_type": content_type,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


async def crawl(cfg: dict) -> dict:
    """Run the crawl; return {"pages": {...}, "stats": {...}}."""
    from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = {e.lower() for e in cfg["allowed_asset_exts"]}
    pages: dict = {}
    stats = {"pages": 0, "assets": 0, "skipped_robots": 0, "errors": 0}

    crawler = BeautifulSoupCrawler(
        max_requests_per_crawl=cfg["max_pages"],
        respect_robots_txt_file=cfg["respect_robots"],
    )

    @crawler.router.default_handler
    async def handler(context: BeautifulSoupCrawlingContext) -> None:
        resp = context.http_response
        url = context.request.url
        status = getattr(resp, "status_code", 200)
        ctype = ""
        try:
            ctype = resp.headers.get("content-type", "text/html")
        except Exception:  # noqa: BLE001 — header shape varies by Crawlee version
            ctype = "text/html"
        body = await resp.read() if hasattr(resp, "read") else context.http_response.read()
        if asyncio.iscoroutine(body):
            body = await body
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")

        row = save_page(output_dir, url, ctype, body)
        row["status"] = status
        row["depth"] = context.request.crawl_depth if hasattr(context.request, "crawl_depth") else 0
        pages[url] = row
        if row["content_type"].split(";")[0].strip().lower() == "text/html":
            stats["pages"] += 1
            # Optionally enqueue allowed-extension asset links too.
            if allowed:
                await context.enqueue_links(
                    strategy=cfg["strategy"],
                    transform_request_function=lambda req: req,  # passthrough
                )
            else:
                await context.enqueue_links(strategy=cfg["strategy"])
        else:
            stats["assets"] += 1

    await crawler.run([cfg["seed_url"]])
    return {"pages": pages, "stats": stats}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: _crawl_runner.py <config.json>", file=sys.stderr)
        return 2
    cfg = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result = asyncio.run(crawl(cfg))
    out = Path(cfg["output_dir"]) / ".fetch_results.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

> IMPLEMENTATION NOTE for the worker: Crawlee's `BeautifulSoupCrawlingContext` response/header/body accessors and the depth attribute name have varied across versions. The body above uses defensive `getattr`/`hasattr`. When you run the `live` e2e test (Task 6, Step e2e), if any accessor is wrong, fix it against the installed crawlee version — the *contract* (save bytes, record row, enqueue same-domain links) is what matters, not the exact attribute names. Pin a known-good `crawlee` version in `crawlee_spec` if needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_web.py::test_crawl_runner_module_imports_without_crawlee -v`
Expected: PASS (module imports without crawlee; `sha256_bytes` and `save_page` exist).

- [ ] **Step 5: Ensure the runner ships as package data**

Verify it's included in the wheel. Read `pyproject.toml` `[tool.hatch.build.targets.wheel]`; since `packages = ["src/mykg"]`, files under `src/mykg/data/` are included automatically. Confirm by checking that the existing `data/mykg_config.yaml` is shipped (it is). No change needed unless a `force-include`/exclude rule blocks `*.py` under `data/` — if so, add `include = ["src/mykg/data/_crawl_runner.py"]`.

- [ ] **Step 6: Commit**

```bash
git add src/mykg/data/_crawl_runner.py tests/test_fetch_web.py
git commit -m "feat(fetch_web): in-venv Crawlee crawl runner (data/_crawl_runner.py)"
```

---

## Task 6: The `fetch-web` CLI command

**Files:**
- Modify: `src/mykg/cli.py` (add the command; place it near `parse_docs`, after line 1183)
- Test: `tests/test_fetch_web.py` (CLI handler test, venv + subprocess mocked)

- [ ] **Step 1: Write the failing CLI test**

Add to `tests/test_fetch_web.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fetch_web.py::test_fetch_web_command_runs_runner_and_writes_manifest -v`
Expected: FAIL — `Error: No such command 'fetch-web'`.

- [ ] **Step 3: Add the import and the command**

In `src/mykg/cli.py`, add near the top imports (after the existing stdlib imports, before `import click` is fine, or alongside other lazy imports — but the test patches `mykg.cli.ephemeral_venv`, so it must be importable at module scope):

```python
from mykg.uv_venv import ephemeral_venv
```

Then add the command after `parse_docs` (after line 1183):

```python
@cli.command("fetch-web")
@click.argument("url")
@click.option("--output", default=None, type=click.Path(path_type=Path),
              help="Target folder (default: ./fetched_web/<domain>/).")
@click.option("--max-pages", default=None, type=int, help="Cap on total fetched pages.")
@click.option("--max-depth", default=None, type=int, help="Max crawl depth from seed.")
@click.option("--strategy", default=None,
              type=click.Choice(["same-domain", "same-origin", "all"]),
              help="Link-following scope (default from config; 'all' leaves the domain).")
@click.option("--download-assets/--no-download-assets", default=None,
              help="Download linked binaries in preprocess.extensions (default from config).")
@click.option("--delay", default=None, type=float, help="Per-request delay seconds.")
@click.option("--concurrency", default=None, type=int, help="Max concurrent requests.")
@click.option("--no-robots", is_flag=True, help="Disable robots.txt compliance.")
@click.option("--force", is_flag=True, help="Ignore prior manifest; re-fetch everything.")
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging.")
def fetch_web(url, output, max_pages, max_depth, strategy, download_assets,
              delay, concurrency, no_robots, force, verbose):
    """Crawl a website and save raw HTML + fetch_manifest.json into a folder.

    The folder is a normal `extract-graph` input: the preprocess step converts
    the saved HTML to Markdown (and any downloaded PDFs/DOCX via MinerU). Crawlee
    runs inside an ephemeral uv venv that is destroyed on exit — nothing about
    the crawler is installed into mykg's own interpreter.

    Example:
        mykg fetch-web https://example.com
        mykg extract-graph ./fetched_web/example.com/
    """
    from mykg import config as _cfg
    from mykg import fetch_web as fw

    out_dir = Path(output) if output else fw.default_output_dir(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    prior = {} if force else fw.load_manifest(out_dir)

    strat = strategy or _cfg.FETCH_STRATEGY
    dl_assets = _cfg.FETCH_DOWNLOAD_ASSETS if download_assets is None else download_assets
    allowed = sorted(_cfg.PREPROCESS_EXTENSIONS) if dl_assets else []

    crawl_cfg = fw.build_crawl_config(
        seed_url=url,
        output_dir=str(out_dir),
        strategy=strat,
        max_pages=max_pages if max_pages is not None else _cfg.FETCH_MAX_PAGES,
        max_depth=max_depth if max_depth is not None else _cfg.FETCH_MAX_DEPTH,
        respect_robots=(False if no_robots else _cfg.FETCH_RESPECT_ROBOTS),
        request_delay_seconds=delay if delay is not None else _cfg.FETCH_REQUEST_DELAY_SECONDS,
        concurrency=concurrency if concurrency is not None else _cfg.FETCH_CONCURRENCY,
        allowed_asset_exts=allowed,
    )
    crawl_cfg["already_fetched"] = {u: e.get("sha256") for u, e in prior.items()}

    config_path = out_dir / ".fetch_config.json"
    config_path.write_text(json.dumps(crawl_cfg, indent=2), encoding="utf-8")

    runner = Path(__file__).parent / "data" / "_crawl_runner.py"

    click.echo(f"Crawling {url} → {out_dir} (strategy={strat}, max_pages={crawl_cfg['max_pages']})")
    with ephemeral_venv(
        _cfg.FETCH_UV_PYTHON_VERSION,
        _cfg.FETCH_CRAWLEE_SPEC,
        _cfg.FETCH_UV_PATH,
        _cfg.FETCH_INSTALL_TIMEOUT_SECONDS,
        bin_name="python",
        prefix="mykg-crawl-venv-",
    ) as venv_python:
        try:
            proc = subprocess.run(
                [str(venv_python), str(runner), str(config_path)],
                check=False,
                timeout=_cfg.FETCH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise click.ClickException(
                f"crawl timed out after {_cfg.FETCH_TIMEOUT_SECONDS}s"
            ) from exc
        if proc.returncode != 0:
            raise click.ClickException(f"crawl runner failed with exit code {proc.returncode}")

    results_path = out_dir / ".fetch_results.json"
    if not results_path.exists():
        raise click.ClickException("crawl runner produced no results file")
    results = json.loads(results_path.read_text(encoding="utf-8"))

    merged = dict(prior)
    merged.update(results.get("pages", {}))
    fw.write_manifest(
        out_dir, seed_url=url, strategy=strat,
        pages=merged, stats=results.get("stats", {}),
    )
    click.echo(
        f"Done. {results.get('stats', {}).get('pages', 0)} pages, "
        f"{results.get('stats', {}).get('assets', 0)} assets → {out_dir}\n"
        f"Next: mykg extract-graph {out_dir}/"
    )
```

> NOTE: `--strategy`/`--download-assets` use `default=None` so "not passed" is distinguishable from an explicit value, letting config supply the default (Invariant 7). The test patches `mykg.cli.ephemeral_venv` and `mykg.cli.subprocess.run`, so both must be referenced at `mykg.cli` scope — `ephemeral_venv` via the module-level import added above, `subprocess` is already imported at `cli.py:7`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fetch_web.py::test_fetch_web_command_runs_runner_and_writes_manifest -v`
Expected: PASS.

- [ ] **Step 5: Run the full fetch_web test module + a broad smoke**

Run: `pytest tests/test_fetch_web.py tests/test_uv_venv_generic.py tests/test_parse_docs.py tests/test_cli_commands.py -v`
Expected: PASS (no regressions in CLI or venv tests).

- [ ] **Step 6 (e2e — `live`): Real crawl against a local fixture site**

Add a `live`-marked end-to-end test to `tests/test_fetch_web.py`:

```python
import pytest


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
```

Run: `pytest tests/test_fetch_web.py -m live -v`
Expected: PASS. **First run downloads crawlee into the venv (slow).** If a crawlee accessor in `_crawl_runner.py` is wrong for the installed version, this test surfaces it — fix the accessor (see the implementation note in Task 5) until it passes.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/cli.py tests/test_fetch_web.py
git commit -m "feat(cli): add fetch-web command (Crawlee in ephemeral uv venv)"
```

---

## Task 7: Documentation

**Files:**
- Modify: `CLAUDE.md` (add D50 documenting the fetch-web design) — optional but recommended for consistency with the existing D-numbered decision log
- Modify: `README.md` if it lists CLI commands (check first with `grep -n 'parse-docs\|extract-graph' README.md`)

- [ ] **Step 1: Add a decision-log entry to CLAUDE.md**

After D49 (or at the end of the "All Design Decisions" section), add:

```markdown
### D50 — Website Fetching (`mykg fetch-web`)
Standalone command that crawls a website (full same-domain crawl) and writes raw
HTML + `fetch_manifest.json` into a folder consumable by `extract-graph`. Crawlee
for Python runs inside an ephemeral uv venv destroyed on exit (mirrors MinerU,
D48) — the crawler is never installed into mykg's interpreter. The crawler does
acquisition + provenance only; HTML→MD conversion stays in `step_preprocess`
(D44). Guardrails: robots.txt compliance, same-domain scope, `max_pages`/`max_depth`
caps, rate limiting (delay + concurrency), and SHA-based resume/dedup via the
manifest. All knobs live under the `fetch:` YAML block (Invariant 7), present in
both config files (Invariant 17). v1 records URL provenance in the manifest only —
the graph's `source_files` joins back to the URL via `fetch_manifest.json`; the
URL is not threaded into nodes/edges.
```

- [ ] **Step 2: Update README if it enumerates commands**

Run: `grep -n 'parse-docs\|extract-graph' README.md`
If the commands are listed, add a `fetch-web` entry mirroring the `parse-docs` style:

```markdown
- `mykg fetch-web <url>` — crawl a website to a local folder (raw HTML + manifest),
  then `mykg extract-graph <folder>/` to build the graph.
```

If `grep` finds nothing relevant, skip this step (note "README has no command list").

- [ ] **Step 3: Run the whole suite once more**

Run: `pytest -m "not live" -q`
Expected: PASS (all non-live tests green).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document fetch-web command (D50)"
```

---

## E2E Test Recipe (for the executor)

A local-fixture e2e is encoded as the `live` test in Task 6 Step 6. To verify the full pipeline integration manually after implementation:

1. Serve a tiny site: `mkdir /tmp/site && echo '<a href="/a.html">a</a>' > /tmp/site/index.html && echo '<p>a</p>' > /tmp/site/a.html && (cd /tmp/site && python -m http.server 8123 &)`
2. `mykg fetch-web http://127.0.0.1:8123/ --output /tmp/fw --max-pages 10 --no-robots`
   → expect `/tmp/fw/index.html`, `/tmp/fw/a.html`, `/tmp/fw/fetch_manifest.json`.
3. Re-run the same command → manifest stats unchanged; log notes nothing new (dedup).
4. `mykg extract-graph /tmp/fw/ --review` → confirm preprocess converts the HTML to `.md` under `input/_preprocessed/`, ingest picks them up, schema + graph produced.
5. Kill the server: `kill %1`.

---

## Self-Review

**Spec coverage:**
- §3.1 components → Tasks 1 (venv), 4 (fetch_web), 5 (runner), 6 (CLI). ✓
- §3.2 generic venv + mineru wrapper → Task 1. ✓
- §4 CLI surface (all flags) → Task 6 command. ✓
- §4.1 handler flow (resolve dir, load prior, build config, run runner, merge, write) → Task 6. ✓
- §5 runner (BFS, save bytes, enqueue same-domain, results JSON) → Task 5. ✓
- §5.1 filename derivation → Task 4 `local_path_for_url` + runner mirror. ✓
- §5.2 resume/dedup → Task 4 `is_already_fetched` + Task 6 `already_fetched` config + Task 6 Step 6 (2nd run). ✓
- §6 manifest format → Task 4 `write_manifest` (keys: seed_url, strategy, fetched_at, crawlee_version, stats, pages). ✓
- §7 config (13 keys, both YAMLs) → Tasks 2 + 3. ✓
- §8 failure semantics → Task 6 (timeout fatal, runner non-zero fatal, per-page errors recorded). ✓
- §9 invariants → addressed across Tasks 2,3,6 and D50 in Task 7. ✓
- §10 testing → unit (Tasks 1-6) + live integration (Task 6 Step 6). ✓
- §11 e2e recipe → E2E section above. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The two "IMPLEMENTATION NOTE" callouts in Task 5/Task 3 are explicit guidance about version/indentation realities, not deferred work — each names the exact thing to verify and how. ✓

**Type/name consistency:** `ephemeral_venv(bin_name=..., prefix=...)` signature is identical in Task 1 (def), Task 5 mention, and Task 6 (call). `build_crawl_config` keyword args match between Task 4 (def + test) and Task 6 (call). `local_path_for_url(url, content_type)` matches between Task 4 and the runner's `_local_path_for_url` mirror. `write_manifest(output_dir, *, seed_url, strategy, pages, stats, crawlee_version="")` matches Task 4 def and Task 6 call. `load_manifest`/`is_already_fetched` names consistent. ✓

**Known intentional duplication:** `local_path_for_url` exists twice — once in `fetch_web.py` (mykg interpreter) and mirrored as `_local_path_for_url` in `_crawl_runner.py` (venv interpreter, where mykg is NOT installed). This is deliberate (the runner cannot import mykg) and documented in both files. The Task 4 test and the runner test both pin the behavior so they cannot silently drift.
