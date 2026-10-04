"""Filesystem-safe naming for path components derived from untrusted strings.

Concept type names come from the LLM-induced schema (Pass 1), so they are not
constrained to a filesystem-safe charset. Anything that turns one into a
directory or filename has to normalize it first, or the write fails on Windows:
``:`` is reserved for drive letters, ``< > " | ? * \\ /`` are rejected outright,
trailing dots and spaces are silently stripped, and the legacy DOS device names
(``CON``, ``NUL``, …) are reserved regardless of extension.

``safe_path_component`` is shared deliberately: the Obsidian exporter writes
``obsidian_vault/<type>/<node-id>.md`` and the MCP server reads the same layout
back, so both must derive the identical name or notes stop resolving — a silent
failure, since the reader falls back to a generated summary.

Node IDs need no such treatment: ``mykg.ids.stable_id`` already emits
``<type-prefix>-<name-slug>`` restricted to ``[a-z0-9-]``, and its type prefix
makes a bare reserved name impossible.
"""

from __future__ import annotations

import re

# Everything outside this set is replaced. Mirrors folder_registry's
# _UNSAFE_PREFIX_CHARS, which solves the same problem for mirror subdirectories.
_UNSAFE_FS_CHARS = re.compile(r"[^A-Za-z0-9._-]+")

# Legacy DOS device names. Windows reserves these with *any* extension, so
# "CON.md" fails just as "CON" does.
_WINDOWS_RESERVED = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{i}" for i in range(1, 10)}
    | {f"lpt{i}" for i in range(1, 10)}
)


def safe_path_component(name: str, fallback: str = "unknown") -> str:
    """Return ``name`` usable as one path component on macOS, Linux and Windows.

    Replaces unsafe characters with ``_``, trims leading/trailing dots, hyphens
    and underscores, suffixes reserved device names, and falls back to
    ``fallback`` when nothing usable remains.

    Idempotent — ``f(f(x)) == f(x)`` — which matters because the writer and the
    reader derive the path independently rather than sharing state.

    Not injective: ``A:B`` and ``A-B`` can collapse to the same component. That
    is the right trade here, since the alternative (hashing) would make vault
    directories unbrowsable, defeating the point of an Obsidian vault. Concept
    types are a small curated set, so collisions are a theoretical concern and
    the function exists for robustness, not uniqueness.
    """
    cleaned = _UNSAFE_FS_CHARS.sub("_", name).strip("._-")
    if not cleaned:
        return fallback
    # Compare the stem, not the whole string: Windows reserves these names with
    # any extension, so "con.md" is refused just as "con" is.
    if cleaned.split(".", 1)[0].lower() in _WINDOWS_RESERVED:
        return f"{cleaned}_"
    return cleaned
