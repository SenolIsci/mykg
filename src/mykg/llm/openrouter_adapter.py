from __future__ import annotations

import concurrent.futures
import os
import time
from typing import TYPE_CHECKING

import httpx
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


class OpenRouterAdapter(LLMAdapter):
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
            api_key = os.environ.get("OPENROUTER_AUTH_TOKEN") or os.environ.get(
                "OPENROUTER_API_KEY"
            )
        if not api_key:
            raise ValueError(
                "OPENROUTER_AUTH_TOKEN (or OPENROUTER_API_KEY) is required — "
                "set it in your environment or supply api_key in mykg_config.yaml"
            )

        self._timeout = timeout
        self._base_url = base_url or "https://openrouter.ai/api/v1"
        # httpx.Timeout enforces per-chunk read timeout so keep-alive bytes
        # from OpenRouter cannot reset the clock indefinitely.
        http_timeout = httpx.Timeout(timeout=float(timeout), connect=10.0)
        self._client = openai.OpenAI(
            api_key=api_key,
            base_url=self._base_url,
            timeout=http_timeout,
        )

    def endpoint_label(self) -> str:
        return f"openrouter / {self._model} @ {self._base_url}"

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

            def _do_request() -> tuple[str, object, str | None]:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    max_tokens=effective_max_tokens,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                )
                usage = resp.usage
                raw = resp.choices[0].message.content or "" if resp.choices else ""
                choice_finish_reason = resp.choices[0].finish_reason if resp.choices else None
                finish_reason = "length" if choice_finish_reason == "length" else None
                return raw, usage, finish_reason

            # Hard wall-clock deadline — prevents OpenRouter keep-alive bytes
            # from resetting the httpx read timeout indefinitely.
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_request)
                try:
                    raw, usage, finish_reason = future.result(timeout=effective_timeout)
                except concurrent.futures.TimeoutError:
                    duration_s = time.monotonic() - t0
                    record_llm_call(
                        provider="openrouter",
                        model=self._model,
                        context_label=context_label,
                        input_tokens=0,
                        output_tokens=0,
                        duration_s=duration_s,
                        system_prompt=system,
                        user_prompt=user,
                        error=f"wall-clock timeout after {effective_timeout}s",
                    )
                    raise TimeoutError(
                        f"OpenRouter call exceeded wall-clock timeout of {effective_timeout}s"
                    )

            if finish_reason is not None:
                log_truncated_output("openrouter", self._model, context_label, finish_reason)
            record_llm_call(
                provider="openrouter",
                model=self._model,
                context_label=context_label,
                input_tokens=usage.prompt_tokens if usage else 0,
                output_tokens=usage.completion_tokens if usage else 0,
                duration_s=time.monotonic() - t0,
                raw_response=raw,
                system_prompt=system,
                user_prompt=user,
                finish_reason=finish_reason,
            )
            return self.strip_code_fences(raw)

        def _call_with_http_error_handling() -> str:
            try:
                return _call()
            except openai.RateLimitError:
                raise  # handled by retry_on_rate_limit below
            except openai.APIStatusError as exc:
                status = exc.status_code
                error_msg = str(exc.message)
                if looks_like_context_exceeded(exc):
                    log_context_overflow("openrouter", self._model, context_label, exc)
                    error_msg = f"context_length_exceeded: {error_msg}"
                record_llm_call(
                    provider="openrouter",
                    model=self._model,
                    context_label=context_label,
                    input_tokens=0,
                    output_tokens=0,
                    duration_s=0.0,
                    system_prompt=system,
                    user_prompt=user,
                    status_code=status,
                    error=error_msg,
                )
                # Retry 5xx as transient; surface all others immediately.
                if status >= 500:
                    raise openai.RateLimitError(
                        f"OpenRouter {status} (retrying as transient): {exc.message}",
                        response=exc.response,
                        body=exc.body,
                    )
                raise

        return retry_on_rate_limit(  # type: ignore[return-value]
            _call_with_http_error_handling,
            openai.RateLimitError,
            "OpenRouter",
            self._retry_429_max,
            self._retry_429_base_delay,
            error_gate=self._error_gate,
        )
