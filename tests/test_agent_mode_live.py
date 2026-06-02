"""Live end-to-end test for agent-mode.

Drives the mykg pipeline against ``AgentAdapter`` while a mock skill (running
in a background thread) drains the session inbox and writes canned answers
matched to the ``step`` field of each task envelope.

This verifies the inbox/outbox contract end-to-end without requiring a real
Claude Code session or a real LLM API key.
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
from pathlib import Path

import pytest

# Ensure tests/fixtures/ is importable for mock_skill.
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from mock_skill import run_watcher  # noqa: E402

from mykg.llm.config import load_adapter  # noqa: E402
from mykg.orchestrator import PipelineContext, run  # noqa: E402
from mykg.pipeline import STEPS  # noqa: E402


def _agent_raw_config() -> dict:
    return {
        "provider": "agent",
        "llm_retry": {"max_retries": 1},
        "llm": {
            "max_output_tokens": 4000,
            "timeout": 30,
            "retry_429_max": 0,
            "retry_429_base_delay": 1.0,
        },
        "agent": {
            "inbox_dir": "agent_inbox",
            "outbox_dir": "agent_outbox",
            "poll_interval_seconds": 0.1,
        },
        "pipeline": {
            "ingest": {"max_workers": 1},
            "chunking": {
                "window_tokens": 1000,
                "overlap_tokens": 100,
                "tiktoken_encoding": "cl100k_base",
            },
            "pass1": {"batch_token_target": 4000, "max_workers": 1, "per_file_batching": False},
            "pass2": {"max_workers": 1, "stateful_chunks": False, "prep_mode": "per_file"},
            "normalize_names": {"enabled": False},
            "orphan_pass": {"enabled": False},
            "error_gate": {"enabled": False},
            "logging": {"max_bytes": 10485760, "backup_count": 3, "capture_prompts": False},
            "assembly": {"confidence_agg": "mean"},
            "export": {"networkx_enabled": False},
            "paths": {"sessions_dir": "sessions"},
        },
    }


@pytest.fixture
def agent_corpus(tmp_path):
    src = Path(__file__).parent / "fixtures" / "agent_corpus"
    dest = tmp_path / "input"
    dest.mkdir()
    for f in src.iterdir():
        if f.is_file() and f.suffix == ".md":
            shutil.copy(f, dest / f.name)
    return dest


def test_agent_mode_pipeline_with_mock_skill(tmp_path, agent_corpus):
    intermediate_dir = tmp_path / "intermediate"
    output_dir = tmp_path / "output"
    intermediate_dir.mkdir()
    output_dir.mkdir()

    inbox = intermediate_dir / "agent_inbox"
    outbox = intermediate_dir / "agent_outbox"

    # Spawn the mock skill in a background thread BEFORE building the adapter,
    # so when the pipeline starts writing tasks, the watcher is already polling.
    stop_event = threading.Event()

    def _watcher_loop():
        while not stop_event.is_set():
            # Drain in 1-second windows so we can react to stop quickly.
            run_watcher(inbox, outbox, stop_after_seconds=1.0, poll_interval=0.1)

    watcher = threading.Thread(target=_watcher_loop, daemon=True)
    watcher.start()

    try:
        adapter = load_adapter(_raw=_agent_raw_config(), intermediate_dir=intermediate_dir)
        ctx = PipelineContext(
            input_dir=agent_corpus,
            output_dir=output_dir,
            intermediate_dir=intermediate_dir,
            adapter=adapter,
            base_schema=None,
            thesaurus=None,
            review=False,
        )
        run(STEPS, ctx)
    finally:
        stop_event.set()
        watcher.join(timeout=2.0)

    # --- Assertions ----------------------------------------------------------
    # The pipeline produced its primary outputs.
    nodes_path = output_dir / "nodes.jsonl"
    edges_path = output_dir / "edges.jsonl"
    ttl_path = output_dir / "knowledge_graph.ttl"
    schema_path = intermediate_dir / "schema.json"

    assert schema_path.exists(), "schema.json not produced — pass1 did not complete"
    schema = json.loads(schema_path.read_text())
    assert isinstance(schema.get("concepts"), list)
    assert isinstance(schema.get("properties"), list)

    assert nodes_path.exists(), "nodes.jsonl not produced"
    node_lines = [l for l in nodes_path.read_text().splitlines() if l.strip()]
    assert node_lines, "nodes.jsonl is empty"
    for line in node_lines:
        node = json.loads(line)
        assert "id" in node and "type" in node

    assert edges_path.exists(), "edges.jsonl not produced"
    assert ttl_path.exists(), "knowledge_graph.ttl not produced"

    # Validate TTL is parseable.
    from rdflib import Graph

    g = Graph()
    g.parse(data=ttl_path.read_text(), format="turtle")

    # Inbox/outbox sanity — at least one task was answered.
    answered = list(outbox.glob("*.done"))
    assert answered, "mock skill did not answer any tasks"


def test_mock_skill_canned_answers_are_valid_json():
    """The canned answers themselves must be valid JSON the pipeline can parse."""
    from mock_skill import (
        _normalize_answer,
        _orphan_chunk_answer,
        _orphan_pair_answer,
        _orphan_schema_gap_answer,
        _pass1_answer,
        _pass2_answer,
    )

    pass1 = json.loads(_pass1_answer())
    assert "concepts" in pass1 and "properties" in pass1
    assert all(c.get("type") for c in pass1["concepts"])

    pass2 = json.loads(_pass2_answer())
    assert "nodes" in pass2 and "edges" in pass2

    json.loads(_normalize_answer())
    json.loads(_orphan_chunk_answer())
    json.loads(_orphan_pair_answer())
    json.loads(_orphan_schema_gap_answer())
