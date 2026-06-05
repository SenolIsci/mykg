from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import yaml

from mykg.exporter import (
    export_edges_jsonl,
    export_html,
    export_nodes_jsonl,
    export_obsidian,
    export_ttl,
)

SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]}
    ],
}

NODES = [
    {
        "id": "person-alice",
        "type": "Person",
        "confidence": 0.99,
        "source_files": ["team.md"],
        "attributes": {
            "name": {"value": "Alice", "confidence": 0.99},
            "email": {"value": "alice@acme.com", "confidence": 0.97},
        },
    },
    {
        "id": "organization-acme-corp",
        "type": "Organization",
        "confidence": 0.99,
        "source_files": ["team.md"],
        "attributes": {"name": {"value": "Acme Corp", "confidence": 0.99}},
    },
]

EDGE_METADATA = {
    "edge-abc123": {
        "type": "works_at",
        "from": "person-alice",
        "to": "organization-acme-corp",
        "confidence": 0.96,
        "source_files": ["team.md"],
        "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
    }
}


def test_nodes_jsonl_line_count():
    lines = export_nodes_jsonl(NODES).strip().split("\n")
    assert len(lines) == 2


def test_nodes_jsonl_valid_json():
    output = export_nodes_jsonl(NODES)
    for line in output.strip().split("\n"):
        obj = json.loads(line)
        assert "id" in obj
        assert "type" in obj


def test_edges_jsonl_line_count():
    lines = export_edges_jsonl(EDGE_METADATA).strip().split("\n")
    assert len(lines) == 1


def test_edges_jsonl_valid_json():
    output = export_edges_jsonl(EDGE_METADATA)
    obj = json.loads(output.strip())
    assert obj["id"] == "edge-abc123"
    assert obj["type"] == "works_at"


def test_ttl_contains_tbox_classes():
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "rdfs:Class" in ttl
    assert "ex:Person" in ttl
    assert "ex:Organization" in ttl


def test_ttl_contains_tbox_properties():
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "ex:works_at" in ttl
    assert "rdf:Property" in ttl


def test_ttl_contains_abox_instances():
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "data:person-alice" in ttl
    assert "data:organization-acme-corp" in ttl


def test_ttl_contains_abox_object_triple():
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "ex:works_at" in ttl
    assert "data:person-alice" in ttl and "data:organization-acme-corp" in ttl


def test_ttl_no_confidence_in_output():
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "confidence" not in ttl


def test_ttl_escapes_newline_in_literal():
    """Attribute values containing newlines must be escaped in Turtle output."""
    from mykg.exporter import export_ttl

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["bio"]}],
        "properties": [],
    }
    nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {
                "bio": {"value": "line one\nline two\r\nline three\ttabbed", "confidence": 0.9}
            },
        }
    ]
    ttl = export_ttl(schema, nodes, {})
    # Parse with rdflib to confirm it's valid Turtle
    from rdflib import Graph

    g = Graph()
    g.parse(data=ttl, format="turtle")  # must not raise


# ---------------------------------------------------------------------------
# export_obsidian tests
# ---------------------------------------------------------------------------

_OBS_NODES = [
    {
        "id": "person-alice-johnson",
        "type": "Person",
        "confidence": 0.94,
        "source_files": ["team.md"],
        "attributes": {
            "name": {"value": "Alice Johnson", "confidence": 1.0},
            "role": {"value": "Engineer", "confidence": 0.91},
            "email": {"value": "alice@example.com", "confidence": 1.0},
        },
        "aliases": ["Alice", "A. Johnson"],
    },
    {
        "id": "organization-acme-corp",
        "type": "Organization",
        "confidence": 0.99,
        "source_files": ["team.md"],
        "attributes": {
            "name": {"value": "Acme Corp", "confidence": 0.99},
        },
    },
    {
        "id": "person-bob-smith",
        "type": "Person",
        "confidence": 0.88,
        "source_files": ["team.md"],
        "attributes": {
            "name": {"value": "Bob Smith", "confidence": 1.0},
        },
    },
]

_OBS_EDGE_METADATA = {
    "edge-001": {
        "type": "works_at",
        "from": "person-alice-johnson",
        "to": "organization-acme-corp",
        "confidence": 0.96,
        "source_files": ["team.md"],
        "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
    },
    "edge-002": {
        "type": "manages",
        "from": "person-bob-smith",
        "to": "person-alice-johnson",
        "confidence": 0.88,
        "source_files": ["team.md"],
        "attributes": {},
    },
}

_OBS_SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "role", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]},
        {"name": "manages", "domain": "Person", "range": "Person", "attributes": []},
    ],
}


def _run_obsidian(tmp_path: Path) -> list[str]:
    """Call export_obsidian with OBSIDIAN_ENABLED patched to True."""
    with mock.patch("mykg.exporter._cfg") as mock_cfg:
        mock_cfg.OBSIDIAN_ENABLED = True
        mock_cfg.JSON_INDENT = 2
        return export_obsidian(_OBS_NODES, _OBS_EDGE_METADATA, _OBS_SCHEMA, tmp_path)


def test_obsidian_returns_empty_when_disabled(tmp_path: Path) -> None:
    """export_obsidian returns [] when OBSIDIAN_ENABLED is False (or absent)."""
    with mock.patch("mykg.exporter._cfg") as mock_cfg:
        mock_cfg.OBSIDIAN_ENABLED = False
        result = export_obsidian(_OBS_NODES, _OBS_EDGE_METADATA, _OBS_SCHEMA, tmp_path)
    assert result == []


def test_obsidian_creates_type_subdirs(tmp_path: Path) -> None:
    """Nodes are written under Type/ subdirectories inside obsidian_vault/."""
    _run_obsidian(tmp_path)
    vault = tmp_path / "obsidian_vault"
    assert (vault / "Person").is_dir()
    assert (vault / "Organization").is_dir()


def test_obsidian_creates_node_files(tmp_path: Path) -> None:
    """One .md file is created per node with the node_id as filename."""
    _run_obsidian(tmp_path)
    vault = tmp_path / "obsidian_vault"
    assert (vault / "Person" / "person-alice-johnson.md").exists()
    assert (vault / "Organization" / "organization-acme-corp.md").exists()
    assert (vault / "Person" / "person-bob-smith.md").exists()


def test_obsidian_frontmatter_is_valid_yaml(tmp_path: Path) -> None:
    """YAML frontmatter in entity notes must parse without error."""
    _run_obsidian(tmp_path)
    note_path = tmp_path / "obsidian_vault" / "Person" / "person-alice-johnson.md"
    content = note_path.read_text(encoding="utf-8")

    # Extract frontmatter between the first pair of '---' delimiters
    parts = content.split("---")
    assert len(parts) >= 3, "expected YAML frontmatter delimiters"
    fm = yaml.safe_load(parts[1])
    assert fm["id"] == "person-alice-johnson"
    assert fm["type"] == "Person"
    assert isinstance(fm["confidence"], float)
    assert "team.md" in fm["sources"]


def test_obsidian_outgoing_wikilink(tmp_path: Path) -> None:
    """Outgoing relationship section contains a wikilink to the target entity."""
    _run_obsidian(tmp_path)
    note_path = tmp_path / "obsidian_vault" / "Person" / "person-alice-johnson.md"
    content = note_path.read_text(encoding="utf-8")
    assert "[[Acme Corp]]" in content
    assert "works_at" in content


def test_obsidian_incoming_wikilink(tmp_path: Path) -> None:
    """Incoming relationship section contains a wikilink to the source entity."""
    _run_obsidian(tmp_path)
    note_path = tmp_path / "obsidian_vault" / "Person" / "person-alice-johnson.md"
    content = note_path.read_text(encoding="utf-8")
    assert "[[Bob Smith]]" in content
    assert "manages" in content


def test_obsidian_index_exists(tmp_path: Path) -> None:
    """index.md is created at the vault root."""
    _run_obsidian(tmp_path)
    assert (tmp_path / "obsidian_vault" / "index.md").exists()


def test_obsidian_index_lists_all_nodes(tmp_path: Path) -> None:
    """index.md wikilinks to every node by display name."""
    _run_obsidian(tmp_path)
    index = (tmp_path / "obsidian_vault" / "index.md").read_text(encoding="utf-8")
    assert "[[Alice Johnson]]" in index
    assert "[[Acme Corp]]" in index
    assert "[[Bob Smith]]" in index


def test_obsidian_return_value_is_list_of_strings(tmp_path: Path) -> None:
    """Return value is a list of relative path strings."""
    result = _run_obsidian(tmp_path)
    assert isinstance(result, list)
    assert all(isinstance(p, str) for p in result)
    assert any(p.startswith("obsidian_vault/") for p in result)
    assert "obsidian_vault/index.md" in result


def test_obsidian_return_value_includes_all_node_paths(tmp_path: Path) -> None:
    """Return value contains one path per node plus index.md."""
    result = _run_obsidian(tmp_path)
    node_paths = [p for p in result if p != "obsidian_vault/index.md"]
    assert len(node_paths) == len(_OBS_NODES)


# ---------------------------------------------------------------------------
# Extra coverage: aliases / subClassOf / NX list flattening / obsidian fallback
# ---------------------------------------------------------------------------


def test_ttl_no_aliases_no_skos_prefix():
    """When no node has aliases, the @prefix skos: line and altLabel triples are absent."""
    ttl = export_ttl(SCHEMA, NODES, EDGE_METADATA)
    assert "skos:altLabel" not in ttl
    assert "@prefix skos:" not in ttl


def test_ttl_with_aliases_emits_altLabel_and_skos_prefix():
    """If at least one node has aliases, skos:altLabel triples + skos: prefix declaration appear."""
    nodes_with_aliases = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.99,
            "attributes": {"name": {"value": "Alice", "confidence": 0.99}},
            "aliases": ["A. Smith", "Allie"],
        },
    ]
    ttl = export_ttl(SCHEMA, nodes_with_aliases, {})
    assert "@prefix skos:" in ttl
    assert "skos:altLabel" in ttl
    assert "A. Smith" in ttl
    assert "Allie" in ttl


def test_ttl_subclassof_branch():
    """A concept whose parent is non-None emits an rdfs:subClassOf triple."""
    schema = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "SoftwareEngineer", "parent": "Person", "attributes": []},
        ],
        "properties": [],
    }
    ttl = export_ttl(schema, [], {})
    assert "ex:SoftwareEngineer rdfs:subClassOf ex:Person" in ttl


def test_ttl_attribute_value_is_list_gets_joined():
    """When an attribute's value is a list, export_ttl joins it with ', '."""
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["nicknames"]}],
        "properties": [],
    }
    nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {"nicknames": {"value": ["Al", "Ally"], "confidence": 0.9}},
        }
    ]
    ttl = export_ttl(schema, nodes, {})
    assert "Al, Ally" in ttl


def test_nx_flatten_attributes_with_list_value():
    """_nx_flatten_attributes joins list values with '|' for GML safety."""
    from mykg.exporter import _nx_flatten_attributes

    flat = _nx_flatten_attributes(
        {"tags": {"value": ["python", "rust"], "confidence": 0.8}}
    )
    assert flat["attr_tags_value"] == "python|rust"
    assert flat["attr_tags_confidence"] == 0.8


def test_node_display_name_falls_back_to_id_when_no_name_attr():
    """_node_display_name returns node['id'] when the 'name' attribute is absent."""
    from mykg.exporter import _node_display_name

    node = {"id": "person-noname", "attributes": {}}
    assert _node_display_name(node) == "person-noname"


def test_node_display_name_falls_back_when_name_value_falsy():
    """If name attr exists but its value is empty, _node_display_name returns the id."""
    from mykg.exporter import _node_display_name

    node = {"id": "person-noname", "attributes": {"name": {"value": "", "confidence": 0.0}}}
    assert _node_display_name(node) == "person-noname"


def test_html_contains_confidence_filter_sliders(tmp_path: Path) -> None:
    """export_html injects two confidence sliders and exposes _confidence on edges."""
    import networkx as nx

    G = nx.DiGraph()
    G.add_node("person-alice", label="Alice", node_type="Person", confidence=0.9)
    G.add_node("organization-acme", label="Acme", node_type="Organization", confidence=0.8)
    G.add_edge(
        "person-alice", "organization-acme", edge_type="works_at", confidence=0.7
    )

    export_html(G, tmp_path)
    content = (tmp_path / "knowledge_graph.html").read_text(encoding="utf-8")

    assert 'id="node-conf-slider"' in content
    assert 'id="edge-conf-slider"' in content
    assert "applyConfidenceFilter" in content
    # _confidence must appear in RAW_NODES (existing) and RAW_EDGES (new)
    assert content.count("_confidence") >= 2


def test_obsidian_entity_note_payload_not_dict_branch(tmp_path: Path) -> None:
    """_obsidian_entity_note handles attribute payloads that are bare values, not dicts."""
    from mykg.exporter import _obsidian_entity_note

    node = {
        "id": "person-bare",
        "type": "Person",
        "confidence": 0.8,
        "attributes": {
            "name": {"value": "Bare Person", "confidence": 1.0},
            "raw_attr": "just-a-string",  # NOT a dict — exercises lines 737-738
        },
        "source_files": [],
    }
    content = _obsidian_entity_note(node, outgoing=[], incoming=[])
    assert "just-a-string" in content
    assert "raw_attr" in content
