from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mykg.merger import (
    build_source_map,
    compute_schema_delta,
    harmonize_merged_schema,
    load_session,
    merge_raw_extractions,
    merge_session_schemas,
    namespace_raw_extractions,
    reextract_for_merge,
)

# ---------------------------------------------------------------------------
# namespace_raw_extractions
# ---------------------------------------------------------------------------


def test_namespace_rewrites_keys():
    raw = {"notes.md": {"nodes": [], "edges": []}}
    result = namespace_raw_extractions(raw, "session_a")
    assert "session_a/notes.md" in result
    assert "notes.md" not in result


def test_namespace_updates_source_files_on_nodes():
    raw = {
        "notes.md": {
            "nodes": [{"id": "n1", "source_files": ["notes.md"]}],
            "edges": [],
        }
    }
    result = namespace_raw_extractions(raw, "session_a")
    node = result["session_a/notes.md"]["nodes"][0]
    assert node["source_files"] == ["session_a/notes.md"]


def test_namespace_updates_source_files_on_edges():
    raw = {
        "notes.md": {
            "nodes": [],
            "edges": [{"id": "e1", "source_files": ["notes.md"]}],
        }
    }
    result = namespace_raw_extractions(raw, "session_a")
    edge = result["session_a/notes.md"]["edges"][0]
    assert edge["source_files"] == ["session_a/notes.md"]


def test_namespace_does_not_mutate_input():
    raw = {"notes.md": {"nodes": [{"id": "n1", "source_files": ["notes.md"]}], "edges": []}}
    original_key = next(iter(raw))
    namespace_raw_extractions(raw, "session_a")
    assert next(iter(raw)) == original_key
    assert raw["notes.md"]["nodes"][0]["source_files"] == ["notes.md"]


def test_namespace_multiple_files():
    raw = {"a.md": {"nodes": [], "edges": []}, "b.md": {"nodes": [], "edges": []}}
    result = namespace_raw_extractions(raw, "session_b")
    assert set(result.keys()) == {"session_b/a.md", "session_b/b.md"}


# ---------------------------------------------------------------------------
# merge_raw_extractions
# ---------------------------------------------------------------------------


def test_merge_no_collision():
    a = {"session_a/a.md": {"nodes": [], "edges": []}}
    b = {"session_b/b.md": {"nodes": [], "edges": []}}
    result = merge_raw_extractions(a, b)
    assert set(result.keys()) == {"session_a/a.md", "session_b/b.md"}


def test_merge_raises_on_key_collision():
    a = {"same_key": {"nodes": [], "edges": []}}
    b = {"same_key": {"nodes": [], "edges": []}}
    with pytest.raises(ValueError, match="collision"):
        merge_raw_extractions(a, b)


def test_merge_result_has_all_entries():
    a = namespace_raw_extractions({"x.md": {"nodes": [], "edges": []}}, "session_a")
    b = namespace_raw_extractions({"x.md": {"nodes": [], "edges": []}}, "session_b")
    result = merge_raw_extractions(a, b)
    assert len(result) == 2
    assert "session_a/x.md" in result
    assert "session_b/x.md" in result


# ---------------------------------------------------------------------------
# merge_session_schemas
# ---------------------------------------------------------------------------


def test_merge_schemas_unions_concepts():
    schema_a = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    schema_b = {
        "concepts": [{"type": "Organization", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    merged, _ = merge_session_schemas(schema_a, schema_b, None, {}, {})
    types = {c["type"] for c in merged["concepts"]}
    assert "Person" in types
    assert "Organization" in types


def test_merge_schemas_unions_properties():
    schema_a = {
        "concepts": [],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
        ],
    }
    schema_b = {
        "concepts": [],
        "properties": [
            {"name": "belongs_to", "domain": "Person", "range": "MilitaryUnit", "attributes": []}
        ],
    }
    merged, _ = merge_session_schemas(schema_a, schema_b, None, {}, {})
    names = {p["name"] for p in merged["properties"]}
    assert "works_at" in names
    assert "belongs_to" in names


def test_merge_schemas_deduplicates_same_concept():
    schema_a = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    schema_b = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["email"]}],
        "properties": [],
    }
    merged, _ = merge_session_schemas(schema_a, schema_b, None, {}, {})
    persons = [c for c in merged["concepts"] if c["type"] == "Person"]
    assert len(persons) == 1
    assert "name" in persons[0]["attributes"]
    assert "email" in persons[0]["attributes"]


# ---------------------------------------------------------------------------
# compute_schema_delta
# ---------------------------------------------------------------------------


def test_delta_identifies_new_properties():
    original = {
        "concepts": [],
        "properties": [
            {"name": "works_at", "domain": "P", "range": "O", "attributes": []}
        ],
    }
    merged = {
        "concepts": [],
        "properties": [
            {"name": "works_at", "domain": "P", "range": "O", "attributes": []},
            {"name": "belongs_to", "domain": "P", "range": "M", "attributes": []},
        ],
    }
    delta = compute_schema_delta(original, merged)
    assert delta == {"belongs_to"}


def test_delta_empty_when_no_new_properties():
    schema = {
        "concepts": [],
        "properties": [{"name": "works_at", "domain": "P", "range": "O", "attributes": []}],
    }
    delta = compute_schema_delta(schema, schema)
    assert delta == set()


# ---------------------------------------------------------------------------
# reextract_for_merge
# ---------------------------------------------------------------------------


def test_reextract_none_returns_unchanged(tmp_path):
    raw = {"session_a/f.md": {"nodes": [], "edges": []}}
    result = reextract_for_merge(
        "session_a", tmp_path, raw, {}, {}, tmp_path, None, {}, "none"
    )
    assert result is raw


def test_reextract_invalid_strategy_raises(tmp_path):
    with pytest.raises(ValueError, match="Unknown reextraction_strategy"):
        reextract_for_merge("session_a", tmp_path, {}, {}, {}, tmp_path, None, {}, "invalid")


def test_reextract_surgical_no_delta_returns_unchanged(tmp_path):
    original = {"concepts": [], "properties": [{"name": "p", "domain": "A", "range": "B", "attributes": []}]}
    merged = original  # identical → delta is empty
    raw = {"session_a/f.md": {"nodes": [], "edges": []}}
    result = reextract_for_merge(
        "session_a", tmp_path, raw, merged, {}, tmp_path, None, {}, "surgical",
        original_schema=original,
    )
    assert result is raw


def test_reextract_surgical_with_delta_calls_pass2(tmp_path):
    """Surgical strategy with a schema delta calls run_pass2 with correct params."""
    # Set up session path with input file.
    session_path = tmp_path / "session_x"
    input_dir = session_path / "input"
    input_dir.mkdir(parents=True)
    (input_dir / "notes.md").write_text("Alice works at Acme.", encoding="utf-8")

    # Set up merged intermediate dir with a namespaced shard for session_x.
    intermediate_dir = tmp_path / "merged_intermediate"
    shard_dir = intermediate_dir / "raw_extractions_shards"
    shard_dir.mkdir(parents=True)
    prior_data = {"nodes": [{"id": "person-alice"}], "edges": []}
    shard_content = {"_fname": "session_x/notes.md", "data": prior_data}
    (shard_dir / "session_x_notes_md.json").write_text(
        json.dumps(shard_content), encoding="utf-8"
    )

    original_schema = {"concepts": [], "properties": []}
    merged_schema = {
        "concepts": [],
        "properties": [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}],
    }
    raw_ns = {"session_x/notes.md": {"nodes": [], "edges": []}}

    mock_adapter = MagicMock()
    # Return both a pre-existing node and a brand-new node from re-extraction.
    new_raw_result = {
        "notes.md": {
            "nodes": [{"id": "person-alice"}, {"id": "organization-acme"}],
            "edges": [{"from": "person-alice", "to": "organization-acme", "type": "works_at"}],
        }
    }
    new_chunk_result = {}
    failed_result = []

    with patch("mykg.merger.run_pass2", return_value=(new_raw_result, new_chunk_result, failed_result)) as mock_pass2, \
         patch("mykg.merger.chunk_file", return_value=[MagicMock()]) as _mock_chunk:
        result = reextract_for_merge(
            "session_x", session_path, raw_ns, merged_schema, {}, intermediate_dir,
            mock_adapter, {}, "surgical",
            original_schema=original_schema,
        )

    # run_pass2 must have been called once.
    mock_pass2.assert_called_once()
    kw = mock_pass2.call_args.kwargs

    # reextract_chunks must map the plain filename to chunk indices.
    assert "reextract_chunks" in kw
    assert "notes.md" in kw["reextract_chunks"]

    # prior_extractions must use the un-namespaced key and carry the shard data.
    assert "prior_extractions" in kw
    assert "notes.md" in kw["prior_extractions"]
    assert kw["prior_extractions"]["notes.md"] == prior_data

    # Result must be namespaced under session_x.
    assert "session_x/notes.md" in result
    file_result = result["session_x/notes.md"]

    # Both the pre-existing and net-new node must survive — no filtering.
    result_ids = {n["id"] for n in file_result["nodes"]}
    assert "person-alice" in result_ids
    assert "organization-acme" in result_ids

    # The edge connecting them must also survive.
    assert len(file_result["edges"]) == 1


# ---------------------------------------------------------------------------
# load_session — filesystem tests
# ---------------------------------------------------------------------------


def test_load_session_missing_schema_raises(tmp_path):
    sessions_root = tmp_path / "sessions"
    (sessions_root / "my-session" / "intermediate").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="schema.json"):
        load_session("my-session", sessions_root)


def test_load_session_missing_extractions_raises(tmp_path):
    sessions_root = tmp_path / "sessions"
    intermediate = sessions_root / "my-session" / "intermediate"
    intermediate.mkdir(parents=True)
    (intermediate / "schema.json").write_text(
        json.dumps({"concepts": [], "properties": []}), encoding="utf-8"
    )
    with pytest.raises(FileNotFoundError, match="raw_extractions.json"):
        load_session("my-session", sessions_root)


def test_load_session_happy_path(tmp_path):
    sessions_root = tmp_path / "sessions"
    intermediate = sessions_root / "my-session" / "intermediate"
    intermediate.mkdir(parents=True)
    schema = {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}], "properties": []}
    (intermediate / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    raw = {"file_a.md": {"nodes": [], "edges": []}}
    (intermediate / "raw_extractions.json").write_text(json.dumps(raw), encoding="utf-8")

    session = load_session("my-session", sessions_root)
    assert session.name == "my-session"
    assert session.schema == schema
    assert "file_a.md" in session.raw_extractions
    assert session.manifest == {}
    assert session.prep_mode == "unknown"


# ---------------------------------------------------------------------------
# build_source_map
# ---------------------------------------------------------------------------


def test_build_source_map_has_meta(tmp_path):
    sessions_root = tmp_path / "sessions"

    def _make(name, files):
        intermediate = sessions_root / name / "intermediate"
        intermediate.mkdir(parents=True)
        (intermediate / "schema.json").write_text(json.dumps({"concepts": [], "properties": []}))
        raw = {f: {"nodes": [], "edges": []} for f in files}
        (intermediate / "raw_extractions.json").write_text(json.dumps(raw))
        return load_session(name, sessions_root)

    sa = _make("sess-a", ["a.md"])
    sb = _make("sess-b", ["b.md"])
    sm = build_source_map(sa, sb)
    assert "_meta" in sm
    assert "session_a" in sm["_meta"]
    assert "session_b" in sm["_meta"]
    assert "session_a/a.md" in sm
    assert "session_b/b.md" in sm


# ---------------------------------------------------------------------------
# harmonize_merged_schema
# ---------------------------------------------------------------------------


def test_harmonize_merged_schema_uses_merge_specific_functions():
    schema = {"concepts": [], "properties": []}
    proposals = [schema, schema]
    adapter = MagicMock()
    harmonized = {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}], "properties": []}

    with patch("mykg.merger.harmonize_schema_for_merge", return_value=harmonized) as mock_harm, \
         patch("mykg.merger.review_schema_quality_for_merge", return_value=harmonized) as mock_qual:
        result = harmonize_merged_schema(schema, proposals, adapter)

    mock_harm.assert_called_once_with(schema, proposals, adapter)
    mock_qual.assert_called_once_with(harmonized, adapter)
    assert result is harmonized


def test_harmonize_merged_schema_skips_llm_when_no_adapter():
    schema = {"concepts": [], "properties": []}
    with patch("mykg.merger.harmonize_schema_for_merge") as mock_harm, \
         patch("mykg.merger.review_schema_quality_for_merge") as mock_qual:
        result = harmonize_merged_schema(schema, [], None)

    mock_harm.assert_not_called()
    mock_qual.assert_not_called()
    assert result is schema


def test_build_source_map_same_filename(tmp_path):
    sessions_root = tmp_path / "sessions"

    def _make(name):
        intermediate = sessions_root / name / "intermediate"
        intermediate.mkdir(parents=True)
        (intermediate / "schema.json").write_text(json.dumps({"concepts": [], "properties": []}))
        (intermediate / "raw_extractions.json").write_text(json.dumps({"notes.md": {"nodes": [], "edges": []}}))
        return load_session(name, sessions_root)

    sa = _make("sess-a")
    sb = _make("sess-b")
    sm = build_source_map(sa, sb)
    assert "session_a/notes.md" in sm
    assert "session_b/notes.md" in sm
    assert sm["session_a/notes.md"]["role"] == "input_a"
    assert sm["session_b/notes.md"]["role"] == "input_b"
