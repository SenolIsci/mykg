"""Atomic file writes shared across pipeline steps.

A bare ``path.write_text(...)`` is not crash-safe: if the process is killed
(SIGKILL/OOM) partway through, the target file is left truncated. Several
pipeline outputs are single sources of truth — most notably
``intermediate/edge_metadata.json`` (D8) — so a truncated write corrupts state
that later re-entry points read back blindly.

Both writers here take the same shape: write to a sibling ``.tmp`` file,
``fsync`` it so the bytes are durably on disk, then ``os.replace`` it over the
target. ``os.replace`` is atomic on POSIX and Windows, so a reader (or a crash)
only ever sees the old complete file or the new complete file, never a partial
one. Finally the containing directory is ``fsync``ed, because fsyncing the file
persists its *contents* but not the rename that publishes it — without that step
a power loss just after ``os.replace`` can lose the rename and leave the target
absent. On any failure the temp file is removed so a failed write never leaves
stray ``.tmp`` files behind.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mykg import config as _cfg


def _fsync_dir(path: Path) -> None:
    """``fsync`` the directory containing ``path`` so a rename into it is durable.

    Fsyncing a file persists its contents; the directory entry created by
    ``os.replace`` is separate metadata and needs its own flush, or a power loss
    immediately after the rename can leave the target missing even though the
    data was written.

    Windows has no directory file descriptor to fsync (``os.open`` on a
    directory fails), and NTFS does not need this, so it is skipped there.
    A failure to open or sync the directory is deliberately swallowed: the
    rename has already succeeded at this point, so the write is correct even if
    this extra durability step is unavailable (e.g. on some network mounts).
    """
    if sys.platform == "win32":
        return
    try:
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def atomic_write_json(path: Path, data: Any) -> None:
    """Serialize ``data`` to JSON and write it to ``path`` atomically.

    Writes to ``<path>.tmp``, ``fsync``s it to disk, ``os.replace``s onto
    ``path``, then ``fsync``s the containing directory so the rename itself is
    durable. Uses the configured ``JSON_INDENT`` so output matches every other
    intermediate file. If anything fails, the temp file is cleaned up so no
    stray ``.tmp`` is left behind.

    ``newline=""`` keeps the indent newlines as LF on every platform rather
    than CRLF on Windows (Invariant 20), so these files hash and diff the same
    wherever the pipeline ran.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    payload = json.dumps(data, indent=_cfg.JSON_INDENT)
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            f.write(payload)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path)


def atomic_write_lines(
    path: Path, lines: Iterable[str], *, trailing_newline: bool = True
) -> int:
    """Write ``lines`` to ``path`` atomically, one per line, streaming.

    The streaming counterpart to ``atomic_write_json``: same
    ``<path>.tmp`` → ``fsync`` → ``os.replace`` → directory ``fsync`` sequence,
    but the payload is consumed lazily, so peak memory stays at one line no
    matter how many are written. Each line is written followed by ``\\n``; lines
    must not already end in one. Returns the number of lines written.

    ``trailing_newline=False`` omits the newline after the final line, for
    callers reproducing an existing file's exact bytes. Prefer the default:
    a text file should end with a newline.

    Atomicity matters more here than for a single JSON document: a truncated
    JSONL file is still *syntactically valid* line-oriented data, so a crash
    partway through a non-atomic write leaves a short file that every reader
    parses as complete rather than rejecting.

    ``newline=""`` disables the platform newline translation that would
    otherwise emit CRLF on Windows (Invariant 20): these outputs are consumed
    byte-for-byte by other tools and compared across platforms, so a line
    ending must not depend on where the pipeline ran.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    count = 0
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            for line in lines:
                if count and not trailing_newline:
                    f.write("\n")
                f.write(line)
                if trailing_newline:
                    f.write("\n")
                count += 1
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path)
    return count
