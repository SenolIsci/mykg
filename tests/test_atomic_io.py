from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from mykg.utility import atomic_io
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
    """Bytes are fsync'd to disk before the rename, guarding against power loss.

    A further fsync of the directory follows the replace (see
    test_write_json_fsyncs_directory_after_replace), so only the leading order
    is asserted here.
    """
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

    assert calls[:2] == ["fsync", "replace"], "fsync must happen before the atomic rename"


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

    assert calls[:2] == ["fsync", "replace"], "fsync must happen before the atomic rename"


def _trace_syncs(monkeypatch) -> list[str]:
    """Record the order of file-fsync / replace / dir-fsync calls."""
    calls: list[str] = []
    real_fsync = os.fsync
    real_replace = os.replace
    real_open = os.open

    dir_fds: set[int] = set()

    def traced_open(p, flags, *a, **kw):
        fd = real_open(p, flags, *a, **kw)
        if Path(p).is_dir():
            dir_fds.add(fd)
        return fd

    def traced_fsync(fd):
        calls.append("fsync_dir" if fd in dir_fds else "fsync_file")
        return real_fsync(fd)

    def traced_replace(src, dst):
        calls.append("replace")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "open", traced_open)
    monkeypatch.setattr(os, "fsync", traced_fsync)
    monkeypatch.setattr(os, "replace", traced_replace)
    return calls


@pytest.mark.skipif(sys.platform == "win32", reason="no directory fsync on Windows")
def test_write_json_fsyncs_directory_after_replace(tmp_path: Path, monkeypatch) -> None:
    """Fsyncing the file persists its contents; the rename that publishes it is
    separate metadata and needs its own flush, or a power loss just after
    os.replace can leave the target absent."""
    calls = _trace_syncs(monkeypatch)

    atomic_write_json(tmp_path / "nodes.json", {"ok": True})

    assert calls == ["fsync_file", "replace", "fsync_dir"]


@pytest.mark.skipif(sys.platform == "win32", reason="no directory fsync on Windows")
def test_write_lines_fsyncs_directory_after_replace(tmp_path: Path, monkeypatch) -> None:
    calls = _trace_syncs(monkeypatch)

    atomic_write_lines(tmp_path / "nodes.jsonl", ['{"a": 1}'])

    assert calls == ["fsync_file", "replace", "fsync_dir"]


def test_dir_fsync_skipped_on_windows(tmp_path: Path, monkeypatch) -> None:
    """Windows has no directory fd to fsync, so the step is skipped rather than
    raising — the rename has already succeeded by then."""
    monkeypatch.setattr(sys, "platform", "win32")
    opened: list[object] = []

    def traced_open(p, flags, *a, **kw):
        opened.append(p)
        raise AssertionError("os.open must not be called on Windows")

    monkeypatch.setattr(os, "open", traced_open)

    atomic_io._fsync_dir(tmp_path / "nodes.json")

    assert opened == [], "should not try to open a directory fd on Windows"


def test_dir_fsync_tolerates_unsupported_filesystem(tmp_path: Path, monkeypatch) -> None:
    """If the directory cannot be opened or synced (some network mounts), the
    write is still correct — os.replace already happened — so the error is
    swallowed rather than failing a completed write."""
    def boom(*a, **kw):
        raise OSError("directory fsync unsupported")

    monkeypatch.setattr(os, "open", boom)

    atomic_write_json(tmp_path / "nodes.json", {"ok": True})

    assert json.loads((tmp_path / "nodes.json").read_text()) == {"ok": True}
