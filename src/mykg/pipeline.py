from __future__ import annotations

from mykg.orchestrator import Step
from mykg.steps.step_assemble import run_assemble
from mykg.steps.step_ingest import run_ingest
from mykg.steps.step_normalize import run_normalize_names
from mykg.steps.step_orphan_connect import run_orphan_connect
from mykg.steps.step_orphan_score import run_orphan_score
from mykg.steps.step_pass1 import run_pass1_step
from mykg.steps.step_pass2 import run_pass2_step, run_schema_flatten
from mykg.steps.step_schema import run_human_review, run_schema_validate
from mykg.steps.step_validate_graph import run_validate_graph

STEPS: list[Step] = [
    Step(name="ingest", fn=run_ingest, outputs=["file_manifest.json"]),
    Step(
        name="pass1",
        fn=run_pass1_step,
        outputs=["schema.json", "schema.ttl"],
        is_llm_step=True,
    ),
    Step(
        name="schema_validate",
        fn=run_schema_validate,
        outputs=["schema_validate.done"],
        is_llm_step=False,
        blocking=False,
    ),
    Step(
        name="human_review",
        fn=run_human_review,
        outputs=["schema_approved.flag"],
        requires_review_flag=True,
    ),
    Step(name="schema_flatten", fn=run_schema_flatten, outputs=["flattened_schema.json"]),
    Step(
        name="pass2",
        fn=run_pass2_step,
        outputs=[
            "raw_extractions.done",
            "raw_extractions.json",
            "chunk_node_index.json",
            "failed_chunks.json",
        ],
        is_llm_step=True,
    ),
    Step(
        name="normalize_names",
        fn=run_normalize_names,
        outputs=["name_normalization.json", "chunk_node_index.json"],
        is_llm_step=True,
    ),
    Step(
        name="assemble",
        fn=run_assemble,
        outputs=["edge_metadata.json", "nodes.json", "merge_log.json"],
    ),
    Step(
        name="orphan_score",
        fn=run_orphan_score,
        outputs=["orphan_candidates.json", "nodes.json"],
        is_llm_step=False,
        blocking=False,
    ),
    Step(
        name="orphan_connect",
        fn=run_orphan_connect,
        outputs=["orphan_connections.json", "orphan_log.json", "schema_gap_proposals.json"],
        is_llm_step=True,
        blocking=False,
    ),
    Step(
        name="validate_graph",
        fn=run_validate_graph,
        outputs=[
            "nodes.jsonl",
            "edges.jsonl",
            "knowledge_graph.ttl",
            "knowledge_graph_validation.json",
        ],
        is_llm_step=False,
        blocking=False,
        output_location="output",
    ),
]

# Alias for backwards compatibility and test access
PIPELINE = STEPS
