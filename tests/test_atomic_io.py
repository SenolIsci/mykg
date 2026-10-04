from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mykg.utility.atomic_io import atomic_write_json, atomic_write_lines


def test_writes_correct_content(tmp_path: Path) -> None:
    target = tmp_path / "edge_metadata.json"
    data = {"edge-1": {"type": "works_at", "from": "a", "to": "b"}}

    atomic_write_json(target, data)

    assert json.loads(target.read_text()) == data


def test_writes_non_ascii_content_as_utf8(tmp_path: Path) -> None:
    target = tmp_path / "nodes.json"
    data = {"name": "café Müller 中文"}

    atomic_write_json(target, data)

    assert json.loads(target.read_text(encoding="utf-8")) == data


def test_overwrites_existing_file(tmp_path: Path) -> None:
    target = tmp_path / "nodes.json"
    target.write_text(json.dumps({"old": True}))

    atomic_write_json(target, {"new": True})

    assert json.loads(target.read_text()) == {"new": True}


def test_serializes_lists(tmp_path: Path) -> None:
    target = tmp_path / "orphan_log.json"
    data = [{"event": "orphan_edge_added"}, {"event": "orphan_edge_rejected"}]

    atomic_write_json(target, data)

    assert json.loads(target.read_text()) == data


def test_leaves_no_tmp_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "schema_gap_proposals.json"

    atomic_write_json(target, {"new_properties": []})

    assert not (tmp_path / "schema_gap_proposals.json.tmp").exists()
    assert list(tmp_path.iterdir()) == [target]


def test_crash_mid_replace_preserves_old_file(tmp_path: Path, monkeypatch) -> None:
    """If os.replace fails (crash window), the original target must remain intact —
    never a truncated file. This is the core guarantee item 23 asks for."""
    target = tmp_path / "edge_metadata.json"
    target.write_text(json.dumps({"intact": True}))

    def boom(src, dst):
        raise OSError("simulated crash during replace")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        atomic_write_json(target, {"new": "data"})

    # Old content survives — no partial/truncated write reached the target.
    assert json.loads(target.read_text()) == {"intact": True}
    # The temp file from the failed write is cleaned up, not left behind.
    assert not (tmp_path / "edge_metadata.json.tmp").exists()


def test_fsync_called_before_replace(tmp_path: Path, monkeypatch) -> None:
    """Bytes are fsync'd to disk before the rename, guarding against power loss."""
    calls: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def traced_fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    def traced_replace(src, dst):
        calls.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "replace", traced_replace)

    atomic_write_json(tmp_path / "nodes.json", {"ok": True})

    assert calls == ["fsync", "replace"], "fsync must happen before the atomic rename"


def test_write_lines_writes_one_line_each_and_returns_count(tmp_path: Path) -> None:
    target = tmp_path / "nodes.jsonl"

    assert atomic_write_lines(target, ['{"a": 1}', '{"b": 2}']) == 2

    assert target.read_text(encoding="utf-8") == '{"a": 1}\n{"b": 2}\n'


def test_write_lines_empty_input_writes_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "edges.jsonl"

    assert atomic_write_lines(target, []) == 0

    assert target.read_text(encoding="utf-8") == ""


def test_write_lines_writes_non_ascii_as_utf8(tmp_path: Path) -> None:
    target = tmp_path / "nodes.jsonl"

    atomic_write_lines(target, ['{"name": "café Müller 中文"}'])

    assert json.loads(target.read_text(encoding="utf-8")) == {"name": "café Müller 中文"}


def test_write_lines_consumes_lazily(tmp_path: Path) -> None:
    """The payload must be pulled one line at a time, never materialized —
    that is the whole point of streaming rather than joining."""
    live = 0
    peak = 0

    def gen():
        nonlocal live, peak
        for i in range(100):
            live += 1
            peak = max(peak, live)
            yield f'{{"i": {i}}}'
            live -= 1

    assert atomic_write_lines(tmp_path / "nodes.jsonl", gen()) == 100
    assert peak == 1, "more than one line was live at once — payload was materialized"


def test_write_lines_raise_mid_iteration_preserves_old_file(tmp_path: Path) -> None:
    """A crash partway through must leave the previous file intact. Without the
    tmp+replace indirection this would leave a short-but-valid JSONL file that
    readers accept as complete."""
    target = tmp_path / "nodes.jsonl"
    target.write_text('{"original": true}\n', encoding="utf-8")

    def boom():
        yield '{"a": 1}'
        raise RuntimeError("simulated crash mid-export")

    with pytest.raises(RuntimeError):
        atomic_write_lines(target, boom())

    assert target.read_text(encoding="utf-8") == '{"original": true}\n'
    assert not (tmp_path / "nodes.jsonl.tmp").exists()


def test_write_lines_leaves_no_tmp_file_on_success(tmp_path: Path) -> None:
    target = tmp_path / "nodes.jsonl"

    atomic_write_lines(target, ['{"a": 1}'])

    assert list(tmp_path.iterdir()) == [target]


def test_write_lines_fsync_called_before_replace(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace

    def traced_fsync(fd):
        calls.append("fsync")
        return real_fsync(fd)

    def traced_replace(src, dst):
        calls.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "replace", traced_replace)

    atomic_write_lines(tmp_path / "nodes.jsonl", ['{"a": 1}'])

    assert calls == ["fsync", "replace"], "fsync must happen before the atomic rename"
