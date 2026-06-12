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
    # Strip any user:pass@ credentials and make the port separator path-safe.
    domain = urlparse(seed_url).netloc.split("@")[-1].replace(":", "_") or "site"
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
    output_dir.mkdir(parents=True, exist_ok=True)
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
