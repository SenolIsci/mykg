"""Concept-type remapping for the merge pipeline.

When the merge schema stage collapses one concept into another — either
algorithmically via ``synonym_collapse`` or with SKOS sanction via
``concept_collapsed_by_thesaurus`` — the schema loses the removed concept but
the extracted instances keep naming it. Since a stable node ID is derived from
``node["type"]`` (D19), those instances keep a dead type and a single entity
ends up split across two node IDs.

This module turns those collapse events into a ``{removed: surviving}`` map and
applies it to raw extractions *before* stable IDs are assigned, so the pair
collapses into one node through the assembler's ordinary deduplication.

Merge pipeline only — ``extract-graph`` never imports this module.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from mykg.logging import get
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.merge_type_remap")

TYPE_REMAP_FILE = "type_remap.json"

# Collapse events and the keys naming (removed_type, surviving_type).
_COLLAPSE_EVENTS = {
    "concept_collapsed_by_thesaurus": ("concept", "collapsed_into"),
    "synonym_collapse": ("discarded", "kept"),
}


def _resolve_chain(remap: dict[str, str]) -> dict[str, str]:
    """Follow A→B→C so every source maps to its final target.

    A cycle (A→B→A) would otherwise loop forever; the visited set breaks it and
    the entry is dropped rather than resolved arbitrarily.
    """
    resolved: dict[str, str] = {}
    for source in remap:
        seen = {source}
        target = remap[source]
        while target in remap:
            if target in seen:
                log.warning(
                    "type_remap — cycle detected starting at %r; dropping the mapping",
                    source,
                )
                target = None
                break
            seen.add(target)
            target = remap[target]
        if target is not None and target != source:
            resolved[source] = target
    return resolved


def build_type_remap(events: list[dict], schema: dict | None = None) -> dict[str, str]:
    """Build ``{removed_type: surviving_type}`` from schema-merge collapse events.

    ``schema`` is the final merged schema. When given, a mapping whose target is
    not a declared concept is dropped — remapping instances onto a type that
    does not exist would strand them exactly as before.
    """
    raw: dict[str, str] = {}
    for event in events:
        keys = _COLLAPSE_EVENTS.get(event.get("event", ""))
        if keys is None:
            continue
        removed, surviving = event.get(keys[0]), event.get(keys[1])
        if not removed or not surviving or removed == surviving:
            continue
        raw[removed] = surviving

    remap = _resolve_chain(raw)

    if schema is not None:
        declared = {
            c["type"] for c in schema.get("concepts", []) if isinstance(c, dict) and "type" in c
        }
        dropped = {s: t for s, t in remap.items() if t not in declared}
        for source, target in dropped.items():
            log.warning(
                "type_remap — target %r for %r is not a declared concept; dropping",
                target,
                source,
            )
        remap = {s: t for s, t in remap.items() if t in declared}

    return remap


def write_type_remap(
    remap: dict[str, str], intermediate_dir: Path, source_events: int = 0
) -> None:
    """Write ``intermediate/type_remap.json``.

    Always written — an empty ``mappings`` is a valid, meaningful result, and a
    present-but-empty file lets the consumer distinguish "no collapses" from
    "the schema step never ran".
    """
    atomic_write_json(
        intermediate_dir / TYPE_REMAP_FILE,
        {
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "mapping_count": len(remap),
                "source_events": source_events,
            },
            "mappings": remap,
        },
    )
    if remap:
        log.info(
            "type_remap — %d concept type(s) will be remapped at assembly: %s",
            len(remap),
            ", ".join(f"{s} -> {t}" for s, t in sorted(remap.items())),
        )


def load_type_remap(intermediate_dir: Path) -> dict[str, str]:
    """Return the ``{removed: surviving}`` map, or ``{}`` when absent/unreadable."""
    import json

    path = intermediate_dir / TYPE_REMAP_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("type_remap — could not read %s: %s; skipping remap", path, exc)
        return {}
    mappings = data.get("mappings", {})
    return mappings if isinstance(mappings, dict) else {}


def apply_type_remap(raw: dict, remap: dict[str, str], log_events: list[dict]) -> dict:
    """Return a copy of ``raw`` with every collapsed node type rewritten.

    Pure: the input is never mutated. Node IDs are deliberately left untouched —
    ``assign_stable_ids`` recomputes them from the new type, and rewrites edge
    endpoints through its own id map.
    """
    if not remap:
        return raw

    updated = deepcopy(raw)
    remapped = 0
    for fname, file_data in updated.items():
        for node in file_data.get("nodes", []):
            old_type = node.get("type")
            new_type = remap.get(old_type)
            if not new_type:
                continue
            node["type"] = new_type
            remapped += 1
            log_events.append(
                {
                    "event": "type_remap",
                    "node_id": node.get("id"),
                    "from_type": old_type,
                    "to_type": new_type,
                    "source_file": fname,
                    "reason": "concept collapsed during schema merge",
                }
            )

    if remapped:
        log.info("type_remap — rewrote the type of %d node occurrence(s)", remapped)
    return updated
