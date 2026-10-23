"""Review-fix tests for the schema-drift CLI (PR #84 follow-ups)."""

from __future__ import annotations

import json

from .test_cli_schema_drift import (  # noqa: F401  (fixtures + helpers)
    NAME,
    _no_provider_env,
    build_session,
    run,
    sessions,
    snap,
)


def test_prune_regenerates_knowledge_graph_ttl(sessions):
    s = build_session(sessions)
    out = s / "output"
    r = run("prune-schema", "--session", NAME)
    assert r.exit_code == 0, r.output
    kg = (out / "knowledge_graph.ttl").read_text(encoding="utf-8")
    for gone in ("Project", "Service", "leads_project", "uses_service"):
        assert gone not in kg
    assert "Person" in kg and "works_at" in kg
    assert "Regenerated outputs" in r.output and "knowledge_graph.ttl" in r.output
    assert "Refreshed" not in r.output


def test_empty_plan_is_nothing_to_prune_and_changes_nothing(sessions):
    s = build_session(sessions)
    assert run("prune-schema", "--session", NAME).exit_code == 0
    before = snap(s)
    inter = s / "intermediate"
    r = run("prune-schema", "--session", NAME)
    assert r.exit_code == 0, r.output
    assert "Nothing to prune" in r.output
    assert "Regenerated" not in r.output
    after = snap(s)
    assert set(after) == set(before)
    changed = {p for p in after if before[p] != after[p]}
    assert changed <= {inter / "schema_drift.json"}


def test_malformed_jsonl_is_clean_error(sessions):
    s = build_session(sessions)
    with (s / "output" / "nodes.jsonl").open("a", encoding="utf-8") as f:
        f.write("{not json\n")
    for args in (["detect-schema-drift"], ["prune-schema"], ["prune-schema", "--preview"]):
        r = run(*args, "--session", NAME)
        assert r.exit_code != 0
        assert isinstance(r.exception, SystemExit)
    assert not (s / "intermediate" / "schema.pre_prune.json").exists()


def test_invalid_utf8_lock_file_is_clean_error(sessions):
    s = build_session(sessions)
    (s / "intermediate" / "base_schema_parsed.json").write_bytes(b"\xff\xfe\x00bad")
    r = run("detect-schema-drift", "--session", NAME)
    assert r.exit_code != 0
    assert "base_schema_parsed.json" in r.output
    assert isinstance(r.exception, SystemExit)


def test_malformed_lock_content_is_clean_error(sessions):
    build_session(sessions, lock={"locked_classes": 5})
    r = run("detect-schema-drift", "--session", NAME)
    assert r.exit_code != 0 and isinstance(r.exception, SystemExit)


def test_session_name_quoted_in_printed_commands(sessions):
    name = "my session;x"
    s = build_session(sessions, name=name)
    r = run("detect-schema-drift", "--session", name)
    assert r.exit_code == 0, r.output
    assert "--session 'my session;x' --preview" in r.output
    r = run("prune-schema", "--session", name, "--preview")
    assert "--session 'my session;x' --plan" in r.output
    r = run("prune-schema", "--session", name)
    assert r.exit_code == 0, r.output
    assert r.output.count("--session 'my session;x'") >= 2
    assert "--session my session" not in r.output
    assert "--from-step validate_graph" in r.output
    assert "NOT regenerated automatically" in r.output
    assert "--from-step schema_flatten" not in r.output
    assert (s / "intermediate" / "schema.pre_prune.json").exists()


def test_no_lock_file_classifies_unused_as_prunable(sessions):
    s = build_session(sessions)
    assert not (s / "intermediate" / "base_schema_parsed.json").exists()
    run("detect-schema-drift", "--session", NAME)
    drift = json.loads((s / "intermediate" / "schema_drift.json").read_text(encoding="utf-8"))
    by = {c["name"]: c["classification"] for c in drift["concepts"]}
    assert by["Project"] == "prunable" and by["Service"] == "prunable"


def test_preview_and_apply_use_same_locks(sessions):
    lock = {"locked_classes": ["Service"], "locked_properties": []}
    s = build_session(sessions, lock=lock)
    inter = s / "intermediate"
    run("prune-schema", "--session", NAME, "--preview")
    plan_path = inter / "schema_prune_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert "Service" not in {e["name"] for e in plan["remove"] if e["kind"] == "concept"}
    r = run("prune-schema", "--session", NAME, "--plan", str(plan_path))
    assert r.exit_code == 0, r.output
    schema = json.loads((inter / "schema.json").read_text(encoding="utf-8"))
    assert "Service" in {c["type"] for c in schema["concepts"]}


def test_absent_flattened_schema_is_not_created(sessions):
    s = build_session(sessions)
    assert run("prune-schema", "--session", NAME).exit_code == 0
    assert not (s / "intermediate" / "flattened_schema.json").exists()


def test_refresh_failure_still_records_drift_and_prints_undo(sessions, monkeypatch):
    s = build_session(sessions)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("mykg.steps.step_validate_graph.run_validate_graph", _boom)
    r = run("prune-schema", "--session", NAME)
    assert r.exit_code != 0 and "refreshing outputs failed" in r.output
    assert "Undo:" in r.output
    drift = json.loads((s / "intermediate" / "schema_drift.json").read_text(encoding="utf-8"))
    assert len(drift["concepts"]) == 3


def test_lock_change_after_preview_invalidates_plan(sessions):
    s = build_session(sessions, lock={"locked_classes": ["Service"], "locked_properties": []})
    inter = s / "intermediate"
    run("prune-schema", "--session", NAME, "--preview")
    (inter / "base_schema_parsed.json").write_text(
        json.dumps({"locked_classes": ["Project"], "locked_properties": []}), encoding="utf-8"
    )
    before = (inter / "schema.json").read_bytes()
    r = run("prune-schema", "--session", NAME, "--plan", str(inter / "schema_prune_plan.json"))
    assert r.exit_code != 0 and "stale" in r.output
    assert (inter / "schema.json").read_bytes() == before
