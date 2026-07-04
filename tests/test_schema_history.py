"""Tests for src/mykg/schema_history.py — schema delta audit log."""

from __future__ import annotations

import json
from pathlib import Path

from mykg.schema_history import (
    TRIGGER_PASS1_MERGE,
    TRIGGER_SCHEMA_GAP,
    write_schema,
)


def test_write_schema_initial_creates_schema_json_and_delta(tmp_path: Path) -> None:
    """write_schema writes schema.json and a delta file when no prior schema exists."""
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    write_schema(schema, tmp_path, TRIGGER_PASS1_MERGE)

    schema_path = tmp_path / "schema.json"
    assert schema_path.exists()
    assert json.loads(schema_path.read_text())["concepts"][0]["type"] == "Person"

    history_dir = tmp_path / "schema_history"
    deltas = sorted(history_dir.glob("*.json"))
    assert len(deltas) == 1
    delta = json.loads(deltas[0].read_text())
    assert delta["seq"] == 1
    assert delta["trigger"] == TRIGGER_PASS1_MERGE
    assert "Person" in delta["concepts_added"]
    assert delta["concepts_total"] == 1


def test_write_schema_no_diff_still_writes_delta(tmp_path: Path) -> None:
    """A no-op write (same schema as before) still produces an empty delta file."""
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    write_schema(schema, tmp_path, TRIGGER_PASS1_MERGE)
    # Second call with identical schema — no real diff
    write_schema(schema, tmp_path, TRIGGER_PASS1_MERGE)

    deltas = sorted((tmp_path / "schema_history").glob("*.json"))
    assert len(deltas) == 2
    second = json.loads(deltas[1].read_text())
    assert second["concepts_added"] == []
    assert second["concepts_removed"] == []
    assert second["properties_added"] == []
    assert second["properties_removed"] == []
    assert second["concepts_total"] == 1
    assert second["properties_total"] == 0


def test_write_schema_handles_concept_missing_type_key(tmp_path: Path) -> None:
    """A malformed concept/property dict missing 'type'/'name' (e.g. from a bad
    LLM feedback correction) must not raise KeyError — it is skipped from the
    delta diff rather than crashing the write."""
    schema = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"parent": None, "attributes": ["bad"]},  # missing "type"
        ],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization"},
            {"domain": "Person", "range": "Organization"},  # missing "name"
        ],
    }
    write_schema(schema, tmp_path, TRIGGER_PASS1_MERGE)

    schema_path = tmp_path / "schema.json"
    assert schema_path.exists()
    deltas = sorted((tmp_path / "schema_history").glob("*.json"))
    delta = json.loads(deltas[0].read_text())
    assert "Person" in delta["concepts_added"]
    assert "works_at" in delta["properties_added"]


def test_write_schema_handles_corrupt_previous_schema(tmp_path: Path) -> None:
    """If the existing schema.json is invalid JSON, write_schema still proceeds (lines 67-68)."""
    # Pre-create a corrupt schema.json
    (tmp_path / "schema.json").write_text("not valid json {{{")

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    write_schema(schema, tmp_path, TRIGGER_PASS1_MERGE)

    # New schema is written and a delta file is created
    after = json.loads((tmp_path / "schema.json").read_text())
    assert after["concepts"][0]["type"] == "Person"
    deltas = sorted((tmp_path / "schema_history").glob("*.json"))
    assert len(deltas) == 1


def test_write_schema_extra_merged_into_delta(tmp_path: Path) -> None:
    """When `extra` is supplied, its keys are merged into the delta file (line 102-103)."""
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [
            {"name": "knows", "domain": "Person", "range": "Person", "attributes": []}
        ],
    }
    write_schema(
        schema,
        tmp_path,
        TRIGGER_SCHEMA_GAP,
        extra={"orphans_resolved": ["person-x"], "note": "schema gap loop"},
    )

    deltas = sorted((tmp_path / "schema_history").glob("*.json"))
    assert len(deltas) == 1
    delta = json.loads(deltas[0].read_text())
    assert delta["orphans_resolved"] == ["person-x"]
    assert delta["note"] == "schema gap loop"


def test_write_schema_sequence_increments(tmp_path: Path) -> None:
    """The sequence number monotonically increments across writes."""
    base = {"concepts": [], "properties": []}
    write_schema(base, tmp_path, TRIGGER_PASS1_MERGE)
    write_schema(base, tmp_path, TRIGGER_PASS1_MERGE)
    write_schema(base, tmp_path, TRIGGER_PASS1_MERGE)
    deltas = sorted((tmp_path / "schema_history").glob("*.json"))
    seqs = [json.loads(d.read_text())["seq"] for d in deltas]
    assert seqs == [1, 2, 3]
