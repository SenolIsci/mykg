"""Unit tests for mykg.walkthrough helper functions.

All tests use tmp_path and minimal fake session directories — no live LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

from mykg.walkthrough import (
    _build_concept_tree,
    _parse_log_lines,
    _section_extraction_summary,
    _section_llm_stats,
    _section_merge_provenance,
    _section_node_edge_trace,
    _section_orphan_pass,
    _section_step_timeline,
    _section_warnings,
    generate_walkthrough,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, (dict, list)):
        path.write_text(json.dumps(data, indent=2))
    else:
        path.write_text(data)


# ---------------------------------------------------------------------------
# 1. test_parse_log_basic
# ---------------------------------------------------------------------------


def test_parse_log_basic(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "21:33:09 [INFO] mykg.cli — Command: mykg extract-graph input/\n"
        "21:33:10 [WARNING] mykg.pass2 — chunk 3 — validation errors: []\n"
        "not a valid log line\n"
    )
    parsed = _parse_log_lines(log_path)
    assert len(parsed) == 2
    assert parsed[0]["ts"] == "21:33:09"
    assert parsed[0]["level"] == "INFO"
    assert parsed[0]["logger"] == "mykg.cli"
    assert "Command:" in parsed[0]["message"]
    assert parsed[1]["level"] == "WARNING"


def test_parse_log_missing_file(tmp_path):
    result = _parse_log_lines(tmp_path / "nonexistent.log")
    assert result == []


# ---------------------------------------------------------------------------
# 2. test_parse_log_step_events
# ---------------------------------------------------------------------------


def test_parse_log_step_events(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "10:00:00 [INFO] mykg.orchestrator — RUN  ingest\n"
        "10:00:05 [INFO] mykg.orchestrator — DONE ingest\n"
        "10:00:05 [INFO] mykg.orchestrator — RUN  pass1\n"
        "10:01:00 [INFO] mykg.orchestrator — DONE pass1\n"
        "10:01:00 [INFO] mykg.orchestrator — SKIP schema_validate — outputs exist\n"
    )
    parsed = _parse_log_lines(log_path)
    orch = [ln for ln in parsed if "orchestrator" in ln["logger"]]
    assert len(orch) == 5
    runs = [ln for ln in orch if ln["message"].startswith("RUN")]
    dones = [ln for ln in orch if ln["message"].startswith("DONE")]
    skips = [ln for ln in orch if ln["message"].startswith("SKIP")]
    assert len(runs) == 2
    assert len(dones) == 2
    assert len(skips) == 1


# ---------------------------------------------------------------------------
# 3. test_step_timeline_duration
# ---------------------------------------------------------------------------


def test_step_timeline_duration(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    state = {"started_at": "2026-05-20T20:33:09+00:00", "steps": {}, "errors": {}}

    log_path = session / "run.log"
    log_path.write_text(
        "10:00:00 [INFO] mykg.orchestrator — RUN  ingest\n"
        "10:00:10 [INFO] mykg.orchestrator — DONE ingest\n"
        "10:00:10 [INFO] mykg.orchestrator — RUN  pass1\n"
        "10:05:10 [INFO] mykg.orchestrator — DONE pass1\n"
    )
    lines = _parse_log_lines(log_path)
    result = _section_step_timeline(session, lines, state)
    # ingest: 10s, pass1: 5min = 300s
    assert "10s" in result
    assert "5m" in result


# ---------------------------------------------------------------------------
# 4. test_schema_tree_rendering
# ---------------------------------------------------------------------------


def test_schema_tree_rendering():
    concepts = [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
        {"type": "Employee", "parent": "Person", "attributes": ["role"]},
    ]
    tree = _build_concept_tree(concepts)
    assert "**Person**" in tree
    assert "**Organization**" in tree
    assert "**Employee**" in tree
    # Employee should be indented (child of Person)
    lines = tree.splitlines()
    person_line = next(ln for ln in lines if "Person" in ln and "Employee" not in ln)
    employee_line = next(ln for ln in lines if "Employee" in ln)
    # Employee line has more leading spaces than Person line
    person_indent = len(person_line) - len(person_line.lstrip())
    employee_indent = len(employee_line) - len(employee_line.lstrip())
    assert employee_indent > person_indent
    assert "is-a: Person" in employee_line


# ---------------------------------------------------------------------------
# 5. test_schema_evolution_empty
# ---------------------------------------------------------------------------


def test_schema_evolution_empty(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    # No schema_history dir, no schema.json
    from mykg.walkthrough import _section_schema_evolution

    result = _section_schema_evolution(session)
    assert "## 4. Schema Evolution" in result
    # Should not raise; should contain graceful fallback text
    assert "not found" in result or "No schema history" in result


# ---------------------------------------------------------------------------
# 6. test_llm_stats_grouping
# ---------------------------------------------------------------------------


def test_llm_stats_grouping(tmp_path):
    session = tmp_path / "session"
    session.mkdir()
    llm_log = session / "llm.log"
    records = [
        {
            "ts": "10:00:01",
            "context": "pass1 batch 1/4",
            "input_tokens": 100,
            "output_tokens": 50,
            "duration_s": 5.0,
            "model": "m",
        },
        {
            "ts": "10:00:02",
            "context": "pass1 batch 2/4",
            "input_tokens": 200,
            "output_tokens": 80,
            "duration_s": 7.0,
            "model": "m",
        },
        {
            "ts": "10:01:00",
            "context": "pass2 chunk extraction",
            "input_tokens": 300,
            "output_tokens": 120,
            "duration_s": 10.0,
            "model": "m",
        },
        {
            "ts": "10:02:00",
            "context": "schema_harmonize call",
            "input_tokens": 500,
            "output_tokens": 200,
            "duration_s": 40.0,
            "model": "m",
        },
    ]
    llm_log.write_text("\n".join(json.dumps(r) for r in records))

    result = _section_llm_stats(session)
    assert "Pass 1 batch induction" in result
    assert "Instance extraction (Pass 2)" in result
    assert "Schema harmonization" in result
    # Total row should show 4 calls
    assert "**4**" in result or "4" in result
    # Total input tokens: 100+200+300+500 = 1,100
    assert "1,100" in result


# ---------------------------------------------------------------------------
# 7. test_orphan_remaining_count
# ---------------------------------------------------------------------------


def test_orphan_remaining_count(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)

    nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 1.0,
            "attributes": {},
            "source_files": [],
        },
        {
            "id": "person-bob",
            "type": "Person",
            "confidence": 1.0,
            "attributes": {},
            "source_files": [],
        },
        {
            "id": "org-acme",
            "type": "Organization",
            "confidence": 1.0,
            "attributes": {},
            "source_files": [],
        },
    ]
    edge_metadata = {
        "edge-001": {
            "id": "edge-001",
            "type": "works_at",
            "from": "person-alice",
            "to": "org-acme",
            "confidence": 0.9,
            "method": "llm_extraction",
            "attributes": {},
            "source_files": [],
        },
    }

    result = _section_orphan_pass(session, [], nodes, edge_metadata)
    # person-bob is orphaned (not in any edge)
    assert "person-bob" in result
    assert "1" in result  # orphans remaining count


# ---------------------------------------------------------------------------
# 8. test_generate_walkthrough_partial
# ---------------------------------------------------------------------------


def test_generate_walkthrough_partial(tmp_path):
    """generate_walkthrough must not raise when most files are absent."""
    session = tmp_path / "partial_session"
    (session / "intermediate").mkdir(parents=True)
    (session / "output").mkdir(parents=True)

    # Minimal run.log only
    (session / "run.log").write_text(
        "10:00:00 [INFO] mykg.cli — LLM endpoint: openrouter / test-model\n"
        "10:00:01 [INFO] mykg.orchestrator — RUN  ingest\n"
        "10:00:02 [INFO] mykg.orchestrator — DONE ingest\n"
    )

    result = generate_walkthrough(session)
    assert isinstance(result, str)
    assert "## 1. Final Graph Summary" in result
    assert "## 2. Run Overview" in result
    assert "## 3. Step Timeline" in result
    assert "## 4. Schema Evolution" in result
    assert "## 5. LLM Call Statistics" in result
    assert "## 6. Extraction Summary" in result
    assert "## 7. Orphan Pass Summary" in result
    assert "## 8. Warnings & Retries" in result


# ---------------------------------------------------------------------------
# 9. test_warnings_section
# ---------------------------------------------------------------------------


def test_warnings_section(tmp_path):
    log_path = tmp_path / "run.log"
    log_path.write_text(
        "10:00:00 [INFO] mykg.cli — Normal startup\n"
        "10:00:05 [WARNING] mykg.pass2 — chunk 3 — validation errors: ['bad type'] — retrying\n"
        "10:00:10 [ERROR] mykg.orchestrator — FAILED pass2 — timeout\n"
        "10:00:15 [INFO] mykg.pass2 — 65_HS1.md — total: 5 node(s), 3 edge(s)\n"
        "10:00:20 [WARNING] mykg.pass2 — 65_HS1.md — dropping edge a→b (dangling after dedup)\n"
    )
    lines = _parse_log_lines(log_path)
    result = _section_warnings(lines)

    assert "## 8. Warnings & Retries" in result
    # INFO lines must NOT appear
    assert "Normal startup" not in result
    assert "total: 5 node" not in result
    # WARNING and ERROR lines must appear
    assert "validation errors" in result
    assert "FAILED" in result
    assert "dropping edge" in result
    # Grouped correctly
    assert "Chunk Errors & Retries" in result
    assert "Dangling Edges" in result


# ---------------------------------------------------------------------------
# Merge-session fixture helpers
# ---------------------------------------------------------------------------


def _make_merge_sessions(tmp_path: Path):
    """Create sessions_root / merged + sess-a + sess-b dirs with all needed files.

    Returns (sessions_root, merged, sess_a, sess_b).
    """
    sessions_root = tmp_path / "sessions"
    merged = sessions_root / "merged"
    sess_a = sessions_root / "sess-a"
    sess_b = sessions_root / "sess-b"

    for d in (merged, sess_a, sess_b):
        (d / "intermediate").mkdir(parents=True)
        (d / "output").mkdir(parents=True)

    # --- session A ---
    _write(
        sess_a / "intermediate" / "nodes.json",
        [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 1.0,
                "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                "source_files": ["a.md"],
            }
        ],
    )
    _write(
        sess_a / "intermediate" / "edge_metadata.json",
        {
            "edge-a1": {
                "type": "works_at",
                "from": "person-alice",
                "to": "org-x",
                "confidence": 0.9,
                "method": "llm_extraction",
                "attributes": {},
                "source_files": ["a.md"],
            }
        },
    )
    _write(
        sess_a / "intermediate" / "schema.json",
        {
            "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
            "properties": [
                {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
            ],
        },
    )
    _write(
        sess_a / "intermediate" / "raw_extractions.json",
        {
            "a.md": {
                "nodes": [
                    {
                        "id": "person-alice",
                        "type": "Person",
                        "confidence": 1.0,
                        "attributes": {},
                        "source_files": [],
                    }
                ],
                "edges": [
                    {
                        "type": "works_at",
                        "from": "person-alice",
                        "to": "org-x",
                        "confidence": 0.9,
                        "attributes": {},
                    }
                ],
            }
        },
    )

    # --- session B ---
    _write(
        sess_b / "intermediate" / "nodes.json",
        [
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 1.0,
                "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
                "source_files": ["b.md"],
            }
        ],
    )
    _write(
        sess_b / "intermediate" / "edge_metadata.json",
        {
            "edge-b1": {
                "type": "works_at",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.8,
                "method": "llm_extraction",
                "attributes": {},
                "source_files": ["b.md"],
            }
        },
    )
    _write(
        sess_b / "intermediate" / "schema.json",
        {
            "concepts": [{"type": "Organization", "parent": None, "attributes": ["name"]}],
            "properties": [
                {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
            ],
        },
    )
    _write(
        sess_b / "intermediate" / "raw_extractions.json",
        {
            "b.md": {
                "nodes": [
                    {
                        "id": "org-acme",
                        "type": "Organization",
                        "confidence": 1.0,
                        "attributes": {},
                        "source_files": [],
                    }
                ],
                "edges": [
                    {
                        "type": "works_at",
                        "from": "person-bob",
                        "to": "org-acme",
                        "confidence": 0.8,
                        "attributes": {},
                    }
                ],
            }
        },
    )

    # --- merged session ---
    _write(
        merged / "intermediate" / "source_map.json",
        {
            "_meta": {
                "session_a": {"name": "sess-a", "prep_mode": "per_file"},
                "session_b": {"name": "sess-b", "prep_mode": "per_file"},
            },
            "session_a/a.md": {
                "original_session": "sess-a",
                "alias": "session_a",
                "sha256": "aaa",
                "role": "input_a",
            },
            "session_b/b.md": {
                "original_session": "sess-b",
                "alias": "session_b",
                "sha256": "bbb",
                "role": "input_b",
            },
        },
    )
    _write(
        merged / "intermediate" / "merge_manifest.json",
        {
            "session_a": "sess-a",
            "session_b": "sess-b",
            "merged_at": "2026-05-28T12:00:00",
            "reextraction_strategy": "surgical",
            "schema_delta_session_a": [],
            "schema_delta_session_b": ["new_prop"],
            "schema_synonym_log": [{"kept": "Person", "removed": "Human"}],
        },
    )
    _write(
        merged / "intermediate" / "schema.json",
        {
            "concepts": [
                {"type": "Person", "parent": None, "attributes": ["name"]},
                {"type": "Organization", "parent": None, "attributes": ["name"]},
            ],
            "properties": [
                {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
                {"name": "new_prop", "domain": "Person", "range": "Organization", "attributes": []},
            ],
        },
    )
    # merged raw_extractions: namespaced keys from both sessions
    _write(
        merged / "intermediate" / "raw_extractions.json",
        {
            "session_a/a.md": {
                "nodes": [
                    {
                        "id": "person-alice",
                        "type": "Person",
                        "confidence": 1.0,
                        "attributes": {},
                        "source_files": [],
                    }
                ],
                "edges": [
                    {
                        "type": "works_at",
                        "from": "person-alice",
                        "to": "org-acme",
                        "confidence": 0.9,
                        "attributes": {},
                    }
                ],
            },
            "session_b/b.md": {
                "nodes": [
                    {
                        "id": "org-acme",
                        "type": "Organization",
                        "confidence": 1.0,
                        "attributes": {},
                        "source_files": [],
                    }
                ],
                "edges": [
                    {
                        "type": "works_at",
                        "from": "person-bob",
                        "to": "org-acme",
                        "confidence": 0.8,
                        "attributes": {},
                    },
                    {
                        "type": "new_prop",
                        "from": "person-alice",
                        "to": "org-acme",
                        "confidence": 0.7,
                        "attributes": {},
                    },
                ],
            },
        },
    )
    _write(
        merged / "intermediate" / "nodes.json",
        [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 1.0,
                "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
                "source_files": ["session_a/a.md"],
            },
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 1.0,
                "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
                "source_files": ["session_b/b.md"],
            },
        ],
    )
    _write(
        merged / "intermediate" / "edge_metadata.json",
        {
            "edge-a1": {
                "type": "works_at",
                "from": "person-alice",
                "to": "org-acme",
                "confidence": 0.9,
                "method": "llm_extraction",
                "attributes": {},
                "source_files": ["session_a/a.md"],
            },
            "edge-b1": {
                "type": "works_at",
                "from": "org-acme",
                "to": "person-alice",
                "confidence": 0.8,
                "method": "llm_extraction",
                "attributes": {},
                "source_files": ["session_b/b.md"],
            },
        },
    )
    _write(
        merged / "intermediate" / "merge_log.json",
        [
            {"event": "node_merge", "id": "person-alice"},
            {"event": "edge_merge", "id": "edge-a1"},
        ],
    )
    _write(
        merged / "intermediate" / "orphan_candidates.json",
        {
            "groups": [
                {
                    "orphan_ids": ["person-bob"],
                    "connected_node_ids": ["org-acme"],
                    "filename": "b.md",
                    "chunk_idx": 0,
                }
            ],
            "schema_gap_orphans": [],
        },
    )
    _write(
        merged / "intermediate" / "orphan_connections.json",
        {
            "edge-orphan-1": {
                "type": "works_at",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.7,
                "method": "orphan_inferred",
                "attributes": {},
                "source_files": [],
            }
        },
    )

    return sessions_root, merged, sess_a, sess_b


# ---------------------------------------------------------------------------
# _section_node_edge_trace tests
# ---------------------------------------------------------------------------


def test_node_edge_trace_returns_none_without_source_map(tmp_path):
    sessions_root = tmp_path / "sessions"
    merged = sessions_root / "merged"
    (merged / "intermediate").mkdir(parents=True)
    # no source_map.json → should return None
    result = _section_node_edge_trace(merged)
    assert result is None


def test_node_edge_trace_returns_none_without_meta_keys(tmp_path):
    sessions_root = tmp_path / "sessions"
    merged = sessions_root / "merged"
    (merged / "intermediate").mkdir(parents=True)
    # source_map exists but _meta lacks session_a/session_b keys
    _write(merged / "intermediate" / "source_map.json", {"_meta": {"foo": "bar"}})
    result = _section_node_edge_trace(merged)
    assert result is None


def test_node_edge_trace_includes_step_table(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_node_edge_trace(merged)
    assert result is not None
    assert "## 2. Node & Edge Count Trace" in result
    assert "merge_setup" in result
    assert "merge_schema" in result
    assert "assemble" in result
    assert "validate_graph" in result


def test_node_edge_trace_counts_merged_raw_nodes_and_edges(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_node_edge_trace(merged)
    assert result is not None
    # merged raw: session_a/a.md has 1 node + 1 edge; session_b/b.md has 1 node + 2 edges
    # total raw: 2 nodes, 3 edges → should appear in table
    assert "2" in result  # merged raw nodes
    assert "3" in result  # merged raw edges


def test_node_edge_trace_reextract_calls_from_llm_log(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    # Write an llm.log with a pass2/reextract call
    (merged / "llm.log").write_text(
        json.dumps(
            {
                "context": "pass2 reextract chunk 1",
                "input_tokens": 100,
                "output_tokens": 50,
                "duration_s": 2.0,
            }
        )
        + "\n"
    )
    result = _section_node_edge_trace(merged)
    assert result is not None
    # reextract_calls = 1 → "LLM ×1" should appear
    assert "LLM ×1" in result


def test_node_edge_trace_filtered_edges_count(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    # Add an edge whose type is NOT in merged schema — should appear in the filter detail
    edge_path = merged / "intermediate" / "edge_metadata.json"
    edge_data = json.loads(edge_path.read_text())
    edge_data["edge-invalid"] = {
        "type": "ghost_prop",
        "from": "person-alice",
        "to": "org-acme",
        "confidence": 0.5,
        "method": "llm_extraction",
        "attributes": {},
        "source_files": [],
    }
    _write(edge_path, edge_data)
    result = _section_node_edge_trace(merged)
    assert result is not None
    assert "ghost_prop" in result


def test_node_edge_trace_returns_string_when_valid(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_node_edge_trace(merged)
    assert isinstance(result, str)
    assert len(result) > 100


def test_node_edge_trace_counts_output_jsonl(tmp_path):
    """Streaming read of nodes.jsonl/edges.jsonl in output/ is exercised."""
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    output = merged / "output"
    output.mkdir(exist_ok=True)
    output.joinpath("nodes.jsonl").write_text(
        '{"id":"person-alice","type":"Person"}\n'
        '{"id":"org-acme","type":"Organization"}\n'
    )
    output.joinpath("edges.jsonl").write_text(
        '{"type":"works_at","from":"person-alice","to":"org-acme"}\n'
    )
    result = _section_node_edge_trace(merged)
    assert result is not None
    assert "2" in result  # 2 nodes in output
    assert "1" in result  # 1 edge in output


# ---------------------------------------------------------------------------
# _section_merge_provenance tests
# ---------------------------------------------------------------------------


def test_merge_provenance_returns_none_without_source_map(tmp_path):
    sessions_root = tmp_path / "sessions"
    merged = sessions_root / "merged"
    (merged / "intermediate").mkdir(parents=True)
    result = _section_merge_provenance(merged)
    assert result is None


def test_merge_provenance_includes_before_after_table(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_merge_provenance(merged)
    assert result is not None
    assert "Before & After" in result
    assert "sess-a" in result
    assert "sess-b" in result
    # table should have Nodes and Edges rows
    assert "Nodes" in result
    assert "Edges" in result
    assert "Schema concepts" in result


def test_merge_provenance_classifies_cross_session_edges(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_merge_provenance(merged)
    assert result is not None
    assert "Edge Provenance" in result
    assert "Cross-session" in result


def test_merge_provenance_net_new_nodes_count(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_merge_provenance(merged)
    assert result is not None
    assert "Net-new" in result
    # In our fixture person-alice is in A, org-acme is in B; neither appears in the other → 0 deduped
    assert "Node Provenance" in result


def test_merge_provenance_synonym_log_present(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_merge_provenance(merged)
    assert result is not None
    # merge_manifest has schema_synonym_log with one entry
    assert "Schema synonyms collapsed" in result
    assert "Person" in result
    assert "Human" in result


def test_merge_provenance_no_cross_session_edges_message(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    # Replace edge_metadata with an A→A self-loop so no cross-session edges exist
    _write(
        merged / "intermediate" / "edge_metadata.json",
        {
            "edge-aa": {
                "type": "works_at",
                "from": "person-alice",
                "to": "person-alice",
                "confidence": 0.9,
                "method": "llm_extraction",
                "attributes": {},
                "source_files": [],
            },
        },
    )
    result = _section_merge_provenance(merged)
    assert result is not None
    assert "No cross-session edges" in result


def test_merge_provenance_delta_props_listed(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = _section_merge_provenance(merged)
    assert result is not None
    # schema_delta_session_b = ["new_prop"] → should appear
    assert "new_prop" in result
    assert "New properties for Session B" in result


# ---------------------------------------------------------------------------
# _section_extraction_summary tests
# ---------------------------------------------------------------------------


def test_extraction_summary_includes_name_normalization_when_present(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    _write(
        session / "intermediate" / "name_normalization.json",
        {
            "metadata": {"aliases_mapped": 5},
            "mappings": {"Person": {"Bob": "Alice"}, "Org": {"Corp": "Company"}},
        },
    )
    result = _section_extraction_summary(session, [], {})
    assert "Name normalization" in result
    assert "5 aliases mapped" in result
    assert "2 concept type(s)" in result


def test_extraction_summary_skips_name_normalization_when_absent(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    # No name_normalization.json
    result = _section_extraction_summary(session, [], {})
    assert "Name normalization" not in result


def test_extraction_summary_includes_dedup_counts_from_merge_log(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    _write(
        session / "intermediate" / "merge_log.json",
        [
            {"event": "node_merge", "id": "x"},
            {"event": "node_merge", "id": "y"},
            {"event": "edge_merge", "id": "e1"},
        ],
    )
    result = _section_extraction_summary(session, [], {})
    assert "Deduplication" in result
    assert "2 node merge(s)" in result
    assert "1 edge merge(s)" in result


def test_extraction_summary_retry_rate_shown_when_chunks_dispatched(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    # Simulate log lines with chunk dispatch and a retry
    log_lines = [
        {
            "ts": "10:00:01",
            "level": "INFO",
            "logger": "mykg.pass2",
            "message": "Processing chunk 1/5",
        },
        {
            "ts": "10:00:02",
            "level": "INFO",
            "logger": "mykg.pass2",
            "message": "Processing chunk 2/5",
        },
        {
            "ts": "10:00:03",
            "level": "WARNING",
            "logger": "mykg.pass2",
            "message": "chunk 1 — JSON parse error — retrying",
        },
    ]
    result = _section_extraction_summary(session, log_lines, {})
    assert "Retry rate" in result
    # 2 chunks dispatched, 1 json parse retry → 50% retry rate
    assert "50.0%" in result


def test_extraction_summary_retry_rate_na_when_no_chunks(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    result = _section_extraction_summary(session, [], {})
    assert "n/a" in result


# ---------------------------------------------------------------------------
# _section_step_timeline tests
# ---------------------------------------------------------------------------


def test_step_timeline_falls_back_to_state_when_no_log_events(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    state = {
        "steps": {
            "ingest": {"status": "done"},
            "pass1": {"status": "done"},
            "pass2": {"status": "failed"},
        }
    }
    # Pass empty lines → no orchestrator events → must fall back to state
    result = _section_step_timeline(session, [], state)
    assert "ingest" in result
    assert "pass1" in result
    assert "pass2" in result
    assert "failed" in result


def test_step_timeline_shows_dash_duration_for_skipped_steps(tmp_path):
    session = tmp_path / "session"
    (session / "intermediate").mkdir(parents=True)
    log_path = session / "run.log"
    log_path.write_text(
        "10:00:00 [INFO] mykg.orchestrator — RUN  ingest\n"
        "10:00:05 [INFO] mykg.orchestrator — DONE ingest\n"
        "10:00:05 [INFO] mykg.orchestrator — SKIP human_review — no --review flag\n"
    )
    lines = _parse_log_lines(log_path)
    result = _section_step_timeline(session, lines, {})
    assert "human_review" in result
    assert "skip" in result
    # skipped steps show "—" for duration
    rows = [ln for ln in result.splitlines() if "human_review" in ln]
    assert rows, "human_review row not found"
    assert "—" in rows[0]


# ---------------------------------------------------------------------------
# generate_walkthrough integration tests
# ---------------------------------------------------------------------------


def test_generate_walkthrough_merge_session_has_provenance_section(tmp_path):
    _, merged, _, _ = _make_merge_sessions(tmp_path)
    result = generate_walkthrough(merged)
    assert isinstance(result, str)
    assert "Merge Provenance" in result
    assert "Node & Edge Count Trace" in result


def test_generate_walkthrough_non_merge_session_no_provenance_section(tmp_path):
    session = tmp_path / "sessions" / "plain"
    (session / "intermediate").mkdir(parents=True)
    (session / "output").mkdir(parents=True)
    # No source_map.json → not a merge session
    result = generate_walkthrough(session)
    assert isinstance(result, str)
    assert "Merge Provenance" not in result
    assert "Node & Edge Count Trace" not in result


def test_generate_walkthrough_partial_merge_data_no_crash(tmp_path):
    """generate_walkthrough must not raise even when only source_map exists."""
    sessions_root = tmp_path / "sessions"
    merged = sessions_root / "merged"
    sess_a = sessions_root / "sess-a"
    sess_b = sessions_root / "sess-b"
    for d in (merged, sess_a, sess_b):
        (d / "intermediate").mkdir(parents=True)
        (d / "output").mkdir(parents=True)
    # Minimal source_map only — all other files absent
    _write(
        merged / "intermediate" / "source_map.json",
        {
            "_meta": {
                "session_a": {"name": "sess-a", "prep_mode": "per_file"},
                "session_b": {"name": "sess-b", "prep_mode": "per_file"},
            }
        },
    )
    # Should not raise
    result = generate_walkthrough(merged)
    assert isinstance(result, str)
    assert len(result) > 0
