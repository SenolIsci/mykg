from __future__ import annotations

import json
import shutil

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.pass2 import run_pass2, run_pass2_batched
from mykg.pass2_concat import build_concat_batches, make_virtual_files
from mykg.schema_flattener import flatten_schema
from mykg.steps.grow_schema_backfill import compute_backfill_chunks

log = get("mykg.steps.pass2")


def _fname_slug(fname: str) -> str:
    return fname.replace("/", "_").replace("\\", "_").replace(" ", "_")


def run_schema_flatten(ctx: PipelineContext) -> None:
    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    flat = flatten_schema(schema)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps(flat, indent=_cfg.JSON_INDENT)
    )
    log.info("Step 5 — flattened %d concept(s)", len(flat))


def _load_manifest(ctx: PipelineContext) -> dict[str, str]:
    if ctx.file_contents is not None:
        return ctx.file_contents
    manifest_path = ctx.intermediate_dir / "file_manifest.json"
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text())
        ctx.file_contents = raw
        log.info("Step 6 — restored file_contents from file_manifest.json (%d file(s))", len(raw))
        return raw
    raise RuntimeError(
        "file_contents is None and intermediate/file_manifest.json not found — "
        "re-run from the ingest step."
    )


def _content_from_entry(entry: str | dict) -> str:
    return entry["content"] if isinstance(entry, dict) else entry


def run_pass2_step(ctx: PipelineContext) -> None:
    manifest = _load_manifest(ctx)
    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    flat = json.loads((ctx.intermediate_dir / "flattened_schema.json").read_text())
    _run(ctx, manifest, schema, flat)


def _run(
    ctx: PipelineContext,
    manifest: dict,
    schema: dict,
    flat: dict,
) -> None:
    raw_path = ctx.intermediate_dir / "raw_extractions.json"
    chunk_path = ctx.intermediate_dir / "chunk_node_index.json"

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"

    # Legacy migration: pre-existing concat sessions wrote shards keyed by virtual
    # batch names (concat_batch_*.md.json). Concat is now real-file-keyed; loading
    # those stale virtual shards would pollute existing_raw/raw_extractions.json with
    # vname keys. Detect and clear them once so the session rebuilds real-keyed.
    if _cfg.PASS2_PREP_MODE == "concat" and shard_dir.exists():
        legacy = list(shard_dir.glob("concat_batch_*.json"))
        if legacy:
            log.warning(
                "Step 6 — concat: detected %d legacy virtual-batch shard(s); "
                "clearing for real-keyed rebuild",
                len(legacy),
            )
            shutil.rmtree(shard_dir)
            if chunk_shard_dir.exists():
                shutil.rmtree(chunk_shard_dir)
            for stale in ("raw_extractions.json", "chunk_node_index.json", "pass2_concat_map.json"):
                (ctx.intermediate_dir / stale).unlink(missing_ok=True)

    existing_raw: dict = {}
    existing_chunk: dict = {}

    if shard_dir.exists():
        for shard_file in shard_dir.glob("*.json"):
            shard_content = json.loads(shard_file.read_text())
            existing_raw[shard_content["_fname"]] = shard_content["data"]
        for shard_file in chunk_shard_dir.glob("*.json") if chunk_shard_dir.exists() else []:
            shard_content = json.loads(shard_file.read_text())
            existing_chunk[shard_content["_fname"]] = shard_content["data"]
        log.debug("Step 6 — loaded %d shard(s) from %s", len(existing_raw), shard_dir)
    elif raw_path.exists():
        existing_raw = json.loads(raw_path.read_text())
        existing_chunk = json.loads(chunk_path.read_text()) if chunk_path.exists() else {}

    if ctx.append and ctx.append_new_files is not None:
        todo = {f: _content_from_entry(manifest[f]) for f in ctx.append_new_files if f in manifest}
    else:
        todo = {f: _content_from_entry(e) for f, e in manifest.items()}

    skip = set(existing_raw.keys())
    todo = {f: c for f, c in todo.items() if f not in skip}

    log.info(
        "Step 6 — %d file(s) already done, %d remaining",
        len(skip),
        len(todo),
    )

    # Surgical re-extraction: when schema_hints are present and shards already exist,
    # only re-run the specific chunks named in shared_chunks rather than all files.
    # This avoids paying full re-extraction cost on every schema-gap restart.
    hints = ctx.schema_hints or []
    reextract_chunks: dict[str, set[int]] | None = None
    if hints and existing_raw:
        reextract_chunks = {}
        for h in hints:
            for ck in h.get("shared_chunks", []):
                # chunk_key format: "filename::chunk_idx" (1-based)
                parts = ck.rsplit("::", 1)
                if len(parts) == 2:
                    fname, idx_str = parts
                    if fname in existing_raw:
                        reextract_chunks.setdefault(fname, set()).add(int(idx_str))
        if reextract_chunks:
            affected = {
                f: _content_from_entry(manifest[f]) for f in reextract_chunks if f in manifest
            }
            log.info(
                "Step 6 — schema-gap surgical re-extraction: %d file(s), chunks %s",
                len(affected),
                {f: sorted(idxs) for f, idxs in reextract_chunks.items()},
            )
            shard_dir.mkdir(exist_ok=True)
            chunk_shard_dir.mkdir(exist_ok=True)

            def _on_file_done_surgical(fname: str, result: dict, file_idx: dict) -> None:
                existing_raw[fname] = result
                existing_chunk[fname] = file_idx
                slug = _fname_slug(fname)
                (shard_dir / f"{slug}.json").write_text(
                    json.dumps({"_fname": fname, "data": result}, indent=_cfg.JSON_INDENT)
                )
                (chunk_shard_dir / f"{slug}.json").write_text(
                    json.dumps({"_fname": fname, "data": file_idx}, indent=_cfg.JSON_INDENT)
                )

            new_raw, new_chunk, _failed = run_pass2(
                affected,
                schema,
                flat,
                ctx.adapter,
                max_workers=ctx.pass2_workers,
                schema_hints=hints,
                on_file_done=_on_file_done_surgical,
                error_gate=ctx.error_gate,
                reextract_chunks=reextract_chunks,
                prior_extractions=existing_raw,
                prior_chunk_index=existing_chunk,
            )
            existing_raw.update(new_raw)
            existing_chunk.update(new_chunk)
            _log_and_write(ctx, existing_raw, existing_chunk)
            return

    # --append-with-grow-schema (D52): when the locked Pass 1 grew the schema,
    # surgically back-fill the OLD files so instances of the new types are picked up
    # there too. Changed files are excluded — they are (re-)extracted in full by the
    # todo path below against the already-grown schema. When the delta is empty this
    # is a no-op and the run collapses to a plain append (changed files only).
    if ctx.grow_schema and existing_raw:
        _grow_schema_backfill(ctx, manifest, schema, flat, existing_raw, existing_chunk)

    if not todo:
        _log_and_write(ctx, existing_raw, existing_chunk)
        return

    shard_dir.mkdir(exist_ok=True)
    chunk_shard_dir.mkdir(exist_ok=True)

    def _write_shard(fname: str, result: dict, file_idx: dict) -> None:
        slug = _fname_slug(fname)
        (shard_dir / f"{slug}.json").write_text(
            json.dumps({"_fname": fname, "data": result}, indent=_cfg.JSON_INDENT)
        )
        (chunk_shard_dir / f"{slug}.json").write_text(
            json.dumps({"_fname": fname, "data": file_idx}, indent=_cfg.JSON_INDENT)
        )

    def _on_file_done(fname: str, result: dict, file_idx: dict) -> None:
        existing_raw[fname] = result
        existing_chunk[fname] = file_idx
        _write_shard(fname, result, file_idx)

    if _cfg.PASS2_PREP_MODE == "concat":
        # Original concat behaviour: bin-pack WHOLE files into virtual batches
        # (dir+prefix grouping, never splitting a file at the packing stage), then
        # run_pass2 re-chunks each virtual file at window_tokens and makes one LLM
        # call per window. The ONLY change vs the original is shard keying: the
        # virtual-batch result is fanned out to one REAL-file-keyed shard per member
        # file (so --append change-detection, orphan-shard freedom, and the surgical
        # schema-gap path all work). concat_map is rebuilt in-memory each run; it is
        # not persisted (resumability now keys on real filenames).
        concat_map = build_concat_batches(todo, _cfg.PASS2_CONCAT_BATCH_TOKEN_TARGET)
        virtual_todo = make_virtual_files(todo, concat_map)
        log.info(
            "Step 6 — concat: %d real file(s) → %d virtual batch(es)",
            sum(len(e["files"]) for e in concat_map.values()),
            len(virtual_todo),
        )

        def _on_file_done_concat(vname: str, result: dict, file_idx: dict) -> None:
            # Fan the virtual-batch result out to each member real file. The
            # assembler's node/edge dedup collapses the duplication (same as
            # batch_chunks over-attribution).
            for real_fname in concat_map.get(vname, {}).get("files", [vname]):
                existing_raw[real_fname] = result
                existing_chunk[real_fname] = file_idx
                _write_shard(real_fname, result, file_idx)

        new_raw, new_chunk, _failed = run_pass2(
            virtual_todo,
            schema,
            flat,
            ctx.adapter,
            max_workers=ctx.pass2_workers,
            schema_hints=ctx.schema_hints or None,
            on_file_done=_on_file_done_concat,
            # skip_files omitted: virtual names regenerate each run; the real-file
            # todo filter above already removed already-done real files.
            error_gate=ctx.error_gate,
        )
    elif _cfg.PASS2_PREP_MODE == "batch_chunks":
        new_raw, new_chunk, _failed, batch_map = run_pass2_batched(
            todo,
            schema,
            flat,
            ctx.adapter,
            batch_token_target=_cfg.PASS2_BATCH_TOKEN_TARGET,
            per_file=_cfg.PASS2_BATCH_PER_FILE,
            max_workers=ctx.pass2_workers,
            schema_hints=ctx.schema_hints or None,
            on_file_done=_on_file_done,
            error_gate=ctx.error_gate,
            intermediate_dir=ctx.intermediate_dir,
            batch_retry_max=_cfg.PASS2_BATCH_RETRY_MAX,
        )
        (ctx.intermediate_dir / "pass2_batch_map.json").write_text(
            json.dumps(batch_map, indent=_cfg.JSON_INDENT)
        )
        log.info(
            "Step 6 — batch map: %d batch(es) written to pass2_batch_map.json",
            len(batch_map),
        )
    else:  # per_file
        new_raw, new_chunk, _failed = run_pass2(
            todo,
            schema,
            flat,
            ctx.adapter,
            max_workers=ctx.pass2_workers,
            schema_hints=ctx.schema_hints or None,
            on_file_done=_on_file_done,
            skip_files=skip,
            error_gate=ctx.error_gate,
        )

    if _cfg.PASS2_PREP_MODE != "concat":
        # concat's new_raw/new_chunk are keyed by virtual batch names; the fan-out
        # in _on_file_done_concat already populated existing_raw with real keys.
        existing_raw.update(new_raw)
        existing_chunk.update(new_chunk)
    _log_and_write(ctx, existing_raw, existing_chunk)


def _log_and_write(
    ctx: PipelineContext,
    raw: dict,
    chunk_node_index: dict,
) -> None:
    total_nodes = sum(len(v.get("nodes", [])) for v in raw.values())
    total_edges = sum(len(v.get("edges", [])) for v in raw.values())
    _log = log.warning if total_nodes == 0 and total_edges == 0 else log.info
    _log("Step 6 — extracted %d node(s), %d edge(s) (raw, total)", total_nodes, total_edges)
    (ctx.intermediate_dir / "raw_extractions.json").write_text(
        json.dumps(raw, indent=_cfg.JSON_INDENT)
    )
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps(chunk_node_index, indent=_cfg.JSON_INDENT)
    )
    (ctx.intermediate_dir / "raw_extractions.done").write_text("")
    ctx.raw_extractions = raw
    ctx.chunk_node_index = chunk_node_index


def _grow_schema_delta(base_schema: dict | None, schema: dict) -> tuple[list[str], list[dict]]:
    """Return (added_concepts, added_properties) of the grown schema vs the locked base.

    The locked base (ctx.base_schema) holds the ORIGINAL pre-growth vocabulary as
    locked_classes/locked_properties, so the delta is exactly what the locked Pass 1
    added. added_properties are the full property dicts from the grown schema (needed
    for domain/range), filtered to the newly-added names.
    """
    locked_classes = (base_schema or {}).get("locked_classes", {})
    locked_properties = (base_schema or {}).get("locked_properties", {})
    added_concepts = [
        c["type"] for c in schema.get("concepts", []) if c["type"] not in locked_classes
    ]
    added_properties = [
        p for p in schema.get("properties", []) if p["name"] not in locked_properties
    ]
    return added_concepts, added_properties


def _grow_schema_backfill(
    ctx: PipelineContext,
    manifest: dict,
    schema: dict,
    flat: dict,
    existing_raw: dict,
    existing_chunk: dict,
) -> None:
    """Surgically re-extract OLD files for newly-added schema types (D52, Invariant 16).

    Mutates existing_raw / existing_chunk in place and rewrites the affected shards.
    No-op when the schema did not grow, when back-fill is disabled (top_k == 0), or
    when no old chunk carries a relevant signal type. In every prep mode existing_raw
    and existing_chunk are keyed by real source filenames, so back-fill targets map
    directly to manifest entries.
    """
    added_concepts, added_properties = _grow_schema_delta(ctx.base_schema, schema)
    if not added_concepts and not added_properties:
        log.info("Step 6 — grow_schema: schema unchanged, no back-fill needed")
        return

    log.info(
        "Step 6 — grow_schema delta: +%d concept(s) %s, +%d property(ies) %s",
        len(added_concepts),
        added_concepts,
        len(added_properties),
        [p["name"] for p in added_properties],
    )

    top_k = _cfg.APPEND_GROW_SCHEMA_BACKFILL_TOP_K_CHUNKS_PER_TYPE
    backfill = compute_backfill_chunks(
        added_concepts, added_properties, schema, existing_chunk, top_k
    )
    changed = ctx.append_new_files or set()

    # Never re-extract the changed files here — they are (re-)extracted in full by the
    # normal todo path against the already-grown schema.
    backfill = {f: idxs for f, idxs in backfill.items() if f in existing_raw and f not in changed}
    if not backfill:
        log.info("Step 6 — grow_schema: no old chunks selected for back-fill")
        return

    affected = {f: _content_from_entry(manifest[f]) for f in backfill if f in manifest}
    if not affected:
        log.warning("Step 6 — grow_schema: back-fill targets not in manifest; skipping")
        return

    log.info(
        "Step 6 — grow_schema back-fill: re-extracting %d old file(s), chunks %s",
        len(affected),
        {f: sorted(idxs) for f, idxs in backfill.items()},
    )

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir(exist_ok=True)
    chunk_shard_dir.mkdir(exist_ok=True)

    def _on_file_done_backfill(fname: str, result: dict, file_idx: dict) -> None:
        existing_raw[fname] = result
        existing_chunk[fname] = file_idx
        slug = _fname_slug(fname)
        (shard_dir / f"{slug}.json").write_text(
            json.dumps({"_fname": fname, "data": result}, indent=_cfg.JSON_INDENT)
        )
        (chunk_shard_dir / f"{slug}.json").write_text(
            json.dumps({"_fname": fname, "data": file_idx}, indent=_cfg.JSON_INDENT)
        )

    new_raw, new_chunk, _failed = run_pass2(
        affected,
        schema,
        flat,
        ctx.adapter,
        max_workers=ctx.pass2_workers,
        on_file_done=_on_file_done_backfill,
        error_gate=ctx.error_gate,
        reextract_chunks=backfill,
        prior_extractions=existing_raw,
        prior_chunk_index=existing_chunk,
    )
    existing_raw.update(new_raw)
    existing_chunk.update(new_chunk)
