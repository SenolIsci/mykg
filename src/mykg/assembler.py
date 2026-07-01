from __future__ import annotations

import hashlib
from copy import deepcopy

from mykg import config as _cfg
from mykg.ids import stable_id as _ids_stable_id
from mykg.logging import get

log = get("mykg.assembler")


def _coerce_attr(val) -> dict:
    """Normalise an attribute value to {value, confidence} regardless of what the LLM returned.

    Enforces:
    - Confidence is a valid float in [0.0, 1.0]
    - Falls back to CONFIDENCE_FALLBACK if conversion fails
    - Clamps to [0.0, 1.0] range with warning if out of bounds
    """
    if isinstance(val, dict) and "value" in val:
        raw_conf = val.get("confidence", _cfg.CONFIDENCE_FALLBACK)
        # Try to convert to float
        try:
            conf = float(raw_conf)
        except (TypeError, ValueError):
            log.warning(
                "_coerce_attr: confidence value %r is not numeric; using fallback %s",
                raw_conf,
                _cfg.CONFIDENCE_FALLBACK,
            )
            conf = _cfg.CONFIDENCE_FALLBACK

        # Clamp to [0.0, 1.0]
        clamped = max(0.0, min(1.0, conf))
        if clamped != conf:
            log.warning(
                "_coerce_attr: confidence value %s out of range [0.0, 1.0]; clamped to %s",
                conf,
                clamped,
            )

        return {"value": val["value"], "confidence": clamped}

    # Scalar path: use fallback directly
    log.warning(
        "_coerce_attr: raw scalar coerced to confidence %s — LLM omitted confidence field",
        _cfg.CONFIDENCE_FALLBACK,
    )
    return {"value": val, "confidence": _cfg.CONFIDENCE_FALLBACK}


def _coerce_conf(val) -> float:
    """Safely convert a top-level node/edge confidence value to float.

    Mirrors _coerce_attr's try/except+clamp logic for the scalar confidence
    field that sits at the node/edge level (not inside an attribute dict).
    """
    try:
        conf = float(val)
    except (TypeError, ValueError):
        log.warning(
            "_coerce_conf: confidence value %r is not numeric; using fallback %s",
            val,
            _cfg.CONFIDENCE_FALLBACK,
        )
        return float(_cfg.CONFIDENCE_FALLBACK)
    clamped = max(0.0, min(1.0, conf))
    if clamped != conf:
        log.warning(
            "_coerce_conf: confidence value %s out of range [0.0, 1.0]; clamped to %s",
            conf,
            clamped,
        )
    return clamped


def _stable_id(node_type: str, name_value: str) -> str:
    """Thin wrapper kept for backwards-compatibility; delegates to ids.stable_id."""
    return _ids_stable_id(node_type, name_value)


def assign_stable_ids(raw: dict) -> dict:
    updated = deepcopy(raw)

    global_id_map: dict[str, str] = {}
    all_stable_ids: set[str] = set()

    for file_data in updated.values():
        for node in file_data["nodes"]:
            raw_name = node["attributes"].get("name", {})
            name_val = _coerce_attr(raw_name)["value"] if raw_name else None
            name_val = name_val or node["id"]
            new_id = _stable_id(node["type"], str(name_val))
            global_id_map[node["id"]] = new_id
            all_stable_ids.add(new_id)
            node["id"] = new_id

    # Build name_slug → list[stable_id] secondary index for type-aware resolution
    name_slug_index: dict[str, list[str]] = {}
    for stable_id in all_stable_ids:
        parts = stable_id.split("-", 1)
        name_slug = parts[1] if len(parts) == 2 else stable_id
        name_slug_index.setdefault(name_slug, []).append(stable_id)

    def _resolve(endpoint: str) -> str:
        if endpoint in global_id_map:
            return global_id_map[endpoint]
        if endpoint in all_stable_ids:
            return endpoint
        # Try exact match in secondary index (type-aware: require same full stable_id)
        parts = endpoint.split("-", 1)
        name_slug = parts[1] if len(parts) == 2 else endpoint
        candidates = name_slug_index.get(name_slug, [])
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            log.warning(
                "Ambiguous cross-file reference '%s': matches %s — leaving unresolved",
                endpoint,
                candidates,
            )
        return endpoint

    for file_data in updated.values():
        for edge in file_data["edges"]:
            edge["from"] = _resolve(edge["from"])
            edge["to"] = _resolve(edge["to"])

    return updated


def deduplicate_nodes(
    raw: dict, confidence_agg: str | None = None
) -> tuple[list[dict], list[dict]]:
    if confidence_agg is None:
        confidence_agg = _cfg.ASSEMBLY_CONFIDENCE_AGG
    groups: dict[str, list[tuple[str, dict]]] = {}
    for source_file, file_data in raw.items():
        for node in file_data["nodes"]:
            groups.setdefault(node["id"], []).append((source_file, node))

    result: list[dict] = []
    merge_log: list[dict] = []

    for stable_id, occurrences in groups.items():
        merged = deepcopy(occurrences[0][1])
        # Coerce first occurrence's attributes to canonical {value, confidence} form
        merged["attributes"] = {k: _coerce_attr(v) for k, v in merged.get("attributes", {}).items()}
        merged["source_files"] = []
        confs = []
        winning_attrs: dict[str, dict] = {}
        losing_attrs: dict[str, dict] = {}
        concatenated_attrs: dict[str, dict] = {}

        for source_file, node in occurrences:
            merged["source_files"].append(source_file)
            confs.append(_coerce_conf(node.get("confidence", _cfg.CONFIDENCE_FALLBACK)))
            node_attrs = node.get("attributes", {})
            if not isinstance(node_attrs, dict):
                node_attrs = {}
            for attr, raw_val in node_attrs.items():
                attr_val = _coerce_attr(raw_val)
                if attr not in merged["attributes"]:
                    merged["attributes"][attr] = attr_val
                    winning_attrs[attr] = attr_val
                else:
                    existing = _coerce_attr(merged["attributes"][attr])
                    if attr_val["confidence"] > existing["confidence"]:
                        losing_attrs[attr] = existing
                        merged["attributes"][attr] = attr_val
                        winning_attrs[attr] = attr_val
                    elif (
                        attr_val["confidence"] == 1.0
                        and existing["confidence"] == 1.0
                        and isinstance(attr_val["value"], str)
                        and isinstance(existing["value"], str)
                        and attr_val["value"] != existing["value"]
                    ):
                        # Both sources are maximally confident with different string values —
                        # concatenate to avoid silent data loss.
                        merged["attributes"][attr] = {
                            "value": existing["value"] + "; " + attr_val["value"],
                            "confidence": 1.0,
                        }
                        winning_attrs[attr] = merged["attributes"][attr]
                        concatenated_attrs[attr] = {
                            "merged_value": merged["attributes"][attr]["value"],
                            "inputs": [existing["value"], attr_val["value"]],
                        }
                    else:
                        losing_attrs[attr] = attr_val

        merged["confidence"] = max(confs) if confidence_agg == "max" else sum(confs) / len(confs)

        # Union aliases across all occurrences (D29); exclude canonical name itself.
        # Field is absent (not []) when no aliases exist, per D29 contract.
        alias_set: set[str] = set()
        for _, occ in occurrences:
            alias_set.update(occ.get("aliases", []))
        canonical_name = merged.get("attributes", {}).get("name", {})
        if isinstance(canonical_name, dict):
            canonical_name = canonical_name.get("value", "")
        alias_set.discard(str(canonical_name) if canonical_name else "")
        if alias_set:
            merged["aliases"] = sorted(alias_set)
        elif "aliases" in merged:
            del merged["aliases"]

        result.append(merged)

        if len(occurrences) > 1:
            entry: dict = {
                "event": "node_merge",
                "id": stable_id,
                "sources": merged["source_files"],
                "winning_attributes": winning_attrs,
                "losing_attributes": losing_attrs,
            }
            if concatenated_attrs:
                entry["concatenated_attributes"] = concatenated_attrs
            merge_log.append(entry)

    return result, merge_log


def deduplicate_edges(
    raw: dict, confidence_agg: str | None = None
) -> tuple[dict[str, dict], list[dict]]:
    if confidence_agg is None:
        confidence_agg = _cfg.ASSEMBLY_CONFIDENCE_AGG
    groups: dict[str, list[tuple[str, dict]]] = {}
    sep = _cfg.ASSEMBLY_EDGE_DEDUP_SEPARATOR
    for source_file, file_data in raw.items():
        for edge in file_data["edges"]:
            key_str = edge["type"] + sep + edge["from"] + sep + edge["to"]
            dedup_key = hashlib.sha256(key_str.encode()).hexdigest()
            groups.setdefault(dedup_key, []).append((source_file, edge))

    result: dict[str, dict] = {}
    merge_log: list[dict] = []

    for dedup_key, occurrences in groups.items():
        edge_id = _cfg.ASSEMBLY_EDGE_ID_PREFIX + dedup_key[: _cfg.ASSEMBLY_EDGE_ID_HEX_LENGTH]
        merged = deepcopy(occurrences[0][1])
        merged["id"] = edge_id
        merged["method"] = "llm_extraction"
        merged["source_files"] = []
        raw_attrs = merged.get("attributes", {})
        if not isinstance(raw_attrs, dict):
            raw_attrs = {}
        merged["attributes"] = {k: _coerce_attr(v) for k, v in raw_attrs.items()}
        confs = []
        winning_attrs: dict[str, dict] = {}
        losing_attrs: dict[str, dict] = {}
        concatenated_attrs: dict[str, dict] = {}

        for source_file, edge in occurrences:
            merged["source_files"].append(source_file)
            confs.append(_coerce_conf(edge.get("confidence", _cfg.CONFIDENCE_FALLBACK)))
            attrs = edge.get("attributes", {})
            if not isinstance(attrs, dict):
                attrs = {}
            for attr, raw_val in attrs.items():
                attr_val = _coerce_attr(raw_val)
                if attr not in merged.get("attributes", {}):
                    merged.setdefault("attributes", {})[attr] = attr_val
                    winning_attrs[attr] = attr_val
                else:
                    existing = _coerce_attr(merged["attributes"][attr])
                    if attr_val["confidence"] > existing["confidence"]:
                        losing_attrs[attr] = existing
                        merged["attributes"][attr] = attr_val
                        winning_attrs[attr] = attr_val
                    elif (
                        attr_val["confidence"] == 1.0
                        and existing["confidence"] == 1.0
                        and isinstance(attr_val["value"], str)
                        and isinstance(existing["value"], str)
                        and attr_val["value"] != existing["value"]
                    ):
                        # Both sources are maximally confident with different string values —
                        # concatenate to avoid silent data loss.
                        merged["attributes"][attr] = {
                            "value": existing["value"] + "; " + attr_val["value"],
                            "confidence": 1.0,
                        }
                        winning_attrs[attr] = merged["attributes"][attr]
                        concatenated_attrs[attr] = {
                            "merged_value": merged["attributes"][attr]["value"],
                            "inputs": [existing["value"], attr_val["value"]],
                        }
                    else:
                        losing_attrs[attr] = attr_val

        merged["confidence"] = max(confs) if confidence_agg == "max" else sum(confs) / len(confs)
        result[edge_id] = merged

        if len(occurrences) > 1:
            entry = {
                "event": "edge_merge",
                "id": edge_id,
                "type": merged["type"],
                "from": merged["from"],
                "to": merged["to"],
                "sources": merged["source_files"],
                "winning_attributes": winning_attrs,
                "losing_attributes": losing_attrs,
            }
            if concatenated_attrs:
                entry["concatenated_attributes"] = concatenated_attrs
            merge_log.append(entry)

    return result, merge_log
