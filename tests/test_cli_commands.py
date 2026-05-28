from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner


def _output(result) -> str:
    return (result.output or "") + str(result.exception or "")


@pytest.fixture()
def input_dir(tmp_path):
    d = tmp_path / "input"
    d.mkdir()
    (d / "doc.md").write_text("# Test\nSome content.")
    return d


def test_extract_session_and_output_dir_mutually_exclusive(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(cli_mod, "load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        [
            "extract-graph",
            str(input_dir),
            "--session",
            "foo",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "--session" in out or "cannot" in out.lower() or "mutually" in out.lower()


def test_extract_append_and_from_step_mutually_exclusive(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))

    (sessions_root / "2026-01-01T00-00-00").mkdir(parents=True)

    monkeypatch.setattr(cli_mod, "load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr(cli_mod, "run", lambda steps, ctx: None)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        [
            "extract-graph",
            str(input_dir),
            "--session",
            "2026-01-01T00-00-00",
            "--append",
            "--from-step",
            "pass2",
        ],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "mutually exclusive" in out.lower() or "--append" in out or "--from-step" in out


def test_approve_schema_writes_flag(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    intermediate_dir = tmp_path / "intermediate"
    intermediate_dir.mkdir()

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    (intermediate_dir / "schema.json").write_text(json.dumps(schema))

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    from mykg import exporter as exp_mod

    monkeypatch.setattr(
        exp_mod,
        "export_ttl",
        lambda schema, nodes, edges: "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["approve-schema", "--intermediate-dir", str(intermediate_dir)],
    )

    assert result.exit_code == 0, result.output
    assert (intermediate_dir / "schema_approved.flag").exists()


def test_approve_schema_missing_schema_errors(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    empty_dir = tmp_path / "empty_intermediate"
    empty_dir.mkdir()

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["approve-schema", "--intermediate-dir", str(empty_dir)],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "schema.json" in out or "not found" in out.lower() or "error" in out.lower()


def test_extract_creates_session_dir(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))
    monkeypatch.setattr(cli_mod, "run", lambda steps, ctx: None)
    monkeypatch.setattr(cli_mod, "load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir)])

    assert result.exit_code == 0, result.output
    subdirs = list(sessions_root.iterdir())
    assert len(subdirs) >= 1
    assert any((d / "intermediate").is_dir() for d in subdirs)


def test_extract_graph_help_contains_obsidian_vault():
    """--help output for extract-graph must advertise --obsidian-vault."""
    import mykg.cli as cli_mod
    from click.testing import CliRunner

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", "--help"])
    assert result.exit_code == 0
    assert "--obsidian-vault" in result.output


def test_from_step_without_session_or_dirs_errors(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(cli_mod, "load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--from-step", "pass2"],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "--session" in out or "session" in out.lower() or "--from-step" in out
