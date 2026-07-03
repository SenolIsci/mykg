from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING

import openai

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

# Model-name prefixes that require `max_completion_tokens` instead of `max_tokens`
# on the Chat Completions endpoint. Older families (gpt-4o, gpt-4-turbo, gpt-3.5)
# still use `max_tokens`. Sending the wrong key returns a 400 unsupported_parameter.
_NEW_TOKEN_PARAM_PREFIXES = ("gpt-5", "gpt-4.1", "o1", "o3", "o4", "chatgpt-")


def _uses_max_completion_tokens(model: str) -> bool:
    name = model.lower()
    return any(name.startswith(p) for p in _NEW_TOKEN_PARAM_PREFIXES)


class OpenAIAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        max_tokens: int,
        timeout: int,
        api_key: str | None = None,
        base_url: str | None = None,
        retry_429_max: int = 5,
        retry_429_base_delay: float = 2.0,
        error_gate: ErrorGate | None = None,
    ):
        self._model = model
        self._max_tokens = max_tokens
        self._retry_429_max = retry_429_max
        self._retry_429_base_delay = retry_429_base_delay
        self._error_gate = error_gate

        if api_key is None:
            api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY is required — set OPENAI_API_KEY in your environment "
                "or supply api_key in mykg_config.yaml"
            )

        self._timeout = timeout
        self._base_url = base_url
        self._client = openai.OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        self._use_max_completion_tokens = _uses_max_completion_tokens(model)
        self._fallback_warned = False

    def endpoint_label(self) -> str:
        url = self._base_url or "https://api.openai.com"
        return f"openai / {self._model} @ {url}"

    def _create_with_token_param(
        self,
        system: str,
        user: str,
        effective_max_tokens: int,
        effective_timeout: int,
        use_completion_key: bool,
    ):
        token_key = "max_completion_tokens" if use_completion_key else "max_tokens"
        kwargs = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "timeout": effective_timeout,
            token_key: effective_max_tokens,
        }
        return self._client.chat.completions.create(**kwargs)

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        effective_max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        effective_timeout = timeout if timeout is not None else self._timeout

        def _call() -> str:
            t0 = time.monotonic()
            try:
                resp = self._create_with_token_param(
                    system,
                    user,
                    effective_max_tokens,
                    effective_timeout,
                    use_completion_key=self._use_max_completion_tokens,
                )
            except openai.BadRequestError as exc:
                # Defensive fallback: an unknown future model family may also reject
                # max_tokens. If the API explicitly says so, swap once and remember.
                msg = str(getattr(exc, "message", "") or exc)
                if (
                    not self._use_max_completion_tokens
                    and "max_tokens" in msg
                    and "max_completion_tokens" in msg
                ):
                    if not self._fallback_warned:
                        _log.warning(
                            "OpenAI model %r rejected max_tokens; "
                            "switching to max_completion_tokens for this adapter.",
                            self._model,
                        )
                        self._fallback_warned = True
                    self._use_max_completion_tokens = True
                    resp = self._create_with_token_param(
                        system,
                        user,
                        effective_max_tokens,
                        effective_timeout,
                        use_completion_key=True,
                    )
                else:
                    if looks_like_context_exceeded(exc):
                        log_context_overflow("openai", self._model, context_label, exc)
                        record_llm_call(
                            provider="openai",
                            model=self._model,
                            context_label=context_label,
                            input_tokens=0,
                            output_tokens=0,
                            duration_s=time.monotonic() - t0,
                            system_prompt=system,
                            user_prompt=user,
                            error=f"context_length_exceeded: {exc}",
                        )
                    raise
            usage = resp.usage
            raw = resp.choices[0].message.content or "" if resp.choices else ""
            # finish_reason == "length" means output was truncated at the token cap —
            # surfaced for diagnosability only (see Invariant 13: window/max_tokens
            # sizing should prevent this in normal operation).
            choice_finish_reason = resp.choices[0].finish_reason if resp.choices else None
            finish_reason = "length" if choice_finish_reason == "length" else None
            if finish_reason is not None:
                log_truncated_output("openai", self._model, context_label, finish_reason)
            record_llm_call(
                provider="openai",
                model=self._model,
                context_label=context_label,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                duration_s=time.monotonic() - t0,
                system_prompt=system,
                user_prompt=user,
                raw_response=raw,
                finish_reason=finish_reason,
            )
            return self.strip_code_fences(raw)

        return retry_on_rate_limit(  # type: ignore[return-value]
            _call,
            openai.RateLimitError,
            "OpenAI",
            self._retry_429_max,
            self._retry_429_base_delay,
            error_gate=self._error_gate,
        )
