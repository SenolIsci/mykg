from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING

import anthropic

from mykg.llm.adapter import LLMAdapter
from mykg.llm.retry import looks_like_context_exceeded, retry_on_rate_limit
from mykg.logging import record_llm_call

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate


class AnthropicAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        max_tokens: int,
        timeout: int,
        base_url: str | None = None,
        api_key: str | None = None,
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
            api_key = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required — set ANTHROPIC_API_KEY or "
                "ANTHROPIC_AUTH_TOKEN in your environment, or supply api_key in "
                "mykg_config.yaml"
            )

        self._timeout = timeout
        self._base_url = base_url
        self._client = anthropic.Anthropic(api_key=api_key, base_url=base_url, timeout=timeout)

    def endpoint_label(self) -> str:
        url = self._base_url or "https://api.anthropic.com"
        return f"anthropic / {self._model} @ {url}"

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
                message = self._client.messages.create(
                    model=self._model,
                    max_tokens=effective_max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    timeout=effective_timeout,
                )
            except anthropic.APIStatusError as exc:
                if looks_like_context_exceeded(exc):
                    record_llm_call(
                        provider="anthropic",
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
            raw = ""
            for block in message.content:
                if hasattr(block, "text"):
                    raw = block.text
                    break
            # Anthropic's stop_reason == "max_tokens" means output was truncated at
            # the max_tokens cap — surfaced for diagnosability only (see Invariant 13:
            # window/max_tokens sizing should prevent this in normal operation).
            finish_reason = "max_tokens" if message.stop_reason == "max_tokens" else None
            record_llm_call(
                provider="anthropic",
                model=self._model,
                context_label=context_label,
                input_tokens=message.usage.input_tokens,
                output_tokens=message.usage.output_tokens,
                duration_s=time.monotonic() - t0,
                raw_response=raw,
                system_prompt=system,
                user_prompt=user,
                finish_reason=finish_reason,
            )
            return self.strip_code_fences(raw)

        return retry_on_rate_limit(  # type: ignore[return-value]
            _call,
            anthropic.RateLimitError,
            "Anthropic",
            self._retry_429_max,
            self._retry_429_base_delay,
            error_gate=self._error_gate,
        )
