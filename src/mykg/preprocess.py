"""
Optional upstream conversion layer (D39–D48).

Converts non-Markdown inputs (PDF, DOCX, PPTX, XLSX, images, HTML) to Markdown
so the existing ``ingest`` step can consume them. Two converter backends:

* **MinerU** (CLI subprocess) — handles PDF/DOCX/PPTX/XLSX/images. Heavy
  optional dependency installed via ``pip install mykg[mineru]``.
* **markdownify** (in-process) — handles HTML/HTM. Lightweight core dep.

The dispatcher routes each file by extension. Every converted file gets a
sidecar ``<stem>.mineru.json`` carrying provenance. Output images (MinerU)
are colocated next to the produced ``.md``.

All models are Pydantic per Invariant 8. All knobs flow from
``mykg_config.yaml`` via ``mykg.config`` per Invariant 7.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from mykg import config as _cfg
from mykg.logging import get

log = get("mykg.preprocess")

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class PreprocessError(Exception):
    """Raised when an upstream conversion fails irrecoverably."""


# ---------------------------------------------------------------------------
# Pydantic models (Invariant 8)
# ---------------------------------------------------------------------------


class ConvertResult(BaseModel):
    """Result of converting a single source file to Markdown."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    source_file: str
    output_file: str | None = None
    converter: str  # "mineru" | "markdownify"
    converter_version: str | None = None
    backend: str | None = None
    language: str | None = None
    duration_seconds: float = 0.0
    success: bool = True
    error: str | None = None
    image_count: int = 0
    sha256: str | None = None
    converted_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PreprocessManifest(BaseModel):
    """Manifest of an entire ``convert_directory`` run."""

    converted: dict[str, ConvertResult] = Field(default_factory=dict)
    skipped: list[str] = Field(default_factory=list)
    failed: dict[str, str] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provenance helpers
# ---------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_sidecar(md_path: Path, result: ConvertResult) -> None:
    """Write ``<stem>.mineru.json`` next to a converted markdown file (D46).

    The suffix is intentionally constant across converters; the ``converter``
    field inside disambiguates the source ("mineru" vs "markdownify").
    """
    sidecar = md_path.with_suffix(".mineru.json")
    sidecar.write_text(json.dumps(result.model_dump(), indent=_cfg.JSON_INDENT))


# ---------------------------------------------------------------------------
# HTML converter — markdownify (Unit 3)
# ---------------------------------------------------------------------------


def _html_to_markdown(input_path: Path, output_dir: Path) -> ConvertResult:
    """Convert a single HTML/HTM file to Markdown using ``markdownify``.

    The output markdown is written to ``output_dir / <stem>.md``. Returns a
    ``ConvertResult``; raises ``PreprocessError`` on read/write failure.
    """
    started = datetime.now(timezone.utc)
    try:
        from markdownify import markdownify as _md
    except ImportError as exc:  # pragma: no cover — markdownify is a core dep
        raise PreprocessError(
            "markdownify is required for HTML preprocessing but is not installed. "
            "Install it with: pip install markdownify"
        ) from exc

    try:
        html_text = input_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise PreprocessError(f"Could not read HTML file {input_path}: {exc}") from exc

    md_text = _md(html_text, heading_style="ATX").strip() + "\n"

    output_dir.mkdir(parents=True, exist_ok=True)
    output_md = output_dir / f"{input_path.stem}.md"
    output_md.write_text(md_text, encoding="utf-8")

    duration = (datetime.now(timezone.utc) - started).total_seconds()
    sha = _sha256_file(input_path)
    converter_version = _get_markdownify_version()

    return ConvertResult(
        source_file=str(input_path),
        output_file=str(output_md),
        converter="markdownify",
        converter_version=converter_version,
        backend=None,
        language=None,
        duration_seconds=duration,
        success=True,
        error=None,
        image_count=0,
        sha256=sha,
    )


def _get_markdownify_version() -> str | None:
    try:
        from importlib.metadata import version

        return version("markdownify")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# MinerU runner — CLI subprocess (Unit 4)
# ---------------------------------------------------------------------------


class MineruRunner(BaseModel):
    """Wraps the ``mineru`` CLI for a single-file conversion.

    All knobs come from ``mykg.config`` (Invariant 7): the binary path,
    backend, OCR language, and per-file timeout are passed at construction
    time so the same instance can run many files in parallel.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    mineru_path: str = Field(default_factory=lambda: _cfg.PREPROCESS_MINERU_PATH)
    backend: str = Field(default_factory=lambda: _cfg.PREPROCESS_BACKEND)
    language: str = Field(default_factory=lambda: _cfg.PREPROCESS_LANGUAGE)
    timeout_seconds: int = Field(default_factory=lambda: _cfg.PREPROCESS_TIMEOUT_SECONDS)

    def resolve_binary(self) -> str | None:
        """Resolve the MinerU binary via ``shutil.which`` (handles bare names + paths).

        Returns the absolute path if found, else ``None``.
        """
        if not self.mineru_path:
            return None
        resolved = shutil.which(self.mineru_path)
        if resolved:
            return resolved
        # Allow absolute paths even if shutil.which doesn't find them on PATH.
        candidate = Path(self.mineru_path)
        if candidate.is_absolute() and candidate.exists():
            return str(candidate)
        return None

    def version(self) -> str | None:
        binary = self.resolve_binary()
        if binary is None:
            return None
        try:
            proc = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            text = ((proc.stdout or "") + (proc.stderr or "")).strip()
            return text.splitlines()[0] if text else None
        except (subprocess.SubprocessError, OSError):
            return None

    def convert(self, input_path: Path, output_dir: Path) -> ConvertResult:
        """Run MinerU on a single file; copy output ``.md`` (and ``images/``)
        into ``output_dir``.

        On success returns a ConvertResult with ``output_file`` pointing to the
        copied markdown. On failure raises ``PreprocessError`` with stderr.
        """
        binary = self.resolve_binary()
        if binary is None:
            raise PreprocessError(
                f"MinerU not found at {self.mineru_path!r}; "
                "install with: pip install mykg[mineru], "
                "or set preprocess.mineru_path in mykg_config.yaml"
            )

        started = datetime.now(timezone.utc)
        output_dir.mkdir(parents=True, exist_ok=True)

        # MinerU writes a deeply nested tree; use a per-file scratch dir so we
        # can locate the canonical .md unambiguously via rglob.
        work_dir = output_dir / f".{input_path.stem}.mineru_work"
        if work_dir.exists():
            shutil.rmtree(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            binary,
            "-p",
            str(input_path),
            "-o",
            str(work_dir),
            "-b",
            self.backend,
            "-l",
            self.language,
        ]

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise PreprocessError(
                f"MinerU timed out after {self.timeout_seconds}s on {input_path}"
            ) from exc
        except OSError as exc:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise PreprocessError(f"MinerU subprocess failed for {input_path}: {exc}") from exc

        if proc.returncode != 0:
            stderr_tail = (proc.stderr or "").strip()[-500:]
            shutil.rmtree(work_dir, ignore_errors=True)
            raise PreprocessError(
                f"MinerU exited with code {proc.returncode} on {input_path}: {stderr_tail}"
            )

        # Locate the canonical markdown (deepest match for <stem>.md).
        md_candidates = sorted(
            work_dir.rglob(f"{input_path.stem}.md"),
            key=lambda p: len(p.parts),
            reverse=True,
        )
        if not md_candidates:
            shutil.rmtree(work_dir, ignore_errors=True)
            raise PreprocessError(f"MinerU produced no markdown for {input_path} under {work_dir}")

        produced_md = md_candidates[0]
        dest_md = output_dir / f"{input_path.stem}.md"
        shutil.copy2(produced_md, dest_md)

        # Colocate the sibling images/ directory if present (D43).
        image_count = 0
        sibling_images = produced_md.parent / "images"
        if sibling_images.is_dir():
            dest_images = output_dir / "images"
            dest_images.mkdir(parents=True, exist_ok=True)
            for img in sibling_images.iterdir():
                if img.is_file():
                    shutil.copy2(img, dest_images / img.name)
                    image_count += 1

        shutil.rmtree(work_dir, ignore_errors=True)

        duration = (datetime.now(timezone.utc) - started).total_seconds()
        sha = _sha256_file(input_path)

        return ConvertResult(
            source_file=str(input_path),
            output_file=str(dest_md),
            converter="mineru",
            converter_version=self.version(),
            backend=self.backend,
            language=self.language,
            duration_seconds=duration,
            success=True,
            error=None,
            image_count=image_count,
            sha256=sha,
        )


# ---------------------------------------------------------------------------
# Dispatcher (Unit 5)
# ---------------------------------------------------------------------------


def _normalize_extension(ext: str) -> str:
    return ext.lower().lstrip(".")


def _is_supported(
    path: Path,
    extensions: Iterable[str],
    html_extensions: Iterable[str],
) -> str | None:
    """Return ``"mineru"`` / ``"markdownify"`` / ``None`` for a given path."""
    ext = _normalize_extension(path.suffix)
    if ext in {_normalize_extension(e) for e in html_extensions}:
        return "markdownify"
    if ext in {_normalize_extension(e) for e in extensions}:
        return "mineru"
    return None


def convert_file(
    input_path: Path,
    output_dir: Path,
    *,
    extensions: Iterable[str] | None = None,
    html_extensions: Iterable[str] | None = None,
    runner: MineruRunner | None = None,
) -> ConvertResult:
    """Convert a single file by extension routing + write a provenance sidecar.

    HTML files are handled in-process via markdownify; all other supported
    extensions go through the MinerU CLI. The sidecar ``<stem>.mineru.json``
    is written next to the produced ``.md``.
    """
    extensions = extensions if extensions is not None else _cfg.PREPROCESS_EXTENSIONS
    html_extensions = (
        html_extensions if html_extensions is not None else _cfg.PREPROCESS_HTML_EXTENSIONS
    )

    target = _is_supported(input_path, extensions, html_extensions)
    if target is None:
        raise PreprocessError(f"Unsupported file type for preprocess: {input_path}")

    if target == "markdownify":
        result = _html_to_markdown(input_path, output_dir)
    else:
        runner = runner or MineruRunner()
        result = runner.convert(input_path, output_dir)

    if result.output_file:
        _write_sidecar(Path(result.output_file), result)
    return result


def _iter_candidate_files(
    input_dir: Path,
    extensions: Iterable[str],
    html_extensions: Iterable[str],
) -> list[Path]:
    """List every file under ``input_dir`` whose extension is supported."""
    all_exts = {_normalize_extension(e) for e in extensions} | {
        _normalize_extension(e) for e in html_extensions
    }
    out: list[Path] = []
    for path in sorted(input_dir.rglob("*")):
        if not path.is_file():
            continue
        if _normalize_extension(path.suffix) in all_exts:
            out.append(path)
    return out


def convert_directory(
    input_dir: Path,
    output_dir: Path,
    extensions: Iterable[str] | None = None,
    html_extensions: Iterable[str] | None = None,
    *,
    max_workers: int | None = None,
    runner: MineruRunner | None = None,
    fail_fast: bool | None = None,
) -> PreprocessManifest:
    """Convert every supported file under ``input_dir`` into ``output_dir``.

    Parallelism via ``ThreadPoolExecutor`` (Invariant 12). Per-file failures
    are recorded in ``manifest.failed`` and (if ``fail_fast`` is True) abort
    the run by re-raising the first error.

    Relative directory structure is preserved: ``input_dir/a/b.pdf`` →
    ``output_dir/a/b.md``.
    """
    extensions = extensions if extensions is not None else _cfg.PREPROCESS_EXTENSIONS
    html_extensions = (
        html_extensions if html_extensions is not None else _cfg.PREPROCESS_HTML_EXTENSIONS
    )
    max_workers = max_workers if max_workers is not None else _cfg.PREPROCESS_MAX_WORKERS
    fail_fast = fail_fast if fail_fast is not None else _cfg.PREPROCESS_FAIL_FAST
    runner = runner or MineruRunner()

    output_dir.mkdir(parents=True, exist_ok=True)

    files = _iter_candidate_files(input_dir, extensions, html_extensions)
    if not files:
        log.info("preprocess: no candidate files in %s", input_dir)
        return PreprocessManifest()

    log.info(
        "preprocess: converting %d file(s) from %s into %s (workers=%d)",
        len(files),
        input_dir,
        output_dir,
        max_workers,
    )

    manifest = PreprocessManifest()

    def _job(src: Path) -> tuple[Path, ConvertResult | None, Exception | None]:
        rel_parent = src.parent.relative_to(input_dir)
        out_subdir = output_dir / rel_parent
        try:
            res = convert_file(
                src,
                out_subdir,
                extensions=extensions,
                html_extensions=html_extensions,
                runner=runner,
            )
            return src, res, None
        except Exception as exc:  # noqa: BLE001 — capture all per-file errors
            return src, None, exc

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = {pool.submit(_job, f): f for f in files}
        for fut in as_completed(futures):
            src, res, exc = fut.result()
            rel = str(src.relative_to(input_dir))
            if exc is not None:
                log.warning("preprocess: failed %s — %s", rel, exc)
                manifest.failed[rel] = str(exc)
                if fail_fast:
                    raise exc
                continue
            if res is None:
                manifest.skipped.append(rel)
                continue
            manifest.converted[rel] = res
            log.info(
                "preprocess: converted %s -> %s (%.2fs)", rel, res.output_file, res.duration_seconds
            )

    return manifest
