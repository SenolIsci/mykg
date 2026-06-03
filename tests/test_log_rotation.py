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
