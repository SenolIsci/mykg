from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext

log = get("mykg.steps.preprocess")


def _write_sentinel(intermediate_dir: Path, manifest: dict) -> None:
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (intermediate_dir / "preprocess.done").write_text("done")
    (intermediate_dir / "preprocess_manifest.json").write_text(
        json.dumps(manifest, indent=_cfg.JSON_INDENT)
    )


def _discover_non_md_files(
    input_dir: Path,
    subdir: str,
    mineru_exts: frozenset[str],
    html_exts: frozenset[str],
) -> tuple[list[Path], list[Path], list[Path]]:
    """Return (mineru_files, html_files, skipped) non-md files under input_dir.

    Routing per suffix (case-insensitive):
      * suffix in `mineru_exts` → routed to MinerU via parse-docs
      * suffix in `html_exts`   → converted inline via markdownify
      * anything else           → logged + recorded as skipped, untouched on disk
    """
    subdir_path = input_dir / subdir
    mineru_files: list[Path] = []
    html_files: list[Path] = []
    skipped: list[Path] = []
    for p in input_dir.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix == ".md":
            continue
        if p == subdir_path or subdir_path in p.parents:
            continue
        if suffix in mineru_exts:
            mineru_files.append(p)
        elif suffix in html_exts:
            html_files.append(p)
        else:
            skipped.append(p)
    return mineru_files, html_files, skipped


def _convert_html_files(
    html_files: list[Path], input_dir: Path, output_dir: Path
) -> list[dict]:
    """Convert each HTML file to Markdown via markdownify, writing into output_dir.

    Output filename mirrors the source stem: `foo.html` → `foo.md`. Returns
    a list of records suitable for the manifest. Failures are logged and
    recorded but do not halt the pipeline (matches D39 non-blocking semantics).
    """
    from markdownify import markdownify

    records: list[dict] = []
    for src in html_files:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel.with_suffix(".md")
        dst.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        try:
            html = src.read_text(encoding="utf-8", errors="replace")
            md = markdownify(html, strip=["img", "a"])
            dst.write_text(md, encoding="utf-8")
        except Exception as exc:
            log.warning("Step 0 — html convert failed for %s: %s", rel, exc)
            records.append({"path": str(rel), "ok": False, "error": str(exc)})
            continue
        duration = time.monotonic() - t0
        log.info("Step 0 — html → md: %s (%.2fs)", rel, duration)
        records.append(
            {
                "path": str(rel),
                "ok": True,
                "output": str(dst.relative_to(input_dir)),
                "duration_seconds": round(duration, 2),
            }
        )
    return records


def run_preprocess(ctx: PipelineContext) -> None:
    if not _cfg.PREPROCESS_ENABLED:
        log.info("Step 0 — preprocess disabled in config; skipping")
        _write_sentinel(ctx.intermediate_dir, {"enabled": False})
        return

    mineru_files, html_files, skipped = _discover_non_md_files(
        ctx.input_dir,
        _cfg.PREPROCESS_SUBDIR,
        _cfg.PREPROCESS_EXTENSIONS,
        _cfg.PREPROCESS_HTML_EXTENSIONS,
    )
    skipped_records = [
        {"path": str(p.relative_to(ctx.input_dir)), "ext": p.suffix.lower()}
        for p in skipped
    ]
    if skipped:
        log.info(
            "Step 0 — skipping %d non-md file(s) outside extension allowlist: %s",
            len(skipped),
            ", ".join(sorted({r["ext"] or "(no ext)" for r in skipped_records})),
        )
        for r in skipped_records:
            log.info("Step 0 —   skipped: %s", r["path"])

    if not mineru_files and not html_files:
        log.info("Step 0 — no eligible non-md files to preprocess; skipping")
        _write_sentinel(
            ctx.intermediate_dir,
            {
                "enabled": True,
                "files_found": 0,
                "skipped": True,
                "skipped_files": skipped_records,
            },
        )
        return

    output_dir = ctx.input_dir / _cfg.PREPROCESS_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)

    html_records: list[dict] = []
    if html_files:
        log.info("Step 0 — converting %d HTML file(s) via markdownify", len(html_files))
        html_records = _convert_html_files(html_files, ctx.input_dir, output_dir)

    mineru_returncode = 0
    mineru_duration = 0.0
    if mineru_files:
        # Use `python -m mykg` so the child runs the SAME interpreter/install
        # as the parent — bare `mykg` would resolve via PATH and could pick up
        # an older system-installed mykg (without parse-docs).
        cmd = [
            sys.executable,
            "-m",
            "mykg",
            "parse-docs",
            "--input",
            str(ctx.input_dir),
            "--output",
            str(output_dir),
            *_cfg.PREPROCESS_EXTRA_ARGS,
        ]
        log.info("Step 0 — running: %s", " ".join(cmd))

        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                timeout=_cfg.PREPROCESS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"mykg parse-docs timed out after {_cfg.PREPROCESS_TIMEOUT_SECONDS}s"
            ) from exc
        mineru_duration = time.monotonic() - t0
        mineru_returncode = proc.returncode

        if proc.returncode != 0:
            raise RuntimeError(
                f"mykg parse-docs failed with exit code {proc.returncode}"
            )

    total_files = len(mineru_files) + len(html_files)
    log.info(
        "Step 0 — preprocess complete (mineru=%d in %.1fs, html=%d, skipped=%d)",
        len(mineru_files),
        mineru_duration,
        len(html_files),
        len(skipped),
    )
    _write_sentinel(
        ctx.intermediate_dir,
        {
            "enabled": True,
            "files_found": total_files,
            "mineru_files": len(mineru_files),
            "html_files": len(html_files),
            "mineru_duration_seconds": round(mineru_duration, 2),
            "mineru_returncode": mineru_returncode,
            "subdir": _cfg.PREPROCESS_SUBDIR,
            "html_records": html_records,
            "skipped_files": skipped_records,
        },
    )
