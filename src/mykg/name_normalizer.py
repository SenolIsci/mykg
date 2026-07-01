from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone

from mykg import config as _cfg
from mykg.ids import _canonical
from mykg.llm.adapter import LLMAdapter
from mykg.logging import get
from mykg.prompts import load_prompt

log = get("mykg.name_normalizer")

NORMALIZE_SYSTEM_PROMPT = load_prompt("normalize/system")


def build_name_inventory(raw: dict) -> dict[str, list[str]]:
    """Collect distinct node name values grouped by type from raw_extractions."""
    inventory: dict[str, set[str]] = {}
    for file_data in raw.values():
        for node in file_data.get("nodes", []):
            ntype = node.get("type", "")
            name_attr = node.get("attributes", {}).get("name", {})
            if isinstance(name_attr, dict):
                name_val = name_attr.get("value")
            else:
                name_val = name_attr
            if name_val:
                inventory.setdefault(ntype, set()).add(str(name_val))
    return {t: sorted(names) for t, names in inventory.items()}


def validate_normalization_output(
    llm_output: dict,
    inventory: dict[str, list[str]],
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Validate and clean the LLM normalization response.

    Returns (clean_map, errors) where clean_map has invalid entries dropped.
    Applies lenient policy: drops bad entries with warnings rather than halting.
    Detects and drops cycles.
    """
    errors: list[str] = []
    clean: dict[str, dict[str, str]] = {}

    for ntype, mappings in llm_output.items():
        if not isinstance(mappings, dict):
            errors.append(
                f"Type '{ntype}': expected dict of mappings, got {type(mappings).__name__}"
            )
            continue

        known = set(inventory.get(ntype, []))
        type_clean: dict[str, str] = {}

        for alias, canonical in mappings.items():
            if not isinstance(alias, str) or not isinstance(canonical, str):
                errors.append(
                    f"Type '{ntype}': non-string entry {alias!r} -> {canonical!r}, dropping"
                )
                continue
            if canonical not in known:
                errors.append(
                    f"Type '{ntype}': canonical '{canonical}' not in inventory, dropping '{alias}'"
                )
                continue
            if alias == canonical:
                continue  # identity mapping — drop silently
            type_clean[alias] = canonical

        # Cycle detection: build directed graph, find any a->b->a or longer cycles
        type_clean = _drop_cycles(type_clean, ntype, errors)

        if type_clean:
            clean[ntype] = type_clean

    return clean, errors


def _drop_cycles(
    mappings: dict[str, str],
    ntype: str,
    errors: list[str],
) -> dict[str, str]:
    """Remove any alias entries that participate in a cycle."""
    visited: set[str] = set()
    in_cycle: set[str] = set()

    def has_cycle(start: str, current: str, path: set[str]) -> bool:
        nxt = mappings.get(current)
        if nxt is None:
            return False
        if nxt == start:
            return True
        if nxt in path:
            return True
        return has_cycle(start, nxt, path | {nxt})

    for alias in list(mappings):
        if alias in visited:
            continue
        visited.add(alias)
        if has_cycle(alias, alias, {alias}):
            in_cycle.add(alias)
            errors.append(f"Type '{ntype}': cycle detected involving '{alias}', dropping")

    return {k: v for k, v in mappings.items() if k not in in_cycle}


def apply_normalization_map(
    raw: dict,
    norm_map: dict[str, dict[str, str]],
) -> dict:
    """Rewrite name attribute values in raw_extractions using the normalization map.

    Uses _canonical for case-insensitive lookup. Leaves node id fields untouched.
    Returns a deepcopy — does not mutate the input.
    """
    updated = deepcopy(raw)
    for file_data in updated.values():
        for node in file_data.get("nodes", []):
            ntype = node.get("type", "")
            type_map = norm_map.get(ntype, {})
            if not type_map:
                continue
            name_attr = node.get("attributes", {}).get("name", {})
            if not isinstance(name_attr, dict):
                continue
            name_val = name_attr.get("value")
            if not name_val:
                continue
            # Case-insensitive lookup via _canonical
            canonical_key = _canonical(str(name_val))
            for alias, canonical in type_map.items():
                if _canonical(alias) == canonical_key:
                    name_attr["value"] = canonical
                    break
    return updated


def build_alias_index(
    norm_map: dict[str, dict[str, str]],
) -> dict[str, dict[str, list[str]]]:
    """Invert norm_map from {type -> {alias -> canonical}} to {type -> {canonical -> [aliases]}}.

    Alias keys are stored as original surface forms (not normalised).
    """
    index: dict[str, dict[str, list[str]]] = {}
    for ntype, mappings in norm_map.items():
        type_index: dict[str, list[str]] = {}
        for alias, canonical in mappings.items():
            type_index.setdefault(canonical, []).append(alias)
        if type_index:
            index[ntype] = type_index
    return index


def _estimate_tokens(obj: dict) -> int:
    """Byte-to-token estimate consistent with pass2_concat.py / context_calculator.py."""
    return len(json.dumps(obj, ensure_ascii=False).encode("utf-8")) // 4


def run_name_normalization(
    inventory: dict[str, list[str]],
    adapter: LLMAdapter,
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Call the LLM with the name inventory and return a validated normalization map.

    Types are bin-packed greedily into token-bounded batches (batch_token_target).
    max_names_per_type acts as a safety-net cap for pathological single types.
    """
    capped: dict[str, list[str]] = {
        t: names[: _cfg.NORMALIZE_NAMES_MAX_PER_TYPE]
        for t, names in inventory.items()
        if len(names) >= 2
    }
    if not capped:
        return {}, []

    # Greedy bin-packing: accumulate types into a batch until the next type
    # would push the token estimate over the budget, then start a new batch.
    budget = _cfg.NORMALIZE_NAMES_BATCH_TOKEN_TARGET
    batches: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    for t, names in capped.items():
        entry = {t: names}
        if current and _estimate_tokens({**current, **entry}) > budget:
            batches.append(current)
            current = entry
        else:
            current.update(entry)
    if current:
        batches.append(current)

    merged_map: dict[str, dict[str, str]] = {}
    all_errors: list[str] = []
    for batch in batches:
        user_text = json.dumps(batch, ensure_ascii=False)
        raw = adapter.complete(NORMALIZE_SYSTEM_PROMPT, user_text)
        try:
            llm_output = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            all_errors.append(f"JSON parse error: {exc}")
            continue
        batch_map, errors = validate_normalization_output(llm_output, inventory)
        all_errors.extend(errors)
        merged_map.update(batch_map)

    return merged_map, all_errors


def build_normalization_file(
    norm_map: dict[str, dict[str, str]],
    inventory: dict[str, list[str]],
    validation_warnings: list[str] | None = None,
) -> dict:
    """Build the full name_normalization.json structure with metadata and warnings."""
    aliases_mapped = sum(len(v) for v in norm_map.values())
    input_counts = {t: len(names) for t, names in inventory.items()}
    result: dict = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input_name_count_by_type": input_counts,
            "aliases_mapped": aliases_mapped,
        },
        "mappings": norm_map,
    }
    if validation_warnings:
        result["validation_warnings"] = validation_warnings
    return result
