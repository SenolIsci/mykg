"""Tests for src/mykg/schema_drift.py — drift detection, prune planning and apply."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg import schema_drift as sd
from mykg.schema_drift import (
    LockedSchema,
    SchemaDriftError,
    analyze_drift,
    apply_prune,
    load_plan,
    plan_prune,
    record_drift,
    stream_jsonl,
    validate_plan,
    write_plan,
)


def _c(name, parent=None, attrs=("name",)):
    return {"type": name, "parent": parent, "attributes": list(attrs)}


def _p(name, domain, range_):
    return {"name": name, "domain": domain, "range": range_, "attributes": []}


def article_schema() -> dict:
    return {
        "concepts": [_c(n) for n in ("Organization", "Person", "Team", "Project", "Service")],
        "properties": [
            _p("works_at", "Person", "Organization"),
            _p("member_of", "Person", "Team"),
            _p("part_of", "Team", "Organization"),
            _p("owns_project", "Organization", "Project"),
            _p("leads_project", "Person", "Project"),
            _p("contributes_to", "Person", "Project"),
            _p("depends_on", "Project", "Project"),
            _p("partners_with", "Organization", "Organization"),
            _p("delivers_service", "Project", "Service"),
            _p("runs_service", "Team", "Service"),
            _p("uses_service", "Person", "Service"),
        ],
    }


def nodes(*types: str) -> list[dict]:
    return [
        {
            "id": f"{t.lower()}-{i}",
            "type": t,
            "attributes": {"name": {"value": "x", "confidence": 1.0}},
        }
        for i, t in enumerate(types)
    ]


def edges(*types: str) -> list[dict]:
    return [{"id": f"e{i}", "type": t, "from": "a", "to": "b"} for i, t in enumerate(types)]


ARTICLE_NODES = nodes("Organization", "Person", "Person", "Team")
ARTICLE_EDGES = edges("works_at", "member_of", "part_of")


def write_session(tmp_path: Path, schema: dict, node_rows, edge_rows) -> tuple[Path, Path]:
    inter = tmp_path / "intermediate"
    out = tmp_path / "output"
    inter.mkdir()
    out.mkdir()
    (inter / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    (out / "nodes.jsonl").write_text(
        "".join(json.dumps(n) + "\n" for n in node_rows), encoding="utf-8"
    )
    (out / "edges.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in edge_rows), encoding="utf-8"
    )
    return inter, out


def cls_of(report, name):
    return {r.name: r for r in [*report.concepts, *report.properties]}[name]


def test_article_example_counts_and_prune(tmp_path):
    schema = article_schema()
    report = analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None)
    assert {c.name for c in report.concepts if c.classification == "prunable"} == {
        "Project",
        "Service",
    }
    assert len([p for p in report.properties if p.classification == "prunable"]) == 8
    plan = plan_prune(report)
    assert plan.totals.before.concepts == 5 and plan.totals.before.properties == 11
    assert plan.totals.after.concepts == 3 and plan.totals.after.properties == 3
    cascaded = cls_of(report, "owns_project")
    assert "removed" in cascaded.reason
    assert cls_of(report, "partners_with").reason == "0 edges"

    inter, _ = write_session(tmp_path, schema, ARTICLE_NODES, ARTICLE_EDGES)
    pruned = apply_prune(plan, inter)
    assert len(pruned["concepts"]) == 3 and len(pruned["properties"]) == 3


def test_counts_include_subtree():
    schema = {
        "concepts": [_c("Person"), _c("Engineer", "Person"), _c("Senior", "Engineer")],
        "properties": [],
    }
    r = analyze_drift(schema, nodes("Senior", "Senior", "Engineer"), [], None)
    assert cls_of(r, "Senior").instance_count == 2
    assert cls_of(r, "Engineer").instance_count == 1
    assert cls_of(r, "Engineer").subtree_count == 3
    p = cls_of(r, "Person")
    assert (p.instance_count, p.subtree_count) == (0, 3)
    assert p.classification == "structural"


def test_structural_range_of_used_property():
    schema = {
        "concepts": [_c("Person"), _c("Project")],
        "properties": [_p("leads", "Person", "Project")],
    }
    r = analyze_drift(schema, nodes("Person"), edges("leads"), None)
    c = cls_of(r, "Project")
    assert c.classification == "structural"
    assert "surviving property" in c.reason


def test_locked_never_pruned_and_keeps_parent():
    schema = {
        "concepts": [_c("Root"), _c("LockedChild", "Root"), _c("Free")],
        "properties": [_p("locked_prop", "Free", "Free"), _p("free_prop", "Free", "Free")],
    }
    locked = LockedSchema.from_parsed(
        {
            "locked_classes": [{"type": "LockedChild"}],
            "locked_properties": [{"name": "locked_prop"}],
        }
    )
    r = analyze_drift(schema, [], [], locked)
    assert cls_of(r, "LockedChild").classification == "locked"
    assert cls_of(r, "Root").classification == "structural"
    assert cls_of(r, "locked_prop").classification == "locked"
    # Free is the endpoint of a locked (surviving) property.
    assert cls_of(r, "Free").classification == "structural"
    assert cls_of(r, "free_prop").classification == "prunable"
    plan = plan_prune(r)
    assert [e.name for e in plan.remove] == ["free_prop"]


def test_locked_accepts_none_and_strings():
    assert LockedSchema.from_parsed(None).classes == set()
    assert LockedSchema.from_parsed({"locked_classes": ["A"]}).classes == {"A"}


def test_parent_cycle_guard():
    schema = {"concepts": [_c("A", "B"), _c("B", "A")], "properties": []}
    r = analyze_drift(schema, nodes("A"), [], None)
    assert cls_of(r, "A").instance_count == 1
    assert cls_of(r, "B").subtree_count == 1


def test_reverse_drift_and_always_null():
    schema = {"concepts": [_c("Person", attrs=("name", "email"))], "properties": []}
    rows = nodes("Person") + nodes("Ghost")
    r = analyze_drift(schema, rows, edges("mystery"), None)
    assert r.undeclared_node_types == {"Ghost": 1}
    assert r.undeclared_edge_types == {"mystery": 1}
    assert cls_of(r, "Person").always_null_attributes == ["email"]


def test_fingerprint_stable_and_changes():
    schema = article_schema()
    a = analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None).schema_fingerprint
    b = analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None).schema_fingerprint
    assert a == b
    c = analyze_drift(
        schema, ARTICLE_NODES + nodes("Project"), ARTICLE_EDGES, None
    ).schema_fingerprint
    assert a != c
    schema2 = article_schema()
    schema2["concepts"].append(_c("Extra"))
    assert a != analyze_drift(schema2, ARTICLE_NODES, ARTICLE_EDGES, None).schema_fingerprint


def test_record_drift_and_plan_roundtrip(tmp_path):
    report = analyze_drift(article_schema(), ARTICLE_NODES, ARTICLE_EDGES, None)
    inter = tmp_path
    p = record_drift(report, inter)
    assert (
        json.loads(p.read_text(encoding="utf-8"))["schema_fingerprint"] == report.schema_fingerprint
    )
    plan = plan_prune(report)
    path = write_plan(plan, inter)
    assert path.name == "schema_prune_plan.json"
    assert load_plan(path) == plan


def test_load_plan_malformed(tmp_path):
    bad = tmp_path / "plan.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaDriftError, match="not valid JSON"):
        load_plan(bad)
    bad.write_text(json.dumps({"remove": "nope"}), encoding="utf-8")
    with pytest.raises(SchemaDriftError, match="malformed"):
        load_plan(bad)
    with pytest.raises(SchemaDriftError, match="Cannot read"):
        load_plan(tmp_path / "missing.json")


def test_stale_plan_rejected():
    report = analyze_drift(article_schema(), ARTICLE_NODES, ARTICLE_EDGES, None)
    plan = plan_prune(report)
    newer = analyze_drift(article_schema(), ARTICLE_NODES + nodes("Team"), ARTICLE_EDGES, None)
    with pytest.raises(SchemaDriftError, match="stale"):
        validate_plan(plan, newer)
    validate_plan(plan, report)


def test_plan_with_non_prunable_entry_rejected(tmp_path):
    schema = article_schema()
    report = analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None)
    plan = plan_prune(report)
    plan.remove.append(sd.PlanEntry(kind="concept", name="Person", reason="forced"))
    with pytest.raises(SchemaDriftError, match="cannot be pruned"):
        validate_plan(plan, report)
    plan.remove[-1] = sd.PlanEntry(kind="concept", name="Nope")
    with pytest.raises(SchemaDriftError, match="not in the schema"):
        validate_plan(plan, report)


def test_dangling_concept_removed_property_kept(tmp_path):
    schema = article_schema()
    report = analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None)
    plan = plan_prune(report)
    # Veto the cascaded properties that touch Project; keep Project removed.
    plan.remove = [e for e in plan.remove if e.name != "owns_project"]
    with pytest.raises(SchemaDriftError, match="owns_project"):
        validate_plan(plan, report)
    inter, _ = write_session(tmp_path, schema, ARTICLE_NODES, ARTICLE_EDGES)
    before = (inter / "schema.json").read_bytes()
    with pytest.raises(SchemaDriftError, match="owns_project"):
        apply_prune(plan, inter)
    assert (inter / "schema.json").read_bytes() == before
    assert not (inter / "schema.pre_prune.json").exists()


def test_removing_zero_edge_property_alone_is_allowed():
    report = analyze_drift(article_schema(), ARTICLE_NODES, ARTICLE_EDGES, None)
    plan = plan_prune(report)
    plan.remove = [e for e in plan.remove if e.name == "partners_with"]
    validate_plan(plan, report)


def test_kept_child_blocks_parent_removal():
    schema = {"concepts": [_c("Root"), _c("Child", "Root")], "properties": []}
    report = analyze_drift(schema, [], [], None)
    plan = plan_prune(report)
    plan.remove = [e for e in plan.remove if e.name == "Root"]
    with pytest.raises(SchemaDriftError, match="has it as parent"):
        validate_plan(plan, report)


def test_pruned_schema_validation_failure_aborts(tmp_path, monkeypatch):
    schema = article_schema()
    inter, _ = write_session(tmp_path, schema, ARTICLE_NODES, ARTICLE_EDGES)
    plan = plan_prune(analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None))
    from mykg import schema_validator
    from mykg.schema_validator import SchemaValidationResult

    monkeypatch.setattr(
        schema_validator,
        "validate_schema_ttl",
        lambda ttl: SchemaValidationResult(valid=False, errors=[{"type": "x"}]),
    )
    before = (inter / "schema.json").read_bytes()
    with pytest.raises(SchemaDriftError, match="failed validation"):
        apply_prune(plan, inter)
    assert (inter / "schema.json").read_bytes() == before
    assert not (inter / "schema.pre_prune.json").exists()
    assert not (inter / "schema_history").exists()


def test_apply_side_effects_and_jsonl_untouched(tmp_path):
    schema = article_schema()
    inter, out = write_session(tmp_path, schema, ARTICLE_NODES, ARTICLE_EDGES)
    nodes_bytes = (out / "nodes.jsonl").read_bytes()
    edges_bytes = (out / "edges.jsonl").read_bytes()
    original = (inter / "schema.json").read_bytes()

    report = analyze_drift(
        json.loads((inter / "schema.json").read_text(encoding="utf-8")),
        stream_jsonl(out / "nodes.jsonl"),
        stream_jsonl(out / "edges.jsonl"),
        None,
    )
    plan = plan_prune(report)
    validate_plan(plan, report)
    apply_prune(plan, inter)

    assert (inter / "schema.pre_prune.json").read_bytes() == original
    pruned = json.loads((inter / "schema.json").read_text(encoding="utf-8"))
    assert [c["type"] for c in pruned["concepts"]] == ["Organization", "Person", "Team"]
    assert len(pruned["properties"]) == 3

    deltas = sorted((inter / "schema_history").glob("*_schema_prune.json"))
    assert len(deltas) == 1
    delta = json.loads(deltas[0].read_text(encoding="utf-8"))
    assert delta["trigger"] == "schema_prune"
    assert delta["timestamp"]
    assert delta["concepts_removed"] == ["Project", "Service"]
    assert len(delta["properties_removed"]) == 8
    assert {e["name"] for e in delta["pruned"]} >= {"Project", "Service", "owns_project"}

    ttl = (inter / "schema.ttl").read_text(encoding="utf-8")
    assert "Team" in ttl and "Project" not in ttl and "owns_project" not in ttl

    assert (out / "nodes.jsonl").read_bytes() == nodes_bytes
    assert (out / "edges.jsonl").read_bytes() == edges_bytes

    # Idempotent: nothing left to prune.
    again = analyze_drift(pruned, ARTICLE_NODES, ARTICLE_EDGES, None)
    assert plan_prune(again).remove == []


def test_stream_jsonl_missing_and_blank_lines(tmp_path):
    with pytest.raises(SchemaDriftError, match="not found"):
        list(stream_jsonl(tmp_path / "nope.jsonl"))
    f = tmp_path / "a.jsonl"
    f.write_text('{"a": 1}\n\n{"a": 2}\n', encoding="utf-8")
    assert [r["a"] for r in stream_jsonl(f)] == [1, 2]
    f.write_text('{"a": 1}\n{oops\n', encoding="utf-8")
    with pytest.raises(SchemaDriftError, match=":2 is not valid JSON"):
        list(stream_jsonl(f))


def test_locked_from_parser_shape_dicts():
    parsed = {"locked_classes": {"A": {"type": "A"}}, "locked_properties": {"p": {"name": "p"}}}
    locked = LockedSchema.from_parsed(parsed)
    assert locked.classes == {"A"} and locked.properties == {"p"}


def test_always_null_is_subtree_aware():
    schema = {
        "concepts": [_c("Person", attrs=("name", "email")), _c("Eng", "Person", attrs=("name",))],
        "properties": [],
    }
    rows = [
        {"type": "Person", "attributes": {"name": {"value": "p"}}},
        {"type": "Eng", "attributes": {"email": {"value": "a@b"}}},
    ]
    assert cls_of(analyze_drift(schema, rows, [], None), "Person").always_null_attributes == []


def test_apply_with_report_rejects_gained_instances(tmp_path):
    schema = article_schema()
    inter, _ = write_session(tmp_path, schema, ARTICLE_NODES, ARTICLE_EDGES)
    plan = plan_prune(analyze_drift(schema, ARTICLE_NODES, ARTICLE_EDGES, None))
    fresh = analyze_drift(schema, ARTICLE_NODES + nodes("Project"), ARTICLE_EDGES, None)
    before = (inter / "schema.json").read_bytes()
    with pytest.raises(SchemaDriftError, match="stale"):
        apply_prune(plan, inter, fresh)
    assert (inter / "schema.json").read_bytes() == before
