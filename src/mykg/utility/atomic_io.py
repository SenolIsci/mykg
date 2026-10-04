"""Atomic file writes shared across pipeline steps.

A bare ``path.write_text(...)`` is not crash-safe: if the process is killed
(SIGKILL/OOM) partway through, the target file is left truncated. Several
pipeline outputs are single sources of truth — most notably
``intermediate/edge_metadata.json`` (D8) — so a truncated write corrupts state
that later re-entry points read back blindly.

``atomic_write_json`` writes to a sibling ``.tmp`` file, ``fsync``s it so the
bytes are durably on disk, and then ``os.replace``s it over the target.
``os.replace`` is atomic on POSIX and Windows, so a reader (or a crash) ever
sees either the old complete file or the new complete file, never a partial one.
The ``fsync`` extends the guarantee to survive sudden power loss, not just a
mid-write process kill. On any failure the temp file is removed so a failed
write never leaves stray ``.tmp`` files behind.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mykg import config as _cfg


def atomic_write_json(path: Path, data: Any) -> None:
    """Serialize ``data`` to JSON and write it to ``path`` atomically.

    Writes to ``<path>.tmp``, ``fsync``s it to disk, then ``os.replace`` onto
    ``path``. Uses the configured ``JSON_INDENT`` so output matches every other
    intermediate file. If anything fails, the temp file is cleaned up so no
    stray ``.tmp`` is left behind.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=_cfg.JSON_INDENT)
    try:
        with tmp.open("w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def atomic_write_lines(path: Path, lines: Iterable[str]) -> int:
    """Write ``lines`` to ``path`` atomically, one per line, streaming.

    The streaming counterpart to ``atomic_write_json``: same
    ``<path>.tmp`` → ``fsync`` → ``os.replace`` guarantee, but the payload is
    consumed lazily, so peak memory stays at one line no matter how many are
    written. Each line is written followed by ``\\n``; lines must not already
    end in one. Returns the number of lines written.

    Atomicity matters more here than for a single JSON document: a truncated
    JSONL file is still *syntactically valid* line-oriented data, so a crash
    partway through a non-atomic write leaves a short file that every reader
    parses as complete rather than rejecting.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    try:
        with tmp.open("w", encoding="utf-8") as f:
            for line in lines:
                f.write(line)
                f.write("\n")
                count += 1
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return count
