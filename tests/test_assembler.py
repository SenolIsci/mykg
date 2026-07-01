from mykg.assembler import assign_stable_ids, deduplicate_edges, deduplicate_nodes

RAW = {
    "file_a.md": {
        "nodes": [
            {
                "id": "person-alice",
                "type": "SoftwareEngineer",
                "confidence": 0.97,
                "attributes": {
                    "name": {"value": "Alice", "confidence": 0.99},
                    "email": {"value": "alice@acme.com", "confidence": 0.97},
                },
            }
        ],
        "edges": [
            {
                "id": "edge-001",
                "type": "works_at",
                "from": "person-alice",
                "to": "org-acme-corp",
                "confidence": 0.96,
                "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
            }
        ],
    },
    "file_b.md": {
        "nodes": [
            {
                "id": "alice-variant",
                "type": "SoftwareEngineer",
                "confidence": 0.88,
                "attributes": {
                    "name": {"value": "Alice", "confidence": 0.80},
                    "email": {"value": "a@acme.com", "confidence": 0.61},
                },
            },
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 0.99,
                "attributes": {"name": {"value": "Acme Corp", "confidence": 0.99}},
            },
        ],
        "edges": [
            {
                "id": "edge-002",
                "type": "works_at",
                "from": "alice-variant",
                "to": "org-acme",
                "confidence": 0.85,
                "attributes": {"role": {"value": "engineer", "confidence": 0.80}},
            }
        ],
    },
}


def test_stable_id_format():
    updated = assign_stable_ids(RAW)
    for file_data in updated.values():
        for node in file_data["nodes"]:
            assert "-" in node["id"]
            # id = type.lower() + "-" + name-slug
            assert node["id"].startswith(node["type"].lower())


def test_stable_id_same_entity_same_id():
    updated = assign_stable_ids(RAW)
    alice_ids = [
        node["id"]
        for file_data in updated.values()
        for node in file_data["nodes"]
        if node["attributes"]["name"]["value"] == "Alice"
    ]
    assert len(set(alice_ids)) == 1


def test_node_dedup_wins_highest_confidence():
    updated = assign_stable_ids(RAW)
    nodes, _ = deduplicate_nodes(updated)
    alice = next(n for n in nodes if n["id"].startswith("softwareengineer-alice"))
    # email from file_a has higher confidence
    assert alice["attributes"]["email"]["value"] == "alice@acme.com"


def test_node_dedup_records_source_files():
    updated = assign_stable_ids(RAW)
    nodes, _ = deduplicate_nodes(updated)
    alice = next(n for n in nodes if n["id"].startswith("softwareengineer-alice"))
    assert "file_a.md" in alice["source_files"]
    assert "file_b.md" in alice["source_files"]


def test_edge_dedup_merges_duplicates():
    updated = assign_stable_ids(RAW)
    edges, _ = deduplicate_edges(updated)
    works_at_edges = [e for e in edges.values() if e["type"] == "works_at"]
    assert len(works_at_edges) == 1


def test_edge_id_format():
    updated = assign_stable_ids(RAW)
    edges, _ = deduplicate_edges(updated)
    for edge_id in edges:
        assert edge_id.startswith("edge-")


def test_stable_id_type_prefix_no_spaces():
    """Type names with spaces must not produce IDs with spaces."""
    from mykg.assembler import _stable_id

    result = _stable_id("HTTP Server", "nginx")
    assert " " not in result
    assert result == "httpserver-nginx"


def test_resolve_type_aware_no_collision():
    """Two entities with same name but different types must not be collapsed."""
    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        },
        "file_b.md": {
            "nodes": [
                {
                    "id": "engineer-alice",
                    "type": "SoftwareEngineer",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [
                {
                    "id": "edge-001",
                    "type": "works_at",
                    "from": "engineer-alice",
                    "to": "person-alice",  # cross-file reference
                    "confidence": 0.8,
                    "attributes": {},
                }
            ],
        },
    }
    from mykg.assembler import assign_stable_ids

    updated = assign_stable_ids(raw)
    # The cross-file reference "person-alice" should resolve to the person-alice stable ID
    # not collapse into softwareengineer-alice
    edge = updated["file_b.md"]["edges"][0]
    assert edge["to"] == "person-alice"
    assert edge["from"] == "softwareengineer-alice"


def test_merge_log_returned_from_dedup_nodes():
    """deduplicate_nodes returns a merge log listing merge decisions."""
    from mykg.assembler import assign_stable_ids, deduplicate_nodes

    updated = assign_stable_ids(RAW)
    nodes, log = deduplicate_nodes(updated)
    assert isinstance(log, list)
    # RAW has two Alice nodes that merge into one
    merge_events = [e for e in log if e["event"] == "node_merge"]
    assert len(merge_events) == 1
    assert merge_events[0]["id"] == "softwareengineer-alice"
    assert len(merge_events[0]["sources"]) == 2


def test_merge_log_returned_from_dedup_edges():
    """deduplicate_edges returns a merge log listing merge decisions."""
    from mykg.assembler import assign_stable_ids, deduplicate_edges

    updated = assign_stable_ids(RAW)
    edges, log = deduplicate_edges(updated)
    assert isinstance(log, list)
    merge_events = [e for e in log if e["event"] == "edge_merge"]
    assert len(merge_events) == 1


def test_step_assemble_writes_merge_log(tmp_path):
    """run_assemble writes intermediate/merge_log.json."""
    import json
    from unittest.mock import MagicMock

    from mykg.steps.step_assemble import run_assemble

    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        }
    }
    (tmp_path / "raw_extractions.json").write_text(json.dumps(raw))
    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path
    run_assemble(ctx)
    assert (tmp_path / "merge_log.json").exists()
    data = json.loads((tmp_path / "merge_log.json").read_text())
    assert isinstance(data, list)


def test_dedup_nodes_confidence_agg_max():
    """deduplicate_nodes with agg='max' takes maximum confidence, not mean."""
    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        },
        "file_b.md": {
            "nodes": [
                {
                    "id": "person-alice-2",
                    "type": "Person",
                    "confidence": 0.5,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.5}},
                }
            ],
            "edges": [],
        },
    }
    updated = assign_stable_ids(raw)
    nodes, _ = deduplicate_nodes(updated, confidence_agg="max")
    assert len(nodes) == 1
    assert nodes[0]["confidence"] == 0.9  # max, not mean (0.7)


def test_dedup_nodes_confidence_agg_mean():
    """deduplicate_nodes with agg='mean' (default) averages confidence."""
    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        },
        "file_b.md": {
            "nodes": [
                {
                    "id": "person-alice-2",
                    "type": "Person",
                    "confidence": 0.5,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.5}},
                }
            ],
            "edges": [],
        },
    }
    updated = assign_stable_ids(raw)
    nodes, _ = deduplicate_nodes(updated, confidence_agg="mean")
    assert abs(nodes[0]["confidence"] - 0.7) < 0.001


def test_dedup_nodes_coerces_first_occurrence_attributes():
    """First occurrence attributes must be coerced to {value, confidence} form.

    This test verifies that if the first occurrence has raw scalar attributes
    (e.g., "engineer" instead of {"value": "engineer", "confidence": 0.91}),
    they are normalized to canonical form in the merged output.
    """
    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    # Raw scalar attribute in first occurrence (violates D9)
                    "attributes": {
                        "name": "Alice",
                        "email": {"value": "alice@acme.com", "confidence": 0.95},
                    },
                }
            ],
            "edges": [],
        },
        "file_b.md": {
            "nodes": [
                {
                    "id": "person-alice-2",
                    "type": "Person",
                    "confidence": 0.8,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.85}},
                }
            ],
            "edges": [],
        },
    }
    updated = assign_stable_ids(raw)
    nodes, _ = deduplicate_nodes(updated)

    alice = nodes[0]
    # Both 'name' and 'email' must have canonical {value, confidence} form
    assert isinstance(alice["attributes"]["name"], dict)
    assert "value" in alice["attributes"]["name"]
    assert "confidence" in alice["attributes"]["name"]
    assert alice["attributes"]["name"]["value"] == "Alice"

    assert isinstance(alice["attributes"]["email"], dict)
    assert "value" in alice["attributes"]["email"]
    assert "confidence" in alice["attributes"]["email"]
    assert alice["attributes"]["email"]["value"] == "alice@acme.com"


def test_coerce_attr_non_numeric_confidence_string():
    """_coerce_attr should handle non-numeric confidence like 'high' by falling back."""
    from mykg.assembler import _coerce_attr

    result = _coerce_attr({"value": "Alice", "confidence": "high"})
    assert result["value"] == "Alice"
    # Should use fallback (from config)
    from mykg import config as _cfg

    assert result["confidence"] == _cfg.CONFIDENCE_FALLBACK


def test_coerce_attr_confidence_above_one():
    """_coerce_attr should clamp confidence > 1.0 to 1.0."""
    from mykg.assembler import _coerce_attr

    result = _coerce_attr({"value": "Bob", "confidence": 1.5})
    assert result["value"] == "Bob"
    assert result["confidence"] == 1.0


def test_coerce_attr_confidence_below_zero():
    """_coerce_attr should clamp confidence < 0.0 to 0.0."""
    from mykg.assembler import _coerce_attr

    result = _coerce_attr({"value": "Charlie", "confidence": -0.2})
    assert result["value"] == "Charlie"
    assert result["confidence"] == 0.0


def test_coerce_attr_valid_confidence_passthrough():
    """_coerce_attr should pass through valid confidence in [0.0, 1.0] unchanged."""
    from mykg.assembler import _coerce_attr

    result = _coerce_attr({"value": "Diana", "confidence": 0.75})
    assert result["value"] == "Diana"
    assert result["confidence"] == 0.75


def test_coerce_attr_scalar_uses_fallback():
    """_coerce_attr should handle scalar values by using fallback confidence."""
    from mykg import config as _cfg
    from mykg.assembler import _coerce_attr

    result = _coerce_attr("raw_string")
    assert result["value"] == "raw_string"
    assert result["confidence"] == _cfg.CONFIDENCE_FALLBACK


# ---------------------------------------------------------------------------
# Extended Unit 12 — assembler edge paths
# ---------------------------------------------------------------------------


def test_node_dedup_confidence_one_string_concat():
    """Two sources with confidence=1.0 different strings concatenate with '; '."""
    from mykg.assembler import deduplicate_nodes

    raw = {
        "a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"role": {"value": "engineer", "confidence": 1.0}},
                }
            ],
            "edges": [],
        },
        "b.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"role": {"value": "manager", "confidence": 1.0}},
                }
            ],
            "edges": [],
        },
    }
    nodes, merge_log = deduplicate_nodes(raw)
    assert len(nodes) == 1
    val = nodes[0]["attributes"]["role"]["value"]
    assert "engineer" in val and "manager" in val and ";" in val
    assert merge_log and "concatenated_attributes" in merge_log[0]


def test_edge_dedup_confidence_one_string_concat():
    """Edge attribute concat when both have confidence=1.0 with different strings."""
    from mykg.assembler import deduplicate_edges

    raw = {
        "a.md": {
            "nodes": [],
            "edges": [
                {
                    "type": "works_at",
                    "from": "p-1",
                    "to": "o-1",
                    "confidence": 1.0,
                    "attributes": {"role": {"value": "engineer", "confidence": 1.0}},
                }
            ],
        },
        "b.md": {
            "nodes": [],
            "edges": [
                {
                    "type": "works_at",
                    "from": "p-1",
                    "to": "o-1",
                    "confidence": 1.0,
                    "attributes": {"role": {"value": "manager", "confidence": 1.0}},
                }
            ],
        },
    }
    edges, merge_log = deduplicate_edges(raw)
    edge = next(iter(edges.values()))
    val = edge["attributes"]["role"]["value"]
    assert "engineer" in val and "manager" in val and ";" in val
    assert merge_log and "concatenated_attributes" in merge_log[0]


def test_node_dedup_alias_union():
    """Aliases from two sources are unioned (D29)."""
    from mykg.assembler import deduplicate_nodes

    raw = {
        "a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                    "aliases": ["Ali"],
                }
            ],
            "edges": [],
        },
        "b.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                    "aliases": ["A.", "Liz"],
                }
            ],
            "edges": [],
        },
    }
    nodes, _ = deduplicate_nodes(raw)
    assert sorted(nodes[0]["aliases"]) == ["A.", "Ali", "Liz"]


def test_node_dedup_no_aliases_field_absent():
    """Nodes with no aliases get no aliases key in the merged output (per D29)."""
    from mykg.assembler import deduplicate_nodes

    raw = {
        "a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                }
            ],
            "edges": [],
        },
    }
    nodes, _ = deduplicate_nodes(raw)
    assert "aliases" not in nodes[0]


def test_edge_dedup_with_non_dict_attrs():
    """Edges with non-dict attributes coerce gracefully."""
    from mykg.assembler import deduplicate_edges

    raw = {
        "a.md": {
            "nodes": [],
            "edges": [
                {
                    "type": "works_at",
                    "from": "p-1",
                    "to": "o-1",
                    "confidence": 0.9,
                    "attributes": "not-a-dict",
                }
            ],
        },
        "b.md": {
            "nodes": [],
            "edges": [
                {
                    "type": "works_at",
                    "from": "p-1",
                    "to": "o-1",
                    "confidence": 0.9,
                    "attributes": {"role": {"value": "engineer", "confidence": 0.8}},
                }
            ],
        },
    }
    edges, _ = deduplicate_edges(raw)
    edge = next(iter(edges.values()))
    assert isinstance(edge["attributes"], dict)


def test_dedup_nodes_with_non_dict_attrs():
    """Node with non-dict attributes still merges without error."""
    from mykg.assembler import deduplicate_nodes

    raw = {
        "a.md": {
            "nodes": [
                {
                    "id": "p-1",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                },
            ],
            "edges": [],
        },
        "b.md": {
            "nodes": [
                {
                    "id": "p-1",
                    "type": "Person",
                    "confidence": 0.5,
                    "attributes": "not-a-dict",
                },
            ],
            "edges": [],
        },
    }
    nodes, _ = deduplicate_nodes(raw)
    assert len(nodes) == 1
    assert nodes[0]["attributes"]["name"]["value"] == "Alice"


def test_deduplicate_nodes_malformed_confidence_does_not_raise():
    """Nodes with non-numeric confidence (e.g. '#') must not crash deduplicate_nodes (issue #32 Bug 1)."""
    from mykg.assembler import assign_stable_ids, deduplicate_nodes

    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": "#",
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        }
    }
    updated = assign_stable_ids(raw)
    nodes, _ = deduplicate_nodes(updated)
    assert len(nodes) == 1
    assert 0.0 <= nodes[0]["confidence"] <= 1.0


def test_deduplicate_edges_malformed_confidence_does_not_raise():
    """Edges with non-numeric confidence (e.g. 'N/A') must not crash deduplicate_edges (issue #32 Bug 1)."""
    from mykg.assembler import assign_stable_ids, deduplicate_edges

    raw = {
        "file_a.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                },
                {
                    "id": "org-acme",
                    "type": "Organization",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
                },
            ],
            "edges": [
                {
                    "type": "works_at",
                    "from": "person-alice",
                    "to": "org-acme",
                    "confidence": "N/A",
                    "attributes": {},
                }
            ],
        }
    }
    updated = assign_stable_ids(raw)
    edge_metadata, _ = deduplicate_edges(updated)
    assert len(edge_metadata) == 1
    edge = next(iter(edge_metadata.values()))
    assert 0.0 <= edge["confidence"] <= 1.0
