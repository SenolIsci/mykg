"""grow_schema_backfill — chunk selector for --append-with-grow-schema (D52).

When the locked Pass 1 grows the schema (new concepts and/or properties), the
already-extracted OLD files are stale: they were extracted against the smaller
schema and so cannot contain instances of the new types. This module decides,
cheaply and with a bounded cost, WHICH old chunks are worth re-extracting against
the grown schema.

The selection is a HEURISTIC, not a guarantee (Invariant 16): it relies solely on
``chunk_node_index.json`` (``filename::chunk_idx → [stable_node_ids]``) so no source
text is re-read. A stable ID encodes its concept type as its prefix (D19:
``node.type.lower()`` with non-alphanumerics stripped, joined to the name slug with
``-``), so for any old chunk we already know which concept types it produced.

Selection rule
--------------
* New property ``p (domain D → range R)`` — a chunk is a candidate IFF it already
  contains ≥1 node of type ``D`` OR ``R`` (domain/range co-occurrence — mirrors the
  merge_graphs surgical selector, D38).
* New concept ``C`` — there is no edge signal, so the is-a hierarchy is used: target
  chunks containing nodes of ``C``'s parent or sibling type(s) from ``new_schema``'s
  concept hierarchy. A ROOT concept with no parent/siblings yields ZERO targeted
  chunks.
* Cap — candidates per type are ranked by co-occurrence count; only the top-K are
  kept (``top_k`` from config). ``top_k == 0`` disables back-fill entirely.

False negatives are backstopped by the orphan pass and future runs; false positives
cost one no-op LLM call, bounded by top-K.
"""

from __future__ import annotations

import re
from collections import defaultdict

from mykg.logging import get

log = get("mykg.steps.grow_schema_backfill")


def _type_prefix(node_type: str) -> str:
    """Stable-ID type prefix per D19: lowercase, non-alphanumerics stripped."""
    return re.sub(r"[^a-z0-9]", "", node_type.lower())


def _stable_id_type(stable_id: str, prefix_to_type: dict[str, str]) -> str | None:
    """Map a stable ID back to its concept type via its prefix (text before first '-')."""
    prefix = stable_id.split("-", 1)[0]
    return prefix_to_type.get(prefix)


def _hierarchy_signal_types(concept_type: str, concepts: list[dict]) -> set[str]:
    """Return parent + sibling type names for a concept from the is-a hierarchy.

    A root concept (no parent) with no siblings sharing a parent yields an empty set.
    """
    by_name = {c["type"]: c for c in concepts}
    target = by_name.get(concept_type)
    if target is None:
        return set()
    parent = target.get("parent")
    if not parent:
        return set()
    signal: set[str] = {parent}
    # Siblings: concepts sharing the same parent (excluding the concept itself).
    for c in concepts:
        if c["type"] != concept_type and c.get("parent") == parent:
            signal.add(c["type"])
    return signal


def compute_backfill_chunks(
    added_concepts: list[str],
    added_properties: list[dict],
    new_schema: dict,
    chunk_node_index: dict[str, dict[str, list[str]]],
    top_k: int,
) -> dict[str, set[int]]:
    """Select old chunks to surgically re-extract after a grow-schema delta (D52).

    Parameters
    ----------
    added_concepts:
        Names of concept types newly added by the locked Pass 1 (absent before).
    added_properties:
        Newly added property dicts (``{"name", "domain", "range", ...}``) — the full
        entry from ``new_schema["properties"]`` is needed for domain/range.
    new_schema:
        The grown schema (``{"concepts": [...], "properties": [...]}``); supplies the
        is-a hierarchy used for the new-concept signal.
    chunk_node_index:
        ``{filename: {"1": [stable_id, ...], ...}}`` from chunk_node_index.json.
        Chunk-index keys are 1-based strings.
    top_k:
        Per-type cap on candidate chunks, ranked by co-occurrence count. 0 disables
        back-fill entirely (returns an empty map).

    Returns
    -------
    ``{filename: {chunk_idx, ...}}`` with 1-based int chunk indices. Empty when there
    is no delta, no signal, or ``top_k == 0``.
    """
    if top_k == 0:
        return {}
    if not added_concepts and not added_properties:
        return {}
    if not chunk_node_index:
        return {}

    concepts = new_schema.get("concepts", [])
    prefix_to_type = {_type_prefix(c["type"]): c["type"] for c in concepts}

    # Per type-source, collect the set of "signal types": a chunk scores if it contains
    # ≥1 node of any signal type. Keyed by a human-readable label only for logging.
    signal_sets: dict[str, set[str]] = {}

    for prop in added_properties:
        types = {t for t in (prop.get("domain"), prop.get("range")) if t}
        if types:
            signal_sets[f"property:{prop['name']}"] = types

    for concept in added_concepts:
        types = _hierarchy_signal_types(concept, concepts)
        if types:
            signal_sets[f"concept:{concept}"] = types
        else:
            log.debug(
                "grow_schema back-fill: concept %s is root/sibling-less — no targeted chunks",
                concept,
            )

    if not signal_sets:
        log.info("grow_schema back-fill: no hierarchy/domain/range signal — nothing to back-fill")
        return {}

    targeted: dict[str, set[int]] = defaultdict(set)
    for label, signal_types in signal_sets.items():
        # Rank all chunks by count of signal-type nodes; keep top-K with score > 0.
        scores: list[tuple[int, str, int]] = []
        for fname, chunk_map in chunk_node_index.items():
            for chunk_idx_str, stable_ids in chunk_map.items():
                try:
                    chunk_idx = int(chunk_idx_str)
                except (ValueError, TypeError):
                    continue
                score = sum(
                    1 for sid in stable_ids if _stable_id_type(sid, prefix_to_type) in signal_types
                )
                if score > 0:
                    # Negative score → ascending sort puts highest co-occurrence first.
                    scores.append((-score, fname, chunk_idx))
        scores.sort()
        for _, fname, chunk_idx in scores[:top_k]:
            targeted[fname].add(chunk_idx)
        log.debug(
            "grow_schema back-fill: %s (signal=%s) → %d candidate chunk(s) (top_k=%d)",
            label,
            sorted(signal_types),
            min(len(scores), top_k),
            top_k,
        )

    result = dict(targeted)
    log.info(
        "grow_schema back-fill: selected %d old chunk(s) across %d file(s) for re-extraction",
        sum(len(v) for v in result.values()),
        len(result),
    )
    return result
