"""Tests for the D58 folder registry (`intermediate/raw_input_folder.json`).

Covers prefix assignment, collision disambiguation, legacy single-path
synthesis, round-tripping, and the folder-turned-file guard.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg import folder_registry as fr


def _dirs(tmp_path: Path, *names: str) -> list[Path]:
    out = []
    for n in names:
        p = tmp_path / n
        p.mkdir(parents=True, exist_ok=True)
        out.append(p)
    return out


# ---------------------------------------------------------------------------
# load
# ---------------------------------------------------------------------------


def test_load_missing_file_returns_empty_registry(tmp_path):
    assert fr.load(tmp_path).folders == []


def test_load_corrupt_file_returns_empty_registry(tmp_path):
    (tmp_path / fr.REGISTRY_FILENAME).write_text("{not json", encoding="utf-8")
    assert fr.load(tmp_path).folders == []


def test_load_synthesises_single_folder_from_legacy_file(tmp_path):
    """A pre-D58 file has only original_input_dir — read it as one unprefixed folder.

    This is what lets existing sessions work with no migration: their files are
    already at flat mirror paths, which is exactly what an empty prefix means.
    """
    (legacy,) = _dirs(tmp_path, "legacy")
    (tmp_path / fr.REGISTRY_FILENAME).write_text(
        json.dumps({"original_input_dir": str(legacy)}), encoding="utf-8"
    )

    registry = fr.load(tmp_path)

    assert len(registry.folders) == 1
    assert registry.folders[0].mirror_prefix == ""
    assert fr.resolve(registry, legacy) is not None


# ---------------------------------------------------------------------------
# register
# ---------------------------------------------------------------------------


def test_first_folder_gets_empty_prefix(tmp_path):
    """Single-folder sessions must keep their pre-D58 flat mirror layout."""
    (a,) = _dirs(tmp_path, "notes")
    registry = fr.Registry()

    entry = fr.register(registry, a)

    assert entry.mirror_prefix == ""
    assert registry.original_input_dir == str(a.resolve())


def test_second_folder_gets_basename_prefix(tmp_path):
    a, b = _dirs(tmp_path, "notes", "manuals")
    registry = fr.Registry()
    fr.register(registry, a)

    assert fr.register(registry, b).mirror_prefix == "manuals/"


def test_colliding_basenames_are_disambiguated(tmp_path):
    """Two folders named `manuals` must not share a mirror subtree."""
    a, b, c = _dirs(tmp_path, "notes", "manuals", "other/manuals")
    registry = fr.Registry()
    fr.register(registry, a)
    fr.register(registry, b)

    assert fr.register(registry, c).mirror_prefix == "manuals-2/"


def test_hidden_basename_is_sanitised(tmp_path):
    """A dot-prefixed prefix would be skipped by every hidden-path filter."""
    a, b = _dirs(tmp_path, "notes", ".cache")
    registry = fr.Registry()
    fr.register(registry, a)

    prefix = fr.register(registry, b).mirror_prefix

    assert not prefix.startswith(".")
    assert prefix == "cache/"


# ---------------------------------------------------------------------------
# resolve / save
# ---------------------------------------------------------------------------


def test_resolve_matches_known_folder_and_rejects_unknown(tmp_path):
    a, b = _dirs(tmp_path, "notes", "elsewhere")
    registry = fr.Registry()
    fr.register(registry, a)

    assert fr.resolve(registry, a) is not None
    assert fr.resolve(registry, b) is None


def test_resolve_normalises_relative_and_dotted_paths(tmp_path):
    (a,) = _dirs(tmp_path, "notes")
    registry = fr.Registry()
    fr.register(registry, a)

    assert fr.resolve(registry, tmp_path / "notes" / ".") is not None
    assert fr.resolve(registry, tmp_path / "sub" / ".." / "notes") is not None


def test_resolve_raises_when_registered_folder_is_now_a_file(tmp_path):
    """rglob on a file yields nothing, so the whole subtree would read as deleted."""
    (a,) = _dirs(tmp_path, "notes")
    registry = fr.Registry()
    fr.register(registry, a)
    a.rmdir()
    a.write_text("now a file", encoding="utf-8")

    with pytest.raises(NotADirectoryError):
        fr.resolve(registry, a)


def test_save_round_trips_and_preserves_original_input_dir(tmp_path):
    a, b = _dirs(tmp_path, "notes", "manuals")
    inter = tmp_path / "intermediate"
    registry = fr.Registry()
    fr.register(registry, a)
    fr.register(registry, b)

    fr.save(registry, inter)
    reloaded = fr.load(inter)

    assert [f.mirror_prefix for f in reloaded.folders] == ["", "manuals/"]
    assert reloaded.original_input_dir == str(a.resolve())


def test_save_creates_intermediate_dir(tmp_path):
    """The registry is resolved before the pipeline's own mkdir calls."""
    (a,) = _dirs(tmp_path, "notes")
    inter = tmp_path / "does" / "not" / "exist"
    registry = fr.Registry()
    fr.register(registry, a)

    fr.save(registry, inter)

    assert (inter / fr.REGISTRY_FILENAME).exists()
