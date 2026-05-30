from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from mykg.uv_venv import ephemeral_mineru_venv


def _fake_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def test_ephemeral_venv_runs_uv_venv_then_install_then_yields_bin(tmp_path: Path) -> None:
    """Happy path: uv venv → uv pip install → yield <venv>/bin/mineru → cleanup."""
    calls: list[list[str]] = []
    yielded_paths: list[Path] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        # Simulate `uv venv` creating the venv tree so the post-install
        # mineru-binary existence check passes.
        if "venv" in cmd and "pip" not in cmd:
            venv_dir = Path(cmd[-1])
            bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
            bin_dir.mkdir(parents=True, exist_ok=True)
            (bin_dir / "python").write_text("")
            (bin_dir / "mineru").write_text("")
        return _fake_proc(0)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
    ):
        with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60) as mineru_bin:
            yielded_paths.append(mineru_bin)
            assert mineru_bin.exists()

    # Two subprocess calls: venv create, then install.
    assert len(calls) == 2
    assert calls[0][:3] == ["/fake/uv", "venv", "--python"]
    assert calls[0][3] == "3.12"
    assert calls[1][:3] == ["/fake/uv", "pip", "install"]
    assert "mineru[all]" in calls[1]
    assert "-U" in calls[1]

    # TemporaryDirectory cleaned up the venv tree on context exit.
    assert not yielded_paths[0].exists()
    assert not yielded_paths[0].parent.parent.exists()


def test_ephemeral_venv_cleans_up_on_exception() -> None:
    """If the with-body raises, the venv tree is still deleted."""
    captured: dict[str, Path] = {}

    def fake_run(cmd, **kwargs):
        if "venv" in cmd and "pip" not in cmd:
            venv_dir = Path(cmd[-1])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").write_text("")
            (venv_dir / "bin" / "mineru").write_text("")
        return _fake_proc(0)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60) as mineru_bin:
                captured["bin"] = mineru_bin
                raise RuntimeError("boom")

    assert not captured["bin"].exists()


def test_ephemeral_venv_install_failure_raises_with_stderr() -> None:
    """A non-zero `uv pip install` exit produces a RuntimeError carrying stderr."""

    def fake_run(cmd, **kwargs):
        if "pip" in cmd:
            return _fake_proc(1, stderr="resolver could not satisfy mineru[all]")
        if "venv" in cmd:
            venv_dir = Path(cmd[-1])
            (venv_dir / "bin").mkdir(parents=True, exist_ok=True)
            (venv_dir / "bin" / "python").write_text("")
        return _fake_proc(0)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
    ):
        with pytest.raises(RuntimeError, match="resolver could not satisfy"):
            with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60):
                pytest.fail("should not enter body when install fails")


def test_ephemeral_venv_uv_missing_raises_actionable_error() -> None:
    """If `uv` isn't on PATH, fail before creating any tempdir."""
    with patch("mykg.uv_venv.shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="uv not found"):
            with ephemeral_mineru_venv("3.12", "mineru[all]", "uv", 60):
                pytest.fail("should not enter body when uv is missing")


def _route_uv_and_mineru(captured_mineru_cmd: dict, mineru_returncode: int = 0):
    """Build a fake subprocess.run that satisfies uv venv/install and lets the
    test inspect the mineru command. Stores the mineru cmd in captured_mineru_cmd['cmd']."""

    def fake_run(cmd, **kwargs):
        head = Path(cmd[0]).name
        if head == "uv":
            if "venv" in cmd and "pip" not in cmd:
                venv_dir = Path(cmd[-1])
                bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
                bin_dir.mkdir(parents=True, exist_ok=True)
                (bin_dir / "python").write_text("")
                (bin_dir / "mineru").write_text("")
            return _fake_proc(0)
        captured_mineru_cmd["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, mineru_returncode)

    return fake_run


def test_parse_docs_command_invokes_mineru_with_correct_shape(tmp_path: Path) -> None:
    """parse-docs must invoke `<venv>/bin/mineru -p INPUT -o OUTPUT [extras...]`."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    captured: dict = {}
    fake_run = _route_uv_and_mineru(captured, mineru_returncode=0)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
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

    assert result.exit_code == 0, (result.output, result.exception)
    assert output_dir.exists()

    cmd = captured["cmd"]
    assert Path(cmd[0]).name == "mineru"
    assert cmd[1:3] == ["-p", str(input_dir)]
    assert cmd[3] == "-o"
    assert cmd[4] == str(output_dir)
    # Extras after --output flow through unchanged.
    assert cmd[-2:] == ["--backend", "pipeline"]


def test_parse_docs_command_propagates_mineru_failure(tmp_path: Path) -> None:
    """A non-zero mineru exit surfaces as ClickException via parse-docs."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    captured: dict = {}
    fake_run = _route_uv_and_mineru(captured, mineru_returncode=2)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )

    assert result.exit_code != 0
    assert "mineru exited with code 2" in result.output
