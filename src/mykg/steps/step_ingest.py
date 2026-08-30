from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, TypeVar

from mykg import config as _cfg
from mykg.chunker import chunk_file
from mykg.chunker import count_tokens as _token_count
from mykg.logging import get
from mykg.orchestrator import PipelineContext

log = get("mykg.steps.ingest")

_T = TypeVar("_T")


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()


def _ingest_file(md_file: Path, input_dir: Path) -> tuple[str, str, str, list]:
    """Pure worker — no shared-state writes. Returns (rel, content, sha256, chunks)."""
    rel = str(md_file.relative_to(input_dir))
    content = md_file.read_text(encoding="utf-8")
    sha = _sha256(content)
    chunks = chunk_file(rel, content)
    return (rel, content, sha, chunks)


def _read_and_hash(md_file: Path, input_dir: Path) -> tuple[str, str, str]:
    """Lightweight worker for append mode — no chunk_file call."""
    rel = str(md_file.relative_to(input_dir))
    content = md_file.read_text(encoding="utf-8")
    sha = _sha256(content)
    return (rel, content, sha)


def _run_parallel(
    worker: Callable[..., _T],
    md_files: list[Path],
    input_dir: Path,
    max_workers: int,
) -> dict[str, _T]:
    """Dispatch worker(md_file, input_dir) for each file in parallel.

    Returns a mapping of rel-path → worker result, skipping files that raise
    OSError or UnicodeDecodeError (warning logged for each skipped file).
    """
    results: dict[str, _T] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(worker, md_file, input_dir): md_file for md_file in md_files
        }
        for future in as_completed(future_to_file):
            md_file = future_to_file[future]
            try:
                result = future.result()
                rel = result[0]  # first element is always the relative path
                results[rel] = result
            except (OSError, UnicodeDecodeError) as exc:
                log.warning("  skipping %s — %s", md_file, exc)
    return results


def _load_manifest(manifest_path) -> dict[str, dict]:
    raw: dict = json.loads(manifest_path.read_text(encoding="utf-8"))
    migrated = False
    result: dict[str, dict] = {}
    for filename, value in raw.items():
        if isinstance(value, str):
            content = value
            result[filename] = {
                "content": content,
                "sha256": _sha256(content),
                "token_count": _token_count(content),
            }
            migrated = True
        else:
            if "token_count" not in value:
                value["token_count"] = _token_count(value["content"])
                migrated = True
            result[filename] = value
    if migrated:
        manifest_path.write_text(json.dumps(result, indent=_cfg.JSON_INDENT), encoding="utf-8")
        log.info("step_ingest — migrated file_manifest.json to dict format")
    return result


def run_ingest(ctx: PipelineContext) -> None:
    if ctx.append:
        _run_append_ingest(ctx)
        return

    md_files = sorted(ctx.input_dir.rglob("*.md"))
    log.info(
        "Step 1 — found %d input file(s): %s",
        len(md_files),
        [str(f.relative_to(ctx.input_dir)) for f in md_files],
    )

    raw = _run_parallel(_ingest_file, md_files, ctx.input_dir, ctx.ingest_workers)

    # Merge in sorted order for deterministic Pass 1 batching
    ctx.all_chunks = []
    ctx.file_contents = {}
    manifest: dict[str, dict] = {}
    for rel in sorted(raw.keys()):
        _, content, sha, chunks = raw[rel]
        ctx.file_contents[rel] = content
        manifest[rel] = {"content": content, "sha256": sha, "token_count": _token_count(content)}
        ctx.all_chunks.extend(chunks)
        log.debug("  %s → %d chunk(s)", rel, len(chunks))

    # Belt-and-suspenders guard: ensure chunk order is deterministic
    ctx.all_chunks.sort(key=lambda c: (c.source_file, c.chunk_index))

    log.info("Step 1 — %d total chunk(s) ready for Pass 1", len(ctx.all_chunks))

    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps(manifest, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )
    log.debug("Step 1 — file_manifest.json written (%d file(s))", len(ctx.file_contents))

    if ctx.base_schema is not None:
        _write_base_schema_parsed(ctx)

    if ctx.thesaurus is not None:
        _write_thesaurus_parsed(ctx)


def _run_append_ingest(ctx: PipelineContext) -> None:
    manifest_path = ctx.intermediate_dir / "file_manifest.json"
    if not manifest_path.exists():
        raise RuntimeError("No existing pipeline found. Run without --append first.")

    manifest = _load_manifest(manifest_path)

    md_files = sorted(ctx.input_dir.rglob("*.md"))
    new_files: list[str] = []
    modified_files: list[str] = []
    changed: set[str] = set()

    read_raw = _run_parallel(_read_and_hash, md_files, ctx.input_dir, ctx.ingest_workers)

    for filename in sorted(read_raw.keys()):
        _, content, sha = read_raw[filename]
        if filename not in manifest:
            new_files.append(filename)
            changed.add(filename)
            manifest[filename] = {
                "content": content,
                "sha256": sha,
                "token_count": _token_count(content),
            }
        elif manifest[filename]["sha256"] != sha:
            modified_files.append(filename)
            if ctx.sync:
                changed.add(filename)
                manifest[filename] = {
                    "content": content,
                    "sha256": sha,
                    "token_count": _token_count(content),
                }
            # Without --sync the entry is left ENTIRELY untouched (D58). Freezing
            # only sha256 while refreshing content would leave a self-inconsistent
            # entry: downstream readers (grow-schema Pass 1, build_chunk_texts,
            # the MCP server) consume `content` without re-hashing, so chunk keys
            # would resolve against text that never produced the stored nodes.
            # Leaving it stale keeps manifest and raw_extractions.json agreeing,
            # and the file re-reports as modified every run until --sync runs.

    # Deleted files: in the manifest but no longer on disk. Detection always
    # runs; only the eviction is gated on --sync (the warning below covers the
    # unflagged case). Popping here is what makes the deletion durable — the
    # manifest is the corpus definition every later step reads — and it also
    # fixes the unextracted-recovery pass below for free, since a popped file
    # is no longer iterated there.
    deleted = set(manifest) - set(read_raw)
    if ctx.sync:
        for filename in deleted:
            manifest.pop(filename, None)
        ctx.deleted_files = (ctx.deleted_files or set()) | deleted

    manifest_path.write_text(json.dumps(manifest, indent=_cfg.JSON_INDENT), encoding="utf-8")

    # Also pick up any manifest files missing from raw_extractions.json — this
    # happens when a previous append run was interrupted after ingest but before
    # pass2, or when output files were deleted while the manifest was left intact.
    raw_path = ctx.intermediate_dir / "raw_extractions.json"
    unextracted: list[str] = []
    extracted: set[str] | None = None
    if raw_path.exists():
        try:
            existing_raw: dict = json.loads(raw_path.read_text(encoding="utf-8"))
            extracted = set(existing_raw)
        except (json.JSONDecodeError, OSError):
            extracted = None
    else:
        # raw_extractions.json is absent, but that does NOT mean nothing was
        # extracted: a schema restart (Re-entry A) unlinks it while deliberately
        # preserving the per-file shards. Treating absence as "re-extract
        # everything" would silently re-run the whole corpus at full LLM cost on
        # the second pass of a restart. Fall back to the shard directory, which
        # is the real record of what has been extracted.
        shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
        extracted = set()
        for shard_file in shard_dir.glob("*.json") if shard_dir.is_dir() else ():
            try:
                shard = json.loads(shard_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            fname = shard.get("_fname")
            if fname:
                extracted.add(fname)

    if extracted is not None:
        for filename in manifest:
            if filename not in extracted and filename not in changed:
                unextracted.append(filename)
                changed.add(filename)

    ctx.append_new_files = changed

    log.info(
        "append_ingest: %d new file(s), %d modified file(s), %d deleted file(s), "
        "%d unextracted file(s)",
        len(new_files),
        len(modified_files),
        len(deleted),
        len(unextracted),
    )

    # Discovery warning: detection ran, but without --sync nothing was acted on.
    # This is what makes the flag findable at the moment it matters — a user who
    # expected --append to pick up an edit sees exactly why it did not land.
    # Recovery files are reported separately: they are re-extracted regardless of
    # --sync, so calling them "modified" would contradict the rest of the message.
    if not ctx.sync and (modified_files or deleted):
        lines = ["file(s) in the graph no longer match the source folder:"]
        if modified_files:
            lines.append("  modified: %s" % ", ".join(sorted(modified_files)))
        if deleted:
            lines.append("  deleted:  %s" % ", ".join(sorted(deleted)))
        lines.append("Re-run with --sync to reconcile them.")
        log.warning(
            "%d %s",
            len(modified_files) + len(deleted),
            "\n         ".join(lines),
        )

    if not changed:
        log.info("Nothing to append, all files up to date")


def _write_base_schema_parsed(ctx: PipelineContext) -> None:
    data = {
        "source": ctx.base_schema.get("_source", "unknown"),
        "locked_classes": ctx.base_schema.get("locked_classes", {}),
        "locked_properties": ctx.base_schema.get("locked_properties", {}),
    }
    (ctx.intermediate_dir / "base_schema_parsed.json").write_text(
        json.dumps(data, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )
    n_classes = len(data["locked_classes"])
    n_props = len(data["locked_properties"])
    n_attrs = sum(len(c.get("attributes", [])) for c in data["locked_classes"].values())
    log.info(
        "Step 1 — base_schema_parsed.json written "
        "(source: %s, %d locked class(es), %d locked object property(ies), "
        "%d locked datatype attribute(s))",
        data["source"],
        n_classes,
        n_props,
        n_attrs,
    )


def _write_thesaurus_parsed(ctx: PipelineContext) -> None:
    thes = ctx.thesaurus
    relations_used = []
    if thes.has_exact_relations():
        relations_used.append("skos:exactMatch")
    if thes.has_close_relations():
        relations_used.append("skos:closeMatch")
    if thes.has_broader_relations():
        relations_used.append("skos:broader")
    if thes.has_narrower_relations():
        relations_used.append("skos:narrower")
    data = {
        "source": getattr(thes, "source_path", "unknown"),
        "term_count": thes.term_count,
        "relations_used": relations_used,
    }
    (ctx.intermediate_dir / "thesaurus_parsed.json").write_text(
        json.dumps(data, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )
    log.info("Step 1 — thesaurus_parsed.json written")
