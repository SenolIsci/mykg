from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from mykg.chunker import count_tokens as _token_count


def _strip_counter_suffix(stem: str) -> str:
    """Return the base prefix by stripping trailing counter patterns: _N, -N, (N), .N"""
    return re.sub(r"([_\-\.])\d+$|\(\d+\)$", "", stem).rstrip("_-.")


def _pack_into_batches(
    files: list[str],
    token_counts: dict[str, int],
    target: int,
) -> list[list[str]]:
    """Greedy sequential bin-packing: fill each bin up to target tokens."""
    batches: list[list[str]] = []
    current: list[str] = []
    current_tokens = 0
    for f in files:
        t = token_counts[f]
        if current and current_tokens + t > target:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(f)
        current_tokens += t
    if current:
        batches.append(current)
    return batches


def build_concat_batches(
    file_contents: dict[str, str],
    batch_token_target: int,
) -> dict[str, dict]:
    """Return {virtual_name: entry} mapping where each entry has:
      - "files": list of real filenames in this virtual batch
      - "file_tokens": {filename: token_count} for each real file
      - "total_tokens": sum of token counts for all files in the batch

    Large files (tokens > batch_token_target) map to themselves with no concatenation.
    Small files are grouped by directory then sorted by prefix, packed into virtual
    batches named concat_batch_0000.md, concat_batch_0001.md, etc.
    """
    if not file_contents:
        return {}

    token_counts = {f: _token_count(c) for f, c in file_contents.items()}

    large = sorted(f for f, t in token_counts.items() if t > batch_token_target)
    small = sorted(f for f in token_counts if f not in large)

    # Group small files: priority 1 = same directory
    by_dir: dict[str, list[str]] = defaultdict(list)
    for f in small:
        by_dir[str(Path(f).parent)].append(f)

    # Within each directory, sort by prefix then filename so related files are adjacent,
    # but keep all files from the same directory in one group for packing.
    subgroups: list[list[str]] = []
    for dir_files in by_dir.values():
        sorted_files = sorted(dir_files, key=lambda f: (_strip_counter_suffix(Path(f).stem), f))
        subgroups.append(sorted_files)

    # Pack each subgroup into batches
    concat_map: dict[str, dict] = {}
    batch_idx = 0

    for group in subgroups:
        for batch in _pack_into_batches(group, token_counts, batch_token_target):
            vname = f"concat_batch_{batch_idx:04d}.md"
            ft = {f: token_counts[f] for f in batch}
            concat_map[vname] = {
                "files": batch,
                "file_tokens": ft,
                "total_tokens": sum(ft.values()),
            }
            batch_idx += 1

    # Large files map to themselves
    for f in large:
        concat_map[f] = {
            "files": [f],
            "file_tokens": {f: token_counts[f]},
            "total_tokens": token_counts[f],
        }

    return concat_map


def make_virtual_files(
    file_contents: dict[str, str],
    concat_map: dict[str, dict],
) -> dict[str, str]:
    """Return {virtual_name: combined_content} ready for run_pass2().

    Single-file virtual files pass content through unchanged.
    Multi-file virtual files are joined with '--- SOURCE: path ---' delimiters.
    """
    result: dict[str, str] = {}
    for vname, entry in concat_map.items():
        real_fnames = entry["files"]
        if len(real_fnames) == 1:
            result[vname] = file_contents[real_fnames[0]]
        else:
            parts = []
            for fname in real_fnames:
                parts.append(f"--- SOURCE: {fname} ---\n{file_contents[fname]}")
            result[vname] = "\n\n".join(parts)
    return result
