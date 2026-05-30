from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import cli


def _output(result) -> str:
    return (result.output or "") + str(result.exception or "")


def test_parse_docs_missing_mineru(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    runner = CliRunner()
    with patch("mykg.cli._resolve_mineru", return_value=None):
        result = runner.invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )
    assert result.exit_code != 0
    out = _output(result).lower()
    assert "mineru" in out
    assert "mykg[mineru]" in out


def test_parse_docs_builds_command(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    runner = CliRunner()
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.cli._resolve_mineru", return_value="/usr/bin/mineru"),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )
    assert result.exit_code == 0, _output(result)
    assert captured["cmd"][0] == "/usr/bin/mineru"
    assert captured["cmd"][1] == "-p"
    assert "-i" in captured["cmd"]
    assert "-o" in captured["cmd"]
    assert str(input_dir) in captured["cmd"]
    assert str(output_dir) in captured["cmd"]
    assert output_dir.exists()


def test_parse_docs_pass_through_args(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    runner = CliRunner()
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.cli._resolve_mineru", return_value="/usr/bin/mineru"),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            cli,
            [
                "parse-docs",
                "--input",
                str(input_dir),
                "--output",
                str(output_dir),
                "--backend",
                "pipeline",
            ],
        )
    assert result.exit_code == 0, _output(result)
    assert captured["cmd"][-2:] == ["--backend", "pipeline"]


def test_parse_docs_nonzero_exit(tmp_path: Path) -> None:
    input_dir = tmp_path / "in"
    input_dir.mkdir()
    output_dir = tmp_path / "out"
    runner = CliRunner()

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2)

    with (
        patch("mykg.cli._resolve_mineru", return_value="/usr/bin/mineru"),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = runner.invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )
    assert result.exit_code != 0
    assert "2" in _output(result)


def test_resolve_mineru_prefers_venv_companion(tmp_path: Path) -> None:
    """_resolve_mineru must find mineru next to sys.executable even when PATH
    does not include the venv bin dir (the case for an unactivated venv that
    a parent process invokes by absolute path)."""
    from mykg.cli import _resolve_mineru

    fake_venv_bin = tmp_path / "bin"
    fake_venv_bin.mkdir()
    fake_python = fake_venv_bin / "python"
    fake_python.write_text("#!/bin/sh\nexec /usr/bin/env python3 \"$@\"\n")
    fake_mineru = fake_venv_bin / "mineru"
    fake_mineru.write_text("#!/bin/sh\necho fake\n")

    # Patch sys.executable so _resolve_mineru looks in our fake venv;
    # patch shutil.which to None so the PATH fallback can't accidentally hit
    # a real mineru on the dev box.
    with (
        patch("mykg.cli.sys.executable", str(fake_python)),
        patch("mykg.cli.shutil.which", return_value=None),
    ):
        resolved = _resolve_mineru()

    assert resolved == str(fake_mineru)


def test_resolve_mineru_falls_back_to_path(tmp_path: Path) -> None:
    """When no venv companion exists, _resolve_mineru must fall back to
    shutil.which so a globally-installed mineru is still discovered."""
    from mykg.cli import _resolve_mineru

    fake_venv_bin = tmp_path / "bin"
    fake_venv_bin.mkdir()
    fake_python = fake_venv_bin / "python"
    fake_python.write_text("#!/bin/sh\nexec /usr/bin/env python3 \"$@\"\n")
    # Note: NO mineru next to python.

    with (
        patch("mykg.cli.sys.executable", str(fake_python)),
        patch("mykg.cli.shutil.which", return_value="/usr/local/bin/mineru"),
    ):
        resolved = _resolve_mineru()

    assert resolved == "/usr/local/bin/mineru"
