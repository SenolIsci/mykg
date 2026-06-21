"""CLI validation tests for --append-with-grow-schema (Unit 1 / D52).

These exercise the early validation gates only — they never reach an LLM call.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from mykg.cli import cli


def test_grow_schema_help_lists_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["extract-graph", "--help"])
    assert result.exit_code == 0
    assert "--append-with-grow-schema" in result.output


def test_grow_schema_implies_append(tmp_path):
    """--append-with-grow-schema without explicit --append must still work
    (the flag implies --append). This test only checks that the 'requires
    --append' error does NOT fire — it will fail later when no session schema
    exists, which is the expected next gate."""
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    result = runner.invoke(
        cli,
        ["extract-graph", str(input_dir), "--append-with-grow-schema"],
        catch_exceptions=True,
    )
    # Must NOT fail with "requires --append"
    assert "requires --append" not in (result.output or "")


def test_grow_schema_excludes_explicit_base_schema(tmp_path, monkeypatch):
    """--append-with-grow-schema must reject an explicit --base-schema (it auto-loads the session)."""
    runner = CliRunner()
    sessions = tmp_path / "mykg_sessions"
    session = sessions / "s1"
    (session / "intermediate").mkdir(parents=True)
    (session / "input").mkdir()
    (session / "intermediate" / "schema.json").write_text("{}")
    monkeypatch.setattr("mykg.cli._sessions_root", lambda: sessions)

    base_ttl = tmp_path / "base.ttl"
    base_ttl.write_text("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")

    src = tmp_path / "src"
    src.mkdir()
    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(src),
            "--append-with-grow-schema",
            "--session",
            "s1",
            "--base-schema",
            str(base_ttl),
        ],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "base-schema" in result.output.lower()


def test_grow_schema_errors_when_session_schema_ttl_missing(tmp_path, monkeypatch):
    """--append-with-grow-schema must fail clearly if the session has no schema.ttl to lock."""
    runner = CliRunner()
    sessions = tmp_path / "mykg_sessions"
    session = sessions / "s1"
    (session / "intermediate").mkdir(parents=True)
    (session / "input").mkdir()
    (session / "intermediate" / "schema.json").write_text("{}")
    monkeypatch.setattr("mykg.cli._sessions_root", lambda: sessions)

    src = tmp_path / "src"
    src.mkdir()
    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(src),
            "--append-with-grow-schema",
            "--session",
            "s1",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    assert "schema.ttl" in result.output


def test_grow_schema_and_from_step_mutually_exclusive(tmp_path):
    """--append-with-grow-schema inherits append's mutual exclusion with --from-step."""
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(input_dir),
            "--append-with-grow-schema",
            "--from-step",
            "pass2",
        ],
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


if __name__ == "__main__":
    pytest.main([str(Path(__file__))])
