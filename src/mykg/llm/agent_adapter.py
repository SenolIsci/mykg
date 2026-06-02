"""Agent-mode LLM adapter — produces answers via filesystem inbox/outbox.

The adapter writes a task envelope to ``<intermediate>/<inbox>/<task_id>.task.json``
and polls ``<outbox>/<task_id>.done`` for a sentinel file. A skill running in the
host coding assistant (e.g. Claude Code) drains the inbox, dispatches subagents,
and writes ``<task_id>.answer.json`` + ``<task_id>.done`` atomically.

The full contract is documented in ``docs/agent-mode.md`` and CLAUDE.md (D49).
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from mykg.llm.adapter import LLMAdapter
from mykg.logging import get, record_llm_call

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate


log = get("mykg.llm.agent")


class TaskEnvelope(BaseModel):
    """Task envelope written by the adapter to the inbox."""

    task_id: str
    step: str = ""
    context_label: str = ""
    system: str
    user: str
    max_tokens: int
    timeout_seconds: int
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class AnswerEnvelope(BaseModel):
    """Answer envelope written by the skill subagent to the outbox."""

    task_id: str
    answer: str


class AgentAdapter(LLMAdapter):
    """Filesystem-based adapter that delegates to a host-side agent skill.

    See ``src/mykg/data/skills/mykg/SKILL.md`` for the skill side of the contract.
    """

    def __init__(
        self,
        inbox_dir: Path,
        outbox_dir: Path,
        poll_interval: float,
        timeout: int,
        max_tokens: int,
        error_gate: ErrorGate | None = None,
    ):
        self._inbox = Path(inbox_dir)
        self._outbox = Path(outbox_dir)
        self._poll_interval = float(poll_interval)
        self._timeout = int(timeout)
        self._max_tokens = int(max_tokens)
        self._error_gate = error_gate

        self._inbox.mkdir(parents=True, exist_ok=True)
        self._outbox.mkdir(parents=True, exist_ok=True)

    def endpoint_label(self) -> str:
        return f"agent / claude-code (inbox={self._inbox})"

    @staticmethod
    def _make_task_id(system: str, user: str, context_label: str) -> str:
        h = hashlib.sha256()
        h.update(system.encode("utf-8"))
        h.update(b"\n--user--\n")
        h.update(user.encode("utf-8"))
        h.update(b"\n--ctx--\n")
        h.update(context_label.encode("utf-8"))
        return h.hexdigest()

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2))
        tmp.replace(path)

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

        task_id = self._make_task_id(system, user, context_label)
        task_path = self._inbox / f"{task_id}.task.json"
        answer_path = self._outbox / f"{task_id}.answer.json"
        done_path = self._outbox / f"{task_id}.done"

        t0 = time.monotonic()

        # Cache hit: re-use an existing answer from a prior run or duplicate task.
        if done_path.exists() and answer_path.exists():
            return self._finish(answer_path, context_label, system, user, t0)

        # Existing call sites use space-separated labels like "pass1 batch 0/1",
        # "pass2 chunk 3", "orphan stage2 …", "schema_harmonize" — first token wins.
        step_label = context_label.split(None, 1)[0] if context_label else ""

        envelope = TaskEnvelope(
            task_id=task_id,
            step=step_label,
            context_label=context_label,
            system=system,
            user=user,
            max_tokens=effective_max_tokens,
            timeout_seconds=effective_timeout,
        )
        self._atomic_write_json(task_path, envelope.model_dump())
        log.info("agent: wrote task %s (step=%s)", task_id[:12], step_label or "?")

        deadline = time.monotonic() + effective_timeout
        while time.monotonic() < deadline:
            if done_path.exists():
                return self._finish(answer_path, context_label, system, user, t0)
            time.sleep(self._poll_interval)

        exc = TimeoutError(
            f"agent task {task_id[:12]} timed out after {effective_timeout}s "
            f"(inbox={self._inbox}, no .done sentinel appeared)"
        )
        if self._error_gate is not None:
            self._error_gate.record_error(exc)
        raise exc

    def _finish(
        self,
        answer_path: Path,
        context_label: str,
        system: str,
        user: str,
        t0: float,
    ) -> str:
        """Read the answer, log the call, return the (fence-stripped) string."""
        answer = json.loads(answer_path.read_text()).get("answer", "")
        record_llm_call(
            provider="agent",
            model="claude-code",
            context_label=context_label,
            input_tokens=0,
            output_tokens=0,
            duration_s=time.monotonic() - t0,
            raw_response=answer,
            system_prompt=system,
            user_prompt=user,
        )
        return self.strip_code_fences(answer)
