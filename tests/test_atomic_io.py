from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mykg.utility.atomic_io import atomic_write_json


def test_writes_correct_content(tmp_path: Path) -> None:
    target = tmp_path / "edge_metadata.json"
    data = {"edge-1": {"type": "works_at", "from": "a", "to": "b"}}

    atomic_write_json(target, data)

    assert json.loads(target.read_text()) == data


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
