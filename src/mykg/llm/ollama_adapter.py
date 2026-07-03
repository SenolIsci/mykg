from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from mykg.llm.adapter import LLMAdapter
from mykg.llm.retry import looks_like_context_exceeded, retry_on_rate_limit
from mykg.logging import record_llm_call

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate


class OllamaAdapter(LLMAdapter):
    def __init__(
        self,
        model: str,
        base_url: str,
        timeout: int,
        stream: bool,
        max_tokens: int,
        context_window: int,
        retry_429_max: int = 5,
        retry_429_base_delay: float = 2.0,
        error_gate: ErrorGate | None = None,
    ):
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._stream = stream
        self._max_tokens = max_tokens
        self._context_window = context_window
        self._retry_429_max = retry_429_max
        self._retry_429_base_delay = retry_429_base_delay
        self._error_gate = error_gate

    def endpoint_label(self) -> str:
        return f"ollama / {self._model} @ {self._base_url}"

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
        payload = json.dumps(
            {
                "model": self._model,
                "prompt": f"<system>\n{system}\n</system>\n\n{user}",
                "stream": self._stream,
                "options": {
                    # num_ctx sizes the model's context window (prompt + output).
                    # Without it Ollama silently falls back to a small default
                    # (often 4096), truncating large Pass 1 prompts to ~1 output
                    # token. Set it from the profile's configured context_window.
                    "num_ctx": self._context_window,
                    "num_predict": effective_max_tokens,
                },
            }
        ).encode()

        req = urllib.request.Request(
            f"{self._base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )

        def _call() -> str:
            t0 = time.monotonic()
            try:
                with urllib.request.urlopen(req, timeout=effective_timeout) as resp:
                    data = json.loads(resp.read())
                    raw = data.get("response", "")
                    # done_reason == "length" means output was truncated at the
                    # num_predict cap — surfaced for diagnosability only (see
                    # Invariant 13: window/max_tokens sizing should prevent this in
                    # normal operation).
                    done_reason = data.get("done_reason")
                    finish_reason = "length" if done_reason == "length" else None
                    record_llm_call(
                        provider="ollama",
                        model=self._model,
                        context_label=context_label,
                        input_tokens=data.get("prompt_eval_count", 0),
                        output_tokens=data.get("eval_count", 0),
                        duration_s=time.monotonic() - t0,
                        raw_response=raw,
                        system_prompt=system,
                        user_prompt=user,
                        finish_reason=finish_reason,
                    )
                    return self.strip_code_fences(raw)
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    raise
                if looks_like_context_exceeded(exc):
                    record_llm_call(
                        provider="ollama",
                        model=self._model,
                        context_label=context_label,
                        input_tokens=0,
                        output_tokens=0,
                        duration_s=time.monotonic() - t0,
                        system_prompt=system,
                        user_prompt=user,
                        error=f"context_length_exceeded: {exc}",
                    )
                raise RuntimeError(f"Ollama request failed: {exc}") from exc
            except urllib.error.URLError as exc:
                if looks_like_context_exceeded(exc):
                    record_llm_call(
                        provider="ollama",
                        model=self._model,
                        context_label=context_label,
                        input_tokens=0,
                        output_tokens=0,
                        duration_s=time.monotonic() - t0,
                        system_prompt=system,
                        user_prompt=user,
                        error=f"context_length_exceeded: {exc}",
                    )
                raise RuntimeError(f"Ollama request failed: {exc}") from exc

        return retry_on_rate_limit(  # type: ignore[return-value]
            _call,
            urllib.error.HTTPError,
            "Ollama",
            self._retry_429_max,
            self._retry_429_base_delay,
            error_gate=self._error_gate,
        )
