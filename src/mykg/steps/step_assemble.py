from __future__ import annotations

import json

from mykg.assembler import assign_stable_ids, deduplicate_edges, deduplicate_nodes
from mykg.logging import get
from mykg.name_normalizer import build_alias_index
from mykg.orchestrator import PipelineContext
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.steps.assemble")


def _annotate_aliases(raw_with_ids: dict, alias_index: dict[str, dict[str, list[str]]]) -> None:
    """Attach aliases list to each node based on the inverted normalization map.

    Mutates raw_with_ids in place. Must run after assign_stable_ids so canonical
    names are already in node["attributes"]["name"]["value"].
    """
    for file_data in raw_with_ids.values():
        for node in file_data.get("nodes", []):
            ntype = node.get("type", "")
            type_index = alias_index.get(ntype, {})
            name_attr = node.get("attributes", {}).get("name", {})
            canonical = name_attr.get("value", "") if isinstance(name_attr, dict) else ""
            if aliases := sorted(type_index.get(str(canonical), [])):
                node["aliases"] = aliases


def run_assemble(ctx: PipelineContext) -> None:
    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    log.info("Steps 7–9 — assigning stable IDs and deduplicating …")
    raw_with_ids = assign_stable_ids(raw)

    # Derive aliases from name_normalization.json at assembly time (D29)
    norm_path = ctx.intermediate_dir / "name_normalization.json"
    if norm_path.exists():
        norm_data = json.loads(norm_path.read_text())
        norm_map = norm_data.get("mappings", {})
        if norm_map:
            alias_index = build_alias_index(norm_map)
            _annotate_aliases(raw_with_ids, alias_index)
            log.debug("Steps 7–9 — aliases annotated from name_normalization.json")

    ctx.nodes, node_log = deduplicate_nodes(raw_with_ids, confidence_agg=ctx.confidence_agg)
    ctx.edge_metadata, edge_log = deduplicate_edges(raw_with_ids, confidence_agg=ctx.confidence_agg)
    log.info(
        "Steps 7–9 — %d unique node(s), %d unique edge(s)",
        len(ctx.nodes),
        len(ctx.edge_metadata),
    )
    atomic_write_json(ctx.intermediate_dir / "edge_metadata.json", ctx.edge_metadata)
    atomic_write_json(ctx.intermediate_dir / "nodes.json", ctx.nodes)

    # Preserve synonym_collapse events written by pass1 (D21), then append
    # dedup events from this assembly run. On Re-entry C (--from-step assemble),
    # pass1 is skipped but its synonym events must survive in the audit log.
    merge_log_path = ctx.intermediate_dir / "merge_log.json"
    synonym_events: list[dict] = []
    if merge_log_path.exists():
        try:
            existing = json.loads(merge_log_path.read_text())
            synonym_events = [e for e in existing if e.get("event") == "synonym_collapse"]
        except (json.JSONDecodeError, ValueError):
            synonym_events = []
    merge_log = synonym_events + node_log + edge_log
    atomic_write_json(merge_log_path, merge_log)
    log.info("Steps 7–9 — merge_log.json written (%d entries)", len(merge_log))
