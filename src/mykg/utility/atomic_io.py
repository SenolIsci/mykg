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
