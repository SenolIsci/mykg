from __future__ import annotations

import json
import shutil
import subprocess
import time
from typing import TYPE_CHECKING

from mykg.config import LOG_ERROR_OUTPUT_MAX_CHARS
from mykg.llm.adapter import LLMAdapter
from mykg.logging import record_llm_call

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate


class ClaudeCLIAdapter(LLMAdapter):
    def __init__(
        self,
        max_tokens: int,
        timeout: int,
        model: str = "auto",
        effort: str = "auto",
        error_gate: ErrorGate | None = None,
        temperature: float | None = None,
    ):
        if shutil.which("claude") is None:
            raise RuntimeError(
                "Claude Code CLI not found on $PATH. "
                "Install from https://claude.ai/code and run `claude` once to authenticate."
            )
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._model = model
        self._effort = effort
        self._error_gate = error_gate
        # Accepted for interface uniformity but deliberately unused: `claude -p`
        # exposes no temperature flag, so there is nothing to forward it to.
        # Same precedent as _max_tokens above, which the CLI also has no way to
        # honour. Do not "fix" this by inventing a flag.
        self._temperature = temperature

    def endpoint_label(self) -> str:
        model_part = self._model if self._model != "auto" else "default"
        effort_part = f", effort={self._effort}" if self._effort != "auto" else ""
        return f"claude-cli / claude (model={model_part}{effort_part})"

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        t0 = time.monotonic()
        effective_timeout = timeout if timeout is not None else self._timeout
        no_skills = "Do not invoke any skills or tools. Respond directly with JSON only.\n\n"
        cmd = [
            "claude",
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--system-prompt",
            no_skills + system,
        ]
        if self._model != "auto":
            cmd += ["--model", self._model]
        if self._effort != "auto":
            cmd += ["--effort", self._effort]
        try:
            proc = subprocess.run(
                cmd,
                input=user,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=effective_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            if self._error_gate:
                self._error_gate.record_error(exc)
            raise RuntimeError(f"claude -p timed out after {effective_timeout}s") from exc

        if proc.returncode != 0:
            stderr = proc.stderr.strip()[:LOG_ERROR_OUTPUT_MAX_CHARS]
            stdout = proc.stdout.strip()[:LOG_ERROR_OUTPUT_MAX_CHARS]
            detail = stderr or stdout or "(no output)"
            exc = RuntimeError(f"claude -p exited {proc.returncode}: {detail}")
            if self._error_gate:
                self._error_gate.record_error(exc)
            raise exc

        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            err = RuntimeError(
                f"claude -p produced unparseable JSON envelope: {exc}; "
                f"first 500 chars of stdout: {proc.stdout[:500]!r}"
            )
            if self._error_gate:
                self._error_gate.record_error(err)
            raise err from exc

        usage = envelope.get("usage") or {}
        input_tokens = int(usage.get("input_tokens", 0) or 0)
        cache_read_tokens = int(usage.get("cache_read_input_tokens", 0) or 0)
        cache_creation_tokens = int(usage.get("cache_creation_input_tokens", 0) or 0)
        output_tokens = int(usage.get("output_tokens", 0) or 0)

        raw = envelope.get("result", "")
        record_llm_call(
            provider="claude-cli",
            model=self._model if self._model != "auto" else "claude-cli",
            context_label=context_label,
            input_tokens=input_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            output_tokens=output_tokens,
            duration_s=time.monotonic() - t0,
            raw_response=proc.stdout,
            system_prompt=system,
            user_prompt=user,
        )

        return self.strip_code_fences(raw)
