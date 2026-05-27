from __future__ import annotations

import json
from pathlib import Path

from mykg.merge_orchestrator import run_merge_graphs


def _make_session(sessions_root: Path, name: str, schema: dict, raw: dict) -> Path:
    """Create a minimal session directory fixture."""
    session_root = sessions_root / name
    intermediate = session_root / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    (session_root / "output").mkdir(exist_ok=True)
    (session_root / "input").mkdir(exist_ok=True)
    (intermediate / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (intermediate / "raw_extractions.json").write_text(json.dumps(raw), encoding="utf-8")
    # pipeline_config.yaml snapshot so load_session can read prep_mode
    (session_root / "pipeline_config.yaml").write_text(
        "profile: test\nprofiles:\n  test:\n    pipeline:\n      pass2:\n        prep_mode: per_file\n      merge_graphs:\n        reextraction_strategy: none\n",
        encoding="utf-8",
    )
    return session_root


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


def _run(tmp_path: Path, raw_a=None, raw_b=None, schema_a=None, schema_b=None):
    sessions_root = tmp_path / "sessions"
    _make_session(sessions_root, "sess-a", schema_a or _SCHEMA_A, raw_a or _RAW_A)
    _make_session(sessions_root, "sess-b", schema_b or _SCHEMA_B, raw_b or _RAW_B)

    merged_root = tmp_path / "merged"
    output_dir = merged_root / "output"
    intermediate_dir = merged_root / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (merged_root / "input").mkdir(exist_ok=True)

    run_merge_graphs(
        "sess-a",
        "sess-b",
        output_dir,
        intermediate_dir,
        adapter=None,
        thesaurus=None,
        base_schema=None,
        review=False,
        sessions_root=sessions_root,
    )
    return output_dir, intermediate_dir


def test_run_merge_creates_output_files(tmp_path):
    output_dir, _ = _run(tmp_path)
    assert (output_dir / "nodes.jsonl").exists()
    assert (output_dir / "edges.jsonl").exists()
    assert (output_dir / "knowledge_graph.ttl").exists()


def test_run_merge_source_map_written(tmp_path):
    _, intermediate_dir = _run(tmp_path)
    sm_path = intermediate_dir / "source_map.json"
    assert sm_path.exists()
    sm = json.loads(sm_path.read_text())
    assert "_meta" in sm
    assert "session_a" in sm["_meta"]
    assert "session_b" in sm["_meta"]


def test_run_merge_merge_manifest_written(tmp_path):
    _, intermediate_dir = _run(tmp_path)
    mm_path = intermediate_dir / "merge_manifest.json"
    assert mm_path.exists()
    mm = json.loads(mm_path.read_text())
    assert mm["session_a"] == "sess-a"
    assert mm["session_b"] == "sess-b"
    assert "merged_at" in mm
    assert "reextraction_strategy" in mm


def test_run_merge_deduplicates_same_node(tmp_path):
    # Both sessions extract the same "Alice" entity — must appear once in output.
    raw_a = {
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
    raw_b = {
        "file_b.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.8,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.8}},
                    "source_files": ["file_b.md"],
                }
            ],
            "edges": [],
        }
    }
    _, intermediate_dir = _run(tmp_path, raw_a=raw_a, raw_b=raw_b)
    nodes = json.loads((intermediate_dir / "nodes.json").read_text())
    alice_nodes = [n for n in nodes if n.get("attributes", {}).get("name", {}).get("value") == "Alice"]
    assert len(alice_nodes) == 1


def test_run_merge_nodes_from_both_sessions(tmp_path):
    # Alice from session A and Bob from session B must both appear.
    output_dir, intermediate_dir = _run(tmp_path)
    nodes = json.loads((intermediate_dir / "nodes.json").read_text())
    names = {n.get("attributes", {}).get("name", {}).get("value") for n in nodes}
    assert "Alice" in names
    assert "Bob" in names


def test_run_merge_source_map_same_filename(tmp_path):
    # Both sessions have a file with the same name — must get distinct namespaced entries.
    raw_a = {"notes.md": {"nodes": [], "edges": []}}
    raw_b = {"notes.md": {"nodes": [], "edges": []}}
    _, intermediate_dir = _run(tmp_path, raw_a=raw_a, raw_b=raw_b)
    sm = json.loads((intermediate_dir / "source_map.json").read_text())
    assert "session_a/notes.md" in sm
    assert "session_b/notes.md" in sm


def test_run_merge_schema_json_written(tmp_path):
    _, intermediate_dir = _run(tmp_path)
    schema_path = intermediate_dir / "schema.json"
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text())
    assert "concepts" in schema
    assert "properties" in schema


def test_run_merge_merged_schema_has_both_properties(tmp_path):
    _, intermediate_dir = _run(tmp_path)
    schema = json.loads((intermediate_dir / "schema.json").read_text())
    prop_names = {p["name"] for p in schema.get("properties", [])}
    # works_at from schema A; belongs_to from schema B
    assert "works_at" in prop_names
    assert "belongs_to" in prop_names
