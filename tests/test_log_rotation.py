"""Tests for log file rotation behaviour."""

from __future__ import annotations

import logging
import logging.handlers


def test_file_handler_is_rotating(tmp_path):
    """setup() must use RotatingFileHandler, not plain FileHandler."""
    from mykg.logging import setup

    log_file = tmp_path / "run.log"
    setup(log_file=log_file)
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1, "Expected exactly one RotatingFileHandler"


def test_rotating_handler_respects_config(tmp_path):
    """RotatingFileHandler must use LOG_MAX_BYTES and LOG_BACKUP_COUNT from config."""
    from mykg import config
    from mykg.logging import setup

    log_file = tmp_path / "run.log"
    setup(log_file=log_file)
    root = logging.getLogger()
    h = next(h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler))
    assert h.maxBytes == config.LOG_MAX_BYTES
    assert h.backupCount == config.LOG_BACKUP_COUNT


def test_llm_log_handler_is_rotating(tmp_path):
    """setup() must install a RotatingFileHandler for llm.log."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)
    assert mykg_logging._llm_handler is not None
    assert isinstance(mykg_logging._llm_handler, logging.handlers.RotatingFileHandler)


def test_llm_log_handler_respects_config(tmp_path):
    """llm.log RotatingFileHandler must use LOG_MAX_BYTES and LOG_BACKUP_COUNT."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging
    from mykg import config

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)
    h = mykg_logging._llm_handler
    assert h.maxBytes == config.LOG_MAX_BYTES
    assert h.backupCount == config.LOG_BACKUP_COUNT


def test_llm_log_rotates_on_size(tmp_path):
    """record_llm_call must rotate llm.log when it exceeds maxBytes."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)

    # Shrink the handler's limit to 200 bytes so rotation happens quickly
    mykg_logging._llm_handler.maxBytes = 200

    for _ in range(20):
        mykg_logging.record_llm_call(
            provider="test",
            model="m",
            context_label="ctx",
            input_tokens=10,
            output_tokens=5,
            duration_s=0.1,
        )

    llm_log = tmp_path / "llm.log"
    backup = tmp_path / "llm.log.1"
    assert llm_log.exists()
    assert backup.exists(), "llm.log.1 should exist after rotation"


def test_log_capture_prompts_config_exists():
    from mykg import config

    assert hasattr(config, "LOG_CAPTURE_PROMPTS")
    assert isinstance(config.LOG_CAPTURE_PROMPTS, bool)


def test_prompt_files_written_when_enabled(tmp_path):
    """write_prompt_files() creates numbered input/output md files in llm_calls/."""
    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    mykg_logging.setup(log_file=log_file)
    mykg_logging._prompt_dir = tmp_path / "llm_calls"
    mykg_logging._prompt_dir.mkdir(exist_ok=True)

    mykg_logging.write_prompt_files(
        n=1,
        context_label="pass1 batch 1/4",
        system_prompt="You are an expert.",
        user_prompt="Extract entities.",
        response="{}",
    )

    files = list((tmp_path / "llm_calls").iterdir())
    names = {f.name for f in files}
    assert "0001_pass1_batch_1_4_input.md" in names
    assert "0001_pass1_batch_1_4_output.md" in names


def test_prompt_input_file_contains_system_and_user(tmp_path):
    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    mykg_logging.setup(log_file=log_file)
    mykg_logging._prompt_dir = tmp_path / "llm_calls"
    mykg_logging._prompt_dir.mkdir(exist_ok=True)

    mykg_logging.write_prompt_files(
        n=1,
        context_label="feedback fix-schema",
        system_prompt="System text here.",
        user_prompt="User text here.",
        response="Response text.",
    )

    input_file = tmp_path / "llm_calls" / "0001_feedback_fix-schema_input.md"
    content = input_file.read_text()
    assert "System text here." in content
    assert "User text here." in content


def test_prompt_output_file_contains_response(tmp_path):
    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    mykg_logging.setup(log_file=log_file)
    mykg_logging._prompt_dir = tmp_path / "llm_calls"
    mykg_logging._prompt_dir.mkdir(exist_ok=True)

    mykg_logging.write_prompt_files(
        n=3,
        context_label="pass2 chunk 7",
        system_prompt="sys",
        user_prompt="usr",
        response='{"nodes": [], "edges": []}',
    )

    output_file = tmp_path / "llm_calls" / "0003_pass2_chunk_7_output.md"
    assert '{"nodes": [], "edges": []}' in output_file.read_text()


def test_adapter_passes_prompts_to_record(tmp_path):
    """Adapters must forward system/user to record_llm_call."""
    from unittest.mock import MagicMock, patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    mykg_logging.setup(log_file=log_file)
    mykg_logging._call_counter = 0
    mykg_logging._prompt_dir = tmp_path / "llm_calls"
    mykg_logging._prompt_dir.mkdir(exist_ok=True)

    captured = {}

    original = mykg_logging.record_llm_call

    def capturing_record(**kwargs):
        captured.update(kwargs)
        return original(**kwargs)

    mock_resp = MagicMock()
    mock_resp.usage.prompt_tokens = 10
    mock_resp.usage.completion_tokens = 5
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = '{"nodes":[]}'

    with (
        patch("mykg.llm.openrouter_adapter.record_llm_call", side_effect=capturing_record),
        patch("openai.OpenAI") as mock_openai_cls,
    ):
        mock_client = MagicMock()
        mock_openai_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="test/model",
            max_tokens=100,
            timeout=30,
            api_key="test-key",
        )
        adapter.complete("SYS PROMPT", "USER PROMPT", context_label="test")

    assert captured.get("system_prompt") == "SYS PROMPT"
    assert captured.get("user_prompt") == "USER PROMPT"


def test_setup_with_no_log_file_adds_no_file_handler(tmp_path):
    """setup(log_file=None) attaches only a stdout handler; _llm_handler and _prompt_dir reset."""
    import logging

    import mykg.logging as mykg_logging

    mykg_logging.setup(log_file=None)
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []
    assert mykg_logging._llm_handler is None
    assert mykg_logging._llm_log_path is None
    assert mykg_logging._prompt_dir is None


def test_color_formatter_wraps_known_levels():
    """_ColorFormatter wraps messages for known log levels with ANSI codes."""
    from mykg.logging import LOG_FORMAT, _ColorFormatter

    fmt = _ColorFormatter(LOG_FORMAT)
    record = logging.makeLogRecord(
        {"name": "x", "levelname": "INFO", "levelno": logging.INFO, "msg": "hello"}
    )
    out = fmt.format(record)
    # ANSI reset is appended when a known color is matched
    assert out.endswith("\033[0m")
    assert "hello" in out


def test_color_formatter_no_color_for_unknown_level():
    """_ColorFormatter does not wrap when levelname is not in _LEVEL_COLORS."""
    from mykg.logging import LOG_FORMAT, _ColorFormatter

    fmt = _ColorFormatter(LOG_FORMAT)
    record = logging.makeLogRecord(
        {"name": "x", "levelname": "TRACE", "levelno": 5, "msg": "hello"}
    )
    out = fmt.format(record)
    assert "\033[" not in out  # no ANSI escape sequence


def test_setup_creates_prompt_dir_when_capture_prompts_enabled(tmp_path):
    """setup() creates intermediate/llm_calls/ when LOG_CAPTURE_PROMPTS is True."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_CAPTURE_PROMPTS", True):
        mykg_logging.setup(log_file=log_file)
    assert mykg_logging._prompt_dir is not None
    assert mykg_logging._prompt_dir.exists()
    assert mykg_logging._prompt_dir.name == "llm_calls"


def test_setup_no_prompt_dir_when_capture_prompts_disabled(tmp_path):
    """setup() leaves _prompt_dir None when LOG_CAPTURE_PROMPTS is False."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_CAPTURE_PROMPTS", False):
        mykg_logging.setup(log_file=log_file)
    assert mykg_logging._prompt_dir is None


def test_write_prompt_files_noop_when_dir_is_none(tmp_path):
    """write_prompt_files is a no-op when _prompt_dir is None."""
    import mykg.logging as mykg_logging

    mykg_logging.setup(log_file=None)
    assert mykg_logging._prompt_dir is None
    # Must not raise nor write anything
    mykg_logging.write_prompt_files(
        n=1,
        context_label="x",
        system_prompt="s",
        user_prompt="u",
        response="r",
    )


def test_record_llm_call_invalid_token_type_returns_silently(tmp_path):
    """record_llm_call returns silently when token counts can't be coerced to int."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)
    before_counter = mykg_logging._call_counter

    # Pass a non-coercible value to trigger the (TypeError, ValueError) branch
    mykg_logging.record_llm_call(
        provider="p",
        model="m",
        context_label="ctx",
        input_tokens="not-a-number",  # type: ignore[arg-type]
        output_tokens=5,
        duration_s=0.1,
    )
    # Counter must not have advanced
    assert mykg_logging._call_counter == before_counter


def test_record_llm_call_status_code_and_error_branches(tmp_path):
    """record_llm_call adds status_code/error fields when provided."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)

    mykg_logging.record_llm_call(
        provider="p",
        model="m",
        context_label="ctx-err",
        input_tokens=0,
        output_tokens=0,
        duration_s=0.0,
        status_code=429,
        error="rate-limited",
    )
    # Flush handler so the entry hits disk
    mykg_logging._llm_handler.flush()
    contents = (tmp_path / "llm.log").read_text(encoding="utf-8")
    assert '"status_code": 429' in contents
    assert '"error": "rate-limited"' in contents


def test_record_llm_call_noop_when_handler_is_none(tmp_path):
    """record_llm_call short-circuits when LOG_LLM_LOG is False (no _llm_handler)."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    # With LOG_LLM_LOG False (the default), _llm_handler should be None
    with patch("mykg.config.LOG_LLM_LOG", False):
        mykg_logging.setup(log_file=log_file)
    assert mykg_logging._llm_handler is None
    # Should be a clean no-op
    mykg_logging.record_llm_call(
        provider="p",
        model="m",
        context_label="ctx",
        input_tokens=1,
        output_tokens=1,
        duration_s=0.1,
    )


def test_call_counter_increments_per_call(tmp_path):
    """record_llm_call increments the global counter for each call."""
    from unittest.mock import patch

    import mykg.logging as mykg_logging

    log_file = tmp_path / "run.log"
    with patch("mykg.config.LOG_LLM_LOG", True):
        mykg_logging.setup(log_file=log_file)
    mykg_logging._call_counter = 0
    mykg_logging._prompt_dir = tmp_path / "llm_calls"
    mykg_logging._prompt_dir.mkdir(exist_ok=True)

    with patch("mykg.config.LOG_CAPTURE_PROMPTS", True):
        mykg_logging.record_llm_call(
            provider="test",
            model="m",
            context_label="ctx-a",
            input_tokens=1,
            output_tokens=1,
            duration_s=0.1,
            system_prompt="s",
            user_prompt="u",
            raw_response="r",
        )
        mykg_logging.record_llm_call(
            provider="test",
            model="m",
            context_label="ctx-b",
            input_tokens=1,
            output_tokens=1,
            duration_s=0.1,
            system_prompt="s",
            user_prompt="u",
            raw_response="r",
        )

    files = {f.name for f in (tmp_path / "llm_calls").iterdir()}
    assert "0001_ctx-a_input.md" in files
    assert "0002_ctx-b_input.md" in files
