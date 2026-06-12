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
        try:
            ctype = resp.headers.get("content-type", "text/html")
        except Exception:  # noqa: BLE001 — header shape varies by Crawlee version
            ctype = "text/html"
        body = resp.read() if hasattr(resp, "read") else b""
        if asyncio.iscoroutine(body):
            body = await body
        if isinstance(body, str):
            body = body.encode("utf-8", "replace")

        row = save_page(output_dir, url, ctype, body)
        row["status"] = status
        row["depth"] = getattr(context.request, "crawl_depth", 0)
        pages[url] = row
        if row["content_type"].split(";")[0].strip().lower() == "text/html":
            stats["pages"] += 1
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
