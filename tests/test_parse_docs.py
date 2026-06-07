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


def _route_uv_and_mineru(
    captured_mineru_cmd: dict | list,
    mineru_returncode: int = 0,
    venv_counter: dict | None = None,
):
    """Build a fake subprocess.run that satisfies uv venv/install and lets the
    test inspect mineru calls.

    `captured_mineru_cmd` may be a dict (last-call mode — stored under
    `["cmd"]`) or a list (accumulating mode — every mineru cmd appended).
    `venv_counter`, when given, increments `["n"]` per venv build.
    """

    def fake_run(cmd, **kwargs):
        head = Path(cmd[0]).name
        if head == "uv":
            if "venv" in cmd and "pip" not in cmd:
                venv_dir = Path(cmd[-1])
                bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
                bin_dir.mkdir(parents=True, exist_ok=True)
                (bin_dir / "python").write_text("")
                (bin_dir / "mineru").write_text("")
                if venv_counter is not None:
                    venv_counter["n"] = venv_counter.get("n", 0) + 1
            return _fake_proc(0)
        if isinstance(captured_mineru_cmd, list):
            captured_mineru_cmd.append(list(cmd))
        else:
            captured_mineru_cmd["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, mineru_returncode)

    return fake_run


def test_parse_docs_command_invokes_mineru_with_correct_shape(tmp_path: Path) -> None:
    """parse-docs must invoke `<venv>/bin/mineru -p INPUT -o OUTPUT [extras...]`."""
    from mykg.cli import cli

    # Single-file input — no recursion involved.
    pdf_file = tmp_path / "doc.pdf"
    output_dir = tmp_path / "out"
    pdf_file.write_bytes(b"%PDF-1.4 fake")

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
                str(pdf_file),
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
    assert cmd[1:3] == ["-p", str(pdf_file)]
    assert cmd[3] == "-o"
    assert cmd[4] == str(output_dir)
    # Extras after --output flow through unchanged.
    assert cmd[-2:] == ["--backend", "pipeline"]


def test_parse_docs_file_flag_loops_inside_one_venv(tmp_path: Path) -> None:
    """When --file is repeated, MinerU is invoked once per file inside one venv."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"%PDF a")
    (input_dir / "sub").mkdir()
    (input_dir / "sub" / "b.pdf").write_bytes(b"%PDF b")

    mineru_calls: list[list[str]] = []
    venv_counter: dict = {}
    fake_run = _route_uv_and_mineru(mineru_calls, venv_counter=venv_counter)

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
                "--file",
                "a.pdf",
                "--file",
                "sub/b.pdf",
            ],
        )

    assert result.exit_code == 0, (result.output, result.exception)
    assert venv_counter["n"] == 1  # one venv built across both files
    assert len(mineru_calls) == 2  # one MinerU invocation per file

    # First call: a.pdf at the input root → output at output_dir root.
    assert mineru_calls[0][1:3] == ["-p", str(input_dir / "a.pdf")]
    assert mineru_calls[0][3:5] == ["-o", str(output_dir)]
    # Second call: sub/b.pdf → output under output_dir / sub (subfolder preserved).
    assert mineru_calls[1][1:3] == ["-p", str(input_dir / "sub" / "b.pdf")]
    assert mineru_calls[1][3:5] == ["-o", str(output_dir / "sub")]


def test_parse_docs_file_list_flag_equivalent_to_file(tmp_path: Path) -> None:
    """`--file-list <path>` produces the same MinerU calls as repeated `--file`."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"%PDF a")
    (input_dir / "sub").mkdir()
    (input_dir / "sub" / "b.pdf").write_bytes(b"%PDF b")

    list_path = tmp_path / "files.txt"
    list_path.write_text("a.pdf\nsub/b.pdf\n")

    mineru_calls: list[list[str]] = []
    venv_counter: dict = {}
    fake_run = _route_uv_and_mineru(mineru_calls, venv_counter=venv_counter)

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
                "--file-list",
                str(list_path),
            ],
        )

    assert result.exit_code == 0, (result.output, result.exception)
    assert venv_counter["n"] == 1
    assert len(mineru_calls) == 2
    by_src = {call[2]: call[4] for call in mineru_calls}
    assert by_src[str(input_dir / "a.pdf")] == str(output_dir)
    assert by_src[str(input_dir / "sub" / "b.pdf")] == str(output_dir / "sub")


def test_parse_docs_file_and_file_list_are_mutually_exclusive(tmp_path: Path) -> None:
    """Passing both --file and --file-list must fail with a usage error."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"%PDF a")
    list_path = tmp_path / "files.txt"
    list_path.write_text("a.pdf\n")

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
    ):
        result = CliRunner().invoke(
            cli,
            [
                "parse-docs",
                "--input",
                str(input_dir),
                "--output",
                str(output_dir),
                "--file",
                "a.pdf",
                "--file-list",
                str(list_path),
            ],
        )

    assert result.exit_code != 0
    assert "mutually exclusive" in result.output


def test_parse_docs_file_list_ignores_blank_lines(tmp_path: Path) -> None:
    """Blank / whitespace-only lines in the list file are skipped."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"%PDF a")

    list_path = tmp_path / "files.txt"
    list_path.write_text("\na.pdf\n\n   \n")

    mineru_calls: list[list[str]] = []
    fake_run = _route_uv_and_mineru(mineru_calls)

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
                "--file-list",
                str(list_path),
            ],
        )

    assert result.exit_code == 0
    assert len(mineru_calls) == 1
    assert mineru_calls[0][2] == str(input_dir / "a.pdf")


def test_parse_docs_directory_input_recurses(tmp_path: Path) -> None:
    """Without --file, parse-docs rglobs the directory and processes each file."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    (input_dir / "a.pdf").write_bytes(b"%PDF a")
    (input_dir / "sub").mkdir()
    (input_dir / "sub" / "b.pdf").write_bytes(b"%PDF b")
    # Markdown files are skipped — they shouldn't reach MinerU.
    (input_dir / "notes.md").write_text("# already markdown")

    mineru_calls: list[list[str]] = []
    venv_counter: dict = {}
    fake_run = _route_uv_and_mineru(mineru_calls, venv_counter=venv_counter)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )

    assert result.exit_code == 0, (result.output, result.exception)
    assert venv_counter["n"] == 1  # one venv across both files
    assert len(mineru_calls) == 2  # the .md is excluded; the two PDFs each get one call

    invoked = sorted(call[2] for call in mineru_calls)  # the `-p <src>` value
    assert invoked == sorted(
        [str(input_dir / "a.pdf"), str(input_dir / "sub" / "b.pdf")]
    )

    # Subfolder structure preserved at the output for the nested file.
    by_src = {call[2]: call[4] for call in mineru_calls}
    assert by_src[str(input_dir / "a.pdf")] == str(output_dir)
    assert by_src[str(input_dir / "sub" / "b.pdf")] == str(output_dir / "sub")


def test_parse_docs_directory_input_continues_on_per_file_failure(tmp_path: Path) -> None:
    """If one file fails MinerU, the loop continues and the run exits non-zero."""
    from mykg.cli import cli

    input_dir = tmp_path / "in"
    output_dir = tmp_path / "out"
    input_dir.mkdir()
    # Both must be MinerU-eligible suffixes — .html is hard-skipped before MinerU
    # (it routes to markdownify), so it can't exercise the per-file MinerU-failure
    # path. Use a second PDF and fail it inside MinerU instead.
    (input_dir / "good.pdf").write_bytes(b"%PDF ok")
    (input_dir / "bad.pdf").write_bytes(b"%PDF bad")

    mineru_calls: list[list[str]] = []

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
        mineru_calls.append(list(cmd))
        # bad.pdf fails in MinerU; everything else succeeds.
        rc = 1 if cmd[2].endswith("bad.pdf") else 0
        return subprocess.CompletedProcess(cmd, rc)

    with (
        patch("mykg.uv_venv.shutil.which", return_value="/fake/uv"),
        patch("mykg.uv_venv.subprocess.run", side_effect=fake_run),
        patch("mykg.cli.subprocess.run", side_effect=fake_run),
    ):
        result = CliRunner().invoke(
            cli,
            ["parse-docs", "--input", str(input_dir), "--output", str(output_dir)],
        )

    # Both files were attempted (no fail-fast).
    assert len(mineru_calls) == 2
    # The run exits non-zero because at least one file failed.
    assert result.exit_code != 0
    assert "1 of 2 files failed" in result.output or "1 of 2 files failed" in str(
        result.exception
    )


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
