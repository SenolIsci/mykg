"""Unit tests for D58 shard eviction and the _fname_slug collision guard."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from mykg.steps.step_pass2 import _fname_slug, _unlink_shard_if_owned


def _shard(path: Path, fname: str) -> Path:
    path.write_text(json.dumps({"_fname": fname, "data": {"nodes": []}}), encoding="utf-8")
    return path


def test_shard_owned_by_deleted_file_is_unlinked(tmp_path):
    shard = _shard(tmp_path / "a.md.json", "a.md")

    _unlink_shard_if_owned(shard, "a.md")

    assert not shard.exists()


def test_colliding_shard_survives_and_warns(tmp_path, caplog):
    """_fname_slug maps / and _ to the same char, so `docs/a.md` and `docs_a.md`
    share a shard name. Unlinking blind would destroy the surviving file's
    extraction with nothing to re-create it — deletion has no re-extraction
    backstop the way a modification does.
    """
    shard = _shard(tmp_path / "docs_a.md.json", "docs_a.md")
    assert _fname_slug("docs/a.md") == _fname_slug("docs_a.md")

    with caplog.at_level(logging.WARNING):
        _unlink_shard_if_owned(shard, "docs/a.md")

    assert shard.exists(), "surviving file's shard must not be destroyed"
    assert "collision" in caplog.text


def test_unreadable_shard_is_left_alone(tmp_path, caplog):
    shard = tmp_path / "bad.json"
    shard.write_text("{not json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        _unlink_shard_if_owned(shard, "bad.md")

    assert shard.exists()
    assert "unreadable" in caplog.text


def test_missing_shard_is_a_no_op(tmp_path):
    _unlink_shard_if_owned(tmp_path / "nope.json", "nope.md")
