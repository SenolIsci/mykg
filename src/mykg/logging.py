from __future__ import annotations

import json
import logging
import re
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
DATE_FORMAT = "%H:%M:%S"

# ANSI color codes applied to stdout only — never written to log files.
_ANSI_RESET = "\033[0m"
_LEVEL_COLORS: dict[str, str] = {
    "DEBUG": "\033[38;5;244m",  # grey
    "INFO": "\033[38;5;153m",  # light blue
    "WARNING": "\033[32m",  # green
    "ERROR": "\033[31m",  # red
    "CRITICAL": "\033[1;31m",  # bold red
}


class _ColorFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        color = _LEVEL_COLORS.get(record.levelname, "")
        msg = super().format(record)
        return f"{color}{msg}{_ANSI_RESET}" if color else msg


# Module-level singletons — set once by setup(), read by adapters.
_llm_log_path: Path | None = None
_llm_log_lock = threading.Lock()
_llm_handler: "logging.handlers.RotatingFileHandler | None" = None
_prompt_dir: Path | None = None
_call_counter: int = 0
_call_counter_lock = threading.Lock()


def setup(log_file: Path | None = None, verbose: bool = False) -> None:
    global _llm_log_path, _llm_handler, _prompt_dir, _call_counter
    import logging.handlers

    from mykg import config

    if sys.platform == "win32":
        for _stream in (sys.stdout, sys.stderr):
            if hasattr(_stream, "reconfigure"):
                _stream.reconfigure(encoding="utf-8", errors="backslashreplace")

    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)

    # Replace existing handlers so reconfiguration (e.g. --verbose) takes effect
    for h in root.handlers[:]:
        root.removeHandler(h)

    # Suppress low-level HTTP noise from openai SDK and its httpx transport layer and network drawing.
    for noisy in ("httpx", "httpcore", "openai._base_client", "openai", "pajek"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root.addHandler(_stdout_handler(level))
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        root.addHandler(_file_handler(log_file, level))
        if config.LOG_LLM_LOG:
            llm_log = log_file.parent / "llm.log"
            _llm_log_path = llm_log
            _llm_handler = logging.handlers.RotatingFileHandler(
                llm_log,
                maxBytes=config.LOG_MAX_BYTES,
                backupCount=config.LOG_BACKUP_COUNT,
                encoding="utf-8",
            )
        else:
            _llm_log_path = None
            _llm_handler = None
        if config.LOG_CAPTURE_PROMPTS:
            _prompt_dir = log_file.parent / "intermediate" / "llm_calls"
            _prompt_dir.mkdir(parents=True, exist_ok=True)
        else:
            _prompt_dir = None
        _call_counter = 0
    else:
        _llm_log_path = None
        _llm_handler = None
        _prompt_dir = None
        _call_counter = 0


def _slug(context_label: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", context_label).strip("_")


def write_prompt_files(
    *,
    n: int,
    context_label: str,
    system_prompt: str,
    user_prompt: str,
    response: str,
) -> None:
    """Write <n>_<slug>_input.md and <n>_<slug>_output.md to _prompt_dir."""
    if _prompt_dir is None:
        return
    slug = _slug(context_label)
    stem = f"{n:04d}_{slug}"
    (_prompt_dir / f"{stem}_input.md").write_text(
        f"## System\n\n{system_prompt}\n\n## User\n\n{user_prompt}\n",
        encoding="utf-8",
    )
    (_prompt_dir / f"{stem}_output.md").write_text(
        f"## Response\n\n{response}\n",
        encoding="utf-8",
    )


def record_llm_call(
    *,
    provider: str,
    model: str,
    context_label: str,
    input_tokens: int,
    output_tokens: int,
    duration_s: float,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
    raw_response: str | None = None,
    system_prompt: str | None = None,
    user_prompt: str | None = None,
    status_code: int | None = None,
    error: str | None = None,
    finish_reason: str | None = None,
) -> None:
    """Append one JSON line to llm.log. No-op if llm.log is not configured."""
    if _llm_handler is None:
        return
    global _call_counter
    try:
        in_tok = int(input_tokens)
        out_tok = int(output_tokens)
        cache_read = int(cache_read_tokens)
        cache_create = int(cache_creation_tokens)
    except (TypeError, ValueError):
        return

    with _call_counter_lock:
        _call_counter += 1
        n = _call_counter

    entry: dict = {
        "ts": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "provider": provider,
        "model": model,
        "context": context_label,
        "input_tokens": in_tok,
        "cache_read_tokens": cache_read,
        "cache_creation_tokens": cache_create,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "duration_s": round(duration_s, 3),
        "raw_response": raw_response,
    }
    if status_code is not None:
        entry["status_code"] = status_code
    if error is not None:
        entry["error"] = error
    if finish_reason is not None:
        entry["finish_reason"] = finish_reason
    line = json.dumps(entry) + "\n"
    record = logging.makeLogRecord({"msg": line, "levelno": logging.INFO})
    with _llm_log_lock:
        _llm_handler.emit(record)

    from mykg import config as _cfg

    if _cfg.LOG_CAPTURE_PROMPTS and system_prompt is not None and user_prompt is not None:
        write_prompt_files(
            n=n,
            context_label=context_label,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response=raw_response or "",
        )


def _stdout_handler(level: int) -> logging.StreamHandler:
    h = logging.StreamHandler(sys.stdout)
    h.setLevel(level)
    use_color = hasattr(sys.stdout, "isatty") and sys.stdout.isatty()
    fmt_cls = _ColorFormatter if use_color else logging.Formatter
    h.setFormatter(fmt_cls(LOG_FORMAT, datefmt=DATE_FORMAT))
    return h


def _file_handler(log_file: Path, level: int) -> logging.handlers.RotatingFileHandler:
    import logging.handlers

    from mykg import config

    h = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=config.LOG_MAX_BYTES,
        backupCount=config.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    h.setLevel(level)
    h.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    return h


def get(name: str) -> logging.Logger:
    return logging.getLogger(name)
