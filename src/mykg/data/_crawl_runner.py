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
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_HTML_EXT = ".html"


def _local_path_for_url(url: str, content_type: str) -> str:
    """Mirror of fetch_web.local_path_for_url (incl. traversal + collision
    hardening), duplicated to avoid importing the mykg package inside the venv
    (mykg is not installed there). Keep in sync with src/mykg/fetch_web.py."""
    parsed = urlparse(url)
    path = parsed.path or "/"
    is_html = content_type.split(";")[0].strip().lower() == "text/html"

    if path.endswith("/"):
        base = path.rstrip("/") + "/index"
    else:
        base = path

    # Neutralize path traversal: drop empty, "." and ".." segments so the
    # result can never escape output_dir. A hostile site controls this path.
    safe_segments = [s for s in base.split("/") if s not in ("", ".", "..")]
    base = "/".join(safe_segments)
    if not base:
        base = "index"

    if is_html:
        stem = base
        stripped_ext = "." in os.path.basename(stem)
        if stripped_ext:
            stem = stem.rsplit(".", 1)[0]
        if parsed.query:
            digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
            return f"{stem}-{digest}{_HTML_EXT}"
        if stripped_ext:
            digest = hashlib.sha1(parsed.path.encode()).hexdigest()[:8]
            return f"{stem}-{digest}{_HTML_EXT}"
        return f"{stem}{_HTML_EXT}"

    if parsed.query:
        digest = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        if "." in os.path.basename(base):
            stem, ext = base.rsplit(".", 1)
            return f"{stem}-{digest}.{ext}"
        return f"{base}-{digest}"
    return base


def _asset_allowed(url: str, allowed: set[str]) -> bool:
    """Decide whether a non-HTML asset body should be saved.

    Pure predicate so it can be unit-tested without a live crawl. The suffix is
    taken from the URL path (e.g. "/foo/bar.pdf" → ".pdf"). Returns True iff the
    lowercased suffix is in `allowed`. An empty `allowed` (download_assets off)
    means no non-HTML asset is ever saved.
    """
    suffix = Path(urlparse(url).path).suffix.lower()
    return suffix in allowed


def _should_skip(url: str, sha256: str, already: dict) -> bool:
    """True iff `url`'s content is unchanged since the prior crawl (dedup/resume).

    `already` is a {url: sha256} map carried from the prior manifest. Returns
    True only when `url` was seen before AND its content hash is unchanged —
    a URL whose content changed is reprocessed even if previously fetched.
    """
    return already.get(url) == sha256


def save_page(output_dir: Path, url: str, content_type: str, body: bytes) -> dict:
    """Write the response bytes to disk and return a manifest row.

    Belt-and-suspenders: even though _local_path_for_url strips traversal,
    assert the resolved destination stays under output_dir before writing.
    """
    rel = _local_path_for_url(url, content_type)
    output_dir = Path(output_dir)
    dest = (output_dir / rel).resolve()
    root = output_dir.resolve()
    if root != dest and root not in dest.parents:
        raise ValueError(f"refusing to write outside output_dir: {dest}")
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
    # Lazy, venv-only imports: keep this module importable without crawlee.
    from crawlee import ConcurrencySettings
    from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed = {e.lower() for e in cfg["allowed_asset_exts"]}
    already = cfg.get("already_fetched", {})
    pages: dict = {}
    stats = {
        "pages": 0,
        "assets": 0,
        "skipped_robots": 0,
        "skipped_cached": 0,
        "errors": 0,
    }

    # Concurrency + rate-limit mapping. request_delay_seconds is translated into
    # Crawlee's max_tasks_per_minute throttle: a delay of D seconds means at most
    # 60/D tasks per minute (e.g. 0.5s → 120/min). When D <= 0 we leave the
    # per-minute rate unbounded and only cap raw concurrency.
    concurrency = cfg.get("concurrency") or 1
    delay = cfg.get("request_delay_seconds", 0) or 0
    # Crawlee defaults desired_concurrency to 10 and rejects desired > max, so
    # pin desired_concurrency to our max_concurrency to keep small caps valid.
    conc_kwargs: dict = {
        "max_concurrency": concurrency,
        "desired_concurrency": concurrency,
    }
    if delay > 0:
        conc_kwargs["max_tasks_per_minute"] = max(1, int(60 / delay))
    conc_settings = ConcurrencySettings(**conc_kwargs)

    crawler_kwargs: dict = {
        "max_requests_per_crawl": cfg["max_pages"],
        "respect_robots_txt_file": cfg["respect_robots"],
        "concurrency_settings": conc_settings,
    }
    # max_crawl_depth caps enqueuing beyond this depth (seed = depth 0). Only
    # pass it when configured so we don't override Crawlee's default with None.
    if cfg.get("max_depth") is not None:
        crawler_kwargs["max_crawl_depth"] = cfg["max_depth"]

    crawler = BeautifulSoupCrawler(**crawler_kwargs)

    @crawler.router.default_handler
    async def handler(context: BeautifulSoupCrawlingContext) -> None:
        url = context.request.url
        resp = context.http_response
        status = getattr(resp, "status_code", 200)
        try:
            ctype = resp.headers.get("content-type", "text/html")
        except Exception:  # noqa: BLE001 — header shape varies by Crawlee version
            ctype = "text/html"
        body = resp.read() if hasattr(resp, "read") else b""
        if asyncio.iscoroutine(body):
            body = await body
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")

        is_html = ctype.split(";")[0].strip().lower() == "text/html"

        # Dedup/resume: if this URL's content is unchanged since the prior run,
        # skip the save/stats — but HTML still gets enqueued so newly-reachable
        # links are discovered even when the page itself hasn't changed.
        # HONEST LIMITATION: Crawlee fetches the response *before* the handler
        # runs, so the HTTP request still goes out; this only avoids re-writing
        # disk. A true network-level skip would require pre-seeding the request
        # queue, which is out of scope here.
        if _should_skip(url, sha256_bytes(body), already):
            stats["skipped_cached"] += 1
            if is_html:
                await context.enqueue_links(strategy=cfg["strategy"])
            return

        if is_html:
            # HTML is always saved; keep enqueuing same-domain links from it.
            row = save_page(output_dir, url, ctype, body)
            row["status"] = status
            row["depth"] = getattr(context.request, "crawl_depth", 0)
            pages[url] = row
            stats["pages"] += 1
            await context.enqueue_links(strategy=cfg["strategy"])
        else:
            # Non-HTML asset: only save (and count) it if its suffix is on the
            # allowlist. With download_assets off, `allowed` is empty → skip all.
            if not _asset_allowed(url, allowed):
                return
            row = save_page(output_dir, url, ctype, body)
            row["status"] = status
            row["depth"] = getattr(context.request, "crawl_depth", 0)
            pages[url] = row
            stats["assets"] += 1

    @crawler.failed_request_handler
    async def on_failed(context: BeautifulSoupCrawlingContext, error: Exception) -> None:
        # Fires after Crawlee exhausts retries for a request (incl. 4xx/5xx that
        # surface as errors). Make the error count real and record a row.
        stats["errors"] += 1
        url = context.request.url
        status = None
        resp = getattr(context, "http_response", None)
        if resp is not None:
            status = getattr(resp, "status_code", None)
        pages[url] = {
            "status": status,
            "error": type(error).__name__,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }

    await crawler.run([cfg["seed_url"]])
    # NOTE on skipped_robots: Crawlee enforces robots.txt internally and does not
    # surface a per-skip hook, so we cannot reliably count robots-skips. Rather
    # than fabricate a number, skipped_robots is left at 0 (honest by design).
    return {"pages": pages, "stats": stats}


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: _crawl_runner.py <config.json>", file=sys.stderr)
        return 2
    cfg = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    result = asyncio.run(crawl(cfg))
    try:
        from importlib.metadata import version

        cv = version("crawlee")
    except Exception:  # noqa: BLE001 — provenance is best-effort
        cv = ""
    result["crawlee_version"] = cv
    out = Path(cfg["output_dir"]) / ".fetch_results.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
