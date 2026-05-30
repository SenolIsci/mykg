"""Tests for the session-based run folder feature (Unit 3 + Unit 5).

Covers:
- _make_session_dirs creates the three subdirectories (output, intermediate, input)
- _make_session_dirs returns a timestamp-shaped name
- _copy_input_files copies flat files (not subdirs)
- extract --help shows --session option
- extract with no flags auto-creates session and echoes name
- extract --session existing-name uses its dirs
- extract --session nonexistent raises error
- extract --session + --output-dir raises error
- input files are refreshed when --session is provided
- _resolve_from_step alias handling
- _delete_from_step file/directory removal logic
- _delete_merge_from_step file/directory removal logic
- merge-graphs CLI command validation and session creation
- approve-schema CLI command via --session option
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def input_dir(tmp_path):
    """A minimal input directory with one Markdown file."""
    d = tmp_path / "input"
    d.mkdir()
    return d


@pytest.fixture()
def dirs(tmp_path):
    """Returns (intermediate_dir, output_dir) pair, both pre-created."""
    inter = tmp_path / "intermediate"
    out = tmp_path / "output"
    inter.mkdir()
    out.mkdir()
    return inter, out


@pytest.fixture()
def sessions_root(tmp_path, monkeypatch):
    """Creates a sessions root dir and patches SESSIONS_DIR to point at it."""
    import mykg.config as cfg_mod

    root = tmp_path / "sessions"
    root.mkdir(parents=True)
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(root))
    return root


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_SHARD_DIRS = ("raw_extractions_shards", "chunk_index_shards")


def _populate_step_files(
    steps, intermediate_dir: Path, output_dir: Path, *, extras: list[str] | None = None
) -> None:
    """Write a placeholder file for every step output, create shard dirs, and write the approval flag.

    extras: additional filenames written into intermediate_dir (e.g. pass2_concat_map.json).
    """
    for step in steps:
        base = output_dir if step.output_location == "output" else intermediate_dir
        for fname in step.outputs:
            (base / fname).write_text("placeholder")

    for name in _SHARD_DIRS:
        d = intermediate_dir / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "dummy.json").write_text("{}")

    (intermediate_dir / "schema_approved.flag").write_text("approved")

    for fname in extras or []:
        (intermediate_dir / fname).write_text("{}")


def _make_step_files(intermediate_dir: Path, output_dir: Path) -> None:
    """Populate all extract-pipeline step outputs."""
    from mykg.pipeline import STEPS

    _populate_step_files(STEPS, intermediate_dir, output_dir, extras=["pass2_concat_map.json"])


def _make_merge_step_files(intermediate_dir: Path, output_dir: Path) -> None:
    """Populate all merge-pipeline step outputs."""
    from mykg.merge_pipeline import MERGE_STEPS

    _populate_step_files(MERGE_STEPS, intermediate_dir, output_dir)


def _minimal_schema() -> dict:
    return {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }


# ---------------------------------------------------------------------------
# 1. _make_session_dirs creates the three subdirs
# ---------------------------------------------------------------------------


def test_make_session_dirs_creates_subdirs(tmp_path):
    from mykg.cli import _make_session_dirs

    name, out, inter = _make_session_dirs(tmp_path)

    assert (tmp_path / name / "output").is_dir()
    assert (tmp_path / name / "intermediate").is_dir()
    assert (tmp_path / name / "input").is_dir()
    assert out == tmp_path / name / "output"
    assert inter == tmp_path / name / "intermediate"


# ---------------------------------------------------------------------------
# 2. _make_session_dirs name is timestamp-shaped
# ---------------------------------------------------------------------------


def test_make_session_dirs_timestamp_format(tmp_path):
    from mykg.cli import _make_session_dirs

    name, _, _ = _make_session_dirs(tmp_path)

    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}$", name)


# ---------------------------------------------------------------------------
# 3. _copy_input_files copies every file (md and non-md, recursively)
# ---------------------------------------------------------------------------


def test_copy_input_files_copies_flat(tmp_path):
    from mykg.cli import _copy_input_files

    src = tmp_path / "src"
    src.mkdir()
    (src / "a.md").write_text("hello")
    (src / "b.md").write_text("world")
    (src / "subdir").mkdir()

    session = tmp_path / "sess"
    _copy_input_files(src, session)

    assert (session / "input" / "a.md").read_text() == "hello"
    assert (session / "input" / "b.md").read_text() == "world"
    # Empty subdirs are not recreated (rglob skips them because is_file() is false).
    assert not (session / "input" / "subdir").exists()


def test_copy_input_files_includes_non_md_and_subdirs(tmp_path):
    """Regression: non-md files (PDFs, DOCX, …) must reach the session so the
    optional preprocess step can convert them via MinerU. Earlier behavior
    filtered to *.md and silently dropped everything else."""
    from mykg.cli import _copy_input_files

    src = tmp_path / "src"
    src.mkdir()
    (src / "notes.md").write_text("# notes")
    (src / "paper.pdf").write_bytes(b"%PDF-1.4 fake")
    nested = src / "dir1"
    nested.mkdir()
    (nested / "deep.pdf").write_bytes(b"%PDF-1.4 fake nested")
    (nested / "deep.md").write_text("# deep")

    session = tmp_path / "sess"
    _copy_input_files(src, session)

    assert (session / "input" / "notes.md").read_text() == "# notes"
    assert (session / "input" / "paper.pdf").read_bytes() == b"%PDF-1.4 fake"
    assert (session / "input" / "dir1" / "deep.pdf").read_bytes() == b"%PDF-1.4 fake nested"
    assert (session / "input" / "dir1" / "deep.md").read_text() == "# deep"


# ---------------------------------------------------------------------------
# 4. extract --help shows --session option
# ---------------------------------------------------------------------------


def test_extract_help_shows_session():
    from mykg.cli import cli

    runner = CliRunner()
    result = runner.invoke(cli, ["extract-graph", "--help"])

    assert "--session" in result.output


# ---------------------------------------------------------------------------
# 5. extract with no flags auto-creates session and echoes name
# ---------------------------------------------------------------------------


def test_extract_auto_creates_session(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    (input_dir / "doc.md").write_text("test")

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir)])

    assert result.exit_code == 0, result.output

    sessions = list((tmp_path / "sessions").iterdir())
    assert len(sessions) == 1

    sess = sessions[0]
    assert (sess / "intermediate").is_dir()
    assert (sess / "output").is_dir()
    assert (sess / "input" / "doc.md").exists()
    assert sess.name in result.output  # session name echoed to stdout
    assert (sess / "run.log").exists()  # log auto-placed in session folder


# ---------------------------------------------------------------------------
# 5b. extract with relative --log-file routes it into session folder
# ---------------------------------------------------------------------------


def test_extract_log_file_placed_in_session(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    (input_dir / "doc.md").write_text("test")

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir), "--log-file", "run.log"])

    assert result.exit_code == 0, result.output
    sess = list((tmp_path / "sessions").iterdir())[0]
    assert (sess / "run.log").exists()
    # log must NOT have been created in cwd
    assert not (tmp_path / "run.log").exists()


# ---------------------------------------------------------------------------
# 6. extract --session existing-name uses its dirs
# ---------------------------------------------------------------------------


def test_extract_session_uses_existing_dirs(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))

    sess = sessions_root / "2026-01-01T00-00-00"
    (sess / "intermediate").mkdir(parents=True)
    (sess / "output").mkdir(parents=True)

    captured = {}

    def fake_run(steps, ctx):
        captured["output_dir"] = ctx.output_dir
        captured["intermediate_dir"] = ctx.intermediate_dir

    monkeypatch.setattr("mykg.orchestrator.run", fake_run)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--session", "2026-01-01T00-00-00"],
    )

    assert result.exit_code == 0, result.output
    assert captured["output_dir"] == sess / "output"
    assert captured["intermediate_dir"] == sess / "intermediate"


# ---------------------------------------------------------------------------
# 7. extract --session nonexistent raises error
# ---------------------------------------------------------------------------


def test_extract_session_nonexistent_raises(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(tmp_path / "sessions"))
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["extract-graph", str(input_dir), "--session", "ghost"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "error" in result.output.lower()


# ---------------------------------------------------------------------------
# 8. extract --session + --output-dir raises error
# ---------------------------------------------------------------------------


def test_extract_session_with_output_dir_raises(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))

    sess = sessions_root / "existing"
    (sess / "intermediate").mkdir(parents=True)
    (sess / "output").mkdir(parents=True)

    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        [
            "extract-graph",
            str(input_dir),
            "--session",
            "existing",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# 9. input files are refreshed when --session is provided
# ---------------------------------------------------------------------------


def test_extract_session_refreshes_input_copy(tmp_path, input_dir, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.config as cfg_mod

    sessions_root = tmp_path / "sessions"
    monkeypatch.setattr(cfg_mod, "SESSIONS_DIR", str(sessions_root))

    sess = sessions_root / "2026-01-01T00-00-00"
    (sess / "intermediate").mkdir(parents=True)
    (sess / "output").mkdir(parents=True)
    (sess / "input").mkdir(parents=True)

    monkeypatch.setattr("mykg.orchestrator.run", lambda steps, ctx: None)
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())

    (input_dir / "new_doc.md").write_text("new content")

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["extract-graph", str(input_dir), "--session", "2026-01-01T00-00-00"],
    )

    assert result.exit_code == 0, result.output
    assert (sess / "input" / "new_doc.md").exists()


# ===========================================================================
# Unit 5 — _resolve_from_step
# ===========================================================================


def test_resolve_from_step_fullsweep_alias():
    from mykg.cli import _resolve_from_step

    step, incremental = _resolve_from_step("orphan_connect_fullsweep")
    assert step == "orphan_connect"
    assert incremental is False


def test_resolve_from_step_incremental_alias():
    from mykg.cli import _resolve_from_step

    step, incremental = _resolve_from_step("orphan_connect_incremental")
    assert step == "orphan_connect"
    assert incremental is True


def test_resolve_from_step_plain_step_name_unchanged():
    from mykg.cli import _resolve_from_step

    step, incremental = _resolve_from_step("pass2")
    assert step == "pass2"
    assert incremental is False


def test_resolve_from_step_unknown_name_passthrough():
    from mykg.cli import _resolve_from_step

    step, incremental = _resolve_from_step("totally_made_up_step")
    assert step == "totally_made_up_step"
    assert incremental is False


# ===========================================================================
# Unit 5 — _delete_from_step
# ===========================================================================


def test_delete_from_step_incremental_preserves_orphan_connections(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    _delete_from_step("orphan_connect", inter, out, incremental=True)

    assert (inter / "orphan_connections.json").exists()
    assert (inter / "orphan_log.json").exists()


def test_delete_from_step_non_incremental_deletes_orphan_connections(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    _delete_from_step("orphan_connect", inter, out, incremental=False)

    assert not (inter / "orphan_connections.json").exists()
    assert not (inter / "orphan_log.json").exists()


def test_delete_from_step_clears_shard_dirs_when_at_or_before_pass2(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    _delete_from_step("pass2", inter, out)

    assert not (inter / "raw_extractions_shards").exists()
    assert not (inter / "chunk_index_shards").exists()


def test_delete_from_step_does_not_clear_shards_when_after_pass2(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    # assemble is after pass2 — shards must survive
    _delete_from_step("assemble", inter, out)

    assert (inter / "raw_extractions_shards").exists()
    assert (inter / "chunk_index_shards").exists()


def test_delete_from_step_removes_concat_map_at_pass2(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    _delete_from_step("pass2", inter, out)

    assert not (inter / "pass2_concat_map.json").exists()


def test_delete_from_step_invalid_step_raises_clickexception(dirs):
    import click

    from mykg.cli import _delete_from_step

    inter, out = dirs

    with pytest.raises(click.ClickException, match="Unknown step"):
        _delete_from_step("nonexistent_step", inter, out)


def test_delete_from_step_deletes_approval_flag_at_human_review(dirs):
    from mykg.cli import _delete_from_step

    inter, out = dirs
    _make_step_files(inter, out)

    # schema_flatten comes after human_review — flag must be deleted
    _delete_from_step("schema_flatten", inter, out)

    assert not (inter / "schema_approved.flag").exists()


# ===========================================================================
# Unit 5 — _delete_merge_from_step
# ===========================================================================


def test_delete_merge_from_step_deletes_outputs_from_step_onward(dirs):
    from mykg.cli import _delete_merge_from_step

    inter, out = dirs
    _make_merge_step_files(inter, out)

    _delete_merge_from_step("assemble", inter, out)

    assert not (inter / "edge_metadata.json").exists()
    assert not (inter / "nodes.json").exists()
    assert not (inter / "merge_log.json").exists()
    # Steps before assemble must be untouched
    assert (inter / "schema.json").exists()


def test_delete_merge_from_step_clears_shard_dirs_at_reextract(dirs):
    from mykg.cli import _delete_merge_from_step

    inter, out = dirs
    _make_merge_step_files(inter, out)

    _delete_merge_from_step("merge_reextract", inter, out)

    assert not (inter / "raw_extractions_shards").exists()
    assert not (inter / "chunk_index_shards").exists()


def test_delete_merge_from_step_invalid_step_raises_clickexception(dirs):
    import click

    from mykg.cli import _delete_merge_from_step

    inter, out = dirs

    with pytest.raises(click.ClickException, match="Unknown merge step"):
        _delete_merge_from_step("nonexistent_merge_step", inter, out)


def test_delete_merge_from_step_removes_approval_flag_at_human_review(dirs):
    from mykg.cli import _delete_merge_from_step

    inter, out = dirs
    _make_merge_step_files(inter, out)

    # schema_flatten comes after human_review in merge pipeline — flag must be removed
    _delete_merge_from_step("schema_flatten", inter, out)

    assert not (inter / "schema_approved.flag").exists()


# ===========================================================================
# Unit 5 — merge-graphs CLI command
# ===========================================================================


def test_merge_graphs_same_session_name_errors(sessions_root, monkeypatch):
    import mykg.cli as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["merge-graphs", "sess-a", "sess-a"])

    assert result.exit_code != 0
    assert "Cannot merge a session with itself" in result.output or "itself" in result.output


def test_merge_graphs_session_a_not_found_errors(sessions_root, monkeypatch):
    import mykg.cli as cli_mod

    (sessions_root / "sess-b").mkdir()

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["merge-graphs", "sess-a", "sess-b"])

    assert result.exit_code != 0
    assert "sess-a" in (result.output + str(result.exception or ""))


def test_merge_graphs_session_b_not_found_errors(sessions_root, monkeypatch):
    import mykg.cli as cli_mod

    (sessions_root / "sess-a").mkdir()

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["merge-graphs", "sess-a", "sess-b"])

    assert result.exit_code != 0
    assert "sess-b" in (result.output + str(result.exception or ""))


def test_merge_graphs_from_step_without_output_session_errors(sessions_root, monkeypatch):
    import mykg.cli as cli_mod

    (sessions_root / "sess-a").mkdir()
    (sessions_root / "sess-b").mkdir()

    runner = CliRunner()
    result = runner.invoke(
        cli_mod.cli,
        ["merge-graphs", "sess-a", "sess-b", "--from-step", "assemble"],
    )

    assert result.exit_code != 0
    assert "--output-session" in result.output or "output-session" in result.output


def test_merge_graphs_creates_merged_session_folder(sessions_root, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.merge_orchestrator as merge_orch_mod

    (sessions_root / "sess-a").mkdir()
    (sessions_root / "sess-b").mkdir()

    fake_run_merge = MagicMock()
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr(merge_orch_mod, "run_merge_graphs", fake_run_merge)

    runner = CliRunner()
    runner.invoke(cli_mod.cli, ["merge-graphs", "sess-a", "sess-b"])

    assert fake_run_merge.called


def test_merge_graphs_with_named_output_session(sessions_root, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.merge_orchestrator as merge_orch_mod

    (sessions_root / "sess-a").mkdir()
    (sessions_root / "sess-b").mkdir()

    fake_run_merge = MagicMock()
    monkeypatch.setattr("mykg.llm.config.load_adapter", lambda **kw: MagicMock())
    monkeypatch.setattr(merge_orch_mod, "run_merge_graphs", fake_run_merge)

    runner = CliRunner()
    runner.invoke(
        cli_mod.cli,
        ["merge-graphs", "sess-a", "sess-b", "--output-session", "merged-result"],
    )

    assert (sessions_root / "merged-result").exists()


# ===========================================================================
# Unit 5 — approve-schema CLI command via --session
# ===========================================================================


def test_approve_schema_via_session_option(sessions_root, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.exporter as exp_mod

    inter = sessions_root / "my-session" / "intermediate"
    inter.mkdir(parents=True)
    (inter / "schema.json").write_text(json.dumps(_minimal_schema()))
    monkeypatch.setattr(
        exp_mod,
        "export_ttl",
        lambda s, nodes, edges: "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["approve-schema", "--session", "my-session"])

    assert result.exit_code == 0, result.output
    assert (inter / "schema_approved.flag").exists()


def test_approve_schema_generates_ttl_and_flag(sessions_root, monkeypatch):
    import mykg.cli as cli_mod
    import mykg.exporter as exp_mod

    inter = sessions_root / "gen-session" / "intermediate"
    inter.mkdir(parents=True)
    (inter / "schema.json").write_text(json.dumps(_minimal_schema()))
    monkeypatch.setattr(
        exp_mod,
        "export_ttl",
        lambda s, nodes, edges: "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n",
    )

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["approve-schema", "--session", "gen-session"])

    assert result.exit_code == 0, result.output
    assert (inter / "schema.ttl").exists()
    assert (inter / "schema.ttl").read_text().startswith("@prefix")
    assert (inter / "schema_approved.flag").read_text() == "approved"


def test_approve_schema_session_not_found_errors(sessions_root, monkeypatch):
    import mykg.cli as cli_mod

    runner = CliRunner()
    result = runner.invoke(cli_mod.cli, ["approve-schema", "--session", "ghost-session"])

    assert result.exit_code != 0
    out = (result.output or "") + str(result.exception or "")
    assert "schema.json" in out or "not found" in out.lower() or "error" in out.lower()
