from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.ids import stable_id
from mykg.logging import get
from mykg.name_normalizer import (
    apply_normalization_map,
    build_name_inventory,
    build_normalization_file,
    run_name_normalization,
)
from mykg.orchestrator import PipelineContext

log = get("mykg.steps.normalize")


def run_normalize_names(ctx: PipelineContext) -> None:
    norm_path = ctx.intermediate_dir / "name_normalization.json"

    if not _cfg.NORMALIZE_NAMES_ENABLED:
        log.info("Step 6b — normalize_names disabled; writing empty sentinel")
        norm_path.write_text(
            json.dumps({"metadata": {"enabled": False}, "mappings": {}}, indent=_cfg.JSON_INDENT),
            encoding="utf-8",
        )
        return

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text(encoding="utf-8"))
    inventory = build_name_inventory(raw)

    if not inventory:
        log.info("Step 6b — no named nodes found; writing empty sentinel")
        norm_path.write_text(json.dumps(build_normalization_file({}, {}), indent=_cfg.JSON_INDENT), encoding="utf-8")
        return

    log.info(
        "Step 6b — normalizing names across %d type(s), %d total names",
        len(inventory),
        sum(len(v) for v in inventory.values()),
    )

    norm_map, errors = run_name_normalization(inventory, ctx.adapter)

    for err in errors:
        log.warning("Step 6b — normalization warning: %s", err)

    payload = build_normalization_file(norm_map, inventory, validation_warnings=errors or None)
    norm_path.write_text(json.dumps(payload, indent=_cfg.JSON_INDENT), encoding="utf-8")
    log.info(
        "Step 6b — %d alias(es) mapped; name_normalization.json written",
        payload["metadata"]["aliases_mapped"],
    )

    if norm_map:
        normalized_raw = apply_normalization_map(raw, norm_map)
        (ctx.intermediate_dir / "raw_extractions.json").write_text(
            json.dumps(normalized_raw, indent=_cfg.JSON_INDENT), encoding="utf-8"
        )
        log.info("Step 6b — raw_extractions.json rewritten with canonical names")

        id_remap = {
            stable_id(type_name, alias): stable_id(type_name, canonical)
            for type_name, aliases in norm_map.items()
            for alias, canonical in aliases.items()
            if alias != canonical
        }

        chunk_idx_path = ctx.intermediate_dir / "chunk_node_index.json"
        if id_remap and chunk_idx_path.exists():
            chunk_idx = json.loads(chunk_idx_path.read_text(encoding="utf-8"))
            updated = {
                fname: {
                    chunk_key: [id_remap.get(nid, nid) for nid in ids]
                    for chunk_key, ids in chunks.items()
                }
                for fname, chunks in chunk_idx.items()
            }
            chunk_idx_path.write_text(json.dumps(updated, indent=_cfg.JSON_INDENT), encoding="utf-8")
            log.info(
                "Step 6b — chunk_node_index.json IDs remapped (%d ID(s) changed)", len(id_remap)
            )

        shard_dir = ctx.intermediate_dir / "chunk_index_shards"
        if id_remap and shard_dir.exists():
            for shard_file in shard_dir.glob("*.json"):
                shard = json.loads(shard_file.read_text(encoding="utf-8"))
                shard["data"] = {
                    chunk_key: [id_remap.get(nid, nid) for nid in ids]
                    for chunk_key, ids in shard["data"].items()
                }
                shard_file.write_text(json.dumps(shard, indent=_cfg.JSON_INDENT), encoding="utf-8")
            log.debug("Step 6b — chunk_index_shards updated")
