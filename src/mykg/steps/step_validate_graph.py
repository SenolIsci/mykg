from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.exporter import export_edges_jsonl, export_networkx, export_nodes_jsonl, export_ttl
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.ttl_validator import sanitize_abox_ttl, validate_knowledge_graph_ttl

log = get("mykg.steps.validate_graph")


def run_validate_graph(ctx: PipelineContext) -> None:
    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    nodes = ctx.nodes
    if nodes is None:
        nodes = json.loads((ctx.intermediate_dir / "nodes.json").read_text())
    edge_metadata = ctx.edge_metadata
    if edge_metadata is None:
        edge_metadata = json.loads((ctx.intermediate_dir / "edge_metadata.json").read_text())
    log.info("Steps 10–12 — validating and writing graph outputs …")
    declared_props = {p["name"] for p in schema.get("properties", [])}
    valid_edge_metadata = {
        eid: e for eid, e in edge_metadata.items() if e["type"] in declared_props
    }
    ttl = sanitize_abox_ttl(export_ttl(schema, nodes, valid_edge_metadata), schema)
    result = validate_knowledge_graph_ttl(ttl)

    (ctx.output_dir / "nodes.jsonl").write_text(export_nodes_jsonl(nodes))
    (ctx.output_dir / "edges.jsonl").write_text(export_edges_jsonl(valid_edge_metadata))
    (ctx.output_dir / "knowledge_graph.ttl").write_text(ttl)

    if _cfg.NETWORKX_ENABLED:
        written = export_networkx(nodes, valid_edge_metadata, ctx.output_dir)
        log.info("Step 12c — NetworkX export: %s", ", ".join(written))

    if _cfg.OBSIDIAN_ENABLED:
        from mykg.exporter import export_obsidian

        obs_written = export_obsidian(nodes, valid_edge_metadata, schema, ctx.output_dir)
        log.info("Step 12d — Obsidian vault export: %d notes written", len(obs_written))

    (ctx.output_dir / "knowledge_graph_validation.json").write_text(
        json.dumps(result, indent=_cfg.JSON_INDENT)
    )
    if result["valid"]:
        log.info("Step 12b — knowledge_graph.ttl valid")
    else:
        n_tbox = len(result["tbox_checks"]["errors"])
        n_abox = len(result["abox_checks"]["errors"])
        if n_tbox > 0:
            log.warning(
                "Step 12b — TTL TBox advisory errors (%d): %s. "
                "See output/knowledge_graph_validation.json. "
                "Re-entry C: fix raw_extractions.json or assembler logic, "
                "then re-run from --from-step assemble.",
                n_tbox,
                result["tbox_checks"]["errors"][0]["message"],
            )
        if n_abox > 0:
            log.warning(
                "Step 12b — TTL ABox advisory errors (%d) — see knowledge_graph_validation.json",
                n_abox,
            )
