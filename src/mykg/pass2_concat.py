from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path


def _strip_counter_suffix(stem: str) -> str:
    """Return the base prefix by stripping trailing counter patterns: _N, -N, (N), .N"""
    return re.sub(r"([_\-\.])\d+$|\(\d+\)$", "", stem).rstrip("_-.")


def concat_file_order(file_contents: dict[str, str]) -> list[str]:
    """Return real filenames ordered so directory- and prefix-related files are adjacent.

    Files are grouped by directory (``Path(f).parent``); directories are emitted in
    sorted order, and within each directory files are sorted by
    ``(_strip_counter_suffix(stem), filename)`` so related notes sit next to each
    other. The result is fully deterministic for a given file set.

    This is the only concat-specific behaviour: feeding chunks to the batch engine
    in this order makes related small files land in the same token-bounded batch,
    giving the LLM cross-file context — without any virtual-batch concatenation.
    No token counting or large/small split is done here; the batch engine packs
    chunks and splits oversized files on its own.
    """
    by_dir: dict[str, list[str]] = defaultdict(list)
    for f in file_contents:
        by_dir[str(Path(f).parent)].append(f)
    order: list[str] = []
    for d in sorted(by_dir):
        order.extend(
            sorted(by_dir[d], key=lambda f: (_strip_counter_suffix(Path(f).stem), f))
        )
    return order
