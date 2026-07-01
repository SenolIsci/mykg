from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.steps.preprocess")

# Backend routing: suffixes the markdownify in-process converter owns.
# Anything else in PREPROCESS_EXTENSIONS goes to MinerU. The mapping is
# hardcoded because which backend can handle which format is a property of
# the format, not a user preference — users toggle availability via the
# preprocess.extensions allowlist in YAML.
_HTML_BACKEND_SUFFIXES: frozenset[str] = frozenset({".html", ".htm"})
_TXT_BACKEND_SUFFIXES: frozenset[str] = frozenset({".txt"})


def _write_sentinel(intermediate_dir: Path, manifest: dict) -> None:
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (intermediate_dir / "preprocess.done").write_text("done", encoding="utf-8")
    _atomic_write_json(intermediate_dir / "preprocess_manifest.json", manifest)


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON atomically. Thin alias kept for in-module call sites."""
    atomic_write_json(path, data)


def _sha256_path(p: Path) -> str:
    """Stream-hash a file. Constant memory regardless of file size."""
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_prior_manifest(intermediate_dir: Path) -> dict:
    """Read prior preprocess_manifest.json or return {} if absent / unreadable."""
    p = intermediate_dir / "preprocess_manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _hash_files_parallel(files: list[Path], workers: int) -> dict[Path, str]:
    """Hash every file in `files` in parallel; return {Path: sha256}."""
    if not files:
        return {}
    results: dict[Path, str] = {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        future_to_path = {pool.submit(_sha256_path, p): p for p in files}
        for fut in as_completed(future_to_path):
            results[future_to_path[fut]] = fut.result()
    return results


def _discover_canonical_md(out_dir: Path, stem: str) -> Path | None:
    """Locate the canonical .md written by MinerU for a source file.

    MinerU emits a nested per-file directory tree under `<out_dir>/<stem>/`;
    the deepest `<stem>.md` is the canonical one (D42).
    """
    matches = sorted(out_dir.rglob(f"{stem}.md"), key=lambda p: len(p.parts))
    return matches[-1] if matches else None


def _flatten_to_md(canonical_md: Path, mineru_root: Path, target: Path) -> None:
    """Move `canonical_md` to `target`, then rmtree `mineru_root` so only the
    final `<stem>.md` remains. `mineru_root` is the per-file MinerU output
    subtree (`<out_dir>/<stem>/`); the caller knows where that is. No-op when
    `canonical_md` already lives at `target`.
    """
    if canonical_md.resolve() == target.resolve():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(canonical_md), str(target))
    if mineru_root.exists() and mineru_root.resolve() != target.resolve():
        shutil.rmtree(mineru_root, ignore_errors=True)


def _discover_non_md_files(
    input_dir: Path,
    subdir: str,
    allowed_exts: frozenset[str],
) -> tuple[list[Path], list[Path], list[Path], list[Path]]:
    """Return (mineru_files, html_files, txt_files, skipped) non-md files under input_dir.

    A single allowlist `allowed_exts` controls which suffixes the preprocess
    step is permitted to convert. The backend per allowed suffix is derived
    internally: suffix in `_HTML_BACKEND_SUFFIXES` → markdownify;
    suffix in `_TXT_BACKEND_SUFFIXES` → shutil.copy2 as .md; otherwise →
    MinerU. Files whose suffix is not in `allowed_exts` are skipped (logged +
    recorded, untouched on disk).
    """
    subdir_path = input_dir / subdir
    mineru_files: list[Path] = []
    html_files: list[Path] = []
    txt_files: list[Path] = []
    skipped: list[Path] = []
    for p in input_dir.rglob("*"):
        if not p.is_file():
            continue
        suffix = p.suffix.lower()
        if suffix == ".md":
            continue
        if p == subdir_path or subdir_path in p.parents:
            continue
        if suffix not in allowed_exts:
            skipped.append(p)
            continue
        if suffix in _HTML_BACKEND_SUFFIXES:
            html_files.append(p)
        elif suffix in _TXT_BACKEND_SUFFIXES:
            txt_files.append(p)
        else:
            mineru_files.append(p)
    return mineru_files, html_files, txt_files, skipped


def _convert_html_files(
    html_files: list[Path],
    input_dir: Path,
    output_dir: Path,
    source_files: dict[str, dict],
) -> list[dict]:
    """Convert each HTML file to Markdown via markdownify, writing into output_dir.

    On success, writes the converted output path back to
    `source_files[rel]["output_md"]`. Failures are logged + recorded but do
    not halt the pipeline (D39).

    Output is already a flat `<stem>.md` next to its source — no nested
    MinerU subtree exists for the HTML path, so `PREPROCESS_KEEP_ARTIFACTS`
    is a no-op here. The flag only governs the MinerU cleanup loop.
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
        source_files[str(rel)]["output_md"] = str(dst.relative_to(input_dir))
    return records


def _convert_txt_files(
    txt_files: list[Path],
    input_dir: Path,
    output_dir: Path,
    source_files: dict[str, dict],
) -> list[dict]:
    """Copy each .txt file to .md via shutil.copy2, writing into output_dir.

    On success, writes the converted output path back to
    ``source_files[rel]["output_md"]``. Failures are logged + recorded but do
    not halt the pipeline (D39).
    """
    records: list[dict] = []
    for src in txt_files:
        rel = src.relative_to(input_dir)
        dst = output_dir / rel.with_suffix(".md")
        dst.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.monotonic()
        try:
            shutil.copy2(src, dst)
        except Exception as exc:
            log.warning("Step 0 — txt copy failed for %s: %s", rel, exc)
            records.append({"path": str(rel), "ok": False, "error": str(exc)})
            continue
        duration = time.monotonic() - t0
        log.info("Step 0 — txt → md: %s (%.2fs)", rel, duration)
        records.append(
            {
                "path": str(rel),
                "ok": True,
                "output": str(dst.relative_to(input_dir)),
                "duration_seconds": round(duration, 2),
            }
        )
        source_files[str(rel)]["output_md"] = str(dst.relative_to(input_dir))
    return records


def run_preprocess(ctx: PipelineContext) -> None:
    if not _cfg.PREPROCESS_ENABLED:
        log.info("Step 0 — preprocess disabled in config; skipping")
        _write_sentinel(ctx.intermediate_dir, {"enabled": False})
        return

    mineru_files, html_files, txt_files, skipped = _discover_non_md_files(
        ctx.input_dir,
        _cfg.PREPROCESS_SUBDIR,
        _cfg.PREPROCESS_EXTENSIONS,
    )
    skipped_records = [
        {"path": str(p.relative_to(ctx.input_dir)), "ext": p.suffix.lower()} for p in skipped
    ]
    if skipped:
        log.info(
            "Step 0 — skipping %d non-md file(s) outside extension allowlist: %s",
            len(skipped),
            ", ".join(sorted({r["ext"] or "(no ext)" for r in skipped_records})),
        )
        for r in skipped_records:
            log.info("Step 0 —   skipped: %s", r["path"])

    if not mineru_files and not html_files and not txt_files:
        log.info("Step 0 — no eligible non-md files to preprocess; skipping")
        # Honor cleanup of leftover .md outputs from prior runs whose source
        # files have been removed. Without this, deleting a PDF leaves its
        # converted .md orphaned under input/_preprocessed/.
        prior_sources = _load_prior_manifest(ctx.intermediate_dir).get("source_files", {})
        for entry in prior_sources.values():
            leftover = entry.get("output_md")
            if leftover:
                (ctx.input_dir / leftover).unlink(missing_ok=True)
        _write_sentinel(
            ctx.intermediate_dir,
            {
                "enabled": True,
                "files_found": 0,
                "skipped": True,
                "skipped_files": skipped_records,
                "source_files": {},
            },
        )
        return

    output_dir = ctx.input_dir / _cfg.PREPROCESS_SUBDIR
    output_dir.mkdir(parents=True, exist_ok=True)

    prior_sources: dict = _load_prior_manifest(ctx.intermediate_dir).get("source_files", {})
    hashes = _hash_files_parallel(mineru_files + html_files + txt_files, ctx.ingest_workers)

    def _is_unchanged(rel: str, sha: str) -> bool:
        entry = prior_sources.get(rel)
        if not entry or entry.get("sha256") != sha:
            return False
        prior_output = entry.get("output_md")
        return bool(prior_output and (ctx.input_dir / prior_output).exists())

    source_files: dict[str, dict] = {}
    to_process_mineru: list[tuple[Path, str]] = []
    to_process_html: list[tuple[Path, str]] = []
    to_process_txt: list[tuple[Path, str]] = []
    skipped_unchanged = 0
    for src, bucket in (
        [(p, to_process_mineru) for p in mineru_files]
        + [(p, to_process_html) for p in html_files]
        + [(p, to_process_txt) for p in txt_files]
    ):
        rel = str(src.relative_to(ctx.input_dir))
        if _is_unchanged(rel, hashes[src]):
            source_files[rel] = prior_sources[rel]
            skipped_unchanged += 1
        else:
            bucket.append((src, rel))
            source_files[rel] = {
                "sha256": hashes[src],
                "output_md": None,
                "size_bytes": src.stat().st_size,
            }

    for rel, entry in prior_sources.items():
        if rel in source_files:
            continue
        leftover = entry.get("output_md")
        if leftover:
            (ctx.input_dir / leftover).unlink(missing_ok=True)

    if skipped_unchanged:
        log.info(
            "Step 0 — %d file(s) unchanged since last run; reusing prior output",
            skipped_unchanged,
        )

    html_records: list[dict] = []
    if to_process_html:
        log.info("Step 0 — converting %d HTML file(s) via markdownify", len(to_process_html))
        html_records = _convert_html_files(
            [src for src, _ in to_process_html], ctx.input_dir, output_dir, source_files
        )

    txt_records: list[dict] = []
    if to_process_txt:
        log.info("Step 0 — copying %d txt file(s) as .md via shutil", len(to_process_txt))
        txt_records = _convert_txt_files(
            [src for src, _ in to_process_txt], ctx.input_dir, output_dir, source_files
        )

    mineru_returncode = 0
    mineru_duration = 0.0
    if to_process_mineru:
        # Write the list of files to process to a sidecar text file and pass it
        # via --file-list. Avoids the OS ARG_MAX ceiling that would otherwise
        # limit the corpus to roughly ten thousand files on macOS/Linux.
        file_list_path = ctx.intermediate_dir / "preprocess_filelist.txt"
        file_list_path.write_text(
            "\n".join(rel for _, rel in to_process_mineru), encoding="utf-8"
        )

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
            "--file-list",
            str(file_list_path),
        ]
        cmd.extend(_cfg.PREPROCESS_EXTRA_ARGS)
        log.info(
            "Step 0 — running: %s (%d file(s) via --file-list)",
            " ".join(cmd),
            len(to_process_mineru),
        )

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
            raise RuntimeError(f"mykg parse-docs failed with exit code {proc.returncode}")

        for src, rel in to_process_mineru:
            # parse-docs writes each file's output under <output_dir>/<rel_parent>/<stem>/.
            search_root = output_dir / Path(rel).parent / src.stem
            canonical = _discover_canonical_md(search_root, src.stem)
            if canonical is None:
                log.warning("Step 0 — no canonical .md found for %s under %s", rel, search_root)
                continue
            if not _cfg.PREPROCESS_KEEP_ARTIFACTS:
                target = output_dir / Path(rel).parent / f"{src.stem}.md"
                _flatten_to_md(canonical, search_root, target)
                canonical = target
            source_files[rel]["output_md"] = str(canonical.relative_to(ctx.input_dir))

    total_files = len(mineru_files) + len(html_files) + len(txt_files)
    log.info(
        "Step 0 — preprocess complete (mineru=%d in %.1fs, html=%d, txt=%d, skipped=%d, unchanged=%d)",
        len(to_process_mineru),
        mineru_duration,
        len(to_process_html),
        len(to_process_txt),
        len(skipped),
        skipped_unchanged,
    )
    _write_sentinel(
        ctx.intermediate_dir,
        {
            "enabled": True,
            "files_found": total_files,
            "mineru_files": len(to_process_mineru),
            "html_files": len(to_process_html),
            "txt_files": len(to_process_txt),
            "mineru_duration_seconds": round(mineru_duration, 2),
            "mineru_returncode": mineru_returncode,
            "subdir": _cfg.PREPROCESS_SUBDIR,
            "html_records": html_records,
            "txt_records": txt_records,
            "skipped_files": skipped_records,
            "source_files": source_files,
            "unchanged_count": skipped_unchanged,
        },
    )
