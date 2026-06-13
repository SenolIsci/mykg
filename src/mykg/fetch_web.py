"""Pure helpers for the `mykg fetch-web` command.

These functions run in mykg's own interpreter. They never import Crawlee —
the crawl itself happens in `data/_crawl_runner.py` inside an ephemeral venv.
Keeping these pure makes them unit-testable without any network or venv.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import click

from mykg.utility.atomic_io import atomic_write_json


_GITHUB_REPO_RE = re.compile(
    r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?/?$"
)

# github.com paths that are not <owner>/<repo> roots (orgs, search, etc.)
_GITHUB_NON_REPO_FIRST_SEGMENTS = frozenset({
    "orgs", "search", "marketplace", "notifications", "settings", "explore",
    "topics", "collections", "sponsors", "issues", "pulls", "codespaces",
})


def is_github_repo_url(url: str) -> tuple[str, str] | None:
    """Return `(owner, repo)` if `url` is `https://github.com/<owner>/<repo>`
    (optionally with `.git`, a trailing slash, or a sub-path like
    `/tree/main/...`), else `None`."""
    match = _GITHUB_REPO_RE.match(url.strip())
    if not match:
        return None
    owner, repo = match.group(1), match.group(2)
    if owner.lower() in _GITHUB_NON_REPO_FIRST_SEGMENTS:
        return None
    return owner, repo


def seed_subdir_name(seed_url: str) -> str:
    """`<seed-domain>` (or `github.com_<owner>_<repo>` for GitHub repo URLs) —
    the per-seed folder name used both under the default output dir
    (single-seed) and directly under `--output` (`--url-list`)."""
    repo_match = is_github_repo_url(seed_url)
    if repo_match:
        owner, repo = repo_match
        return f"github.com_{owner}_{repo}"
    # Strip any user:pass@ credentials and make the port separator path-safe.
    return urlparse(seed_url).netloc.split("@")[-1].replace(":", "_") or "site"


def default_output_dir(seed_url: str, output_dir: str, base: Path | None = None) -> Path:
    """`./<output_dir>/<seed-domain>/` so a bare invocation is one-shot usable.

    `output_dir` is `fetch.output_dir` from `mykg_config.yaml` (default
    `mykg_web_fetch`). GitHub repo URLs get a per-repo directory
    `github.com_<owner>_<repo>/` so different repos under `github.com` never
    collide.
    """
    base = base or Path.cwd()
    return base / output_dir / seed_subdir_name(seed_url)


def infer_max_depth(url: str, configured_default: int) -> int:
    """Bare domain/origin → `configured_default`; specific page → `0`.

    A URL whose path (after stripping one trailing `/`) is empty is treated
    as a same-domain crawl seed and uses the configured default depth. A URL
    with any non-empty path component is treated as a single page and gets
    `max_depth=0` (no link-following).
    """
    path = urlparse(url).path
    if path.endswith("/"):
        path = path[:-1]
    return configured_default if path == "" else 0


def parse_url_list(path: Path) -> list[str]:
    """Read one URL per line; blank lines and `#`-comments are ignored."""
    urls: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        urls.append(stripped)
    return urls


def clone_github_repo(
    owner: str, repo: str, dest: Path, *, depth: int, timeout_seconds: int
) -> None:
    """`git clone --depth <depth> https://github.com/<owner>/<repo>.git <dest>`.

    Raises `click.ClickException` if `git` is unavailable, the clone fails,
    or it times out. `.git/` is left in `dest` (not stripped).
    """
    if shutil.which("git") is None:
        raise click.ClickException(
            "git is required for GitHub repo fetching but was not found on PATH"
        )
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{owner}/{repo}.git"
    try:
        subprocess.run(
            ["git", "clone", "--depth", str(depth), url, str(dest)],
            capture_output=True,
            timeout=timeout_seconds,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", "replace")[-2000:] if exc.stderr else ""
        raise click.ClickException(
            f"git clone failed for {owner}/{repo}: {stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise click.ClickException(
            f"git clone timed out after {timeout_seconds}s for {owner}/{repo}"
        ) from exc


def filter_repo_files(
    repo_dir: Path, input_dir: Path, allowed_exts: frozenset[str]
) -> dict:
    """Copy `.md` + `allowed_exts` files from `repo_dir` into `input_dir`,
    preserving relative structure and skipping `.git/`.

    Returns `{"copied": [...], "skipped": [{"path", "ext"}, ...],
    "total_files": N, "copied_count": M}`.
    """
    copied: list[str] = []
    skipped: list[dict] = []
    total_files = 0

    for src in sorted(repo_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(repo_dir)
        if rel.parts and rel.parts[0] == ".git":
            continue
        total_files += 1
        ext = src.suffix.lower()
        if ext == ".md" or ext in allowed_exts:
            dest = input_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            copied.append(str(rel))
        else:
            skipped.append({"path": str(rel), "ext": ext})

    return {
        "copied": copied,
        "skipped": skipped,
        "total_files": total_files,
        "copied_count": len(copied),
    }


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

    # Neutralize path traversal before any extension logic: drop empty, "."
    # and ".." segments so the result can never escape the output dir. A
    # hostile site controls this path via links/redirects.
    safe_segments = [s for s in base.split("/") if s not in ("", ".", "..")]
    base = "/".join(safe_segments)
    if not base:
        base = "index"

    if is_html:
        # Drop any existing suffix; we control the .html extension.
        stem = base
        stripped_ext = "." in os.path.basename(stem)
        if stripped_ext:
            stem = stem.rsplit(".", 1)[0]
        if parsed.query:
            digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
            return f"{stem}-{digest}{_HTML_EXT}"
        if stripped_ext:
            # Stripping a suffix can collide /foo with /foo.html — fold a short
            # hash of the original path into the name to keep them distinct.
            digest = hashlib.sha1(parsed.path.encode()).hexdigest()[:8]
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
    seed_url: str | None,
    strategy: str | None,
    pages: dict,
    stats: dict,
    crawlee_version: str = "",
    seeds: list[dict] | None = None,
) -> None:
    """Atomically write fetch_manifest.json via atomic_write_json.

    For a single seed (the default), `seed_url`/`strategy` are set and
    `seeds` is `None`. For `--url-list`, pass `seeds=[...]` with `seed_url`
    and `strategy` both `None`; `pages`/`stats` should be the aggregated
    (union/summed) values across all seeds.
    """
    data = {
        "seed_url": seed_url,
        "strategy": strategy,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "crawlee_version": crawlee_version,
        "stats": stats,
        "pages": pages,
    }
    if seeds is not None:
        data["seeds"] = seeds
    output_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_dir / "fetch_manifest.json", data)


__all__ = [
    "default_output_dir",
    "build_crawl_config",
    "local_path_for_url",
    "load_manifest",
    "is_already_fetched",
    "write_manifest",
    "is_github_repo_url",
    "clone_github_repo",
    "filter_repo_files",
    "infer_max_depth",
    "parse_url_list",
    "seed_subdir_name",
]
