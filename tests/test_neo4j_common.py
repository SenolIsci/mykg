from __future__ import annotations

from pathlib import Path

import pytest

from mykg.exporters.neo4j._common import (
    flatten_edge_properties,
    flatten_node_properties,
    load_session,
    parent_chain,
    sanitize_label,
    sanitize_rel_type,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "neo4j_sample_session"


def test_load_session_returns_nodes_edges_schema():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    assert len(nodes) == 6
    assert len(edges) == 6
    assert {c["type"] for c in schema["concepts"]} == {"Person", "SoftwareEngineer", "Organization"}


def test_load_session_missing_nodes_jsonl(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "intermediate").mkdir()
    (tmp_path / "intermediate" / "schema.json").write_text("{}")
    with pytest.raises(FileNotFoundError, match="nodes.jsonl"):
        load_session(tmp_path)


def test_load_session_missing_schema(tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "nodes.jsonl").write_text("")
    (tmp_path / "output" / "edges.jsonl").write_text("")
    with pytest.raises(FileNotFoundError, match="schema.json"):
        load_session(tmp_path)


@pytest.mark.parametrize("raw,expected", [
    ("Person", "Person"),
    ("SoftwareEngineer", "SoftwareEngineer"),
    ("software_engineer", "SoftwareEngineer"),
    ("software-engineer", "SoftwareEngineer"),
    ("urban planner", "UrbanPlanner"),
    ("123Bad", "Bad"),
])
def test_sanitize_label(raw, expected):
    assert sanitize_label(raw) == expected


SCHEMA_FIXTURE = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": []},
        {"type": "SoftwareEngineer", "parent": "Person", "attributes": []},
        {"type": "SeniorEngineer", "parent": "SoftwareEngineer", "attributes": []},
        {"type": "Organization", "parent": None, "attributes": []},
    ]
}


def test_parent_chain_root_type():
    assert parent_chain(SCHEMA_FIXTURE, "Person") == []


def test_parent_chain_single_parent():
    assert parent_chain(SCHEMA_FIXTURE, "SoftwareEngineer") == ["Person"]


def test_parent_chain_multi_level():
    assert parent_chain(SCHEMA_FIXTURE, "SeniorEngineer") == ["SoftwareEngineer", "Person"]


def test_parent_chain_unknown_type_returns_empty():
    assert parent_chain(SCHEMA_FIXTURE, "Alien") == []


def test_parent_chain_breaks_cycle():
    cyclic = {"concepts": [
        {"type": "A", "parent": "B"},
        {"type": "B", "parent": "A"},
    ]}
    assert parent_chain(cyclic, "A") == ["B"]


def test_flatten_node_full():
    node = {
        "id": "softwareengineer-alice",
        "type": "SoftwareEngineer",
        "confidence": 0.95,
        "attributes": {
            "name": {"value": "Alice", "confidence": 0.99},
            "email": {"value": "alice@acme.com", "confidence": 0.97},
        },
        "aliases": ["A. Smith", "Alice Smith"],
        "source_files": ["team.md"],
    }
    props = flatten_node_properties(node, SCHEMA_FIXTURE)
    assert props == {
        "id": "softwareengineer-alice",
        "name": "Alice",
        "name_confidence": 0.99,
        "email": "alice@acme.com",
        "email_confidence": 0.97,
        "_node_confidence": 0.95,
        "_parents": ["Person"],
        "_aliases": ["A. Smith", "Alice Smith"],
        "_source_files": ["team.md"],
    }


def test_flatten_node_omits_null_attributes():
    node = {
        "id": "person-bob",
        "type": "Person",
        "confidence": 0.90,
        "attributes": {
            "name": {"value": "Bob", "confidence": 0.99},
            "email": {"value": None, "confidence": 0.0},
        },
        "aliases": [],
        "source_files": ["team.md"],
    }
    props = flatten_node_properties(node, SCHEMA_FIXTURE)
    assert "email" not in props
    assert "email_confidence" not in props
    assert props["_aliases"] == []


def test_flatten_node_omits_aliases_when_absent():
    node = {
        "id": "person-carol",
        "type": "Person",
        "confidence": 0.93,
        "attributes": {"name": {"value": "Carol", "confidence": 0.99}},
        "source_files": ["notes.md"],
    }
    props = flatten_node_properties(node, SCHEMA_FIXTURE)
    assert "_aliases" not in props


def test_flatten_edge_full():
    edge = {
        "id": "edge-001",
        "type": "works_at",
        "from": "softwareengineer-alice",
        "to": "organization-acme-corp",
        "confidence": 0.96,
        "attributes": {
            "role": {"value": "engineer", "confidence": 0.91},
            "start_date": {"value": "2024-01-15", "confidence": 0.88},
        },
        "method": "llm_extraction",
        "source_files": ["team.md"],
    }
    props = flatten_edge_properties(edge)
    assert props == {
        "confidence": 0.96,
        "role": "engineer",
        "role_confidence": 0.91,
        "start_date": "2024-01-15",
        "start_date_confidence": 0.88,
        "method": "llm_extraction",
        "source_files": ["team.md"],
    }


def test_flatten_edge_omits_null_attrs():
    edge = {
        "id": "edge-002",
        "type": "works_at",
        "from": "a",
        "to": "b",
        "confidence": 0.92,
        "attributes": {
            "role": {"value": "manager", "confidence": 0.89},
            "start_date": {"value": None, "confidence": 0.0},
        },
        "method": "llm_extraction",
        "source_files": ["team.md"],
    }
    props = flatten_edge_properties(edge)
    assert "start_date" not in props
    assert "start_date_confidence" not in props


def test_flatten_edge_empty_attributes():
    edge = {
        "id": "edge-004",
        "type": "knows",
        "from": "a",
        "to": "b",
        "confidence": 0.85,
        "attributes": {},
        "method": "orphan_inferred",
        "source_files": ["team.md"],
    }
    props = flatten_edge_properties(edge)
    assert props == {
        "confidence": 0.85,
        "method": "orphan_inferred",
        "source_files": ["team.md"],
    }


@pytest.mark.parametrize("raw,expected", [
    ("works_at", "WORKS_AT"),
    ("worksAt", "WORKS_AT"),
    ("WorksAt", "WORKS_AT"),
    ("works at", "WORKS_AT"),
    ("works-at", "WORKS_AT"),
    ("located_in", "LOCATED_IN"),
])
def test_sanitize_rel_type(raw, expected):
    assert sanitize_rel_type(raw) == expected
