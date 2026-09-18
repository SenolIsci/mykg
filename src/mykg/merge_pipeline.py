from __future__ import annotations

from mykg.orchestrator import Step
from mykg.steps.step_merge_assemble import run_merge_assemble
from mykg.steps.step_merge_manifest import run_merge_manifest
from mykg.steps.step_merge_raw import run_merge_raw
from mykg.steps.step_merge_reextract import run_merge_reextract
from mykg.steps.step_merge_schema import run_merge_schema
from mykg.steps.step_merge_setup import run_merge_setup
from mykg.steps.step_orphan_connect import run_orphan_connect
from mykg.steps.step_orphan_score import run_orphan_score
from mykg.steps.step_pass2 import run_schema_flatten
from mykg.steps.step_schema import run_human_review, run_schema_validate
from mykg.steps.step_validate_graph import run_validate_graph

MERGE_STEPS: list[Step] = [
    # Phase 0 — load sessions, namespace shards, write source_map.json
    Step(
        name="merge_setup",
        fn=run_merge_setup,
        outputs=["source_map.json"],
    ),
    # Phase 1 — merge schemas + LLM harmonization + quality review
    Step(
        name="merge_schema",
        fn=run_merge_schema,
        outputs=["schema.json", "schema.ttl"],
        is_llm_step=True,
    ),
    # Phase 2 — RDFS validation of merged schema.ttl (non-blocking advisory)
    Step(
        name="schema_validate",
        fn=run_schema_validate,
        outputs=["schema_validate.done"],
        blocking=False,
    ),
    # Phase 3 — optional human review gate (only active when ctx.review=True)
    Step(
        name="human_review",
        fn=run_human_review,
        outputs=["schema_approved.flag"],
        requires_review_flag=True,
    ),
    # Phase 4 — flatten merged schema for LLM prompts
    Step(
        name="schema_flatten",
        fn=run_schema_flatten,
        outputs=["flattened_schema.json"],
    ),
    # Phase 5 — surgical/full re-extraction with merged schema
    Step(
        name="merge_reextract",
        fn=run_merge_reextract,
        outputs=["merge_reextract.done"],
        is_llm_step=True,
    ),
    # Phase 6 — namespace + merge raw_extractions from both sessions
    Step(
        name="merge_raw",
        fn=run_merge_raw,
        outputs=["raw_extractions.json", "raw_extractions.done", "chunk_node_index.json"],
    ),
    # Phase 7 — assign stable IDs, deduplicate nodes/edges
    Step(
        name="assemble",
        fn=run_merge_assemble,
        outputs=["edge_metadata.json", "nodes.json", "merge_log.json"],
    ),
    # Phase 8 — identify orphan nodes by source chunk (non-blocking)
    Step(
        name="orphan_score",
        fn=run_orphan_score,
        outputs=["orphan_candidates.json", "nodes.json"],
        is_llm_step=False,
        blocking=False,
    ),
    # Phase 9 — LLM confirms orphan edges and optionally extends schema (non-blocking)
    Step(
        name="orphan_connect",
        fn=run_orphan_connect,
        outputs=["orphan_connections.json", "orphan_log.json", "schema_gap_proposals.json"],
        is_llm_step=True,
        blocking=False,
    ),
    # Phase 10 — export nodes.jsonl, edges.jsonl, knowledge_graph.ttl (non-blocking)
    Step(
        name="validate_graph",
        fn=run_validate_graph,
        outputs=[
            "nodes.jsonl",
            "edges.jsonl",
            "knowledge_graph.ttl",
            "knowledge_graph_validation.json",
        ],
        blocking=False,
        output_location="output",
    ),
    # Phase 11 — write merge_manifest.json (non-blocking; informational)
    Step(
        name="merge_manifest",
        fn=run_merge_manifest,
        outputs=["merge_manifest.json"],
        blocking=False,
    ),
]
