"""Concept-type remapping at assembly time (merge pipeline only).

When the schema merge collapses Employee into Person, instances extracted as
Employee must be retyped before stable IDs are derived, so the pair becomes one
node rather than two.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from mykg.assembler import assign_stable_ids, deduplicate_nodes
from mykg.merge_type_remap import apply_type_remap, build_type_remap, load_type_remap
from mykg.steps.step_merge_assemble import run_merge_assemble

# ---------------------------------------------------------------------------
# build_type_remap
# ---------------------------------------------------------------------------

_SCHEMA = {"concepts": [{"type": "Person"}, {"type": "Organization"}, {"type": "C"}]}


def test_build_remap_from_thesaurus_collapse():
    events = [
        {
            "event": "concept_collapsed_by_thesaurus",
            "concept": "Employee",
            "collapsed_into": "Person",
        }
    ]
    assert build_type_remap(events, _SCHEMA) == {"Employee": "Person"}


def test_build_remap_from_synonym_collapse():
    events = [{"event": "synonym_collapse", "discarded": "Org", "kept": "Organization"}]
    assert build_type_remap(events, _SCHEMA) == {"Org": "Organization"}


def test_build_remap_ignores_unrelated_events():
    events = [
        {"event": "concept_restored", "concept": "Product"},
        {"event": "parent_conflict", "concept": "Team"},
        {"event": "attribute_synonym", "owner": "Person"},
    ]
    assert build_type_remap(events, _SCHEMA) == {}


def test_build_remap_resolves_chain():
    """A -> B -> C must resolve to C, not leave A pointing at a removed B."""
    events = [
        {"event": "synonym_collapse", "discarded": "A", "kept": "B"},
        {"event": "synonym_collapse", "discarded": "B", "kept": "C"},
    ]
    assert build_type_remap(events, _SCHEMA) == {"A": "C", "B": "C"}


def test_build_remap_drops_cycle():
    """A cycle must be dropped rather than looping or resolving arbitrarily."""
    events = [
        {"event": "synonym_collapse", "discarded": "A", "kept": "B"},
        {"event": "synonym_collapse", "discarded": "B", "kept": "A"},
    ]
    assert build_type_remap(events, _SCHEMA) == {}


def test_build_remap_drops_undeclared_target():
    """Remapping onto a type the schema does not declare would strand the node."""
    events = [
        {
            "event": "concept_collapsed_by_thesaurus",
            "concept": "X",
            "collapsed_into": "NotInSchema",
        }
    ]
    assert build_type_remap(events, _SCHEMA) == {}


def test_build_remap_without_schema_skips_declared_check():
    events = [{"event": "synonym_collapse", "discarded": "X", "kept": "Whatever"}]
    assert build_type_remap(events, None) == {"X": "Whatever"}


# ---------------------------------------------------------------------------
# apply_type_remap
# ---------------------------------------------------------------------------


def _raw_two_types():
    return {
        "a.md": {
            "nodes": [
                {
                    "id": "n1",
                    "type": "Employee",
                    "confidence": 0.9,
                    "attributes": {
                        "name": {"value": "Alice Chen", "confidence": 1.0},
                        "join_date": {"value": "2020", "confidence": 0.8},
                    },
                }
            ],
            "edges": [],
        },
        "b.md": {
            "nodes": [
                {
                    "id": "n2",
                    "type": "Person",
                    "confidence": 0.8,
                    "attributes": {
                        "name": {"value": "Alice Chen", "confidence": 1.0},
                        "email": {"value": "alice@x.com", "confidence": 0.9},
                    },
                }
            ],
            "edges": [],
        },
    }


def test_apply_remap_does_not_mutate_input():
    raw = _raw_two_types()
    apply_type_remap(raw, {"Employee": "Person"}, [])
    assert raw["a.md"]["nodes"][0]["type"] == "Employee"


def test_apply_remap_rewrites_type_and_logs():
    events: list[dict] = []
    out = apply_type_remap(_raw_two_types(), {"Employee": "Person"}, events)
    assert out["a.md"]["nodes"][0]["type"] == "Person"
    assert len(events) == 1
    assert events[0]["event"] == "type_remap"
    assert events[0]["from_type"] == "Employee"
    assert events[0]["to_type"] == "Person"


def test_apply_remap_empty_map_is_identity():
    raw = _raw_two_types()
    assert apply_type_remap(raw, {}, []) is raw


def test_remap_collapses_two_nodes_into_one():
    """The whole point: same person, two types, becomes one node."""
    before, _ = deduplicate_nodes(assign_stable_ids(_raw_two_types()))
    assert len(before) == 2

    remapped = apply_type_remap(_raw_two_types(), {"Employee": "Person"}, [])
    after, _ = deduplicate_nodes(assign_stable_ids(remapped))
    assert len(after) == 1
    assert after[0]["type"] == "Person"
    assert after[0]["id"] == "person-alice-chen"


def test_remap_merges_attributes_and_sources():
    """Attributes from both occurrences survive; existing dedup rules apply."""
    remapped = apply_type_remap(_raw_two_types(), {"Employee": "Person"}, [])
    nodes, _ = deduplicate_nodes(assign_stable_ids(remapped))
    attrs = nodes[0]["attributes"]
    assert attrs["join_date"]["value"] == "2020"
    assert attrs["email"]["value"] == "alice@x.com"
    assert set(nodes[0]["source_files"]) == {"a.md", "b.md"}


def test_remap_collapses_parallel_edges():
    """Edges whose endpoints converge must dedup into one."""
    raw = {
        "a.md": {
            "nodes": [
                {
                    "id": "employee-alice",
                    "type": "Employee",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                },
                {
                    "id": "organization-acme",
                    "type": "Organization",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
                },
            ],
            "edges": [
                {
                    "type": "works_at",
                    "from": "employee-alice",
                    "to": "organization-acme",
                    "confidence": 1.0,
                    "attributes": {},
                }
            ],
        },
        "b.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                },
                {
                    "id": "organization-acme",
                    "type": "Organization",
                    "confidence": 1.0,
                    "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
                },
            ],
            "edges": [
                {
                    "type": "works_at",
                    "from": "person-alice",
                    "to": "organization-acme",
                    "confidence": 1.0,
                    "attributes": {},
                }
            ],
        },
    }
    from mykg.assembler import deduplicate_edges

    remapped = apply_type_remap(raw, {"Employee": "Person"}, [])
    with_ids = assign_stable_ids(remapped)
    nodes, _ = deduplicate_nodes(with_ids)
    edges, _ = deduplicate_edges(with_ids)
    assert len([n for n in nodes if n["type"] == "Person"]) == 1
    assert len(edges) == 1
    edge = next(iter(edges.values()))
    assert edge["from"] == "person-alice"


# ---------------------------------------------------------------------------
# run_merge_assemble
# ---------------------------------------------------------------------------


def _ctx(tmp_path, raw, remap=None):
    (tmp_path / "raw_extractions.json").write_text(json.dumps(raw), encoding="utf-8")
    if remap is not None:
        (tmp_path / "type_remap.json").write_text(
            json.dumps({"mappings": remap}), encoding="utf-8"
        )
    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path
    ctx.confidence_agg = "mean"
    return ctx


def test_step_applies_remap_and_logs_event(tmp_path):
    ctx = _ctx(tmp_path, _raw_two_types(), {"Employee": "Person"})
    run_merge_assemble(ctx)
    nodes = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
    assert len(nodes) == 1
    assert nodes[0]["type"] == "Person"
    events = json.loads((tmp_path / "merge_log.json").read_text(encoding="utf-8"))
    assert [e for e in events if e["event"] == "type_remap"]


def test_step_without_remap_file_matches_plain_assemble(tmp_path):
    """No type_remap.json -> behaviour identical to the extract-path assembler."""
    ctx = _ctx(tmp_path, _raw_two_types())
    run_merge_assemble(ctx)
    nodes = json.loads((tmp_path / "nodes.json").read_text(encoding="utf-8"))
    assert len(nodes) == 2
    assert {n["type"] for n in nodes} == {"Employee", "Person"}


def test_step_preserves_prior_schema_merge_events(tmp_path):
    ctx = _ctx(tmp_path, _raw_two_types(), {"Employee": "Person"})
    (tmp_path / "merge_log.json").write_text(
        json.dumps(
            [
                {"event": "concept_collapsed_by_thesaurus", "concept": "Employee"},
                {"event": "totally_unknown", "x": 1},
            ]
        ),
        encoding="utf-8",
    )
    run_merge_assemble(ctx)
    events = json.loads((tmp_path / "merge_log.json").read_text(encoding="utf-8"))
    kinds = {e["event"] for e in events}
    assert "concept_collapsed_by_thesaurus" in kinds
    assert "type_remap" in kinds
    assert "totally_unknown" not in kinds


def test_load_type_remap_missing_file(tmp_path):
    assert load_type_remap(tmp_path) == {}


def test_load_type_remap_corrupt_file(tmp_path):
    (tmp_path / "type_remap.json").write_text("not json {", encoding="utf-8")
    assert load_type_remap(tmp_path) == {}
