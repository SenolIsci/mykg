"""CLI tests for ``mykg detect-schema-drift`` and ``mykg prune-schema``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from mykg.cli import cli
from mykg.exporter import write_edges_jsonl, write_nodes_jsonl

NAME = "s1"


def _c(name, parent=None):
    return {"type": name, "parent": parent, "attributes": ["name"]}


def _p(name, domain, range_):
    return {"name": name, "domain": domain, "range": range_, "attributes": []}


SCHEMA = {
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


def _node(t, name):
    return {
        "id": f"{t.lower()}-{name}",
        "type": t,
        "attributes": {"name": {"value": name, "confidence": 1.0}},
        "confidence": 1.0,
        "source_files": ["a.md"],
    }


NODES = [_node("Organization", "acme"), _node("Person", "alice"), _node("Team", "core")]
EDGES = {
    "edge-1": {"type": "works_at", "from": "person-alice", "to": "organization-acme",
               "confidence": 0.9, "method": "llm_extraction", "attributes": {},
               "source_files": ["a.md"]},
    "edge-2": {"type": "member_of", "from": "person-alice", "to": "team-core",
               "confidence": 0.9, "method": "llm_extraction", "attributes": {},
               "source_files": ["a.md"]},
    "edge-3": {"type": "part_of", "from": "team-core", "to": "organization-acme",
               "confidence": 0.9, "method": "llm_extraction", "attributes": {},
               "source_files": ["a.md"]},
}


@pytest.fixture(autouse=True)
def _no_provider_env(monkeypatch):
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    # Neither command may ever load an LLM adapter.
    def _boom(*a, **k):
        raise AssertionError("load_adapter must not be called")

    monkeypatch.setattr("mykg.llm.config.load_adapter", _boom)


@pytest.fixture
def sessions(tmp_path, monkeypatch):
    root = tmp_path / "sessions"
    monkeypatch.setattr("mykg.cli._sessions_root", lambda: root)
    return root


def build_session(sessions: Path, name=NAME, schema=SCHEMA, steps=None, lock=None) -> Path:
    s = sessions / name
    inter, out = s / "intermediate", s / "output"
    for d in (inter, out, s / "input"):
        d.mkdir(parents=True)
    (inter / "schema.json").write_text(json.dumps(schema, indent=2), encoding="utf-8")
    (inter / "nodes.json").write_text(json.dumps(NODES), encoding="utf-8")
    (inter / "edge_metadata.json").write_text(json.dumps(EDGES), encoding="utf-8")
    write_nodes_jsonl(out / "nodes.jsonl", NODES)
    write_edges_jsonl(out / "edges.jsonl", EDGES)
    (inter / "pipeline_state.json").write_text(
        json.dumps({"steps": steps or {"pass2": {"status": "done"}}}), encoding="utf-8"
    )
    if lock is not None:
        (inter / "base_schema_parsed.json").write_text(json.dumps(lock), encoding="utf-8")
    return s


def run(*args):
    return CliRunner().invoke(cli, list(args))


def snap(s: Path):
    return {p: p.read_bytes() for p in s.rglob("*") if p.is_file()}


def test_help_lists_commands():
    out = run("--help").output
    assert "detect-schema-drift" in out and "prune-schema" in out


def test_detect_reports_and_writes_only_drift_file(sessions):
    s = build_session(sessions)
    before = snap(s)
    r = run("detect-schema-drift", "--session", NAME)
    assert r.exit_code == 0, r.output
    assert "declared concepts: Organization, Person, Team, Project, Service" in r.output
    assert "unused concepts: Project (0 instances), Service (0 instances)" in r.output
    assert "declared properties: 11 (8 unreferenced by active edges)" in r.output
    assert "no locked schema recorded; treating all entries as unlocked" in r.output
    after = snap(s)
    new = set(after) - set(before)
    assert new == {s / "intermediate" / "schema_drift.json"}
    assert all(after[p] == before[p] for p in before)


def test_detect_with_lock_has_no_notice_and_marks_locked(sessions):
    build_session(sessions, lock={"locked_classes": ["Project"], "locked_properties": []})
    r = run("detect-schema-drift", "--session", NAME)
    assert "no locked schema recorded" not in r.output
    assert "concept  Project: locked" in r.output


def test_preview_writes_plan_only(sessions):
    s = build_session(sessions)
    before = snap(s)
    r = run("prune-schema", "--session", NAME, "--preview")
    assert r.exit_code == 0, r.output
    assert "5 concepts / 11 properties -> 3 / 3" in r.output
    assert "--append-with-grow-schema" in r.output
    after = snap(s)
    inter = s / "intermediate"
    assert set(after) - set(before) == {inter / "schema_drift.json", inter / "schema_prune_plan.json"}
    assert all(after[p] == before[p] for p in before)
    assert not (inter / "schema_history").exists()


def test_one_shot_prune(sessions):
    s = build_session(sessions)
    inter, out = s / "intermediate", s / "output"
    nodes_b, edges_b = (out / "nodes.jsonl").read_bytes(), (out / "edges.jsonl").read_bytes()
    # A real session has flattened_schema.json; apply_prune only refreshes an existing one.
    from mykg.schema_flattener import flatten_schema

    (inter / "flattened_schema.json").write_text(json.dumps(flatten_schema(SCHEMA)), encoding="utf-8")
    r = run("prune-schema", "--session", NAME)
    assert r.exit_code == 0, r.output
    schema = json.loads((inter / "schema.json").read_text(encoding="utf-8"))
    assert len(schema["concepts"]) == 3 and len(schema["properties"]) == 3
    assert json.loads((inter / "schema.pre_prune.json").read_text(encoding="utf-8")) == SCHEMA
    hist = list((inter / "schema_history").glob("*_schema_prune.json"))
    assert len(hist) == 1
    ttl = (inter / "schema.ttl").read_text(encoding="utf-8")
    assert "Project" not in ttl and "Person" in ttl
    flat = (inter / "flattened_schema.json").read_text(encoding="utf-8")
    assert "Project" not in flat and "Person" in flat
    kg = (out / "knowledge_graph.ttl").read_text(encoding="utf-8")
    assert "Project" not in kg
    assert (out / "nodes.jsonl").read_bytes() == nodes_b
    assert (out / "edges.jsonl").read_bytes() == edges_b
    assert "Backup:" in r.output and "Undo:" in r.output
    assert "5 concepts / 11 properties -> 3 / 3" in r.output
    drift = json.loads((inter / "schema_drift.json").read_text(encoding="utf-8"))
    assert len(drift["concepts"]) == 3 and len(drift["properties"]) == 3


def test_prune_walkthrough_schema_health_is_not_stale(sessions, monkeypatch):
    """The walkthrough regenerated by the prune refresh must see the re-recorded drift
    record (regression: it was regenerated before the record, so it said "Stale")."""
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "REPORT_ENABLED", True)
    s = build_session(sessions)
    r = run("prune-schema", "--session", NAME)
    assert r.exit_code == 0, r.output
    assert "walkthrough.md" in r.output
    text = (s / "walkthrough.md").read_text(encoding="utf-8")
    assert "Schema Health" in text
    assert "Stale" not in text
    assert "3 declared, 3 used, 0 unused" in text


def test_plan_after_removing_an_entry(sessions):
    s = build_session(sessions)
    inter = s / "intermediate"
    run("prune-schema", "--session", NAME, "--preview")
    plan_path = inter / "schema_prune_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["remove"] = [e for e in plan["remove"] if e["name"] != "partners_with"]
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    r = run("prune-schema", "--session", NAME, "--plan", str(plan_path))
    assert r.exit_code == 0, r.output
    schema = json.loads((inter / "schema.json").read_text(encoding="utf-8"))
    assert len(schema["concepts"]) == 3
    assert {p["name"] for p in schema["properties"]} == {
        "works_at", "member_of", "part_of", "partners_with"
    }


def test_plan_with_non_prunable_entry_rejected(sessions):
    s = build_session(sessions)
    inter = s / "intermediate"
    run("prune-schema", "--session", NAME, "--preview")
    plan_path = inter / "schema_prune_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    plan["remove"].append({"kind": "concept", "name": "Person", "reason": "x"})
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    before = (inter / "schema.json").read_bytes()
    r = run("prune-schema", "--session", NAME, "--plan", str(plan_path))
    assert r.exit_code != 0
    assert "Person" in r.output and "Nothing was changed" in r.output
    assert (inter / "schema.json").read_bytes() == before
    assert not (inter / "schema.pre_prune.json").exists()


def test_stale_plan_refused(sessions):
    s = build_session(sessions)
    inter, out = s / "intermediate", s / "output"
    run("prune-schema", "--session", NAME, "--preview")
    extra = _node("Person", "bob")
    with (out / "nodes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(extra) + "\n")
    before = (inter / "schema.json").read_bytes()
    r = run("prune-schema", "--session", NAME, "--plan", str(inter / "schema_prune_plan.json"))
    assert r.exit_code != 0 and "stale" in r.output
    assert (inter / "schema.json").read_bytes() == before


def test_preview_and_plan_mutually_exclusive(sessions):
    build_session(sessions)
    r = run("prune-schema", "--session", NAME, "--preview", "--plan", "x.json")
    assert r.exit_code != 0 and "mutually exclusive" in r.output


def test_errors_missing_schema_unknown_session(sessions):
    s = build_session(sessions)
    (s / "intermediate" / "schema.json").unlink()
    for cmd in ("detect-schema-drift", "prune-schema"):
        r = run(cmd, "--session", NAME)
        assert r.exit_code != 0 and "schema.json not found" in r.output
        r = run(cmd, "--session", "nope")
        assert r.exit_code != 0 and "nope" in r.output


def test_refuses_when_step_running(sessions):
    s = build_session(sessions, steps={"pass2": {"status": "running"}})
    before = snap(s)
    for args in (["detect-schema-drift"], ["prune-schema"], ["prune-schema", "--preview"]):
        r = run(*args, "--session", NAME)
        assert r.exit_code != 0 and "running" in r.output
    assert snap(s) == before


def test_missing_nodes_jsonl_is_error(sessions):
    s = build_session(sessions)
    (s / "output" / "edges.jsonl").unlink()
    r = run("detect-schema-drift", "--session", NAME)
    assert r.exit_code != 0 and "edges.jsonl" in r.output


def test_latest_session_default(sessions):
    build_session(sessions, name="2020-01-01")
    build_session(sessions, name="2021-01-01")
    r = run("detect-schema-drift")
    assert r.exit_code == 0, r.output
    assert (sessions / "2021-01-01" / "intermediate" / "schema_drift.json").exists()
    assert not (sessions / "2020-01-01" / "intermediate" / "schema_drift.json").exists()
