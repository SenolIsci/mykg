"""Tests for the terminal query path (src/mykg/query.py) and its parity with
the MCP ``mykg_query_graph`` tool, plus the ``mykg query`` CLI command.

The terminal query is a replication of the MCP tool (mcp_server.py is
read-only). These tests lock in that the two produce byte-for-byte identical
output for the same session data.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from mykg.query import QueryGraph, build_query_graph, query_graph


SCHEMA = {
    "concepts": [
        {"type": "Person", "attributes": ["name", "email"], "parent": None},
        {"type": "Organization", "attributes": ["name", "industry"], "parent": None},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization",
         "attributes": ["role"]},
    ],
}

NODES = [
    {
        "id": "person-alice",
        "type": "Person",
        "confidence": 0.95,
        "attributes": {
            "name": {"value": "Alice", "confidence": 1.0},
            "email": {"value": "alice@acme.com", "confidence": 0.9},
        },
        "aliases": ["Ally"],
        "source_files": ["team.md"],
    },
    {
        "id": "organization-acme",
        "type": "Organization",
        "confidence": 0.9,
        "attributes": {
            "name": {"value": "Acme Corp", "confidence": 1.0},
            "industry": {"value": "Tech", "confidence": 0.8},
        },
        "source_files": ["team.md"],
    },
]

EDGES = [
    {
        "id": "edge-001",
        "type": "works_at",
        "from": "person-alice",
        "to": "organization-acme",
        "confidence": 0.96,
        "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
        "source_files": ["team.md"],
    },
]


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    output = tmp_path / "output"
    output.mkdir()
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    (output / "nodes.jsonl").write_text(
        "\n".join(json.dumps(n) for n in NODES), encoding="utf-8"
    )
    (output / "edges.jsonl").write_text(
        "\n".join(json.dumps(e) for e in EDGES), encoding="utf-8"
    )
    (intermediate / "schema.json").write_text(json.dumps(SCHEMA), encoding="utf-8")
    return tmp_path


@pytest.fixture
def qg(session_dir: Path) -> QueryGraph:
    return build_query_graph(session_dir)


class TestBuildQueryGraph:
    def test_indexes_built(self, qg: QueryGraph):
        assert set(qg.nodes_by_id) == {"person-alice", "organization-acme"}
        # name + alias both indexed
        names = {entry[0] for entry in qg.name_index}
        assert "alice" in names
        assert "ally" in names  # alias, lowercased
        assert "acme corp" in names
        # edges_by_node indexed on both endpoints
        assert any(e["id"] == "edge-001" for e in qg.edges_by_node["person-alice"])
        assert any(e["id"] == "edge-001" for e in qg.edges_by_node["organization-acme"])


class TestQueryGraph:
    def test_exact_name_seed_and_format(self, qg: QueryGraph):
        out = query_graph(qg, "Alice", mode="bfs", depth=2)
        assert out.startswith("# Knowledge Graph Context: Alice")
        assert "Seeds: person-alice | Mode: bfs | Depth: 2" in out
        assert "## Nodes" in out
        assert "## Relationships" in out
        assert "- [Person] Alice (person-alice) conf=0.95 (email=alice@acme.com)" in out
        assert "- person-alice --[works_at]--> organization-acme (conf=0.96)" in out

    def test_alias_resolves(self, qg: QueryGraph):
        out = query_graph(qg, "Ally")
        assert "Seeds: person-alice" in out

    def test_no_match(self, qg: QueryGraph):
        out = query_graph(qg, "zzz-nomatch")
        assert out == (
            "No nodes found matching 'zzz-nomatch'. "
            "Try mykg_search_nodes for more flexible search."
        )

    def test_dfs_mode(self, qg: QueryGraph):
        out = query_graph(qg, "Alice", mode="dfs", depth=1)
        assert "Mode: dfs | Depth: 1" in out


def _invoke_mcp_tool(session_dir: Path, question: str, **kwargs) -> str:
    """Invoke the real MCP mykg_query_graph tool via its underlying .fn."""
    from mykg.mcp_server import KnowledgeGraph, mcp

    kg = KnowledgeGraph(session_root=session_dir)
    lifespan_ctx = SimpleNamespace(kg=kg)
    request_ctx = SimpleNamespace(lifespan_context=lifespan_ctx)
    ctx = SimpleNamespace(request_context=request_ctx)

    tool = next(t for t in mcp._tool_manager.list_tools() if t.name == "mykg_query_graph")
    return asyncio.run(tool.fn(question=question, ctx=ctx, **kwargs))


class TestParityWithMCP:
    @pytest.mark.parametrize(
        "question,kwargs",
        [
            ("Alice", {}),
            ("Alice", {"mode": "dfs", "depth": 1}),
            ("Acme", {"depth": 2}),
            ("Ally", {}),
            ("zzz-nomatch", {}),
            ("alice@acme.com", {}),  # attribute-value (score 40) match
            ("Alice", {"token_budget": 1}),  # truncation path
        ],
    )
    def test_terminal_matches_mcp(self, session_dir: Path, question: str, kwargs: dict):
        qg = build_query_graph(session_dir)
        terminal_out = query_graph(qg, question, **kwargs)
        mcp_out = _invoke_mcp_tool(session_dir, question, **kwargs)
        assert terminal_out == mcp_out


class TestQueryCLI:
    def test_query_command(self, session_dir: Path, monkeypatch, tmp_path: Path):
        import mykg.cli as cli_mod
        import mykg.config as cfg_mod

        sessions_root = tmp_path / "sessions"
        (sessions_root / "synth").mkdir(parents=True)
        # move the synthetic session under sessions_root/synth
        import shutil
        shutil.copytree(session_dir / "output", sessions_root / "synth" / "output")
        shutil.copytree(session_dir / "intermediate", sessions_root / "synth" / "intermediate")

        monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))

        runner = CliRunner()
        result = runner.invoke(cli_mod.cli, ["query", "Alice", "--session", "synth"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("# Knowledge Graph Context: Alice")

    def test_query_no_sessions(self, monkeypatch, tmp_path: Path):
        import mykg.cli as cli_mod
        import mykg.config as cfg_mod

        monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "nope"))
        runner = CliRunner()
        result = runner.invoke(cli_mod.cli, ["query", "Alice"])
        assert result.exit_code != 0
        assert "No sessions directory" in result.output
