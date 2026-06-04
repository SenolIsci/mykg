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
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

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

    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)

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
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir)])

    assert result.exit_code == 0, result.output
    subdirs = list(sessions_root.iterdir())
    assert len(subdirs) >= 1
    assert any((d / "intermediate").is_dir() for d in subdirs)


def test_extract_graph_help_contains_obsidian_vault():
    """--help output for extract-graph must advertise --obsidian-vault."""
    from click.testing import CliRunner

    import mykg.cli as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", "--help"])
    assert result.exit_code == 0
    assert "--obsidian-vault" in result.output


def test_extract_graph_help_contains_neo4j_csv():
    """--help output for extract-graph must advertise --neo4j-csv."""
    from click.testing import CliRunner

    import mykg.cli as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", "--help"])
    assert result.exit_code == 0
    assert "--neo4j-csv" in result.output


def test_from_step_without_session_or_dirs_errors(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--from-step", "pass2"],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "--session" in out or "session" in out.lower() or "--from-step" in out


# ---------------------------------------------------------------------------
# Extended Unit 3 coverage
# ---------------------------------------------------------------------------


def test_extract_obsidian_vault_flag_mutates_config(tmp_path, input_dir, monkeypatch):
    """--obsidian-vault flag flips mykg.config.OBSIDIAN_ENABLED to True."""
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(cfg_mod, "OBSIDIAN_ENABLED", False)
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli, ["extract-graph", str(input_dir), "--obsidian-vault"]
    )

    assert result.exit_code == 0, result.output
    assert cfg_mod.OBSIDIAN_ENABLED is True


def test_extract_neo4j_csv_flag_mutates_config(tmp_path, input_dir, monkeypatch):
    """--neo4j-csv flag flips mykg.config.NEO4J_CSV_ENABLED to True."""
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr(cfg_mod, "NEO4J_CSV_ENABLED", False)
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir), "--neo4j-csv"])

    assert result.exit_code == 0, result.output
    assert cfg_mod.NEO4J_CSV_ENABLED is True


def test_extract_base_schema_argument(tmp_path, input_dir, monkeypatch):
    """--base-schema parses the TTL file and feeds it into PipelineContext."""
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr(
        "mykg.base_schema.parse_base_schema",
        lambda content: {"concepts": [], "properties": []},
    )

    base_ttl = tmp_path / "base.ttl"
    base_ttl.write_text("# fake ttl\n")

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--base-schema", str(base_ttl)],
    )

    assert result.exit_code == 0, result.output


def test_extract_thesaurus_argument(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr(
        "mykg.thesaurus.parse_thesaurus",
        lambda content, source=None: {"terms": []},
    )

    thes = tmp_path / "thes.ttl"
    thes.write_text("@prefix skos: <http://www.w3.org/2004/02/skos/core#> .\n")

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--thesaurus", str(thes)],
    )

    assert result.exit_code == 0, result.output


def test_resolve_from_step_aliases():
    from mykg.cli import _resolve_from_step

    assert _resolve_from_step("orphan_connect_fullsweep") == ("orphan_connect", False)
    assert _resolve_from_step("orphan_connect_incremental") == ("orphan_connect", True)
    assert _resolve_from_step("pass2") == ("pass2", False)


def test_delete_from_step_unknown_step_raises(tmp_path):
    """Unknown step name -> ClickException."""
    import click

    from mykg.cli import _delete_from_step

    with pytest.raises(click.ClickException) as exc_info:
        _delete_from_step("does_not_exist", tmp_path, tmp_path)
    assert "Unknown step" in str(exc_info.value.message)


def test_delete_from_step_pass2_clears_shards(tmp_path):
    """Re-running from pass2 must wipe shard directories."""
    from mykg.cli import _delete_from_step

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()

    # Create shard dirs and a concat_map
    for shard_name in ("raw_extractions_shards", "chunk_index_shards"):
        d = intermediate / shard_name
        d.mkdir()
        (d / "foo.json").write_text("{}")
    (intermediate / "pass2_concat_map.json").write_text("{}")

    _delete_from_step("pass2", intermediate, output)

    assert not (intermediate / "raw_extractions_shards").exists()
    assert not (intermediate / "chunk_index_shards").exists()
    assert not (intermediate / "pass2_concat_map.json").exists()


def test_delete_from_step_validate_graph_clears_obsidian(tmp_path, monkeypatch):
    """Re-running from validate_graph deletes obsidian_vault directory."""
    import mykg.config as cfg_mod

    from mykg.cli import _delete_from_step

    monkeypatch.setattr(cfg_mod, "OBSIDIAN_VAULT_DIR", "obsidian_vault")

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()

    obs = output / "obsidian_vault"
    obs.mkdir()
    (obs / "Person.md").write_text("test")

    _delete_from_step("validate_graph", intermediate, output)

    assert not obs.exists()


def test_delete_from_step_after_human_review_clears_approval_flag(tmp_path):
    """Stepping from a step after human_review wipes the approval flag."""
    from mykg.cli import _delete_from_step

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()

    (intermediate / "schema_approved.flag").write_text("approved")

    _delete_from_step("schema_flatten", intermediate, output)

    assert not (intermediate / "schema_approved.flag").exists()


def test_delete_from_step_orphan_connect_incremental_preserves_files(tmp_path):
    """Incremental sweep preserves orphan_connections.json and orphan_log.json."""
    from mykg.cli import _delete_from_step

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()

    (intermediate / "orphan_connections.json").write_text("{}")
    (intermediate / "orphan_log.json").write_text("[]")

    _delete_from_step("orphan_connect", intermediate, output, incremental=True)

    # Both files must be preserved (incremental sweep).
    assert (intermediate / "orphan_connections.json").exists()
    assert (intermediate / "orphan_log.json").exists()


def test_delete_merge_from_step_unknown_raises(tmp_path):
    import click

    from mykg.cli import _delete_merge_from_step

    with pytest.raises(click.ClickException) as exc:
        _delete_merge_from_step("does_not_exist", tmp_path, tmp_path)
    assert "Unknown merge step" in str(exc.value.message)


def test_delete_merge_from_step_clears_shards(tmp_path):
    from mykg.cli import _delete_merge_from_step

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()

    for shard_name in ("raw_extractions_shards", "chunk_index_shards"):
        d = intermediate / shard_name
        d.mkdir()
        (d / "foo.json").write_text("{}")

    _delete_merge_from_step("merge_reextract", intermediate, output)

    assert not (intermediate / "raw_extractions_shards").exists()
    assert not (intermediate / "chunk_index_shards").exists()


def test_delete_merge_from_step_clears_flag(tmp_path):
    from mykg.cli import _delete_merge_from_step

    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir()
    output.mkdir()
    (intermediate / "schema_approved.flag").write_text("approved")

    _delete_merge_from_step("schema_flatten", intermediate, output)

    assert not (intermediate / "schema_approved.flag").exists()


def test_merge_graphs_self_merge_errors(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["merge-graphs", "session-a", "session-a"],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "Cannot merge a session with itself" in out


def test_merge_graphs_missing_session_errors(tmp_path, monkeypatch):
    """Two distinct session names, but they don't exist on disk -> sys.exit(1)."""
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["merge-graphs", "session-a", "session-b"],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "not found" in out


def test_walkthrough_cmd_missing_session(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["walkthrough", "--session", "does-not-exist"],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "Session not found" in out or "not found" in out


def test_parse_docs_subcommand_mineru_success(tmp_path, monkeypatch):
    """parse-docs invokes ephemeral_mineru_venv + subprocess.run cleanly."""
    import subprocess
    from contextlib import contextmanager

    import mykg.cli as cli_mod

    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_text("fake pdf")
    out_dir = tmp_path / "out"

    @contextmanager
    def fake_venv(*a, **kw):
        yield tmp_path / "fake_mineru"

    monkeypatch.setattr("mykg.uv_venv.ephemeral_mineru_venv", fake_venv)

    captured = {}

    class FakeProc:
        returncode = 0

    def fake_run(cmd, check=False, timeout=None):
        captured["cmd"] = cmd
        return FakeProc()

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["parse-docs", "--input", str(input_dir), "--output", str(out_dir)],
    )

    assert result.exit_code == 0, result.output
    assert "Done" in result.output
    assert "-p" in captured["cmd"]


def test_parse_docs_subcommand_timeout(tmp_path, monkeypatch):
    import subprocess
    from contextlib import contextmanager

    import mykg.cli as cli_mod

    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_text("fake")
    out_dir = tmp_path / "out"

    @contextmanager
    def fake_venv(*a, **kw):
        yield tmp_path / "fake_mineru"

    monkeypatch.setattr("mykg.uv_venv.ephemeral_mineru_venv", fake_venv)

    def fake_run(cmd, check=False, timeout=None):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(subprocess, "run", fake_run)

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["parse-docs", "--input", str(input_dir), "--output", str(out_dir)],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "timed out" in out


def test_parse_docs_subcommand_nonzero_exit(tmp_path, monkeypatch):
    import subprocess
    from contextlib import contextmanager

    import mykg.cli as cli_mod

    input_dir = tmp_path / "in"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_text("fake")
    out_dir = tmp_path / "out"

    @contextmanager
    def fake_venv(*a, **kw):
        yield tmp_path / "fake_mineru"

    monkeypatch.setattr("mykg.uv_venv.ephemeral_mineru_venv", fake_venv)

    class FakeProc:
        returncode = 17

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: FakeProc())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["parse-docs", "--input", str(input_dir), "--output", str(out_dir)],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "exited with code 17" in out


def test_main_invokes_cli(monkeypatch):
    """mykg.cli.main() is the entry point used by the `mykg` console script."""
    called = {}

    def fake_cli(*a, **kw):
        called["yes"] = True

    monkeypatch.setattr("mykg.cli.cli", fake_cli)

    from mykg.cli import main

    main()
    assert called.get("yes") is True


def test_approve_schema_session_and_intermediate_dir_mutex(tmp_path, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        [
            "approve-schema",
            "--session",
            "foo",
            "--intermediate-dir",
            str(tmp_path / "intermediate"),
        ],
    )

    assert result.exit_code != 0
    out = _output(result)
    assert "cannot be combined" in out
