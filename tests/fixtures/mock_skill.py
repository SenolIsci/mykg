"""Mock skill — drains the agent-mode inbox with canned answers.

Used by ``tests/test_agent_mode_live.py``. Runs as a background thread (or
standalone subprocess); polls ``intermediate/agent_inbox/`` for ``*.task.json``
files, reads the ``step`` field of each envelope, returns a canned JSON answer
that matches the step's expected schema, and writes ``<id>.answer.json`` plus
``<id>.done`` to ``intermediate/agent_outbox/`` atomically.

Canned answers are intentionally minimal — just enough to let the pipeline
complete every step without LLM errors. The goal is to verify the inbox/outbox
contract works end-to-end, not to produce a high-quality graph.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Canned answers per pipeline step
# ---------------------------------------------------------------------------


def _pass1_answer() -> str:
    """Minimal valid schema with one concept and one property."""
    return json.dumps(
        {
            "concepts": [
                {"type": "Person", "parent": None, "attributes": ["name"]},
                {"type": "Organization", "parent": None, "attributes": ["name"]},
            ],
            "properties": [
                {
                    "name": "works_at",
                    "domain": "Person",
                    "range": "Organization",
                    "attributes": [],
                }
            ],
        }
    )


def _pass2_answer() -> str:
    """Minimal valid extraction — one Person, one Organization, one edge."""
    return json.dumps(
        {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {
                        "name": {"value": "Alice", "confidence": 0.95}
                    },
                    "confidence": 0.95,
                },
                {
                    "id": "organization-acme-corp",
                    "type": "Organization",
                    "attributes": {
                        "name": {"value": "Acme Corp", "confidence": 0.95}
                    },
                    "confidence": 0.95,
                },
            ],
            "edges": [
                {
                    "type": "works_at",
                    "from": "person-alice",
                    "to": "organization-acme-corp",
                    "attributes": {},
                    "confidence": 0.9,
                }
            ],
        }
    )


def _normalize_answer() -> str:
    """Minimal normalization map — no aliases to resolve."""
    return json.dumps({"mappings": {}})


def _orphan_chunk_answer() -> str:
    return json.dumps({"edges": []})


def _orphan_pair_answer() -> str:
    return json.dumps({"answer": "no"})


def _orphan_schema_gap_answer() -> str:
    return json.dumps({"new_properties": []})


def _schema_merge_answer() -> str:
    """Harmonize / quality steps — pass schema through unchanged-ish."""
    return _pass1_answer()


def _feedback_schema_answer() -> str:
    return _pass1_answer()


_DISPATCH = {
    "pass1": _pass1_answer,
    "pass2": _pass2_answer,
    "normalize_names": _normalize_answer,
    "normalize": _normalize_answer,
    "schema_harmonize": _schema_merge_answer,
    "schema_quality_review": _schema_merge_answer,
    "merge_schema_harmonize": _schema_merge_answer,
    "merge_schema_quality_review": _schema_merge_answer,
    "orphan": _orphan_pair_answer,
    "feedback": _feedback_schema_answer,
}


def _route(envelope: dict) -> str:
    step = (envelope.get("step") or "").lower()
    context_label = (envelope.get("context_label") or "").lower()

    if step in _DISPATCH:
        return _DISPATCH[step]()

    # Fallbacks by inspecting context_label keywords.
    if "chunk_recovery" in context_label or "schema-gap" in context_label:
        return _orphan_chunk_answer() if "chunk" in context_label else _orphan_schema_gap_answer()
    if "stage2" in context_label or "confirm" in context_label:
        return _orphan_pair_answer()
    if "harmoniz" in context_label or "quality" in context_label:
        return _schema_merge_answer()
    if "feedback" in context_label:
        return _feedback_schema_answer()
    if "normaliz" in context_label:
        return _normalize_answer()
    if "pass1" in context_label:
        return _pass1_answer()
    if "pass2" in context_label:
        return _pass2_answer()

    # Last resort — return a valid-looking pass2 answer.
    return _pass2_answer()


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------


def _atomic_write(path: Path, payload: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload)
    tmp.replace(path)


def handle_task(task_path: Path, outbox: Path) -> None:
    envelope = json.loads(task_path.read_text())
    task_id = envelope["task_id"]
    answer_path = outbox / f"{task_id}.answer.json"
    done_path = outbox / f"{task_id}.done"
    if done_path.exists():
        return
    answer_text = _route(envelope)
    payload = json.dumps({"task_id": task_id, "answer": answer_text})
    _atomic_write(answer_path, payload)
    # Touch the .done sentinel last (after answer file is fully on disk).
    done_path.touch()


def run_watcher(
    inbox: Path,
    outbox: Path,
    stop_after_seconds: float,
    poll_interval: float = 0.2,
) -> int:
    """Drain the inbox until stop_after_seconds elapse. Returns task count handled."""
    inbox.mkdir(parents=True, exist_ok=True)
    outbox.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + stop_after_seconds
    handled = 0
    while time.monotonic() < deadline:
        for task_path in sorted(inbox.glob("*.task.json")):
            task_id = task_path.name.removesuffix(".task.json")
            if (outbox / f"{task_id}.done").exists():
                continue
            try:
                handle_task(task_path, outbox)
                handled += 1
            except json.JSONDecodeError:
                # Half-written task file — try again next pass.
                continue
        time.sleep(poll_interval)
    return handled


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mock mykg agent-mode skill")
    parser.add_argument("--inbox", required=True, type=Path)
    parser.add_argument("--outbox", required=True, type=Path)
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--poll", type=float, default=0.2)
    args = parser.parse_args(argv)
    handled = run_watcher(
        args.inbox, args.outbox, args.seconds, poll_interval=args.poll
    )
    print(f"mock_skill: handled {handled} tasks", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
