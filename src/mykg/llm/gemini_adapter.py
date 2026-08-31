from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from mykg.llm.adapter import LLMAdapter
from mykg.llm.retry import (
    log_context_overflow,
    log_truncated_output,
    looks_like_context_exceeded,
    retry_on_rate_limit,
)
from mykg.logging import record_llm_call

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate

_log = logging.getLogger(__name__)

# Gemini 3.x models reason before answering, and those thinking tokens are drawn
# from the same max_output_tokens budget as the visible answer. A budget that is
# too small returns finish_reason=MAX_TOKENS with an EMPTY response body rather
# than an error, which the pipeline would record as a blank_response chunk (D33).
#
# "low" is the default rather than leaving thinking unconfigured because omitting
# it costs materially more for no gain: measured on a representative extraction
# prompt (gemini-3.5-flash), omitted = 942 thinking tokens / 4.4s versus
# low = 442 / 2.9s, with both producing identical parseable output. Those tokens
# are billed as output and consume the max_output_tokens allowance.
#
# `thinking_level` is the portable control: thinking_budget=0 is rejected with
# 400 INVALID_ARGUMENT by gemini-3.6-flash while being accepted by 3.7/3.5/3.1.
# The shipped gemini profile does not carry the key, so this default applies;
# add an optional llm.thinking_level to the profile to override it, or set it to
# null there to omit thinking_config entirely and let the model decide.
_DEFAULT_THINKING_LEVEL = "low"


# google-genai logs an INFO notice on every generate_content call recommending
# Chat.send_message for automatic function calling. mykg never uses tools, so
# that notice is pure noise repeated once per chunk in run.log.
#
# A filter on that one message is used rather than raising the logger's level:
# setLevel would also suppress genuine warnings from google_genai.models, and
# re-applying it per adapter construction would mutate global logging state on
# behalf of the whole process. The filter is installed exactly once and drops
# only the AFC line.
# Two distinct AFC lines are emitted: an INFO "AFC is enabled with max remote
# calls: N." on every call, and a longer "Direct use of automatic function
# calling (AFC) ... is not recommended" notice.
_AFC_MARKERS = ("automatic function calling", "afc is enabled")
_afc_filter_installed = False


def _drop_afc_notice(record: logging.LogRecord) -> bool:
    msg = record.getMessage().lower()
    return not any(marker in msg for marker in _AFC_MARKERS)


def _silence_afc_notice() -> None:
    """Install the AFC-notice filter once per process."""
    global _afc_filter_installed
    if _afc_filter_installed:
        return
    logging.getLogger("google_genai.models").addFilter(_drop_afc_notice)
    _afc_filter_installed = True


class _GeminiRetryable(Exception):
    """Marker for Gemini errors worth retrying (429 and 5xx).

    google-genai raises ClientError for the whole 4xx family, so catching it
    wholesale in retry_on_rate_limit would also retry genuine caller mistakes
    (bad model name, malformed request) that no amount of retrying can fix.
    Wrapping only the retryable statuses keeps precondition errors failing fast.
    """

    def __init__(self, message: str, original: BaseException):
        super().__init__(message)
        self.original = original


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status extraction from a google-genai APIError."""
    code = getattr(exc, "code", None)
    if isinstance(code, int):
        return code
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


class GeminiAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        max_tokens: int,
        timeout: int,
        api_key: str | None = None,
        thinking_level: str | None = _DEFAULT_THINKING_LEVEL,
        retry_429_max: int = 5,
        retry_429_base_delay: float = 2.0,
        error_gate: ErrorGate | None = None,
        temperature: float | None = None,
    ):
        self._model = model
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._thinking_level = thinking_level
        self._temperature = temperature
        self._retry_429_max = retry_429_max
        self._retry_429_base_delay = retry_429_base_delay
        self._error_gate = error_gate

        if api_key is None:
            api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY (or GOOGLE_API_KEY) is required — "
                "set it in your environment or supply api_key in mykg_config.yaml"
            )

        _silence_afc_notice()
        self._client = genai.Client(api_key=api_key)

    def endpoint_label(self) -> str:
        return f"gemini / {self._model} @ https://generativelanguage.googleapis.com"

    def _build_config(
        self,
        system: str,
        max_output_tokens: int,
        timeout_s: int,
        temperature: float | None = None,
    ) -> genai_types.GenerateContentConfig:
        # The system prompt carries the run-stable prefix (flattened schema +
        # instructions). Passing it as system_instruction is what lets Gemini's
        # implicit caching latch onto it — no explicit cache object is created or
        # needed; caching is automatic and server-side on 2.5+ models.
        thinking = (
            genai_types.ThinkingConfig(thinking_level=self._thinking_level)
            if self._thinking_level
            else None
        )
        return genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_output_tokens,
            response_mime_type="application/json",
            thinking_config=thinking,
            # A None temperature is dropped from the serialized request by the
            # SDK (verified: model_dump(exclude_none=True) omits it), so unlike
            # the other adapters no explicit conditional is needed here. A
            # configured 0.0 is retained.
            temperature=temperature,
            # HttpOptions.timeout is in MILLISECONDS, while every mykg timeout
            # config value is in seconds.
            http_options=genai_types.HttpOptions(timeout=timeout_s * 1000),
        )

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        effective_timeout = timeout if timeout is not None else self._timeout
        effective_temperature = temperature if temperature is not None else self._temperature

        def _call() -> str:
            t0 = time.monotonic()
            try:
                resp = self._client.models.generate_content(
                    model=self._model,
                    contents=user,
                    config=self._build_config(
                        system,
                        effective_max_tokens,
                        effective_timeout,
                        effective_temperature,
                    ),
                )
            except genai_errors.APIError as exc:
                status = _status_of(exc)
                error_msg = str(exc)
                if looks_like_context_exceeded(exc):
                    log_context_overflow("gemini", self._model, context_label, exc)
                    error_msg = f"context_length_exceeded: {error_msg}"
                record_llm_call(
                    provider="gemini",
                    model=self._model,
                    context_label=context_label,
                    input_tokens=0,
                    output_tokens=0,
                    duration_s=time.monotonic() - t0,
                    system_prompt=system,
                    user_prompt=user,
                    status_code=status,
                    error=error_msg,
                )
                # 429 (quota) and 5xx (transient overload) are worth retrying;
                # everything else is a caller error that retrying cannot fix.
                if status == 429 or (status is not None and status >= 500):
                    raise _GeminiRetryable(f"Gemini {status}: {exc}", exc) from exc
                raise

            raw = resp.text or ""
            raw_reason = self._raw_finish_reason(resp)
            truncated = raw_reason is not None and raw_reason.endswith("MAX_TOKENS")
            finish_reason = "max_tokens" if truncated else None
            label = f" [{context_label}]" if context_label else ""
            blocked_reason: str | None = None

            if truncated:
                log_truncated_output("gemini", self._model, context_label, finish_reason)
                if not raw.strip():
                    # The entire token budget went to thinking, leaving no answer.
                    # Without this warning the failure surfaces far downstream as an
                    # unexplained blank chunk.
                    _log.warning(
                        "gemini/%s%s — hit max_output_tokens with an empty response; "
                        "the thinking budget consumed the whole allowance. Raise "
                        "llm.max_output_tokens or lower llm.thinking_level.",
                        self._model,
                        label,
                    )
            elif not raw.strip() and raw_reason not in (None, "STOP", "FINISH_REASON_UNSPECIFIED"):
                # SAFETY / RECITATION / PROHIBITED_CONTENT and friends return an
                # empty body with a 200. Without this the chunk lands in
                # failed_chunks.json as an unexplained blank_response (D33).
                blocked_reason = raw_reason
                _log.warning(
                    "gemini/%s%s — empty response, blocked with finish_reason=%s; "
                    "the model refused to answer for this input.",
                    self._model,
                    label,
                    raw_reason,
                )

            usage = getattr(resp, "usage_metadata", None)
            input_tokens = _count(usage, "prompt_token_count")
            output_tokens = _count(usage, "candidates_token_count") + _count(
                usage, "thoughts_token_count"
            )
            # Implicit caching is automatic — this only reports the saving it
            # already delivered. cache_creation_tokens stays 0: there is no
            # creation step for an implicit cache.
            cache_read = _count(usage, "cached_content_token_count")

            record_llm_call(
                provider="gemini",
                model=self._model,
                context_label=context_label,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_s=time.monotonic() - t0,
                cache_read_tokens=cache_read,
                raw_response=raw,
                system_prompt=system,
                user_prompt=user,
                finish_reason=finish_reason,
                error=(f"blocked: finish_reason={blocked_reason}" if blocked_reason else None),
            )
            return self.strip_code_fences(raw)

        try:
            return retry_on_rate_limit(  # type: ignore[return-value]
                _call,
                _GeminiRetryable,
                "Gemini",
                self._retry_429_max,
                self._retry_429_base_delay,
                error_gate=self._error_gate,
            )
        except _GeminiRetryable as exc:
            # Retries exhausted — surface the provider's own exception, not the
            # internal marker, so callers see a normal google-genai error.
            raise exc.original from None

    @staticmethod
    def _raw_finish_reason(resp: object) -> str | None:
        """Return the response's finish reason as an upper-case name, if any.

        google-genai reports finish_reason as a FinishReason enum, so this reads
        the member name rather than comparing against a string literal.
        """
        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            return None
        reason = getattr(candidates[0], "finish_reason", None)
        if reason is None:
            return None
        name = getattr(reason, "name", None) or str(reason)
        return name.rsplit(".", 1)[-1].upper() or None


def _count(usage: object, field: str) -> int:
    """Read a token count off usage_metadata, coercing absent/None to 0.

    Probing showed these attributes are present-but-None (not absent, not 0)
    whenever the corresponding count does not apply to a response.
    """
    value = getattr(usage, field, 0) or 0
    return value if isinstance(value, int) else 0
