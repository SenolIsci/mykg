from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mykg.merger import (
    _build_targeted_reextract_chunks,
    _copy_shard_dir,
    _namespace_shards,
    _read_prep_mode,
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


# ---------------------------------------------------------------------------
# _read_prep_mode
# ---------------------------------------------------------------------------


def test_read_prep_mode_no_config_file_returns_unknown(tmp_path):
    """When pipeline_config.yaml is absent, return 'unknown'."""
    result = _read_prep_mode(tmp_path)
    assert result == "unknown"


def test_read_prep_mode_no_profile_reads_top_level(tmp_path):
    """When no active profile, read pipeline.pass2.prep_mode from top-level."""
    (tmp_path / "pipeline_config.yaml").write_text(
        "pipeline:\n  pass2:\n    prep_mode: per_file\n", encoding="utf-8"
    )
    result = _read_prep_mode(tmp_path)
    assert result == "per_file"


def test_read_prep_mode_active_profile_takes_precedence(tmp_path):
    """When an active profile is set, its prep_mode overrides the top-level."""
    yaml_text = (
        "profile: fast\n"
        "pipeline:\n"
        "  pass2:\n"
        "    prep_mode: per_file\n"
        "profiles:\n"
        "  fast:\n"
        "    pipeline:\n"
        "      pass2:\n"
        "        prep_mode: concat\n"
    )
    (tmp_path / "pipeline_config.yaml").write_text(yaml_text, encoding="utf-8")
    result = _read_prep_mode(tmp_path)
    assert result == "concat"


def test_read_prep_mode_key_missing_returns_unknown(tmp_path):
    """When pipeline_config.yaml exists but prep_mode key is absent, return 'unknown'."""
    (tmp_path / "pipeline_config.yaml").write_text(
        "pipeline:\n  pass2: {}\n", encoding="utf-8"
    )
    result = _read_prep_mode(tmp_path)
    assert result == "unknown"


def test_read_prep_mode_invalid_yaml_returns_unknown(tmp_path):
    """When YAML is unparseable, return 'unknown' without raising."""
    (tmp_path / "pipeline_config.yaml").write_text(
        ":\n  bad: [unterminated\n", encoding="utf-8"
    )
    result = _read_prep_mode(tmp_path)
    assert result == "unknown"


# ---------------------------------------------------------------------------
# load_session — error handling paths
# ---------------------------------------------------------------------------


def _make_minimal_session(sessions_root, name):
    """Create a valid minimal session and return (session_path, intermediate)."""
    intermediate = sessions_root / name / "intermediate"
    intermediate.mkdir(parents=True)
    (intermediate / "schema.json").write_text(
        json.dumps({"concepts": [], "properties": []}), encoding="utf-8"
    )
    (intermediate / "raw_extractions.json").write_text(
        json.dumps({"f.md": {"nodes": [], "edges": []}}), encoding="utf-8"
    )
    return sessions_root / name, intermediate


def test_load_session_corrupt_shard_skipped_gracefully(tmp_path):
    """A corrupt shard file is skipped; the session still loads successfully."""
    sessions_root = tmp_path / "sessions"
    _, intermediate = _make_minimal_session(sessions_root, "my-session")
    shard_dir = intermediate / "raw_extractions_shards"
    shard_dir.mkdir()
    (shard_dir / "bad_shard.json").write_text("NOT VALID JSON {{}", encoding="utf-8")
    (shard_dir / "good_shard.json").write_text(
        json.dumps({"_fname": "f.md", "data": {}}), encoding="utf-8"
    )
    session = load_session("my-session", sessions_root)
    # The good shard loads; the bad one is silently skipped.
    assert "f.md" in session.shards
    assert len(session.shards) == 1


def test_load_session_corrupt_manifest_skipped_gracefully(tmp_path):
    """A corrupt file_manifest.json is skipped; manifest stays empty dict."""
    sessions_root = tmp_path / "sessions"
    _, intermediate = _make_minimal_session(sessions_root, "my-session")
    (intermediate / "file_manifest.json").write_text(
        "TOTALLY BAD JSON ][", encoding="utf-8"
    )
    session = load_session("my-session", sessions_root)
    assert session.manifest == {}


# ---------------------------------------------------------------------------
# _copy_shard_dir
# ---------------------------------------------------------------------------


def test_copy_shard_dir_namespaces_fname(tmp_path):
    """Shard _fname is rewritten to <alias>/<original_fname>."""
    src = tmp_path / "src_shards"
    dst = tmp_path / "dst_shards"
    src.mkdir()
    shard_content = {"_fname": "notes.md", "data": {"nodes": []}}
    (src / "notes_md.json").write_text(json.dumps(shard_content), encoding="utf-8")

    _copy_shard_dir(src, dst, "session_a")

    assert dst.is_dir()
    written = list(dst.glob("*.json"))
    assert len(written) == 1
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["_fname"] == "session_a/notes.md"


def test_copy_shard_dir_skips_corrupt_shard_continues(tmp_path):
    """Corrupt shard files are skipped; valid ones are still copied."""
    src = tmp_path / "src_shards"
    dst = tmp_path / "dst_shards"
    src.mkdir()
    (src / "bad.json").write_text("NOT JSON {{", encoding="utf-8")
    (src / "good.json").write_text(
        json.dumps({"_fname": "good.md", "data": {}}), encoding="utf-8"
    )

    _copy_shard_dir(src, dst, "session_a")

    written = list(dst.glob("*.json"))
    assert len(written) == 1
    data = json.loads(written[0].read_text(encoding="utf-8"))
    assert data["_fname"] == "session_a/good.md"


def test_copy_shard_dir_long_filename_uses_sha1_hash(tmp_path):
    """When the candidate dst filename exceeds 240 bytes, SHA1 hash is used."""
    src = tmp_path / "src_shards"
    dst = tmp_path / "dst_shards"
    src.mkdir()
    # Build a shard filename that exceeds 240 bytes after prefixing with alias.
    long_stem = "x" * 250
    long_name = f"{long_stem}.json"
    shard_content = {"_fname": long_stem, "data": {}}
    (src / long_name).write_text(json.dumps(shard_content), encoding="utf-8")

    _copy_shard_dir(src, dst, "session_a")

    written = list(dst.glob("*.json"))
    assert len(written) == 1
    filename = written[0].name
    # Must be the hash form, not the full name.
    assert len(filename.encode()) <= 240
    # Verify it follows the sha1 pattern: session_a_<16hex chars>.json
    assert filename.startswith("session_a_")
    assert filename.endswith(".json")
    hex_part = filename[len("session_a_"):-len(".json")]
    assert len(hex_part) == 16
    assert all(c in "0123456789abcdef" for c in hex_part)


def test_copy_shard_dir_missing_src_dir_is_noop(tmp_path):
    """When src_dir does not exist, the function returns without error."""
    src = tmp_path / "nonexistent_shards"
    dst = tmp_path / "dst_shards"
    _copy_shard_dir(src, dst, "session_a")
    assert not dst.exists()


def test_copy_shard_dir_creates_dst_dir(tmp_path):
    """dst_dir is created when it does not exist yet."""
    src = tmp_path / "src_shards"
    dst = tmp_path / "deep" / "nested" / "dst_shards"
    src.mkdir()
    (src / "shard.json").write_text(
        json.dumps({"_fname": "f.md", "data": {}}), encoding="utf-8"
    )
    _copy_shard_dir(src, dst, "session_a")
    assert dst.is_dir()


# ---------------------------------------------------------------------------
# _namespace_shards
# ---------------------------------------------------------------------------


def test_namespace_shards_rewrites_fname_in_place(tmp_path):
    """_fname values that lack the prefix are rewritten to <alias>/<fname>."""
    shard_dir = tmp_path / "raw_extractions_shards"
    shard_dir.mkdir()
    shard_data = {"_fname": "notes.md", "data": {}}
    shard_file = shard_dir / "notes_md.json"
    shard_file.write_text(json.dumps(shard_data), encoding="utf-8")

    _namespace_shards(tmp_path, "session_a")

    result = json.loads(shard_file.read_text(encoding="utf-8"))
    assert result["_fname"] == "session_a/notes.md"


def test_namespace_shards_skips_already_prefixed(tmp_path):
    """Shards already carrying the prefix are not modified."""
    shard_dir = tmp_path / "raw_extractions_shards"
    shard_dir.mkdir()
    shard_data = {"_fname": "session_a/notes.md", "data": {}}
    shard_file = shard_dir / "notes_md.json"
    shard_file.write_text(json.dumps(shard_data), encoding="utf-8")

    _namespace_shards(tmp_path, "session_a")

    result = json.loads(shard_file.read_text(encoding="utf-8"))
    assert result["_fname"] == "session_a/notes.md"


def test_namespace_shards_handles_corrupt_shard(tmp_path):
    """Corrupt shard files are skipped without raising an exception."""
    shard_dir = tmp_path / "raw_extractions_shards"
    shard_dir.mkdir()
    (shard_dir / "bad.json").write_text("NOT JSON ][", encoding="utf-8")
    _namespace_shards(tmp_path, "session_a")


def test_namespace_shards_processes_both_subdirs(tmp_path):
    """Both raw_extractions_shards and chunk_index_shards are processed."""
    for subdir in ("raw_extractions_shards", "chunk_index_shards"):
        d = tmp_path / subdir
        d.mkdir()
        (d / "shard.json").write_text(
            json.dumps({"_fname": "f.md", "data": {}}), encoding="utf-8"
        )

    _namespace_shards(tmp_path, "session_b")

    for subdir in ("raw_extractions_shards", "chunk_index_shards"):
        result = json.loads((tmp_path / subdir / "shard.json").read_text(encoding="utf-8"))
        assert result["_fname"] == "session_b/f.md"


@pytest.mark.parametrize("alias", ["session_a", "session_b", "my_session"])
def test_namespace_shards_alias_parametrized(tmp_path, alias):
    """_namespace_shards works correctly for various alias strings."""
    shard_dir = tmp_path / "raw_extractions_shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "shard.json"
    shard_file.write_text(json.dumps({"_fname": "doc.md", "data": {}}), encoding="utf-8")

    _namespace_shards(tmp_path, alias)

    result = json.loads(shard_file.read_text(encoding="utf-8"))
    assert result["_fname"] == f"{alias}/doc.md"


# ---------------------------------------------------------------------------
# _build_targeted_reextract_chunks
# ---------------------------------------------------------------------------


def _make_schema_with_props(props):
    """Helper: build a merged schema dict from a list of property dicts."""
    return {"concepts": [], "properties": props}


def test_build_targeted_top_k_zero_returns_empty_dict():
    """When top_k=0, the function returns an empty dict (re-extraction disabled)."""
    prior_chunk_index = {"f.md": {"1": ["person-alice"]}}
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions={"f.md": {"nodes": [{"id": "person-alice", "type": "Person"}], "edges": []}},
        prior_chunk_index=prior_chunk_index,
        top_k=0,
    )
    assert result == {}


def test_build_targeted_no_prior_chunk_index_returns_none():
    """When prior_chunk_index is empty, return None (caller falls back to full enum)."""
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions={"f.md": {"nodes": [], "edges": []}},
        prior_chunk_index={},
        top_k=5,
    )
    assert result is None


def test_build_targeted_no_affected_chunks_returns_empty_dict():
    """When no chunk contains a node of an affected type, return an empty dict."""
    # prior_chunk_index has chunks, but nodes are of type "Animal", not "Person"/"Organization".
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions={
            "f.md": {"nodes": [{"id": "animal-fido", "type": "Animal"}], "edges": []}
        },
        prior_chunk_index={"f.md": {"1": ["animal-fido"]}},
        top_k=5,
    )
    assert result == {}


def test_build_targeted_normal_selects_top_k_chunks():
    """With top_k=1, only the highest-scoring chunk is selected per property."""
    prior_extractions = {
        "f.md": {
            "nodes": [
                {"id": "person-alice", "type": "Person"},
                {"id": "org-acme", "type": "Organization"},
            ],
            "edges": [],
        }
    }
    prior_chunk_index = {
        "f.md": {
            "1": ["person-alice"],       # score=1 for works_at
            "2": ["person-alice", "org-acme"],  # score=2 for works_at — top chunk
        }
    }
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions=prior_extractions,
        prior_chunk_index=prior_chunk_index,
        top_k=1,
    )
    assert result is not None
    assert "f.md" in result
    # Chunk 2 has the higher score and should be selected with top_k=1.
    assert 2 in result["f.md"]
    assert 1 not in result["f.md"]


def test_build_targeted_domain_and_range_both_scored():
    """Both domain and range type nodes contribute to a chunk's score."""
    prior_extractions = {
        "f.md": {
            "nodes": [
                {"id": "person-bob", "type": "Person"},
                {"id": "org-beta", "type": "Organization"},
            ],
            "edges": [],
        }
    }
    prior_chunk_index = {"f.md": {"1": ["person-bob", "org-beta"]}}
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions=prior_extractions,
        prior_chunk_index=prior_chunk_index,
        top_k=5,
    )
    assert result is not None
    assert "f.md" in result
    assert 1 in result["f.md"]


def test_build_targeted_multiple_new_properties_union_chunks():
    """Chunks from multiple new properties are unioned in the result."""
    prior_extractions = {
        "f.md": {
            "nodes": [
                {"id": "person-c", "type": "Person"},
                {"id": "org-d", "type": "Organization"},
                {"id": "place-e", "type": "Place"},
            ],
            "edges": [],
        }
    }
    prior_chunk_index = {
        "f.md": {
            "1": ["person-c"],        # relevant for works_at (Person domain)
            "2": ["place-e"],         # relevant for located_in (Place domain)
            "3": ["org-d"],           # relevant for works_at (Organization range) + located_in (Organization range)
        }
    }
    merged_schema = _make_schema_with_props([
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
        {"name": "located_in", "domain": "Place", "range": "Organization", "attributes": []},
    ])
    result = _build_targeted_reextract_chunks(
        delta={"works_at", "located_in"},
        merged_schema=merged_schema,
        prior_extractions=prior_extractions,
        prior_chunk_index=prior_chunk_index,
        top_k=5,
    )
    assert result is not None
    all_chunks = result.get("f.md", set())
    # All three chunks should be included since each contains an affected-type node.
    assert 1 in all_chunks
    assert 2 in all_chunks
    assert 3 in all_chunks


def test_build_targeted_chunk_idx_non_numeric_skipped():
    """Non-numeric chunk index keys in prior_chunk_index are silently skipped."""
    prior_extractions = {
        "f.md": {"nodes": [{"id": "person-x", "type": "Person"}], "edges": []}
    }
    prior_chunk_index = {
        "f.md": {
            "not_a_number": ["person-x"],
            "2": ["person-x"],
        }
    }
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions=prior_extractions,
        prior_chunk_index=prior_chunk_index,
        top_k=5,
    )
    assert result is not None
    # Only chunk 2 (valid int key) should appear.
    assert "f.md" in result
    assert "not_a_number" not in {str(c) for c in result["f.md"]}
    assert 2 in result["f.md"]


@pytest.mark.parametrize("top_k", [1, 2, 5])
def test_build_targeted_top_k_variations(top_k):
    """Result has at most top_k chunks per property for various top_k values."""
    # 6 chunks, each with one Person node.
    nodes = [{"id": f"person-{i}", "type": "Person"} for i in range(6)]
    chunk_index = {str(i + 1): [f"person-{i}"] for i in range(6)}
    prior_extractions = {"f.md": {"nodes": nodes, "edges": []}}
    prior_chunk_index = {"f.md": chunk_index}
    result = _build_targeted_reextract_chunks(
        delta={"works_at"},
        merged_schema=_make_schema_with_props(
            [{"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}]
        ),
        prior_extractions=prior_extractions,
        prior_chunk_index=prior_chunk_index,
        top_k=top_k,
    )
    assert result is not None
    total_chunks = sum(len(v) for v in result.values())
    assert total_chunks <= top_k
