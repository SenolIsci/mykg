"""Tests for the `mykg query` terminal command and its core `query_graph`.

Mirrors the synthetic-session fixture style of ``tests/test_mcp_server.py``.

Independent-mergeability guard: this file may land before the sibling unit that
adds ``src/mykg/query.py`` and the ``query`` CLI command. The query-dependent
tests are skipped (not failed) until those exist, so this file is green either
way.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from click.testing import CliRunner

from mykg.cli import cli

# ---------------------------------------------------------------------------
# Independent-mergeability guard
# ---------------------------------------------------------------------------

try:
    from mykg.query import build_query_graph, query_graph  # noqa: F401

    _QUERY_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only pre-sibling-merge
    build_query_graph = None  # type: ignore[assignment]
    query_graph = None  # type: ignore[assignment]
    _QUERY_AVAILABLE = False

_QUERY_CMD_REGISTERED = "query" in cli.commands

requires_query = pytest.mark.skipif(
    not _QUERY_AVAILABLE, reason="mykg.query not present yet"
)
requires_query_cmd = pytest.mark.skipif(
    not (_QUERY_AVAILABLE and _QUERY_CMD_REGISTERED),
    reason="mykg query CLI command not registered yet",
)


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
        "id": "org-acme",
        "type": "Organization",
        "confidence": 0.98,
        "attributes": {
            "name": {"value": "Acme Corp", "confidence": 1.0},
            "industry": {"value": "Technology", "confidence": 0.9},
        },
        "source_files": ["partners.md"],
        "aliases": ["ACME"],
    },
]

EDGES = [
    {
        "id": "edge-001",
        "type": "works_at",
        "from": "person-alice",
        "to": "org-acme",
        "confidence": 0.92,
        "attributes": {"role": {"value": "Engineer", "confidence": 0.88}},
    },
]


def _write_session(sessions_root: Path, name: str) -> Path:
    """Build a tmp session dir with nodes/edges/schema. Returns the session root."""
    session_root = sessions_root / name
    output = session_root / "output"
    output.mkdir(parents=True)
    intermediate = session_root / "intermediate"
    intermediate.mkdir(parents=True)

    (output / "nodes.jsonl").write_text(
        "\n".join(json.dumps(n, ensure_ascii=False) for n in NODES),
        encoding="utf-8",
    )
    (output / "edges.jsonl").write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in EDGES),
        encoding="utf-8",
    )
    (intermediate / "schema.json").write_text(
        json.dumps(SCHEMA, ensure_ascii=False), encoding="utf-8"
    )
    return session_root


@pytest.fixture
def sessions_root(tmp_path: Path) -> Path:
    return tmp_path / "mykg_sessions"


@pytest.fixture
def session_name() -> str:
    return "test-session"


@pytest.fixture
def session_root(sessions_root: Path, session_name: str) -> Path:
    return _write_session(sessions_root, session_name)


# ---------------------------------------------------------------------------
# 1. Core test — build_query_graph + query_graph
# ---------------------------------------------------------------------------


@requires_query
def test_query_graph_core(session_root: Path):
    qg = build_query_graph(session_root)
    out = query_graph(qg, "Alice")
    assert "# Knowledge Graph Context" in out
    assert "Alice" in out
    assert "## Nodes" in out
    assert "## Relationships" in out


# ---------------------------------------------------------------------------
# 2. CLI parity test — byte-for-byte with the core function
# ---------------------------------------------------------------------------


@requires_query_cmd
def test_query_cli_parity(
    session_root: Path, sessions_root: Path, session_name: str, monkeypatch
):
    monkeypatch.setattr("mykg.cli._sessions_root", lambda: sessions_root)

    qg = build_query_graph(session_root)
    expected = query_graph(qg, "Alice")

    result = CliRunner().invoke(
        cli, ["query", "Alice", "--session", session_name]
    )
    assert result.exit_code == 0, result.output
    assert result.output.rstrip("\n") == expected.rstrip("\n")


# ---------------------------------------------------------------------------
# 3. No-match test — core + CLI
# ---------------------------------------------------------------------------


@requires_query
def test_query_graph_no_match(session_root: Path):
    out = query_graph(build_query_graph(session_root), "zzznotathing")
    assert out.startswith("No nodes found matching")


@requires_query_cmd
def test_query_cli_no_match(
    session_root: Path, sessions_root: Path, session_name: str, monkeypatch
):
    monkeypatch.setattr("mykg.cli._sessions_root", lambda: sessions_root)

    result = CliRunner().invoke(
        cli, ["query", "zzznotathing", "--session", session_name]
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith("No nodes found matching")
