from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.orphan_connector import score_orphan_candidates_v2

log = get("mykg.steps.orphan_score")


def run_orphan_score(ctx: PipelineContext) -> None:
    if not _cfg.ORPHAN_PASS_ENABLED:
        log.info("Step orphan_score — skipped (orphan_pass.enabled: false)")
        (ctx.intermediate_dir / "orphan_candidates.json").write_text(
            json.dumps({"groups": [], "schema_gap_orphans": []}, indent=_cfg.JSON_INDENT),
            encoding="utf-8",
        )
        return

    nodes = ctx.nodes
    if nodes is None:
        nodes = json.loads((ctx.intermediate_dir / "nodes.json").read_text(encoding="utf-8"))

    edge_metadata = ctx.edge_metadata
    if edge_metadata is None:
        edge_metadata = json.loads((ctx.intermediate_dir / "edge_metadata.json").read_text(encoding="utf-8"))

    chunk_node_index = ctx.chunk_node_index
    if chunk_node_index is None:
        index_path = ctx.intermediate_dir / "chunk_node_index.json"
        if not index_path.exists():
            raise FileNotFoundError(
                "intermediate/chunk_node_index.json not found. "
                "Re-run from --from-step pass2 to regenerate it."
            )
        chunk_node_index = json.loads(index_path.read_text(encoding="utf-8"))

    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text(encoding="utf-8"))

    failed_chunks: list[dict] = []
    failed_path = ctx.intermediate_dir / "failed_chunks.json"
    if failed_path.exists() and _cfg.ORPHAN_BLANK_RECOVERY_ENABLED:
        failed_chunks = json.loads(failed_path.read_text(encoding="utf-8"))

    file_manifest = ctx.file_contents
    if file_manifest is None:
        manifest_path = ctx.intermediate_dir / "file_manifest.json"
        if manifest_path.exists():
            file_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    groups, unresolvable_orphans = score_orphan_candidates_v2(
        nodes,
        edge_metadata,
        chunk_node_index,
        schema,
        failed_chunks=failed_chunks,
        file_manifest=file_manifest,
    )

    (ctx.intermediate_dir / "nodes.json").write_text(json.dumps(nodes, indent=_cfg.JSON_INDENT), encoding="utf-8")
    ctx.nodes = nodes

    payload = {
        "groups": [g.model_dump() for g in groups],
        "schema_gap_orphans": [],
    }
    (ctx.intermediate_dir / "orphan_candidates.json").write_text(
        json.dumps(payload, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )

    # Write advisory events for orphans with no resolvable source chunk.
    if unresolvable_orphans:
        orphan_log_path = ctx.intermediate_dir / "orphan_log.json"
        existing: list[dict] = []
        if orphan_log_path.exists():
            try:
                existing = json.loads(orphan_log_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = []
        for orphan_id in unresolvable_orphans:
            existing.append({"event": "orphan_unconnectable", "orphan_id": orphan_id})
        orphan_log_path.write_text(json.dumps(existing, indent=_cfg.JSON_INDENT), encoding="utf-8")

    total_orphans = sum(len(g.orphan_ids) for g in groups)
    blank_groups = sum(1 for g in groups if g.is_blank_response)
    log.info(
        "Step orphan_score — %d orphan(s) in %d group(s) (%d blank-response group(s)), "
        "%d unresolvable orphan(s) logged as advisory",
        total_orphans,
        len(groups),
        blank_groups,
        len(unresolvable_orphans),
    )
