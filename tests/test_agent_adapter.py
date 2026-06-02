"""Tests for ``mykg.llm.agent_adapter.AgentAdapter``."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from mykg.llm.agent_adapter import AgentAdapter


def _make_adapter(tmp_path: Path, **overrides) -> AgentAdapter:
    kwargs = {
        "inbox_dir": tmp_path / "agent_inbox",
        "outbox_dir": tmp_path / "agent_outbox",
        "poll_interval": 0.05,
        "timeout": 5,
        "max_tokens": 1000,
    }
    kwargs.update(overrides)
    return AgentAdapter(**kwargs)


def _write_answer_atomic(outbox: Path, task_id: str, answer: str) -> None:
    """Mimics the skill's atomic write contract."""
    answer_path = outbox / f"{task_id}.answer.json"
    done_path = outbox / f"{task_id}.done"
    tmp = answer_path.with_suffix(answer_path.suffix + ".tmp")
    tmp.write_text(json.dumps({"task_id": task_id, "answer": answer}))
    tmp.replace(answer_path)
    done_path.touch()


def test_task_id_is_deterministic_sha256():
    """Same (system, user, context_label) → same task_id; different inputs → different ids."""
    a = AgentAdapter._make_task_id("sys", "usr", "ctx")
    b = AgentAdapter._make_task_id("sys", "usr", "ctx")
    c = AgentAdapter._make_task_id("sys", "usr", "ctx-different")
    d = AgentAdapter._make_task_id("sys-different", "usr", "ctx")

    assert a == b
    assert a != c
    assert a != d
    assert len(a) == 64  # hex sha256
    assert all(ch in "0123456789abcdef" for ch in a)


def test_endpoint_label_includes_inbox_path(tmp_path):
    adapter = _make_adapter(tmp_path)
    label = adapter.endpoint_label()
    assert "agent" in label
    assert "claude-code" in label
    assert str(tmp_path / "agent_inbox") in label


def test_complete_writes_task_and_returns_answer(tmp_path):
    adapter = _make_adapter(tmp_path, timeout=10)

    system = "you are a JSON producer"
    user = "produce a tiny JSON object"
    context_label = "pass1 batch 0/1"

    expected_task_id = AgentAdapter._make_task_id(system, user, context_label)
    expected_answer = '{"concepts": [], "properties": []}'

    def responder():
        # Wait for the inbox file to appear, then write the answer.
        inbox_file = tmp_path / "agent_inbox" / f"{expected_task_id}.task.json"
        for _ in range(200):
            if inbox_file.exists():
                break
            time.sleep(0.02)
        else:
            pytest.fail("inbox file never appeared")

        envelope = json.loads(inbox_file.read_text())
        assert envelope["task_id"] == expected_task_id
        assert envelope["step"] == "pass1"
        assert envelope["system"] == system
        assert envelope["user"] == user
        assert envelope["context_label"] == context_label
        _write_answer_atomic(tmp_path / "agent_outbox", expected_task_id, expected_answer)

    t = threading.Thread(target=responder, daemon=True)
    t.start()

    result = adapter.complete(system, user, context_label=context_label)
    t.join(timeout=5)

    assert result == expected_answer


def test_complete_cache_hit_skips_write(tmp_path):
    """If the answer already exists in the outbox, complete() returns it without polling."""
    adapter = _make_adapter(tmp_path, timeout=2)
    task_id = AgentAdapter._make_task_id("s", "u", "ctx")
    cached_answer = '{"cached": true}'

    _write_answer_atomic(tmp_path / "agent_outbox", task_id, cached_answer)
    assert not (tmp_path / "agent_inbox" / f"{task_id}.task.json").exists()

    t0 = time.monotonic()
    result = adapter.complete("s", "u", context_label="ctx")
    elapsed = time.monotonic() - t0

    assert result == cached_answer
    # Cache hit should be near-instant — no inbox write, no poll.
    assert elapsed < 1.0
    assert not (tmp_path / "agent_inbox" / f"{task_id}.task.json").exists()


def test_complete_timeout_raises(tmp_path):
    adapter = _make_adapter(tmp_path, timeout=1, poll_interval=0.05)

    t0 = time.monotonic()
    with pytest.raises(TimeoutError) as exc_info:
        adapter.complete("s", "u", context_label="ctx")
    elapsed = time.monotonic() - t0

    assert "timed out" in str(exc_info.value)
    # Should have waited approximately the timeout (within poll-interval tolerance).
    assert 0.9 <= elapsed <= 2.5


def test_atomic_write_via_tmp_rename(tmp_path):
    """The task envelope must be written through a .tmp + rename to avoid half-written reads."""
    adapter = _make_adapter(tmp_path, timeout=10)
    task_id = AgentAdapter._make_task_id("s", "u", "")

    inbox_dir = tmp_path / "agent_inbox"

    saw_tmp = threading.Event()
    saw_final = threading.Event()

    def watcher():
        for _ in range(400):
            for p in inbox_dir.glob("*.tmp"):
                saw_tmp.set()
            if (inbox_dir / f"{task_id}.task.json").exists():
                saw_final.set()
                _write_answer_atomic(tmp_path / "agent_outbox", task_id, '"ok"')
                return
            time.sleep(0.005)

    t = threading.Thread(target=watcher, daemon=True)
    t.start()
    adapter.complete("s", "u", context_label="")
    t.join(timeout=5)

    assert saw_final.is_set()
    # No .tmp file should be left behind.
    assert not list(inbox_dir.glob("*.tmp"))
