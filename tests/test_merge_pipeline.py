from __future__ import annotations

import json
from pathlib import Path

from mykg.merge_context import MergeContext
from mykg.merge_pipeline import MERGE_STEPS
from mykg.merge_run import run_merge

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_NON_BLOCKING_STEPS = {s.name for s in MERGE_STEPS if not s.blocking}

_SCHEMA_A = {
    "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
    ],
}

_SCHEMA_B = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "belongs_to", "domain": "Person", "range": "Organization", "attributes": []}
    ],
}

_RAW_A = {
    "file_a.md": {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.9,
                "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                "source_files": ["file_a.md"],
            }
        ],
        "edges": [],
    }
}

_RAW_B = {
    "file_b.md": {
        "nodes": [
            {
                "id": "person-bob",
                "type": "Person",
                "confidence": 0.85,
                "attributes": {"name": {"value": "Bob", "confidence": 0.85}},
                "source_files": ["file_b.md"],
            }
        ],
        "edges": [],
    }
}

_PIPELINE_CFG = (
    "profile: test\n"
    "profiles:\n"
    "  test:\n"
    "    pipeline:\n"
    "      pass2:\n"
    "        prep_mode: per_file\n"
    "      merge_graphs:\n"
    "        reextraction_strategy: none\n"
)


def _make_session(sessions_root: Path, name: str, schema: dict, raw: dict) -> Path:
    session_root = sessions_root / name
    intermediate = session_root / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    (session_root / "output").mkdir(exist_ok=True)
    (session_root / "input").mkdir(exist_ok=True)
    (intermediate / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (intermediate / "raw_extractions.json").write_text(json.dumps(raw), encoding="utf-8")
    (session_root / "pipeline_config.yaml").write_text(_PIPELINE_CFG, encoding="utf-8")
    return session_root


def _make_ctx(tmp_path: Path, schema_a=None, schema_b=None, raw_a=None, raw_b=None) -> tuple[MergeContext, Path, Path]:
    sessions_root = tmp_path / "sessions"
    _make_session(sessions_root, "sess-a", schema_a or _SCHEMA_A, raw_a or _RAW_A)
    _make_session(sessions_root, "sess-b", schema_b or _SCHEMA_B, raw_b or _RAW_B)

    merged_root = tmp_path / "merged"
    output_dir = merged_root / "output"
    intermediate_dir = merged_root / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (merged_root / "input").mkdir(exist_ok=True)

    ctx = MergeContext(
        session_a_name="sess-a",
        session_b_name="sess-b",
        sessions_root=sessions_root,
        input_dir=sessions_root,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=None,
        review=False,
    )
    return ctx, output_dir, intermediate_dir


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------

def test_merge_steps_ordered():
    names = [s.name for s in MERGE_STEPS]
    assert names[0] == "merge_setup"
    assert names[-1] == "merge_manifest"
    assert "merge_schema" in names
    assert "assemble" in names
    assert "validate_graph" in names


def test_merge_pipeline_has_orphan_steps():
    names = [s.name for s in MERGE_STEPS]
    assert "orphan_score" in names
    assert "orphan_connect" in names
    assemble_idx = names.index("assemble")
    orphan_score_idx = names.index("orphan_score")
    orphan_connect_idx = names.index("orphan_connect")
    assert orphan_score_idx == assemble_idx + 1, (
        f"orphan_score must come immediately after assemble "
        f"(assemble={assemble_idx}, orphan_score={orphan_score_idx})"
    )
    assert orphan_connect_idx == orphan_score_idx + 1, (
        f"orphan_connect must come immediately after orphan_score "
        f"(orphan_score={orphan_score_idx}, orphan_connect={orphan_connect_idx})"
    )


def test_merge_steps_have_outputs():
    for step in MERGE_STEPS:
        assert step.outputs, f"Step {step.name!r} has no outputs defined"


def test_merge_steps_llm_flags():
    llm_steps = {s.name for s in MERGE_STEPS if s.is_llm_step}
    assert "merge_schema" in llm_steps
    assert "merge_reextract" in llm_steps
    assert "assemble" not in llm_steps
    assert "merge_setup" not in llm_steps


# ---------------------------------------------------------------------------
# Integration tests (run_merge end-to-end with no LLM adapter)
# ---------------------------------------------------------------------------

def test_run_merge_creates_output_files(tmp_path):
    ctx, output_dir, _ = _make_ctx(tmp_path)
    run_merge(ctx)
    assert (output_dir / "nodes.jsonl").exists()
    assert (output_dir / "edges.jsonl").exists()
    assert (output_dir / "knowledge_graph.ttl").exists()


def test_run_merge_writes_pipeline_state(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    state_path = intermediate_dir / "pipeline_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert "steps" in state
    for step in MERGE_STEPS:
        assert step.name in state["steps"]


def test_run_merge_all_steps_done(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    state = json.loads((intermediate_dir / "pipeline_state.json").read_text())
    for step in MERGE_STEPS:
        status = state["steps"][step.name]["status"]
        allowed = {"done", "failed"} if step.name in _NON_BLOCKING_STEPS else {"done"}
        assert status in allowed, f"Step {step.name!r} expected status in {allowed}, got {status!r}"


def test_run_merge_source_map_written(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    sm = json.loads((intermediate_dir / "source_map.json").read_text())
    assert "_meta" in sm
    assert "session_a" in sm["_meta"]
    assert "session_b" in sm["_meta"]


def test_run_merge_schema_has_both_properties(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    schema = json.loads((intermediate_dir / "schema.json").read_text())
    prop_names = {p["name"] for p in schema.get("properties", [])}
    assert "works_at" in prop_names
    assert "belongs_to" in prop_names


def test_run_merge_manifest_written(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    mm = json.loads((intermediate_dir / "merge_manifest.json").read_text())
    assert mm["session_a"] == "sess-a"
    assert mm["session_b"] == "sess-b"
    assert "merged_at" in mm
    assert "reextraction_strategy" in mm


def test_run_merge_deduplicates_same_node(tmp_path):
    raw_a = {"file_a.md": {"nodes": [{"id": "person-alice", "type": "Person", "confidence": 0.9, "attributes": {"name": {"value": "Alice", "confidence": 0.9}}, "source_files": ["file_a.md"]}], "edges": []}}
    raw_b = {"file_b.md": {"nodes": [{"id": "person-alice", "type": "Person", "confidence": 0.8, "attributes": {"name": {"value": "Alice", "confidence": 0.8}}, "source_files": ["file_b.md"]}], "edges": []}}
    ctx, _, intermediate_dir = _make_ctx(tmp_path, raw_a=raw_a, raw_b=raw_b)
    run_merge(ctx)
    nodes = json.loads((intermediate_dir / "nodes.json").read_text())
    alice_nodes = [n for n in nodes if n.get("attributes", {}).get("name", {}).get("value") == "Alice"]
    assert len(alice_nodes) == 1


def test_run_merge_nodes_from_both_sessions(tmp_path):
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)
    nodes = json.loads((intermediate_dir / "nodes.json").read_text())
    names = {n.get("attributes", {}).get("name", {}).get("value") for n in nodes}
    assert "Alice" in names
    assert "Bob" in names


def test_run_merge_resumable_skips_done_steps(tmp_path):
    """Second run_merge call on same ctx skips all steps whose outputs exist."""
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)

    # Re-build ctx pointing at same dirs and run again
    ctx2, _, _ = _make_ctx.__wrapped__(tmp_path) if hasattr(_make_ctx, "__wrapped__") else (
        MergeContext(
            session_a_name="sess-a",
            session_b_name="sess-b",
            sessions_root=tmp_path / "sessions",
            input_dir=tmp_path / "sessions",
            output_dir=tmp_path / "merged" / "output",
            intermediate_dir=tmp_path / "merged" / "intermediate",
            adapter=None,
            review=False,
        ),
        tmp_path / "merged" / "output",
        tmp_path / "merged" / "intermediate",
    )
    run_merge(ctx2)

    state2 = json.loads((intermediate_dir / "pipeline_state.json").read_text())
    # All blocking steps must be done; non-blocking steps may be failed or done
    for step in MERGE_STEPS:
        status = state2["steps"][step.name]["status"]
        allowed = {"done", "failed"} if step.name in _NON_BLOCKING_STEPS else {"done"}
        assert status in allowed, f"Step {step.name!r} expected status in {allowed}, got {status!r}"

# ---------------------------------------------------------------------------
# chunk_node_index tests
# ---------------------------------------------------------------------------

def _add_chunk_index_shards(sessions_root: Path, session_name: str, shards: list[dict]) -> None:
    """Write chunk_index_shards into a session's intermediate directory."""
    shards_dir = sessions_root / session_name / "intermediate" / "chunk_index_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)
    for shard in shards:
        slug = shard["_fname"].replace("/", "_").replace(".", "_")
        (shards_dir / f"{slug}.json").write_text(json.dumps(shard), encoding="utf-8")


def test_merge_raw_writes_chunk_node_index(tmp_path):
    """merge_raw builds chunk_node_index.json with namespaced keys from both sessions."""
    sessions_root = tmp_path / "sessions"
    _make_session(sessions_root, "sess-a", _SCHEMA_A, _RAW_A)
    _make_session(sessions_root, "sess-b", _SCHEMA_B, _RAW_B)

    # Add chunk index shards to each session
    _add_chunk_index_shards(sessions_root, "sess-a", [
        {"_fname": "file_a.md", "data": {"0": ["person-alice"]}},
    ])
    _add_chunk_index_shards(sessions_root, "sess-b", [
        {"_fname": "file_b.md", "data": {"0": ["person-bob"], "1": ["person-charlie"]}},
    ])

    merged_root = tmp_path / "merged"
    output_dir = merged_root / "output"
    intermediate_dir = merged_root / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (merged_root / "input").mkdir(exist_ok=True)

    ctx = MergeContext(
        session_a_name="sess-a",
        session_b_name="sess-b",
        sessions_root=sessions_root,
        input_dir=sessions_root,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=None,
        review=False,
    )
    run_merge(ctx)

    # chunk_node_index.json must exist
    index_path = intermediate_dir / "chunk_node_index.json"
    assert index_path.exists(), "chunk_node_index.json was not written"

    index = json.loads(index_path.read_text(encoding="utf-8"))

    # Keys must be namespaced
    assert "session_a/file_a.md" in index, f"Expected 'session_a/file_a.md' in {list(index)}"
    assert "session_b/file_b.md" in index, f"Expected 'session_b/file_b.md' in {list(index)}"

    # Values must match the original shard data
    assert index["session_a/file_a.md"] == {"0": ["person-alice"]}
    assert index["session_b/file_b.md"]["0"] == ["person-bob"]
    assert index["session_b/file_b.md"]["1"] == ["person-charlie"]

    # ctx.chunk_node_index must be set
    assert ctx.chunk_node_index is not None
    assert "session_a/file_a.md" in ctx.chunk_node_index
    assert "session_b/file_b.md" in ctx.chunk_node_index


def test_merge_raw_chunk_node_index_empty_when_no_shards(tmp_path):
    """chunk_node_index.json is written as an empty dict when sessions have no chunk index shards."""
    ctx, _, intermediate_dir = _make_ctx(tmp_path)
    run_merge(ctx)

    index_path = intermediate_dir / "chunk_node_index.json"
    assert index_path.exists(), "chunk_node_index.json was not written even when empty"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index == {}, f"Expected empty dict, got {index}"


def test_merge_raw_step_outputs_includes_chunk_node_index():
    """The merge_raw step's outputs list must include chunk_node_index.json."""
    merge_raw_step = next(s for s in MERGE_STEPS if s.name == "merge_raw")
    assert "chunk_node_index.json" in merge_raw_step.outputs
