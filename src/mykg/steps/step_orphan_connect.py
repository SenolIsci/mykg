from __future__ import annotations

import hashlib
import json

from mykg import config as _cfg
from mykg.logging import get
from mykg.orchestrator import PipelineContext, SchemaUpdatedError
from mykg.orphan_connector import (
    OrphanChunkGroup,
    SchemaGapOrphan,
    build_chunk_texts,
    confirm_orphan_chunk_groups,
    propose_schema_additions,
)
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.steps.orphan_connect")


def _edge_id(edge: dict) -> str:
    sep = _cfg.ASSEMBLY_EDGE_DEDUP_SEPARATOR
    key_str = edge["type"] + sep + edge["from"] + sep + edge["to"]
    digest = hashlib.sha256(key_str.encode()).hexdigest()
    return _cfg.ASSEMBLY_EDGE_ID_PREFIX + digest[: _cfg.ASSEMBLY_EDGE_ID_HEX_LENGTH]


def run_orphan_connect(ctx: PipelineContext) -> None:
    if not _cfg.ORPHAN_PASS_ENABLED:
        log.info("Step orphan_connect — skipped (orphan_pass.enabled: false)")
        atomic_write_json(ctx.intermediate_dir / "orphan_connections.json", {})
        atomic_write_json(ctx.intermediate_dir / "orphan_log.json", [])
        return

    raw_payload = json.loads((ctx.intermediate_dir / "orphan_candidates.json").read_text())
    groups = [OrphanChunkGroup(**g) for g in raw_payload.get("groups", [])]
    schema_gap_orphans = [SchemaGapOrphan(**g) for g in raw_payload.get("schema_gap_orphans", [])]

    nodes = ctx.nodes
    if nodes is None:
        nodes = json.loads((ctx.intermediate_dir / "nodes.json").read_text())

    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())

    file_manifest = ctx.file_contents
    if file_manifest is None:
        manifest_path = ctx.intermediate_dir / "file_manifest.json"
        if manifest_path.exists():
            file_manifest = json.loads(manifest_path.read_text())

    chunk_texts: dict[str, str] = build_chunk_texts(file_manifest) if file_manifest else {}
    if not chunk_texts:
        log.warning("Step orphan_connect — no file_manifest; LLM receives no source text context")

    # Additive sweep: load previously confirmed edges as a seed so that only
    # unresolved groups are re-sent to the LLM.
    # Triggered by --from-step orphan_connect_incremental (ctx.orphan_incremental=True).
    # Schema-gap restarts always do a full re-run (seed not loaded).
    prior_connections: dict[str, dict] = {}
    orphan_connections_path = ctx.intermediate_dir / "orphan_connections.json"
    if ctx.orphan_incremental and orphan_connections_path.exists():
        prior_connections = json.loads(orphan_connections_path.read_text())

    already_connected: set[str] = set()
    for edge in prior_connections.values():
        already_connected.add(edge["from"])
        already_connected.add(edge["to"])

    unresolved_groups = [
        g for g in groups if not all(oid in already_connected for oid in g.orphan_ids)
    ]
    skipped_groups = len(groups) - len(unresolved_groups)
    if skipped_groups:
        log.info(
            "Step orphan_connect — %d group(s) already resolved; passing %d unresolved group(s) to LLM",
            skipped_groups,
            len(unresolved_groups),
        )

    confirmed, rejections = confirm_orphan_chunk_groups(
        unresolved_groups,
        nodes,
        schema,
        ctx.adapter,
        chunk_texts=chunk_texts,
        error_gate=ctx.error_gate,
    )

    atomic_write_json(ctx.intermediate_dir / "nodes.json", nodes)
    ctx.nodes = nodes

    # Seed from prior run; new confirmations are overlaid (dedup by ID).
    orphan_connections: dict[str, dict] = dict(prior_connections)
    orphan_log: list[dict] = []
    confirmed_orphan_ids: set[str] = set(already_connected)

    for edge in confirmed:
        eid = _edge_id(edge)
        stored = {k: v for k, v in edge.items() if not k.startswith("_")}
        stored["id"] = eid
        orphan_connections[eid] = stored
        confirmed_orphan_ids.add(edge["from"])
        confirmed_orphan_ids.add(edge["to"])
        orphan_log.append(
            {
                "event": "orphan_edge_added",
                "id": eid,
                "type": edge["type"],
                "from": edge["from"],
                "to": edge["to"],
                "confidence": edge["confidence"],
                "rationale": edge.get("_rationale", ""),
                "llm_confidence": edge.get("_llm_confidence", 0.0),
                "chunk_key": edge.get("_chunk_key", ""),
            }
        )

    for rejection in rejections:
        orphan_log.append(
            {
                "event": "orphan_edge_rejected",
                "orphan_id": rejection["orphan_id"],
                "candidate_id": rejection.get("candidate_id"),
                "reason": rejection["reason"],
            }
        )

    # Audit trail: emit retained entries for edges carried over from a prior sweep.
    new_edge_ids = {_edge_id(e) for e in confirmed}
    for eid, edge in prior_connections.items():
        if eid not in new_edge_ids:
            orphan_log.append(
                {
                    "event": "orphan_edge_retained",
                    "id": eid,
                    "type": edge["type"],
                    "from": edge["from"],
                    "to": edge["to"],
                    "confidence": edge["confidence"],
                }
            )

    edge_metadata_path = ctx.intermediate_dir / "edge_metadata.json"
    edge_metadata = json.loads(edge_metadata_path.read_text())
    skipped = 0
    for eid, edge in orphan_connections.items():
        if eid in edge_metadata:
            skipped += 1
            continue
        edge_metadata[eid] = edge

    atomic_write_json(edge_metadata_path, edge_metadata)
    ctx.edge_metadata = edge_metadata

    atomic_write_json(ctx.intermediate_dir / "orphan_log.json", orphan_log)
    atomic_write_json(ctx.intermediate_dir / "orphan_connections.json", orphan_connections)

    log.info(
        "Step orphan_connect — %d edge(s) added to edge_metadata.json (%d skipped as duplicates)",
        len(orphan_connections) - skipped,
        skipped,
    )

    node_by_id = {n["id"]: n for n in nodes}
    all_orphan_ids = {oid for g in groups for oid in g.orphan_ids}
    for oid in all_orphan_ids - confirmed_orphan_ids:
        node = node_by_id.get(oid)
        schema_gap_orphans.append(
            SchemaGapOrphan(
                orphan_id=oid,
                orphan_type=node.get("type", "") if node else "",
                orphan_name=oid,
                cooccurring_types=[],
                shared_chunks=[g.chunk_key for g in groups if oid in g.orphan_ids],
            )
        )
        log.info("Step orphan_connect — %s: no edges confirmed; promoted to schema-gap orphan", oid)

    if schema_gap_orphans:
        if _cfg.ORPHAN_SCHEMA_MAX_RESTARTS == 0:
            log.debug(
                "Step orphan_connect — %d schema-gap orphan(s) found but "
                "schema_max_restarts=0; skipping schema proposal LLM call.",
                len(schema_gap_orphans),
            )
            atomic_write_json(
                ctx.intermediate_dir / "schema_gap_proposals.json",
                {"new_properties": []},
            )
            return
        log.info(
            "Step orphan_connect — %d schema-gap orphan(s); "
            "calling LLM to propose schema additions",
            len(schema_gap_orphans),
        )
        proposal = propose_schema_additions(schema_gap_orphans, schema, ctx.adapter, chunk_texts)
        atomic_write_json(
            ctx.intermediate_dir / "schema_gap_proposals.json",
            proposal or {"new_properties": []},
        )

        if proposal and proposal.get("new_properties"):
            new_props = proposal["new_properties"]
            existing_names = {p["name"] for p in schema.get("properties", [])}
            added: list[str] = []
            for prop in new_props:
                if prop.get("name") and prop["name"] not in existing_names:
                    schema.setdefault("properties", []).append(prop)
                    existing_names.add(prop["name"])
                    added.append(prop["name"])

            if added:
                from mykg.schema_history import TRIGGER_SCHEMA_GAP, write_schema

                write_schema(schema, ctx.intermediate_dir, TRIGGER_SCHEMA_GAP)
                log.info(
                    "Step orphan_connect — schema.json updated with "
                    "%d new property/properties: %s. Triggering Re-entry A from pass2.",
                    len(added),
                    added,
                )
                raise SchemaUpdatedError(added, gap_orphans=schema_gap_orphans)
