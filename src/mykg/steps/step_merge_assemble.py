"""Assembly step for the merge pipeline, with concept-type remapping.

Identical to ``step_assemble.run_assemble`` except for one thing: before stable
IDs are assigned, instances of any concept the schema merge collapsed are
rewritten to the surviving type. Because a stable ID is derived from
``node["type"]`` (D19), that rewrite is what turns ``employee-alice-chen`` and
``person-alice-chen`` into a single node instead of two.

The remap runs first and everything after it is the ordinary assembler:
``assign_stable_ids`` recomputes IDs and edge endpoints from the new types, and
``deduplicate_nodes`` collapses the pair through its existing rules — highest
confidence wins, two values both at confidence 1.0 concatenate, ``source_files``
and ``aliases`` union.

Merge pipeline only. ``extract-graph`` keeps ``run_assemble`` untouched.
"""

from __future__ import annotations

import json

from mykg.assembler import assign_stable_ids, deduplicate_edges, deduplicate_nodes
from mykg.logging import get
from mykg.merge_type_remap import apply_type_remap, load_type_remap
from mykg.name_normalizer import build_alias_index
from mykg.orchestrator import PipelineContext
from mykg.steps.step_assemble import SCHEMA_MERGE_EVENTS, _annotate_aliases
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.steps.merge_assemble")


def run_merge_assemble(ctx: PipelineContext) -> None:
    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text(encoding="utf-8"))

    # Collapsed-concept instances must be retyped before IDs are derived from
    # their type, or they keep a type the merged schema no longer declares.
    remap_events: list[dict] = []
    type_remap = load_type_remap(ctx.intermediate_dir)
    if type_remap:
        raw = apply_type_remap(raw, type_remap, remap_events)

    log.info("merge_assemble — assigning stable IDs and deduplicating …")
    raw_with_ids = assign_stable_ids(raw)

    # Derive aliases from name_normalization.json at assembly time (D29). Runs
    # after the remap so the index is consulted with the surviving type.
    norm_path = ctx.intermediate_dir / "name_normalization.json"
    if norm_path.exists():
        norm_data = json.loads(norm_path.read_text(encoding="utf-8"))
        norm_map = norm_data.get("mappings", {})
        if norm_map:
            alias_index = build_alias_index(norm_map)
            _annotate_aliases(raw_with_ids, alias_index)
            log.debug("merge_assemble — aliases annotated from name_normalization.json")

    ctx.nodes, node_log = deduplicate_nodes(raw_with_ids, confidence_agg=ctx.confidence_agg)
    ctx.edge_metadata, edge_log = deduplicate_edges(raw_with_ids, confidence_agg=ctx.confidence_agg)
    log.info(
        "merge_assemble — %d unique node(s), %d unique edge(s)",
        len(ctx.nodes),
        len(ctx.edge_metadata),
    )
    atomic_write_json(ctx.intermediate_dir / "edge_metadata.json", ctx.edge_metadata)
    atomic_write_json(ctx.intermediate_dir / "nodes.json", ctx.nodes)

    # Preserve schema-merge events from the merge_schema step, then append this
    # run's remap and dedup events.
    merge_log_path = ctx.intermediate_dir / "merge_log.json"
    synonym_events: list[dict] = []
    if merge_log_path.exists():
        try:
            existing = json.loads(merge_log_path.read_text(encoding="utf-8"))
            synonym_events = [e for e in existing if e.get("event") in SCHEMA_MERGE_EVENTS]
        except (json.JSONDecodeError, ValueError):
            synonym_events = []
    merge_log = synonym_events + remap_events + node_log + edge_log
    atomic_write_json(merge_log_path, merge_log)
    log.info("merge_assemble — merge_log.json written (%d entries)", len(merge_log))
