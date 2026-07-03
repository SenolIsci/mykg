from __future__ import annotations

import time
from typing import TYPE_CHECKING, Callable, TypeVar

from mykg import config as _cfg
from mykg.llm.adapter import LLMAdapter
from mykg.logging import get

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate

log = get("mykg.llm.retry")

E = TypeVar("E", bound=BaseException)

# Substrings seen across providers/SDKs when a prompt is rejected outright for not
# fitting the model's context window (HTTP 400 from OpenAI, Ollama, vLLM, etc.).
# There is no single exception type shared across SDKs for this, so detection is a
# heuristic match on the stringified exception — observability only, this does not
# drive a retry (see `looks_like_context_exceeded` callers).
_CONTEXT_EXCEEDED_MARKERS = (
    "context size",
    "context length",
    "context_length",
    "context window",
    "n_ctx",
    "exceeds the available",
    "maximum context",
    "too many tokens",
    "prompt is too long",
    "context_length_exceeded",
)


def looks_like_context_exceeded(exc: BaseException) -> bool:
    """Heuristically classify an exception as a context-window overflow.

    Different backends raise different exception types/messages for the same
    underlying problem (the prompt didn't fit the model's context window). This
    matches on substrings of the stringified exception so callers can log a clear
    diagnostic marker before re-raising, without depending on a specific SDK
    exception class.
    """
    msg = str(exc).lower()
    return any(marker in msg for marker in _CONTEXT_EXCEEDED_MARKERS)


def log_truncated_output(provider: str, model: str, context_label: str, finish_reason: str) -> None:
    """Warn on the standard logger (→ stdout + run.log) when output was
    truncated at the token cap. Independent of llm.log / LOG_LLM_LOG — this is
    the only copy of the signal visible when the opt-in llm.log sink is off.
    """
    label = f" [{context_label}]" if context_label else ""
    log.warning(
        "%s/%s%s — output truncated (finish_reason=%s); response may be "
        "incomplete/unparseable",
        provider,
        model,
        label,
        finish_reason,
    )


def log_context_overflow(provider: str, model: str, context_label: str, exc: BaseException) -> None:
    """Warn on the standard logger (→ stdout + run.log) when the prompt was
    rejected for exceeding the model's context window. Independent of
    llm.log / LOG_LLM_LOG.
    """
    label = f" [{context_label}]" if context_label else ""
    log.warning(
        "%s/%s%s — context length exceeded, request rejected: %s",
        provider,
        model,
        label,
        exc,
    )


def llm_complete_with_retry(
    adapter: LLMAdapter,
    system: str,
    user: str,
    context_label: str = "",
    max_tokens: int | None = None,
    timeout: int | None = None,
) -> str:
    """Call adapter.complete(), retrying up to LLM_RETRY_MAX_RETRIES times on empty response.

    Returns the first non-empty (non-whitespace) response. If all attempts return empty,
    returns "" so callers can handle it as they would a failed parse (existing behaviour).

    max_tokens: per-call override forwarded to the adapter; None means use adapter default.
    timeout: per-call override in seconds forwarded to the adapter; None means use adapter default.
    """
    max_retries = _cfg.LLM_RETRY_MAX_RETRIES
    label = f" [{context_label}]" if context_label else ""
    for retry in range(max_retries + 1):
        raw = adapter.complete(
            system,
            user,
            context_label=context_label,
            max_tokens=max_tokens,
            timeout=timeout,
        )
        if raw.strip():
            return raw
        if retry < max_retries:
            log.warning("empty response%s — retrying (retry %d/%d)", label, retry + 1, max_retries)
        else:
            log.warning(
                "empty response%s — all %d retr%s exhausted",
                label,
                max_retries,
                "y" if max_retries == 1 else "ies",
            )
    return ""


def retry_on_rate_limit(
    fn: Callable[[], E],
    exc_type: type[E],
    provider: str,
    retry_max: int,
    base_delay: float,
    error_gate: ErrorGate | None = None,
) -> object:
    """Call fn(), retrying on rate-limit errors with exponential backoff.

    Args:
        fn: Zero-argument callable that performs the LLM call and returns its result.
        exc_type: The rate-limit exception class to catch (e.g. anthropic.RateLimitError).
        provider: Human-readable provider name used in log messages (e.g. "Anthropic").
        retry_max: Maximum number of retries (not counting the initial attempt).
        base_delay: Base sleep duration in seconds; doubles each attempt.
        error_gate: Optional shared gate; notified after all retries are exhausted.

    Returns:
        The return value of fn() on success.

    Raises:
        exc_type: After all retries are exhausted.
    """
    last_exc: BaseException | None = None
    for attempt in range(retry_max + 1):
        try:
            return fn()
        except exc_type as exc:  # type: ignore[misc]
            last_exc = exc
            if attempt < retry_max:
                delay = base_delay * (2**attempt)
                log.warning(
                    "%s 429 rate-limit (attempt %d/%d) — retrying in %.1fs",
                    provider,
                    attempt + 1,
                    retry_max,
                    delay,
                )
                time.sleep(delay)
    if error_gate is not None:
        error_gate.record_error(last_exc)  # type: ignore[arg-type]
    raise last_exc  # type: ignore[misc]
