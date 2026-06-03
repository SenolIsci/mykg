"""Unit tests for untested sections in mykg.walkthrough."""

from __future__ import annotations

import json
from pathlib import Path

from mykg.walkthrough import (
    _load_json,
    _parse_log_lines,
    _section_extraction_summary,
    _section_final_graph,
    _section_health_status,
    _section_llm_stats,
    _section_merge_provenance,
    _section_node_edge_trace,
    _section_orphan_pass,
    _section_run_overview,
    _section_schema_evolution,
    _section_warnings,
    _seconds_to_hms,
    _ts_to_seconds,
    generate_walkthrough,
)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2))
    else:
        path.write_text(data)


# ---------------------------------------------------------------------------
# 1. _section_schema_evolution — with history
# ---------------------------------------------------------------------------


def test_section_schema_evolution_with_history(tmp_path):
    session = tmp_path / "session"
    delta = {
        "seq": 1,
        "trigger": "pass1_merge",
        "concepts_added": ["Person", "Organization"],
        "concepts_removed": [],
        "properties_added": ["works_at"],
        "properties_removed": [],
        "timestamp": "2026-05-20T10:00:00+00:00",
    }
    _write(session / "intermediate" / "schema_history" / "001_pass1_merge.json", delta)
    _write(
        session / "intermediate" / "schema.json",
        {
            "concepts": [
                {"type": "Person", "parent": None, "attributes": ["name", "email"]},
                {"type": "Organization", "parent": None, "attributes": ["name"]},
            ],
            "properties": [
                {
                    "name": "works_at",
                    "domain": "Person",
                    "range": "Organization",
                    "attributes": ["role"],
                },
            ],
        },
    )

    result = _section_schema_evolution(session)

    assert "## 4. Schema Evolution" in result
    assert "pass1_merge" in result
    assert "Person" in result


# ---------------------------------------------------------------------------
# 2. _section_schema_evolution — no history dir
# ---------------------------------------------------------------------------


def test_section_schema_evolution_no_history(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)

    result = _section_schema_evolution(session)

    assert result
    assert "## 4. Schema Evolution" in result


# ---------------------------------------------------------------------------
# 3. _section_llm_stats — groups present
# ---------------------------------------------------------------------------


def test_section_llm_stats_groups(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    records = [
        {
            "context": "pass1 batch induction",
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_read_tokens": 10,
            "cache_creation_tokens": 5,
            "duration_s": 3.0,
        },
        {
            "context": "pass2 file extraction",
            "input_tokens": 200,
            "output_tokens": 80,
            "cache_read_tokens": 20,
            "cache_creation_tokens": 0,
            "duration_s": 8.0,
        },
        {
            "context": "orphan chunk recovery",
            "input_tokens": 150,
            "output_tokens": 60,
            "cache_read_tokens": 0,
            "cache_creation_tokens": 0,
            "duration_s": 5.0,
        },
    ]
    (session / "llm.log").write_text("\n".join(json.dumps(r) for r in records))

    result = _section_llm_stats(session)

    assert "Pass 1" in result
    assert "Pass 2" in result or "Instance extraction" in result
    assert "Orphan" in result


# ---------------------------------------------------------------------------
# 4. _section_llm_stats — missing file
# ---------------------------------------------------------------------------


def test_section_llm_stats_missing_file(tmp_path):
    session = tmp_path / "session"
    session.mkdir()

    result = _section_llm_stats(session)

    assert result
    assert "## 5. LLM Call Statistics" in result


# ---------------------------------------------------------------------------
# 5. _section_orphan_pass — with data
# ---------------------------------------------------------------------------


def test_section_orphan_pass_with_data(tmp_path):
    session = tmp_path / "session"
    _write(
        session / "intermediate" / "orphan_candidates.json",
        {
            "groups": [
                {"orphan_ids": ["person-charlie", "person-dana"], "connected_ids": ["org-acme"]},
            ],
            "schema_gap_orphans": [],
        },
    )
    _write(
        session / "intermediate" / "orphan_log.json",
        [
            {
                "event": "orphan_edge_added",
                "id": "edge-100",
                "type": "works_at",
                "from": "person-charlie",
                "to": "org-acme",
            },
            {
                "event": "orphan_edge_rejected",
                "orphan_id": "person-dana",
                "candidate_id": "org-acme",
                "reason": "low confidence",
            },
        ],
    )
    nodes = [
        {"id": "person-charlie", "type": "Person"},
        {"id": "person-dana", "type": "Person"},
        {"id": "org-acme", "type": "Organization"},
    ]
    edges = {
        "edge-100": {
            "type": "works_at",
            "from": "person-charlie",
            "to": "org-acme",
            "method": "orphan_inferred",
        },
    }

    result = _section_orphan_pass(session, [], nodes, edges)

    assert "## 7. Orphan Pass Summary" in result
    assert "Total orphans across groups: **2**" in result


# ---------------------------------------------------------------------------
# 6. _section_final_graph — with validation errors
# ---------------------------------------------------------------------------


def test_section_final_graph_with_validation_errors(tmp_path):
    session = tmp_path / "session"
    nodes = [
        {"id": "person-alice", "type": "Person"},
        {"id": "org-acme", "type": "Organization"},
    ]
    edges = {
        "edge-001": {
            "type": "works_at",
            "from": "person-alice",
            "to": "org-acme",
            "method": "llm_extraction",
        },
    }
    _write(
        session / "output" / "knowledge_graph_validation.json",
        {
            "valid": False,
            "tbox_checks": {"errors": ["some error"]},
            "abox_checks": {"errors": []},
        },
    )

    result = _section_final_graph(session, nodes, edges)

    assert "## 1. Final Graph Summary" in result
    assert "**invalid**" in result
    assert "1 TBox" in result


# ---------------------------------------------------------------------------
# 7. generate_walkthrough — minimal session
# ---------------------------------------------------------------------------


def test_generate_walkthrough_minimal(tmp_path):
    session = tmp_path / "2026-05-20T10-00-00"
    (session / "intermediate").mkdir(parents=True)
    (session / "output").mkdir(parents=True)

    _write(
        session / "run.log",
        "10:00:00 [INFO] mykg.orchestrator — RUN  ingest\n"
        "10:00:02 [INFO] mykg.orchestrator — DONE ingest\n",
    )
    _write(
        session / "intermediate" / "pipeline_state.json",
        {"started_at": "2026-05-20T10:00:00+00:00", "steps": {}},
    )
    _write(session / "intermediate" / "file_manifest.json", {"doc.md": "some content"})
    _write(
        session / "intermediate" / "schema.json",
        {"concepts": [], "properties": []},
    )
    _write(session / "intermediate" / "nodes.json", [])
    _write(session / "intermediate" / "edge_metadata.json", {})
    _write(
        session / "output" / "knowledge_graph_validation.json",
        {"valid": True, "tbox_checks": {"errors": []}, "abox_checks": {"errors": []}},
    )

    result = generate_walkthrough(session)

    assert isinstance(result, str)
    assert result
    assert "##" in result


# ---------------------------------------------------------------------------
# Helper coverage
# ---------------------------------------------------------------------------


def test_seconds_to_hms_negative():
    """Negative durations are clamped to 0."""
    assert _seconds_to_hms(-5) == "0s"


def test_seconds_to_hms_with_hours():
    assert _seconds_to_hms(3661) == "1h 01m 01s"


def test_seconds_to_hms_with_minutes_only():
    assert _seconds_to_hms(125) == "2m 05s"


def test_seconds_to_hms_seconds_only():
    assert _seconds_to_hms(7) == "7s"


def test_load_json_malformed_returns_none(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("not valid json {{{")
    assert _load_json(p) is None


def test_load_json_absent_returns_none(tmp_path):
    p = tmp_path / "missing.json"
    assert _load_json(p) is None


# ---------------------------------------------------------------------------
# _section_run_overview — missing fields branches (lines 110, 116, 121, 123)
# ---------------------------------------------------------------------------


def test_run_overview_no_log_lines(tmp_path):
    """Empty lines list -> 'unknown' duration."""
    session = tmp_path / "session"
    session.mkdir()
    result = _section_run_overview(session, [], {}, {})
    assert "unknown" in result


def test_run_overview_unknown_provider(tmp_path):
    """No LLM endpoint line in log -> provider stays 'unknown'."""
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "09:00:00", "level": "INFO", "logger": "mykg.orchestrator", "message": "x"},
        {"ts": "09:30:00", "level": "INFO", "logger": "mykg.orchestrator", "message": "done"},
    ]
    result = _section_run_overview(session, lines, {}, {})
    assert "| LLM provider | unknown |" in result


def test_run_overview_duration_wraps_midnight(tmp_path):
    """End < start -> +86400 wrap branch."""
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "23:59:00", "level": "INFO", "logger": "mykg.orchestrator", "message": "x"},
        {"ts": "00:01:00", "level": "INFO", "logger": "mykg.orchestrator", "message": "y"},
    ]
    result = _section_run_overview(session, lines, {}, {})
    # Should be reasonable duration not negative
    assert "| Total duration |" in result


def test_run_overview_warning_count_only(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "09:00:00", "level": "INFO", "logger": "x", "message": "x"},
        {"ts": "09:30:00", "level": "WARNING", "logger": "x", "message": "warn"},
    ]
    result = _section_run_overview(session, lines, {}, {})
    assert "healthy with warnings" in result


def test_run_overview_health_with_errors(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "09:00:00", "level": "ERROR", "logger": "x", "message": "boom"},
    ]
    result = _section_run_overview(session, lines, {}, {})
    assert "unhealthy" in result


def test_run_overview_schema_gap_count(tmp_path):
    """schema_history dir with schema_gap files counts gap restarts."""
    session = tmp_path / "session"
    schema_hist = session / "intermediate" / "schema_history"
    schema_hist.mkdir(parents=True)
    (schema_hist / "001_pass1_merge.json").write_text("{}")
    (schema_hist / "002_schema_gap.json").write_text("{}")
    (schema_hist / "003_schema_gap_correct.json").write_text("{}")

    result = _section_run_overview(session, [], {}, {})
    assert "Schema-gap restarts | 2 |" in result


# ---------------------------------------------------------------------------
# _section_extraction_summary — branches at 171–175, 386–387, 391–392, 395–406, 434–443
# ---------------------------------------------------------------------------


def test_extraction_summary_with_retries_and_partial_recovery(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    (session / "intermediate").mkdir()

    lines = [
        {
            "ts": "09:00:00",
            "level": "INFO",
            "logger": "mykg.pass2",
            "message": "doc.md — total: 10 node(s), 5 edge(s)",
        },
        {
            "ts": "09:00:01",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "doc.md — chunk 1 — validation errors found",
        },
        {
            "ts": "09:00:02",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "doc.md — chunk 2 — JSON parse error: foo — retrying",
        },
        {
            "ts": "09:00:03",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "doc.md — chunk 2 — retry JSON parse error",
        },
        {
            "ts": "09:00:04",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "skipping chunk 7",
        },
        {
            "ts": "09:00:05",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "partial recovery — dropped 3 invalid edge(s) and dropped 2 unanchored node(s)",
        },
        {
            "ts": "09:00:06",
            "level": "INFO",
            "logger": "mykg.pass2",
            "message": "doc.md chunk 1/3 dispatched",
        },
        {
            "ts": "09:00:07",
            "level": "WARNING",
            "logger": "mykg.assembler",
            "message": "dropping edge — unknown id",
        },
    ]

    result = _section_extraction_summary(session, lines, {"doc.md": "x"})
    # Retry stats present
    assert "JSON parse error → retry" in result
    assert "Partial recoveries" in result
    assert "Per-file extraction" in result
    assert "doc.md" in result
    # Dangling edges line present
    assert "Dangling edges dropped:" in result


def test_extraction_summary_includes_dedup_and_normalization(tmp_path):
    session = tmp_path / "session"
    inter = session / "intermediate"
    inter.mkdir(parents=True)

    (inter / "name_normalization.json").write_text(
        json.dumps(
            {
                "mappings": {"Person": {"al": "Alice"}},
                "metadata": {"aliases_mapped": 1},
            }
        )
    )
    (inter / "merge_log.json").write_text(
        json.dumps(
            [
                {"event": "node_merge", "id": "person-alice"},
                {"event": "node_merge", "id": "person-bob"},
                {"event": "edge_merge", "id": "edge-1"},
            ]
        )
    )

    lines = []
    result = _section_extraction_summary(session, lines, {})
    assert "Name normalization" in result
    assert "Deduplication" in result
    assert "1 edge merge" in result


# ---------------------------------------------------------------------------
# _section_orphan_pass — empty paths (386-387, 391-392, 395-406)
# ---------------------------------------------------------------------------


def test_section_orphan_pass_no_files(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    result = _section_orphan_pass(session, [], [], {})
    assert "## 7. Orphan Pass Summary" in result
    assert "not found" in result


def test_section_orphan_pass_promoted_to_schema_gap(tmp_path):
    """Logs that mention 'promoted to schema-gap orphan' surface in the section."""
    session = tmp_path / "session"
    inter = session / "intermediate"
    inter.mkdir(parents=True)
    (inter / "orphan_candidates.json").write_text(json.dumps({"groups": [], "schema_gap_orphans": []}))

    lines = [
        {
            "ts": "09:00:00",
            "level": "INFO",
            "logger": "x",
            "message": "orphan-1 promoted to schema-gap orphan",
        }
    ]
    result = _section_orphan_pass(session, lines, [], {})
    assert "Promoted to schema-gap orphan" in result


def test_section_orphan_pass_many_orphans_truncate(tmp_path):
    """If >20 orphans remain in graph, render the '...and N more' line.

    The orphan tail rendering branch only fires when ``edge_data`` is non-empty,
    so we provide a single dummy edge that doesn't connect any of the orphans.
    """
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)

    nodes = [{"id": f"p-{i}", "type": "Person"} for i in range(25)]
    edges = {"dummy": {"type": "x", "from": "other-1", "to": "other-2"}}
    result = _section_orphan_pass(session, [], nodes, edges)
    assert "…and 5 more" in result


# ---------------------------------------------------------------------------
# _section_final_graph — empty branches and networkx output
# ---------------------------------------------------------------------------


def test_section_final_graph_empty(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    result = _section_final_graph(session, [], {})
    assert "**Total nodes:** 0" in result
    assert "**Total edges:** 0" in result


def test_section_final_graph_with_networkx_output(tmp_path):
    session = tmp_path / "session"
    out_dir = session / "output"
    nx_dir = out_dir / "networkx_output"
    nx_dir.mkdir(parents=True)
    (nx_dir / "graph.gml").write_text("graph []")
    (nx_dir / "graph.graphml").write_text("<graphml/>")
    (out_dir / "nodes.jsonl").write_text("")

    result = _section_final_graph(session, [], {})
    assert "networkx_output/" in result
    assert "graph.gml" in result


# ---------------------------------------------------------------------------
# _section_warnings — title rendering branches (line 1104)
# ---------------------------------------------------------------------------


def test_section_warnings_no_warnings():
    result = _section_warnings([])
    assert "No warnings or errors recorded" in result


def test_section_warnings_categorization():
    lines = [
        {
            "ts": "09:00:00",
            "level": "WARNING",
            "logger": "pass2",
            "message": "chunk 1 — validation errors",
        },
        {
            "ts": "09:00:01",
            "level": "WARNING",
            "logger": "assembler",
            "message": "dropping edge edge-1 dangling",
        },
        {
            "ts": "09:00:02",
            "level": "WARNING",
            "logger": "schema_validate",
            "message": "schema property foo missing range",
        },
        {
            "ts": "09:00:03",
            "level": "WARNING",
            "logger": "x",
            "message": "something else",
        },
    ]
    result = _section_warnings(lines)
    assert "Chunk Errors & Retries" in result
    assert "Dangling Edges Dropped" in result
    assert "Schema Issues" in result
    assert "Other Warnings" in result


# ---------------------------------------------------------------------------
# _section_health_status — credit + abox advisory branches (1054, 1059, 1065)
# ---------------------------------------------------------------------------


def test_section_health_status_failed_steps(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    state = {"steps": {"pass2": {"status": "failed"}}}
    result = _section_health_status(session, [], state)
    assert "step(s) failed" in result


def test_section_health_status_credit_error(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "09:00:00", "level": "ERROR", "logger": "x", "message": "402 insufficient credit"},
    ]
    result = _section_health_status(session, lines, {})
    assert "402" in result
    assert "credit error" in result


def test_section_health_status_other_errors(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    lines = [
        {"ts": "09:00:00", "level": "ERROR", "logger": "x", "message": "some random failure"},
    ]
    result = _section_health_status(session, lines, {})
    assert "other error" in result.lower()


def test_section_health_status_abox_advisory(tmp_path):
    session = tmp_path / "session"
    out = session / "output"
    out.mkdir(parents=True)
    (out / "knowledge_graph_validation.json").write_text(
        json.dumps(
            {
                "valid": False,
                "tbox_checks": {"errors": []},
                "abox_checks": {"errors": ["err1", "err2"]},
            }
        )
    )
    result = _section_health_status(session, [], {})
    assert "ABox advisory" in result


def test_section_health_status_clean(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    result = _section_health_status(session, [], {})
    assert "✓ Clean" in result


# ---------------------------------------------------------------------------
# Merge sections
# ---------------------------------------------------------------------------


def _make_minimal_merge_session(tmp_path, with_net_new=False, with_cross_edge=False):
    """Set up a fake merge session structure under tmp_path."""
    sessions_root = tmp_path / "sessions"
    session = sessions_root / "merged"
    session_a = sessions_root / "sess-a"
    session_b = sessions_root / "sess-b"
    for s in (session, session_a, session_b):
        (s / "intermediate").mkdir(parents=True)
        (s / "output").mkdir(parents=True)

    # Source-map (key invariant: meta has session_a + session_b)
    source_map = {
        "_meta": {
            "session_a": {"name": "sess-a"},
            "session_b": {"name": "sess-b"},
        },
        "sess-a/doc.md": {"role": "input_a", "sha256": "deadbeef"},
        "sess-b/doc.md": {"role": "input_b", "sha256": "cafebabe"},
    }
    _write(session / "intermediate" / "source_map.json", source_map)

    # Source-session artifacts
    for s, ids in [(session_a, ["a-1", "a-2"]), (session_b, ["b-1"])]:
        nodes = [{"id": nid, "type": "X", "attributes": {"name": {"value": nid}}} for nid in ids]
        _write(s / "intermediate" / "nodes.json", nodes)
        _write(s / "intermediate" / "edge_metadata.json", {})
        _write(s / "intermediate" / "schema.json", {"concepts": [], "properties": []})
        _write(s / "intermediate" / "raw_extractions.json", {f"{s.name}/doc.md": {"nodes": [], "edges": []}})

    # Merged artifacts
    merged_nodes = [
        {"id": "a-1", "type": "X", "attributes": {"name": {"value": "n1"}}},
        {"id": "b-1", "type": "X", "attributes": {"name": {"value": "n3"}}},
    ]
    if with_net_new:
        merged_nodes.append({"id": "net-new-1", "type": "Y", "attributes": {"name": {"value": "n4"}}})

    merged_edges = {}
    if with_cross_edge:
        merged_edges["edge-x"] = {
            "type": "works_at",
            "from": "a-1",
            "to": "b-1",
            "method": "orphan_inferred",
        }

    _write(session / "intermediate" / "nodes.json", merged_nodes)
    _write(session / "intermediate" / "edge_metadata.json", merged_edges)
    _write(
        session / "intermediate" / "schema.json",
        {"concepts": [], "properties": [{"name": "works_at"}]},
    )
    _write(
        session / "intermediate" / "merge_manifest.json",
        {
            "session_a": "sess-a",
            "session_b": "sess-b",
            "merged_at": "2026-05-20T10:00:00+00:00",
            "reextraction_strategy": "surgical",
            "schema_delta_session_a": [],
            "schema_delta_session_b": ["works_at"],
            "schema_synonym_log": [{"kept": "works_at", "removed": "employed_at"}],
        },
    )
    _write(
        session / "intermediate" / "raw_extractions.json",
        {
            "sess-a/doc.md": {"nodes": [], "edges": []},
            "sess-b/doc.md": {"nodes": [], "edges": []},
        },
    )
    return session


def test_section_node_edge_trace_no_source_map(tmp_path):
    """No source_map.json -> returns None."""
    session = tmp_path / "session"
    session.mkdir()
    assert _section_node_edge_trace(session) is None


def test_section_node_edge_trace_meta_missing(tmp_path):
    """source_map present but _meta lacks session_a/session_b -> None."""
    session = tmp_path / "session"
    inter = session / "intermediate"
    inter.mkdir(parents=True)
    (inter / "source_map.json").write_text(json.dumps({"_meta": {}}))
    assert _section_node_edge_trace(session) is None


def test_section_node_edge_trace_with_data(tmp_path):
    session = _make_minimal_merge_session(tmp_path, with_cross_edge=True)
    result = _section_node_edge_trace(session)
    assert result is not None
    assert "Node & Edge Count Trace" in result


def test_section_merge_provenance_no_source_map(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    assert _section_merge_provenance(session) is None


def test_section_merge_provenance_meta_missing(tmp_path):
    session = tmp_path / "session"
    inter = session / "intermediate"
    inter.mkdir(parents=True)
    (inter / "source_map.json").write_text(json.dumps({"_meta": {}}))
    assert _section_merge_provenance(session) is None


def test_section_merge_provenance_with_data(tmp_path):
    session = _make_minimal_merge_session(tmp_path, with_net_new=True, with_cross_edge=True)
    result = _section_merge_provenance(session)
    assert result is not None
    assert "## 2. Merge Provenance" in result
    assert "Net-new" in result
    assert "Cross-session" in result
    # Synonym log rendering
    assert "works_at" in result


def test_section_merge_provenance_no_cross_edges(tmp_path):
    """Renders the 'No cross-session edges' fallback message."""
    session = _make_minimal_merge_session(tmp_path)
    result = _section_merge_provenance(session)
    assert result is not None
    assert "No cross-session edges" in result


def test_section_merge_provenance_many_net_new(tmp_path):
    """Net-new >20 -> truncation row."""
    session = _make_minimal_merge_session(tmp_path)
    # Add many net-new nodes
    nodes = _load_json(session / "intermediate" / "nodes.json")
    for i in range(25):
        nodes.append(
            {"id": f"net-{i}", "type": "Z", "attributes": {"name": {"value": f"n{i}"}}}
        )
    _write(session / "intermediate" / "nodes.json", nodes)

    result = _section_merge_provenance(session)
    assert "…and " in result and "more" in result


def test_section_merge_provenance_many_cross_edges(tmp_path):
    """Many cross-session edges -> truncation row."""
    session = _make_minimal_merge_session(tmp_path)
    # Build 25 cross-session edges
    edges = {}
    for i in range(25):
        edges[f"edge-{i}"] = {
            "type": "works_at",
            "from": "a-1",
            "to": "b-1",
            "method": "orphan_inferred",
        }
    _write(session / "intermediate" / "edge_metadata.json", edges)
    result = _section_merge_provenance(session)
    assert "…and " in result


def test_section_merge_provenance_many_new_prop_edges(tmp_path):
    session = _make_minimal_merge_session(tmp_path)
    edges = {}
    # All use "works_at" which is in delta_session_b
    for i in range(25):
        # Use a node id present in a (so they're not cross-session)
        edges[f"edge-{i}"] = {
            "type": "works_at",
            "from": "a-1",
            "to": "a-1",
            "method": "llm_extraction",
        }
    _write(session / "intermediate" / "edge_metadata.json", edges)
    result = _section_merge_provenance(session)
    assert "Edges using new merged property types" in result


def test_section_merge_provenance_synonym_log_with_string_entry(tmp_path):
    session = _make_minimal_merge_session(tmp_path)
    # Patch manifest with a string-form entry to trigger the "else" branch
    _write(
        session / "intermediate" / "merge_manifest.json",
        {
            "session_a": "sess-a",
            "session_b": "sess-b",
            "reextraction_strategy": "surgical",
            "schema_delta_session_a": ["foo"],
            "schema_delta_session_b": [],
            "schema_synonym_log": ["raw entry 1"],
        },
    )
    result = _section_merge_provenance(session)
    assert "raw entry 1" in result
    # Schema delta A rendering branch
    assert "Session A" in result


def test_section_merge_provenance_long_synonym_log(tmp_path):
    session = _make_minimal_merge_session(tmp_path)
    log_entries = [{"kept": f"k{i}", "removed": f"r{i}"} for i in range(15)]
    _write(
        session / "intermediate" / "merge_manifest.json",
        {
            "session_a": "sess-a",
            "session_b": "sess-b",
            "reextraction_strategy": "surgical",
            "schema_delta_session_a": [],
            "schema_delta_session_b": [],
            "schema_synonym_log": log_entries,
        },
    )
    result = _section_merge_provenance(session)
    assert "and 5 more" in result


def test_parse_log_lines_handles_bad_lines(tmp_path):
    log = tmp_path / "run.log"
    log.write_text(
        "10:00:00 [INFO] mykg.orchestrator — RUN  ingest\n"
        "garbage line that does not match\n"
        "10:00:02 [DONE] mykg.orchestrator — done\n"
    )
    out = _parse_log_lines(log)
    # Two well-formed lines, garbage skipped
    assert len(out) == 2


def test_parse_log_lines_missing_file(tmp_path):
    out = _parse_log_lines(tmp_path / "nope.log")
    assert out == []


def test_ts_to_seconds():
    assert _ts_to_seconds("01:02:03") == 3723
