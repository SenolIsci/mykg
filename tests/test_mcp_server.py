"""Tests for the mykg MCP server module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.mcp_server import KnowledgeGraph, _node_name, _node_summary


# ---------------------------------------------------------------------------
# Fixtures — synthetic session data
# ---------------------------------------------------------------------------

SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name", "industry"]},
    ],
    "properties": [
        {
            "name": "works_at",
            "domain": "Person",
            "range": "Organization",
            "attributes": ["role"],
        },
    ],
}

NODES = [
    {
        "id": "person-alice",
        "type": "Person",
        "confidence": 0.95,
        "attributes": {
            "name": {"value": "Alice Smith", "confidence": 0.99},
            "email": {"value": "alice@example.com", "confidence": 0.85},
        },
        "source_files": ["team.md"],
        "aliases": ["A. Smith"],
    },
    {
        "id": "person-bob",
        "type": "Person",
        "confidence": 0.90,
        "attributes": {
            "name": {"value": "Bob Jones", "confidence": 0.95},
            "email": {"value": None, "confidence": 0.0},
        },
        "source_files": ["team.md"],
    },
    {
        "id": "organization-acme",
        "type": "Organization",
        "confidence": 0.98,
        "attributes": {
            "name": {"value": "Acme Corp", "confidence": 1.0},
            "industry": {"value": "Technology", "confidence": 0.9},
        },
        "source_files": ["partners.md"],
        "aliases": ["ACME", "Acme Corporation"],
    },
]

EDGES = [
    {
        "id": "edge-001",
        "type": "works_at",
        "from": "person-alice",
        "to": "organization-acme",
        "confidence": 0.92,
        "attributes": {"role": {"value": "Engineer", "confidence": 0.88}},
        "method": "llm_extraction",
        "source_files": ["team.md"],
    },
    {
        "id": "edge-002",
        "type": "works_at",
        "from": "person-bob",
        "to": "organization-acme",
        "confidence": 0.85,
        "attributes": {"role": {"value": "Manager", "confidence": 0.80}},
        "method": "llm_extraction",
        "source_files": ["team.md"],
    },
]


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    """Create a temporary session directory with synthetic data."""
    output = tmp_path / "output"
    output.mkdir()
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()

    (output / "nodes.jsonl").write_text(
        "\n".join(json.dumps(n) for n in NODES), encoding="utf-8"
    )
    (output / "edges.jsonl").write_text(
        "\n".join(json.dumps(e) for e in EDGES), encoding="utf-8"
    )
    (intermediate / "schema.json").write_text(
        json.dumps(SCHEMA), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def kg(session_dir: Path) -> KnowledgeGraph:
    """Load a KnowledgeGraph from the temp session."""
    return KnowledgeGraph(session_root=session_dir)


# ---------------------------------------------------------------------------
# KnowledgeGraph loading and index tests
# ---------------------------------------------------------------------------


class TestKnowledgeGraphLoading:
    def test_loads_nodes_edges_schema(self, kg: KnowledgeGraph):
        assert len(kg.nodes) == 3
        assert len(kg.edges) == 2
        assert "concepts" in kg.schema
        assert "properties" in kg.schema

    def test_builds_nodes_by_id(self, kg: KnowledgeGraph):
        assert "person-alice" in kg.nodes_by_id
        assert "person-bob" in kg.nodes_by_id
        assert "organization-acme" in kg.nodes_by_id
        assert kg.nodes_by_id["person-alice"]["type"] == "Person"

    def test_builds_nodes_by_type(self, kg: KnowledgeGraph):
        assert len(kg.nodes_by_type["Person"]) == 2
        assert len(kg.nodes_by_type["Organization"]) == 1

    def test_builds_edges_by_node(self, kg: KnowledgeGraph):
        assert len(kg.edges_by_node["person-alice"]) == 1
        assert len(kg.edges_by_node["organization-acme"]) == 2

    def test_builds_name_index(self, kg: KnowledgeGraph):
        names = [entry[0] for entry in kg.name_index]
        assert "alice smith" in names
        assert "a. smith" in names
        assert "acme corp" in names

    def test_builds_alias_index(self, kg: KnowledgeGraph):
        assert kg.alias_index["acme"] == "organization-acme"
        assert kg.alias_index["a. smith"] == "person-alice"

    def test_builds_networkx_graph(self, kg: KnowledgeGraph):
        assert kg.graph.number_of_nodes() == 3
        assert kg.graph.number_of_edges() == 2

    def test_session_name(self, kg: KnowledgeGraph):
        assert kg.session_name == kg.session_root.name

    def test_vault_dir_none_when_missing(self, kg: KnowledgeGraph):
        assert kg.vault_dir is None

    def test_vault_dir_found(self, kg: KnowledgeGraph):
        vault = kg.session_root / "output" / "obsidian_vault"
        vault.mkdir(parents=True)
        assert kg.vault_dir == vault


# ---------------------------------------------------------------------------
# Helper function tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_node_name(self):
        assert _node_name(NODES[0]) == "Alice Smith"
        assert _node_name({"attributes": {}}) == ""
        assert _node_name({}) == ""

    def test_node_summary(self):
        s = _node_summary(NODES[0])
        assert s["id"] == "person-alice"
        assert s["type"] == "Person"
        assert s["name"] == "Alice Smith"
        assert s["confidence"] == 0.95


# ---------------------------------------------------------------------------
# Search logic tests (testing the query logic directly via KnowledgeGraph)
# ---------------------------------------------------------------------------


class TestSearchLogic:
    def test_search_exact_match(self, kg: KnowledgeGraph):
        results = []
        for name_lower, nid, original in kg.name_index:
            if name_lower == "alice smith":
                results.append(nid)
        assert "person-alice" in results

    def test_search_substring_match(self, kg: KnowledgeGraph):
        results = []
        for name_lower, nid, original in kg.name_index:
            if "alice" in name_lower:
                results.append(nid)
        assert "person-alice" in results

    def test_search_alias_match(self, kg: KnowledgeGraph):
        results = []
        for name_lower, nid, original in kg.name_index:
            if "acme" in name_lower:
                results.append(nid)
        assert "organization-acme" in results

    def test_search_by_type_filter(self, kg: KnowledgeGraph):
        persons = kg.nodes_by_type.get("Person", [])
        assert len(persons) == 2
        orgs = kg.nodes_by_type.get("Organization", [])
        assert len(orgs) == 1

    def test_get_node_found(self, kg: KnowledgeGraph):
        node = kg.nodes_by_id.get("person-alice")
        assert node is not None
        assert node["type"] == "Person"

    def test_get_node_not_found(self, kg: KnowledgeGraph):
        assert kg.nodes_by_id.get("nonexistent") is None


class TestNeighbors:
    def test_neighbors_both(self, kg: KnowledgeGraph):
        edges = kg.edges_by_node.get("organization-acme", [])
        assert len(edges) == 2

    def test_neighbors_outgoing(self, kg: KnowledgeGraph):
        edges = kg.edges_by_node.get("person-alice", [])
        outgoing = [e for e in edges if e["from"] == "person-alice"]
        assert len(outgoing) == 1
        assert outgoing[0]["to"] == "organization-acme"

    def test_neighbors_incoming(self, kg: KnowledgeGraph):
        edges = kg.edges_by_node.get("organization-acme", [])
        incoming = [e for e in edges if e["to"] == "organization-acme"]
        assert len(incoming) == 2


class TestPathFinding:
    def test_path_exists(self, kg: KnowledgeGraph):
        import networkx as _nx
        path = _nx.shortest_path(kg.graph, "person-alice", "organization-acme")
        assert path == ["person-alice", "organization-acme"]

    def test_path_between_persons(self, kg: KnowledgeGraph):
        import networkx as _nx
        undirected = kg.graph.to_undirected()
        path = _nx.shortest_path(undirected, "person-alice", "person-bob")
        assert len(path) == 3
        assert "organization-acme" in path

    def test_no_directed_path_reversed(self, kg: KnowledgeGraph):
        import networkx as _nx
        with pytest.raises(_nx.NetworkXNoPath):
            _nx.shortest_path(kg.graph, "organization-acme", "person-alice")


class TestStats:
    def test_graph_stats(self, kg: KnowledgeGraph):
        import networkx as _nx
        G = kg.graph
        assert G.number_of_nodes() == 3
        assert G.number_of_edges() == 2
        assert _nx.number_weakly_connected_components(G) == 1

    def test_type_distribution(self, kg: KnowledgeGraph):
        dist = {t: len(ns) for t, ns in kg.nodes_by_type.items()}
        assert dist["Person"] == 2
        assert dist["Organization"] == 1


class TestSubgraph:
    def test_filter_by_type(self, kg: KnowledgeGraph):
        persons = [n for n in kg.nodes if n.get("type") == "Person"]
        person_ids = {n["id"] for n in persons}
        edges = [e for e in kg.edges if e["from"] in person_ids and e["to"] in person_ids]
        assert len(persons) == 2
        assert len(edges) == 0

    def test_filter_by_confidence(self, kg: KnowledgeGraph):
        high_conf = [n for n in kg.nodes if n.get("confidence", 0) >= 0.95]
        assert len(high_conf) == 2


class TestNodeTypes:
    def test_list_sorted_descending(self, kg: KnowledgeGraph):
        types = sorted(kg.nodes_by_type.items(), key=lambda x: -len(x[1]))
        assert types[0][0] == "Person"
        assert types[1][0] == "Organization"


class TestHubNodes:
    def test_hub_by_degree(self, kg: KnowledgeGraph):
        degrees = sorted(kg.graph.degree(), key=lambda x: -x[1])
        assert degrees[0][0] == "organization-acme"
        assert degrees[0][1] == 2


class TestReadNote:
    def test_fallback_without_vault(self, kg: KnowledgeGraph):
        node = kg.nodes_by_id["person-alice"]
        assert node is not None
        assert kg.vault_dir is None

    def test_vault_note_found(self, kg: KnowledgeGraph):
        vault = kg.session_root / "output" / "obsidian_vault" / "Person"
        vault.mkdir(parents=True)
        note = vault / "person-alice.md"
        note.write_text("# Alice Smith\nSome note content.", encoding="utf-8")
        assert note.exists()
        content = note.read_text(encoding="utf-8")
        assert "Alice Smith" in content


# ---------------------------------------------------------------------------
# MCP server registration tests
# ---------------------------------------------------------------------------


class TestMCPServerRegistration:
    def test_mcp_server_has_tools(self):
        from mykg.mcp_server import mcp
        tool_names = [t.name for t in mcp._tool_manager.list_tools()]
        expected = [
            "mykg_search_nodes",
            "mykg_get_node",
            "mykg_get_neighbors",
            "mykg_find_path",
            "mykg_get_schema",
            "mykg_list_node_types",
            "mykg_query_subgraph",
            "mykg_get_stats",
            "mykg_query_graph",
            "mykg_hub_nodes",
            "mykg_orphan_nodes",
            "mykg_read_note",
            "mykg_list_sessions",
        ]
        for name in expected:
            assert name in tool_names, f"Tool '{name}' not registered"
        assert len(tool_names) == 13
