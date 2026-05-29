"""
Pipeline step: ``preprocess`` (D39).

Converts every non-Markdown source file under ``ctx.input_dir`` into a
sibling ``.md`` file via the MinerU CLI (binary docs) or markdownify (HTML),
then yields to the existing ``ingest`` step. Idempotent via the
``preprocess.done`` sentinel.

Failure semantics:
- Per-file conversion failures are recorded in the manifest and the step
  continues (``preprocess.fail_fast: false``).
- If MinerU is required (non-HTML files exist) but missing, the step logs an
  actionable error and either halts (``fail_fast: true``) or continues with
  whatever HTML/MD files are present.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.preprocess import (
    MineruRunner,
    PreprocessError,
    PreprocessManifest,
    _normalize_extension,
    convert_directory,
)

log = get("mykg.steps.preprocess")


def _files_with_extensions(input_dir: Path, extensions: list[str]) -> list[Path]:
    """Return every regular file under ``input_dir`` matching ``extensions``."""
    exts = {_normalize_extension(e) for e in extensions}
    return [
        p for p in input_dir.rglob("*") if p.is_file() and _normalize_extension(p.suffix) in exts
    ]


def _write_sentinel_and_manifest(ctx: PipelineContext, manifest: PreprocessManifest) -> None:
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    (ctx.intermediate_dir / "preprocess_manifest.json").write_text(
        json.dumps(manifest.model_dump(), indent=_cfg.JSON_INDENT)
    )
    (ctx.intermediate_dir / "preprocess.done").write_text("done")


def run_preprocess(ctx: PipelineContext) -> None:
    """Run the optional upstream conversion step."""
    if not _cfg.PREPROCESS_ENABLED:
        log.info("preprocess: disabled via preprocess.enabled=false — skipping")
        _write_sentinel_and_manifest(ctx, PreprocessManifest())
        return

    input_dir = ctx.input_dir
    if not input_dir.exists():
        log.warning("preprocess: input dir %s does not exist — skipping", input_dir)
        _write_sentinel_and_manifest(ctx, PreprocessManifest())
        return

    mineru_targets = _files_with_extensions(input_dir, _cfg.PREPROCESS_EXTENSIONS)
    html_targets = _files_with_extensions(input_dir, _cfg.PREPROCESS_HTML_EXTENSIONS)

    if not mineru_targets and not html_targets:
        log.info("preprocess: no non-Markdown candidates in %s — skipping", input_dir)
        _write_sentinel_and_manifest(ctx, PreprocessManifest())
        return

    runner = MineruRunner()
    binary = runner.resolve_binary()
    if mineru_targets and binary is None:
        message = (
            f"MinerU not found at {runner.mineru_path!r}; install with: "
            "pip install mykg[mineru], or set preprocess.mineru_path in mykg_config.yaml. "
            f"{len(mineru_targets)} non-Markdown file(s) require MinerU."
        )
        if _cfg.PREPROCESS_FAIL_FAST:
            log.error("preprocess: %s", message)
            raise PreprocessError(message)
        log.warning("preprocess: %s — skipping MinerU files, proceeding with HTML only", message)
        # If we still have HTML files, run them and skip the binary types.
        if not html_targets:
            manifest = PreprocessManifest(
                failed={
                    str(p.relative_to(input_dir)): "mineru-not-installed" for p in mineru_targets
                }
            )
            _write_sentinel_and_manifest(ctx, manifest)
            return
        manifest = convert_directory(
            input_dir,
            input_dir,
            extensions=[],
            html_extensions=_cfg.PREPROCESS_HTML_EXTENSIONS,
            max_workers=ctx.preprocess_workers,
            runner=runner,
            fail_fast=_cfg.PREPROCESS_FAIL_FAST,
        )
        for src in mineru_targets:
            manifest.failed[str(src.relative_to(input_dir))] = "mineru-not-installed"
        _write_sentinel_and_manifest(ctx, manifest)
        return

    # Standard path: convert in place under input_dir so ingest's rglob picks up
    # the produced .md files alongside any hand-written ones.
    manifest = convert_directory(
        input_dir,
        input_dir,
        extensions=_cfg.PREPROCESS_EXTENSIONS,
        html_extensions=_cfg.PREPROCESS_HTML_EXTENSIONS,
        max_workers=ctx.preprocess_workers,
        runner=runner,
        fail_fast=_cfg.PREPROCESS_FAIL_FAST,
    )
    log.info(
        "preprocess: %d converted, %d failed, %d skipped",
        len(manifest.converted),
        len(manifest.failed),
        len(manifest.skipped),
    )
    _write_sentinel_and_manifest(ctx, manifest)


def cleanup_converted_outputs(intermediate_dir: Path, input_dir: Path) -> int:
    """Delete every converted .md + sidecar listed in the preprocess manifest.

    Used by ``--from-step preprocess`` re-entry (D47). Returns the number of
    files removed. Original source files (PDF/DOCX/…) are preserved.
    """
    manifest_path = intermediate_dir / "preprocess_manifest.json"
    if not manifest_path.exists():
        return 0
    try:
        data = json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0

    removed = 0
    for rel, entry in (data.get("converted") or {}).items():
        # Prefer the absolute output_file stored at conversion time; fall back
        # to the rel-path derived guess.
        out = entry.get("output_file") if isinstance(entry, dict) else None
        candidates: list[Path] = []
        if out:
            candidates.append(Path(out))
        # Fallback path: input_dir / <stem>.md (relative to original source)
        src_rel = Path(rel)
        candidates.append(input_dir / src_rel.with_suffix(".md"))

        for md_path in candidates:
            if md_path.exists():
                md_path.unlink()
                removed += 1
                sidecar = md_path.with_suffix(".mineru.json")
                if sidecar.exists():
                    sidecar.unlink()
                    removed += 1
                # Drop the colocated images/ folder when present.
                images_dir = md_path.parent / "images"
                if images_dir.is_dir():
                    shutil.rmtree(images_dir, ignore_errors=True)
                break
    return removed
