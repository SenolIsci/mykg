from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from mykg.llm.claude_cli_adapter import ClaudeCLIAdapter
from mykg.llm.config import load_adapter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    proc = MagicMock()
    proc.returncode = returncode
    proc.stdout = stdout
    proc.stderr = stderr
    return proc


def _envelope(result: str = '{"nodes": []}', usage: dict | None = None) -> str:
    return json.dumps(
        {
            "result": result,
            "usage": usage or {"input_tokens": 10, "output_tokens": 5},
        }
    )


# ---------------------------------------------------------------------------
# __init__ — CLI discovery
# ---------------------------------------------------------------------------


def test_claude_cli_adapter_not_found():
    with patch("shutil.which", return_value=None):
        with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
            ClaudeCLIAdapter(max_tokens=1024, timeout=60)


def test_claude_cli_adapter_init_succeeds_when_found():
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
    assert adapter._max_tokens == 1024
    assert adapter._timeout == 60


# ---------------------------------------------------------------------------
# complete() — success path
# ---------------------------------------------------------------------------


def test_claude_cli_adapter_complete_success():
    expected_result = '{"nodes": [], "edges": []}'
    proc = _make_proc(stdout=_envelope(expected_result))

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc) as mock_run,
        patch("mykg.llm.claude_cli_adapter.record_llm_call"),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        result = adapter.complete("sys prompt", "user message", context_label="test")

    assert result == expected_result

    call_args = mock_run.call_args
    cmd = call_args.args[0]
    assert cmd[0] == "claude"
    assert "-p" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd
    assert "--no-session-persistence" in cmd
    assert "--system-prompt" in cmd
    system_prompt_arg = cmd[cmd.index("--system-prompt") + 1]
    assert "sys prompt" in system_prompt_arg
    assert call_args.kwargs["input"] == "user message"
    assert call_args.kwargs["encoding"] == "utf-8"


def test_claude_cli_adapter_complete_records_tokens():
    usage = {
        "input_tokens": 100,
        "output_tokens": 50,
        "cache_read_input_tokens": 20,
        "cache_creation_input_tokens": 10,
    }
    proc = _make_proc(stdout=_envelope(usage=usage))

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc),
        patch("mykg.llm.claude_cli_adapter.record_llm_call") as mock_record,
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        adapter.complete("sys", "user")

    mock_record.assert_called_once()
    kwargs = mock_record.call_args.kwargs
    assert kwargs["provider"] == "claude-cli"
    assert kwargs["model"] == "claude-cli"
    assert kwargs["input_tokens"] == 100
    assert kwargs["cache_read_tokens"] == 20
    assert kwargs["cache_creation_tokens"] == 10
    assert kwargs["output_tokens"] == 50


def test_claude_cli_adapter_complete_empty_result():
    proc = _make_proc(stdout=json.dumps({"result": "", "usage": {}}))

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc),
        patch("mykg.llm.claude_cli_adapter.record_llm_call"),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        result = adapter.complete("sys", "user")

    assert result == ""


# ---------------------------------------------------------------------------
# complete() — error paths
# ---------------------------------------------------------------------------


def test_claude_cli_adapter_nonzero_exit():
    proc = _make_proc(returncode=1, stderr="auth error")

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        with pytest.raises(RuntimeError, match="claude -p exited 1"):
            adapter.complete("sys", "user")


def test_claude_cli_adapter_json_parse_error():
    proc = _make_proc(stdout="not json at all")

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        with pytest.raises(RuntimeError, match="unparseable JSON envelope"):
            adapter.complete("sys", "user")


def test_claude_cli_adapter_timeout():
    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["claude"], 60)),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60)
        with pytest.raises(RuntimeError, match="timed out"):
            adapter.complete("sys", "user")


# ---------------------------------------------------------------------------
# error_gate integration
# ---------------------------------------------------------------------------


def test_claude_cli_adapter_notifies_error_gate_on_failure():
    from mykg.llm.error_gate import ErrorGate

    gate = MagicMock(spec=ErrorGate)
    proc = _make_proc(returncode=1, stderr="boom")

    with (
        patch("shutil.which", return_value="/usr/local/bin/claude"),
        patch("subprocess.run", return_value=proc),
    ):
        adapter = ClaudeCLIAdapter(max_tokens=1024, timeout=60, error_gate=gate)
        with pytest.raises(RuntimeError):
            adapter.complete("sys", "user")

    gate.record_error.assert_called_once()


# ---------------------------------------------------------------------------
# load_adapter() integration
# ---------------------------------------------------------------------------


def test_config_creates_claude_cli_adapter():
    raw = {
        "provider": "claude-cli",
        "llm": {"max_output_tokens": 2048, "timeout": 120},
    }
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        adapter = load_adapter(raw)

    assert isinstance(adapter, ClaudeCLIAdapter)
    assert adapter._max_tokens == 2048
    assert adapter._timeout == 120


# ---------------------------------------------------------------------------
# temperature — accepted for interface uniformity, deliberately unused
# ---------------------------------------------------------------------------


def test_claude_cli_accepts_temperature_without_changing_argv():
    """`claude -p` has no temperature flag, so the argv must be byte-identical."""
    with patch("shutil.which", return_value="/usr/bin/claude"):
        with patch("subprocess.run", return_value=_make_proc(stdout=_envelope())) as run:
            ClaudeCLIAdapter(max_tokens=4096, timeout=30).complete("sys", "user")
            argv_without = run.call_args[0][0]

        with patch("subprocess.run", return_value=_make_proc(stdout=_envelope())) as run:
            adapter = ClaudeCLIAdapter(max_tokens=4096, timeout=30, temperature=0.2)
            adapter.complete("sys", "user", temperature=0.9)
            argv_with = run.call_args[0][0]

    assert argv_with == argv_without
    assert not any("temperature" in str(a) for a in argv_with)


def test_claude_cli_complete_accepts_temperature_kwarg():
    """The adapter must stay callable through llm_complete_with_retry."""
    with patch("shutil.which", return_value="/usr/bin/claude"):
        with patch("subprocess.run", return_value=_make_proc(stdout=_envelope())):
            adapter = ClaudeCLIAdapter(max_tokens=4096, timeout=30)
            assert adapter.complete("sys", "user", temperature=0.0) == '{"nodes": []}'


def test_claude_cli_discards_the_zero_default():
    """DEFAULT_TEMPERATURE reaches this adapter but cannot be acted on.

    `claude -p` has no temperature flag, so the README's reproducibility
    guarantee explicitly excludes this profile. Pinned here so the code and that
    caveat cannot drift apart.
    """
    from mykg.llm.config import load_adapter
    from mykg.llm.temperature import DEFAULT_TEMPERATURE

    raw = {
        "provider": "claude-cli",
        "llm": {"model": "sonnet", "max_output_tokens": 4096, "timeout": 30},
    }
    with patch("shutil.which", return_value="/usr/bin/claude"):
        adapter = load_adapter(_raw=raw)
        assert adapter._temperature == DEFAULT_TEMPERATURE

        with patch("subprocess.run", return_value=_make_proc(stdout=_envelope())) as run:
            adapter.complete("sys", "user")

    argv = run.call_args[0][0]
    assert not any("temperature" in str(a) for a in argv)
