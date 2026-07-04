from __future__ import annotations

import json

import click

from mykg import config as _cfg
from mykg.chunker import chunk_file
from mykg.exporter import export_ttl
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.pass1 import run_pass1
from mykg.schema_merge import harmonize_schema, merge_proposals, review_schema_quality
from mykg.steps.step_pass2 import _content_from_entry

log = get("mykg.steps.pass1")


def _write_batch_proposal_shard(
    intermediate_dir,
    batch_index: int,
    proposal: dict | None,
    error: str | None,
) -> None:
    """Write intermediate/pass1_batch_proposals/<index>.json — called
    incrementally as each batch resolves, so a crash mid-dispatch only loses
    batches still in flight (see run_pass1's on_batch_done callback).
    """
    shard_dir = intermediate_dir / "pass1_batch_proposals"
    shard_dir.mkdir(exist_ok=True)
    if proposal is not None:
        entry = {"batch_index": batch_index, "status": "ok", "proposal": proposal}
    else:
        entry = {"batch_index": batch_index, "status": "failed", "error": error or "unknown error"}
    (shard_dir / f"{batch_index:04d}.json").write_text(
        json.dumps(entry, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )


def _load_batch_proposals_for_merge(intermediate_dir) -> list[dict]:
    """Load every pass1_batch_proposals/*.json shard and return the "ok"
    proposals as a list, in the same shape run_pass1() would have returned —
    used by the merge_proposals --from-step entry point, which skips Pass 1
    LLM dispatch entirely and jumps straight to merge/harmonize/quality-review.
    """
    shard_dir = intermediate_dir / "pass1_batch_proposals"
    if not shard_dir.exists():
        raise click.ClickException(
            "--from-step merge_proposals requires intermediate/pass1_batch_proposals/ "
            "to already exist (from a prior Pass 1 run) — nothing to merge."
        )
    entries = []
    for shard_file in sorted(shard_dir.glob("*.json")):
        try:
            entry = json.loads(shard_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        entries.append(entry)
    proposals = [e["proposal"] for e in entries if e.get("status") == "ok"]
    if not proposals:
        raise click.ClickException(
            "--from-step merge_proposals found no successful batch proposals in "
            "intermediate/pass1_batch_proposals/ — nothing to merge."
        )
    return proposals


def run_pass1_step(ctx: PipelineContext) -> None:
    if ctx.pass1_merge_only:
        locked_classes = ctx.base_schema.get("locked_classes", {}) if ctx.base_schema else {}
        locked_properties = ctx.base_schema.get("locked_properties", {}) if ctx.base_schema else {}
        locked_block = ""
        if locked_classes or locked_properties:
            class_names = ", ".join(locked_classes.keys())
            prop_names = ", ".join(locked_properties.keys())
            locked_block = (
                "EXISTING SCHEMA (DO NOT RENAME, REMOVE, OR DUPLICATE THESE):\n"
                f"Classes: {class_names}\nProperties: {prop_names}\n"
                "You may add new subclasses, new properties, or new root classes.\n"
                "Do not output any of the locked names as new entries."
            )
        proposals = _load_batch_proposals_for_merge(ctx.intermediate_dir)
        log.info(
            "Step 2 — merge_proposals: reusing %d persisted batch proposal(s), "
            "skipping Pass 1 LLM dispatch entirely",
            len(proposals),
        )
        _merge_harmonize_and_write(ctx, proposals, locked_classes, locked_properties, locked_block)
        return

    if ctx.freeze_schema:
        if not ctx.base_schema:
            raise RuntimeError(
                "freeze_schema is set but no base_schema was provided. "
                "Pass --base-schema <path-to-ttl> on the CLI, or set base_schema on PipelineContext."
            )
        locked_classes = ctx.base_schema.get("locked_classes", {})
        locked_properties = ctx.base_schema.get("locked_properties", {})
        schema, _ = merge_proposals([], locked_classes, locked_properties, ctx.thesaurus)
        n_concepts = len(schema.get("concepts", []))
        n_props = len(schema.get("properties", []))
        log.info(
            "Step 2 — freeze-schema: using base schema verbatim (%d concept(s), %d property(ies))",
            n_concepts,
            n_props,
        )
        from mykg.schema_history import TRIGGER_FREEZE_SCHEMA, write_schema

        write_schema(schema, ctx.intermediate_dir, TRIGGER_FREEZE_SCHEMA)
        ttl = export_ttl(schema, [], {})
        (ctx.intermediate_dir / "schema.ttl").write_text(ttl, encoding="utf-8")
        merge_log_path = ctx.intermediate_dir / "merge_log.json"
        merge_log_path.write_text(json.dumps([], indent=_cfg.JSON_INDENT), encoding="utf-8")
        return

    # --append-with-grow-schema (D52): run the locked re-induction over ONLY the changed
    # files so the LLM sees just the new material when proposing additions. The append
    # ingest step does not chunk (it only hashes), so all_chunks must be (re)built here
    # from the changed files in the manifest. Falls through to the all-files paths below
    # when not in grow-schema mode.
    if ctx.grow_schema and ctx.append_new_files:
        manifest_path = ctx.intermediate_dir / "file_manifest.json"
        if not manifest_path.exists():
            raise RuntimeError(
                "grow_schema: file_manifest.json not found — re-run from the ingest step."
            )
        file_contents: dict[str, str | dict] = json.loads(manifest_path.read_text(encoding="utf-8"))
        ctx.all_chunks = []
        changed = [f for f in ctx.append_new_files if f in file_contents]
        for fname in changed:
            ctx.all_chunks.extend(chunk_file(fname, _content_from_entry(file_contents[fname])))
        log.info(
            "Step 2 — grow_schema: locked Pass 1 over %d changed file(s) → %d chunk(s)",
            len(changed),
            len(ctx.all_chunks),
        )
    # Recovery path for --from-step pass1: ingest was skipped but file_manifest.json exists.
    elif ctx.all_chunks is None:
        manifest_path = ctx.intermediate_dir / "file_manifest.json"
        if manifest_path.exists():
            file_contents = json.loads(manifest_path.read_text(encoding="utf-8"))
            ctx.all_chunks = []
            for fname, entry in file_contents.items():
                ctx.all_chunks.extend(chunk_file(fname, _content_from_entry(entry)))
            log.info(
                "Step 2 — restored %d chunk(s) from file_manifest.json (%d file(s))",
                len(ctx.all_chunks),
                len(file_contents),
            )
        else:
            raise RuntimeError(
                "all_chunks is None and intermediate/file_manifest.json not found — "
                "re-run from the ingest step."
            )

    locked_classes = ctx.base_schema.get("locked_classes", {}) if ctx.base_schema else {}
    locked_properties = ctx.base_schema.get("locked_properties", {}) if ctx.base_schema else {}
    locked_block = ""
    if locked_classes or locked_properties:
        class_names = ", ".join(locked_classes.keys())
        prop_names = ", ".join(locked_properties.keys())
        locked_block = (
            "EXISTING SCHEMA (DO NOT RENAME, REMOVE, OR DUPLICATE THESE):\n"
            f"Classes: {class_names}\nProperties: {prop_names}\n"
            "You may add new subclasses, new properties, or new root classes.\n"
            "Do not output any of the locked names as new entries."
        )

    log.info("Step 2 — running Pass 1 (schema induction) …")

    def _on_batch_done(idx: int, proposal: dict | None, error: str | None) -> None:
        _write_batch_proposal_shard(ctx.intermediate_dir, idx, proposal, error)

    proposals = run_pass1(
        ctx.all_chunks,
        ctx.adapter,
        locked_schema_block=locked_block,
        error_gate=ctx.error_gate,
        intermediate_dir=ctx.intermediate_dir,
        on_batch_done=_on_batch_done,
    )
    log.info("Step 2 — received %d schema proposal(s)", len(proposals))

    if not proposals:
        raise RuntimeError(
            "Pass 1 produced no valid proposals — all LLM batches failed to parse. "
            "Check LLM configuration and adapter logs."
        )

    _merge_harmonize_and_write(ctx, proposals, locked_classes, locked_properties, locked_block)


def _merge_harmonize_and_write(
    ctx: PipelineContext,
    proposals: list[dict],
    locked_classes: dict,
    locked_properties: dict,
    locked_block: str,
) -> None:
    """Merge batch proposals, harmonize, review quality, and write schema.json
    / schema.ttl. Shared by the normal Pass 1 path and the merge_proposals
    --from-step entry point (which supplies proposals loaded from disk
    instead of freshly dispatching Pass 1 LLM batches).
    """
    log.info("Step 3 — merging schema proposals …")
    schema, synonym_log = merge_proposals(
        proposals, locked_classes, locked_properties, ctx.thesaurus
    )
    n_concepts = len(schema.get("concepts", []))
    n_props = len(schema.get("properties", []))
    log.info("Step 3 — schema: %d concept(s), %d property(ies)", n_concepts, n_props)

    # Write synonym events. step_assemble reads these back and prepends them
    # to its own dedup events so the full audit trail is preserved on Re-entry C.
    merge_log_path = ctx.intermediate_dir / "merge_log.json"
    merge_log_path.write_text(json.dumps(synonym_log, indent=_cfg.JSON_INDENT), encoding="utf-8")
    if synonym_log:
        log.info("Step 3 — %d synonym collapse(s) logged to merge_log.json", len(synonym_log))

    from mykg.schema_history import (
        TRIGGER_PASS1_MERGE,
        TRIGGER_SCHEMA_HARMONIZE,
        TRIGGER_SCHEMA_QUALITY,
        write_schema,
    )

    write_schema(schema, ctx.intermediate_dir, TRIGGER_PASS1_MERGE)

    log.info("Step 3 — harmonizing schema (semantic near-duplicate collapse) …")
    schema = harmonize_schema(schema, proposals, ctx.adapter, locked_block=locked_block)
    n_concepts_h = len(schema.get("concepts", []))
    n_props_h = len(schema.get("properties", []))
    log.info(
        "Step 3 — schema after harmonization: %d concept(s), %d property(ies)",
        n_concepts_h,
        n_props_h,
    )
    write_schema(schema, ctx.intermediate_dir, TRIGGER_SCHEMA_HARMONIZE)

    log.info("Step 3 — reviewing schema quality …")
    schema = review_schema_quality(schema, ctx.adapter, locked_block=locked_block)
    n_concepts_q = len(schema.get("concepts", []))
    n_props_q = len(schema.get("properties", []))
    log.info(
        "Step 3 — schema after quality review: %d concept(s), %d property(ies)",
        n_concepts_q,
        n_props_q,
    )
    write_schema(schema, ctx.intermediate_dir, TRIGGER_SCHEMA_QUALITY)

    ttl = export_ttl(schema, [], {})
    (ctx.intermediate_dir / "schema.ttl").write_text(ttl, encoding="utf-8")
