"""Unit tests for the merge-pipeline step modules.

Covers:
- step_merge_raw.run_merge_raw  — cold re-entry path, namespacing skip-when-already-namespaced,
  malformed chunk shard skip, JSON-decode error skip.
- step_merge_schema.run_merge_schema  — RuntimeError when sessions are missing,
  base_schema lock injection branch.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mykg.merge_context import MergeContext
from mykg.steps.step_merge_raw import run_merge_raw
from mykg.steps.step_merge_schema import run_merge_schema


def _make_session_on_disk(sessions_root: Path, name: str) -> Path:
    """Create a minimal session directory laid out as load_session expects."""
    root = sessions_root / name
    (root / "intermediate").mkdir(parents=True, exist_ok=True)
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    raw = {f"{name}/x.md": {"nodes": [], "edges": []}}
    (root / "intermediate" / "schema.json").write_text(json.dumps(schema), encoding="utf-8")
    (root / "intermediate" / "raw_extractions.json").write_text(json.dumps(raw), encoding="utf-8")
    return root


def _make_ctx(tmp_path: Path) -> MergeContext:
    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    _make_session_on_disk(sessions_root, "sess-a")
    _make_session_on_disk(sessions_root, "sess-b")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)

    return MergeContext(
        session_a_name="sess-a",
        session_b_name="sess-b",
        sessions_root=sessions_root,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate,
        adapter=None,
        review=False,
    )


# ---------------------------------------------------------------------------
# step_merge_raw
# ---------------------------------------------------------------------------


def test_merge_raw_cold_reentry_loads_sessions(tmp_path):
    """When ctx.session_a is None, run_merge_raw reloads both sessions from disk (lines 24-28)."""
    ctx = _make_ctx(tmp_path)
    assert ctx.session_a is None and ctx.session_b is None

    run_merge_raw(ctx)
    # Sessions must now be loaded
    assert ctx.session_a is not None
    assert ctx.session_b is not None
    # Output files written
    assert (ctx.intermediate_dir / "raw_extractions.json").exists()
    assert (ctx.intermediate_dir / "raw_extractions.done").exists()
    assert (ctx.intermediate_dir / "name_normalization.json").exists()
    assert (ctx.intermediate_dir / "chunk_node_index.json").exists()


def test_merge_raw_skips_already_namespaced_raw(tmp_path):
    """When raw_extractions are already namespaced, the namespace step is skipped (lines 34, 36 skipped)."""
    from mykg.merger import SessionData

    ctx = _make_ctx(tmp_path)
    # Manually populate session_a / session_b with already-namespaced keys
    ctx.session_a = SessionData(
        name="sess-a",
        path=tmp_path / "sessions" / "sess-a",
        schema={"concepts": [], "properties": []},
        raw_extractions={"session_a/file.md": {"nodes": [], "edges": []}},
        shards={},
        manifest={},
        prep_mode="per_file",
    )
    ctx.session_b = SessionData(
        name="sess-b",
        path=tmp_path / "sessions" / "sess-b",
        schema={"concepts": [], "properties": []},
        raw_extractions={"session_b/file.md": {"nodes": [], "edges": []}},
        shards={},
        manifest={},
        prep_mode="per_file",
    )

    # If both inputs are already namespaced, the branches at lines 33-36 are skipped
    run_merge_raw(ctx)

    merged = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "session_a/file.md" in merged
    assert "session_b/file.md" in merged


def test_merge_raw_skips_malformed_shard(tmp_path):
    """run_merge_raw warns and skips shards that are not valid JSON or have wrong structure."""
    ctx = _make_ctx(tmp_path)

    shards_dir = ctx.intermediate_dir / "chunk_index_shards"
    shards_dir.mkdir(parents=True, exist_ok=True)

    # Shard 1 — valid JSON, good shape (will be included)
    (shards_dir / "good.json").write_text(
        json.dumps({"_fname": "session_a/x.md", "data": {"0": ["n1"]}}),
        encoding="utf-8",
    )
    # Shard 2 — invalid JSON (triggers JSONDecodeError -> lines 59-63)
    (shards_dir / "bad.json").write_text("{not valid json", encoding="utf-8")
    # Shard 3 — valid JSON but missing _fname (triggers lines 67-68)
    (shards_dir / "incomplete.json").write_text(
        json.dumps({"data": {"0": ["n2"]}}), encoding="utf-8"
    )
    # Shard 4 — valid JSON but `data` is not a dict (triggers lines 67-68 as well)
    (shards_dir / "wrong_type.json").write_text(
        json.dumps({"_fname": "session_b/y.md", "data": "oops"}), encoding="utf-8"
    )

    run_merge_raw(ctx)

    cni = json.loads((ctx.intermediate_dir / "chunk_node_index.json").read_text())
    assert "session_a/x.md" in cni
    # Bad / incomplete shards must NOT have made it in
    assert "session_b/y.md" not in cni


def test_merge_raw_does_not_overwrite_existing_norm_file(tmp_path):
    """run_merge_raw must NOT overwrite an existing name_normalization.json (line 46 branch)."""
    ctx = _make_ctx(tmp_path)
    norm = ctx.intermediate_dir / "name_normalization.json"
    norm.write_text(json.dumps({"mappings": {"Person": {"Alice": "Alice Smith"}}}), encoding="utf-8")

    run_merge_raw(ctx)

    after = json.loads(norm.read_text())
    assert after["mappings"]["Person"]["Alice"] == "Alice Smith"


# ---------------------------------------------------------------------------
# step_merge_schema
# ---------------------------------------------------------------------------


def test_merge_schema_raises_when_sessions_missing(tmp_path):
    """run_merge_schema must raise RuntimeError when session_a/session_b are not set (line 20)."""
    ctx = _make_ctx(tmp_path)
    assert ctx.session_a is None and ctx.session_b is None

    with pytest.raises(RuntimeError, match="merge_setup"):
        run_merge_schema(ctx)


def test_merge_schema_uses_locked_classes_from_base_schema(tmp_path):
    """When ctx.base_schema is set, locked_classes/locked_properties are extracted (lines 27-28)."""
    from mykg.merger import SessionData

    ctx = _make_ctx(tmp_path)
    ctx.session_a = SessionData(
        name="sess-a",
        path=tmp_path / "sessions" / "sess-a",
        schema={"concepts": [], "properties": []},
        raw_extractions={},
        shards={},
        manifest={},
        prep_mode="per_file",
    )
    ctx.session_b = SessionData(
        name="sess-b",
        path=tmp_path / "sessions" / "sess-b",
        schema={"concepts": [], "properties": []},
        raw_extractions={},
        shards={},
        manifest={},
        prep_mode="per_file",
    )
    ctx.base_schema = {
        "locked_classes": {"Person": {"attributes": ["name"]}},
        "locked_properties": {"works_at": {"domain": "Person", "range": "Org"}},
    }

    captured = {}

    def fake_merge(schema_a, schema_b, thesaurus, locked_classes, locked_properties):
        captured["locked_classes"] = locked_classes
        captured["locked_properties"] = locked_properties
        return ({"concepts": [], "properties": []}, [])

    def fake_harmonize(merged, _proposals, _adapter):
        return merged

    with (
        patch("mykg.steps.step_merge_schema.merge_session_schemas", side_effect=fake_merge),
        patch("mykg.steps.step_merge_schema.harmonize_merged_schema", side_effect=fake_harmonize),
    ):
        run_merge_schema(ctx)

    assert "Person" in captured["locked_classes"]
    assert "works_at" in captured["locked_properties"]
