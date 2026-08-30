"""Folder registry for `intermediate/raw_input_folder.json` (D58).

A session's mirror at `session/input/` is fed by one or more *source folders*.
Historically the file recorded a single `original_input_dir` string, written
once and never updated, so a second folder appended to the same session was
invisible: `_copy_input_files` flattened both into one namespace and files
sharing a basename silently overwrote each other.

The registry records every contributing folder and gives each one a
`mirror_prefix` — the subtree of `session/input/` it owns:

    {
      "original_input_dir": "/abs/path/to/notes",
      "folders": [
        {"path": "/abs/path/to/notes",   "mirror_prefix": "",           "added_at": "..."},
        {"path": "/abs/path/to/manuals", "mirror_prefix": "manuals/",   "added_at": "..."}
      ]
    }

**The first folder keeps an empty prefix**, so single-folder sessions produce
byte-identical mirror layouts, manifest keys, shard names and `source_files`
values to pre-D58. Only the second and later folders are namespaced.

`original_input_dir` is retained because `mcp_server.py` reads it, and a file
with no `folders` key is read as a single unprefixed folder — so pre-existing
sessions work with no migration and nothing on disk is rewritten.

This module is pure data: no CLI, no pipeline imports, no I/O beyond the one
JSON file.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from mykg.utility.atomic_io import atomic_write_json

REGISTRY_FILENAME = "raw_input_folder.json"

# Mirror prefixes become real directories under session/input/. A component
# starting with "." would be skipped by the hidden-path filters in
# _copy_input_files and the ingest/preprocess rglobs, so the folder's files
# would be copied and then never seen again.
_UNSAFE_PREFIX_CHARS = re.compile(r"[^A-Za-z0-9._-]+")


class FolderEntry(BaseModel):
    """One source folder contributing to a session's mirror."""

    path: str
    mirror_prefix: str = ""
    added_at: str = ""


class Registry(BaseModel):
    """Every source folder that has fed this session, in registration order."""

    original_input_dir: str = ""
    folders: list[FolderEntry] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sanitize_prefix(name: str) -> str:
    """Make a folder basename safe to use as a mirror subdirectory component."""
    cleaned = _UNSAFE_PREFIX_CHARS.sub("-", name).strip(".-")
    return cleaned or "folder"


def load(intermediate_dir: Path) -> Registry:
    """Read the registry, synthesising one from a legacy single-path file.

    A missing or unreadable file yields an empty registry rather than raising:
    the caller registers into it and saves, which is the correct behaviour for
    a fresh session.
    """
    path = intermediate_dir / REGISTRY_FILENAME
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return Registry()
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return Registry()
    if not isinstance(data, dict):
        return Registry()

    original = str(data.get("original_input_dir") or "")
    folders_raw = data.get("folders")
    if isinstance(folders_raw, list) and folders_raw:
        folders = [FolderEntry(**f) for f in folders_raw if isinstance(f, dict)]
    elif original:
        # Legacy layout: one folder, unprefixed, matching how its files were
        # already copied into the mirror.
        folders = [FolderEntry(path=original, mirror_prefix="")]
    else:
        folders = []
    return Registry(original_input_dir=original, folders=folders)


def resolve(registry: Registry, input_dir: Path) -> FolderEntry | None:
    """Return the entry for ``input_dir``, or None if it is not registered.

    Comparison is on ``Path.resolve()`` for both sides, which normalises ``~``,
    relative paths and symlinks — the same form `original_input_dir` is already
    stored in. Raises if a registered path now points at a file: ``rglob`` on a
    file yields nothing, so the whole subtree would read as deleted and a
    ``--sync`` run would remove it from the graph.
    """
    target = input_dir.resolve()
    for entry in registry.folders:
        candidate = Path(entry.path)
        try:
            same = candidate.resolve() == target
        except OSError:
            continue
        if same:
            if candidate.exists() and not candidate.is_dir():
                raise NotADirectoryError(
                    f"Registered source folder {entry.path!r} is now a file. "
                    "Point it back at a directory, or edit "
                    f"intermediate/{REGISTRY_FILENAME}."
                )
            return entry
    return None


def register(registry: Registry, input_dir: Path) -> FolderEntry:
    """Add ``input_dir`` to the registry and return its new entry.

    The first folder gets an empty prefix so single-folder sessions keep their
    pre-D58 flat layout. Later folders get their sanitised basename, with a
    numeric suffix on collision (``manuals/``, ``manuals-2/``).
    """
    resolved = str(input_dir.resolve())
    if not registry.folders:
        entry = FolderEntry(path=resolved, mirror_prefix="", added_at=_now())
        registry.folders.append(entry)
        if not registry.original_input_dir:
            registry.original_input_dir = resolved
        return entry

    taken = {f.mirror_prefix for f in registry.folders}
    base = _sanitize_prefix(input_dir.resolve().name)
    prefix = f"{base}/"
    counter = 2
    while prefix in taken:
        prefix = f"{base}-{counter}/"
        counter += 1

    entry = FolderEntry(path=resolved, mirror_prefix=prefix, added_at=_now())
    registry.folders.append(entry)
    return entry


def save(registry: Registry, intermediate_dir: Path) -> None:
    """Write the registry atomically, creating ``intermediate_dir`` if needed.

    The directory may not exist yet: the registry is resolved before the copy
    step, which runs before the pipeline's own mkdir calls.
    """
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_json(intermediate_dir / REGISTRY_FILENAME, registry.model_dump())
