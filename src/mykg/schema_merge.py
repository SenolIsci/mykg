from __future__ import annotations

import json
import logging
import re

from mykg.llm.adapter import LLMAdapter
from mykg.llm.retry import llm_complete_with_retry
from mykg.prompts import load_prompt
from mykg.thesaurus import SynonymIndex

_log = logging.getLogger("mykg.schema_merge")
_QUALITY_SYSTEM_PROMPT = load_prompt("schema_merge/quality_system")
_HARMONIZE_SYSTEM_PROMPT = load_prompt("schema_merge/harmonize_system")
_MERGE_HARMONIZE_SYSTEM_PROMPT = load_prompt("schema_merge/merge_harmonize_system")
_MERGE_QUALITY_SYSTEM_PROMPT = load_prompt("schema_merge/merge_quality_system")


def _normalise(name: str) -> str:
    name = re.sub(r"([a-z])([A-Z])", r"\1_\2", name)
    return re.sub(r"[\s\-_]+", "_", name.strip().lower())


def synonym_match(a: str, b: str, thesaurus: SynonymIndex | None) -> bool:
    if a == b:
        return True
    if _normalise(a) == _normalise(b):
        return True
    if thesaurus is not None:
        if thesaurus.is_exact(a, b) or thesaurus.is_close(a, b):
            return True
    return False


def merge_proposals(
    proposals: list[dict],
    locked_classes: dict,
    locked_properties: dict,
    thesaurus: SynonymIndex | None,
) -> tuple[dict, list[dict]]:
    # Build working sets seeded with locked entries
    concepts: dict[str, dict] = {k: dict(v) for k, v in locked_classes.items()}
    for c in concepts.values():
        c["attributes"] = list(c["attributes"])

    properties: dict[str, dict] = {k: dict(v) for k, v in locked_properties.items()}
    for p in properties.values():
        p["attributes"] = list(p["attributes"])

    synonym_log: list[dict] = []

    for proposal in proposals:
        for concept in proposal.get("concepts", []):
            if not isinstance(concept, dict):
                _log.warning("Skipping non-dict concept entry: %r", concept)
                continue
            ctype = concept["type"]

            # Invariant 5: reject any concept named "Relationship"
            if ctype.lower() == "relationship":
                _log.warning(
                    "Rejected concept '%s': 'Relationship' is reserved (Invariant 5)", ctype
                )
                continue

            # Check if this matches any existing entry
            match_key = _find_match(ctype, concepts, thesaurus, synonym_log)
            if match_key:
                existing = concepts[match_key]
                # If match_key is locked, only union attributes
                new_attrs = [
                    a for a in concept.get("attributes", []) if a not in existing["attributes"]
                ]
                existing["attributes"].extend(new_attrs)
                # Keep existing parent if locked; update only if no existing parent
                if existing["parent"] is None and concept.get("parent"):
                    if match_key not in locked_classes:
                        existing["parent"] = concept["parent"]
            else:
                concepts[ctype] = {
                    "type": ctype,
                    "parent": concept.get("parent"),
                    "attributes": list(concept.get("attributes", [])),
                }

        for prop in proposal.get("properties", []):
            if not isinstance(prop, dict):
                _log.warning("Skipping non-dict property entry: %r", prop)
                continue
            pname = prop["name"]
            match_key = _find_match(pname, properties, thesaurus, synonym_log)
            if match_key:
                existing = properties[match_key]
                new_attrs = [
                    a for a in prop.get("attributes", []) if a not in existing["attributes"]
                ]
                existing["attributes"].extend(new_attrs)
            else:
                properties[pname] = {
                    "name": pname,
                    "domain": prop.get("domain"),
                    "range": prop.get("range"),
                    "attributes": list(prop.get("attributes", [])),
                }

    return (
        {"concepts": list(concepts.values()), "properties": list(properties.values())},
        synonym_log,
    )


def _find_match(
    name: str,
    existing: dict,
    thesaurus: SynonymIndex | None,
    synonym_log: list[dict],
) -> str | None:
    for key in existing:
        if not synonym_match(name, key, thesaurus):
            continue
        # Log close matches per D21; exact/normalised matches are silent
        if (
            thesaurus is not None
            and thesaurus.is_close(name, key)
            and name != key
            and _normalise(name) != _normalise(key)
        ):
            synonym_log.append(
                {
                    "event": "synonym_collapse",
                    "kept": key,
                    "discarded": name,
                    "reason": "skos:closeMatch",
                }
            )
        return key
    return None


def _normalize_schema(schema: dict) -> dict:
    """Filter null items from concepts/properties lists and backfill missing 'attributes'."""
    schema["concepts"] = [c for c in (schema.get("concepts") or []) if c is not None]
    schema["properties"] = [p for p in (schema.get("properties") or []) if p is not None]
    for concept in schema["concepts"]:
        if "attributes" not in concept:
            concept["attributes"] = []
    for prop in schema["properties"]:
        if "attributes" not in prop:
            prop["attributes"] = []
    return schema


def harmonize_schema(
    schema: dict, proposals: list[dict], adapter: LLMAdapter, locked_block: str = ""
) -> dict:
    """LLM pass that collapses semantic near-duplicates the algorithmic merge missed.

    Sees both the merged schema and all raw batch proposals so it can detect concepts
    that were kept separate only because their names differed slightly across batches.
    Returns the improved schema, or the original if the response is unparseable.

    ``locked_block`` is the base-schema lock notice (D27). When non-empty it is appended
    to the system prompt so this unlocked pass is told which names it must not rename,
    remove, or duplicate — the same mechanism Pass 1 extraction uses. Empty by default,
    so behaviour is unchanged when no base schema is in play.
    """
    proposals_block = json.dumps(proposals, indent=2)
    merged_block = json.dumps(schema, indent=2)
    user = "MERGED SCHEMA:\n" + merged_block + "\n\nRAW PROPOSALS:\n" + proposals_block
    system = _HARMONIZE_SYSTEM_PROMPT
    if locked_block:
        system = system + "\n\n" + locked_block
    try:
        raw = llm_complete_with_retry(
            adapter,
            system,
            user,
            context_label="schema_harmonize",
        )
        improved = json.loads(raw)
        if not isinstance(improved.get("concepts"), list) or not isinstance(
            improved.get("properties"), list
        ):
            _log.warning("schema_harmonize — wrong structure from LLM; keeping original")
            return schema
        return _normalize_schema(improved)
    except Exception as exc:
        _log.warning("schema_harmonize — failed (%s); keeping original schema", exc)
        return schema


def _reject_empty_schema(improved: dict, original: dict, label: str) -> dict | None:
    """Return None if improved passes the lower-bound guard, else log and return original."""
    concepts = improved.get("concepts") or []
    original_concepts = original.get("concepts") or []
    if len(concepts) < 1:
        _log.warning("%s — LLM returned empty schema (0 concepts); keeping original", label)
        return original
    if original_concepts and len(concepts) < 0.5 * len(original_concepts):
        _log.warning(
            "%s — LLM removed >50%% of concepts (%d → %d); keeping original",
            label,
            len(original_concepts),
            len(concepts),
        )
        return original
    return None


def review_schema_quality(schema: dict, adapter: LLMAdapter, locked_block: str = "") -> dict:
    """Call the LLM to review the merged schema for quality issues.

    Returns the improved schema dict, or the original if the LLM response
    cannot be parsed or has the wrong structure.

    ``locked_block`` is the base-schema lock notice (D27). When non-empty it is appended
    to the system prompt so this unlocked pass — whose instructions explicitly tell the
    LLM to remove "singleton" concepts and rename "generic" properties — is told which
    names it must not touch. Empty by default; behaviour unchanged without a base schema.
    """
    user = json.dumps(schema, indent=2)
    system = _QUALITY_SYSTEM_PROMPT
    if locked_block:
        system = system + "\n\n" + locked_block
    try:
        raw = llm_complete_with_retry(
            adapter,
            system,
            user,
            context_label="schema_quality_review",
        )
        improved = json.loads(raw)
        if not isinstance(improved.get("concepts"), list) or not isinstance(
            improved.get("properties"), list
        ):
            _log.warning("schema_quality_review — wrong structure from LLM; keeping original")
            return schema
        fallback = _reject_empty_schema(improved, schema, "schema_quality_review")
        if fallback is not None:
            return fallback
        return _normalize_schema(improved)
    except Exception as exc:
        _log.warning("schema_quality_review — failed (%s); keeping original schema", exc)
        return schema


def harmonize_schema_for_merge(schema: dict, proposals: list[dict], adapter: LLMAdapter) -> dict:
    """LLM harmonization pass for the merge-graphs path.

    Uses a merge-specific prompt that forbids dropping any attributes from the union.
    Sees both the merged schema and the two source session schemas as proposals.
    Returns the improved schema, or the original if the response is unparseable.
    """
    proposals_block = json.dumps(proposals, indent=2)
    merged_block = json.dumps(schema, indent=2)
    user = "MERGED SCHEMA:\n" + merged_block + "\n\nSESSION SCHEMAS:\n" + proposals_block
    try:
        raw = llm_complete_with_retry(
            adapter,
            _MERGE_HARMONIZE_SYSTEM_PROMPT,
            user,
            context_label="merge_schema_harmonize",
        )
        improved = json.loads(raw)
        if not isinstance(improved.get("concepts"), list) or not isinstance(
            improved.get("properties"), list
        ):
            _log.warning("merge_schema_harmonize — wrong structure from LLM; keeping original")
            return schema
        return _normalize_schema(improved)
    except Exception as exc:
        _log.warning("merge_schema_harmonize — failed (%s); keeping original schema", exc)
        return schema


def review_schema_quality_for_merge(schema: dict, adapter: LLMAdapter) -> dict:
    """Quality review pass for the merge-graphs path.

    Uses a merge-specific prompt that has no attribute cap and explicitly forbids
    dropping any attribute present in the input schema.
    Returns the improved schema, or the original if the response is unparseable.
    """
    user = json.dumps(schema, indent=2)
    try:
        raw = llm_complete_with_retry(
            adapter,
            _MERGE_QUALITY_SYSTEM_PROMPT,
            user,
            context_label="merge_schema_quality_review",
        )
        improved = json.loads(raw)
        if not isinstance(improved.get("concepts"), list) or not isinstance(
            improved.get("properties"), list
        ):
            _log.warning("merge_schema_quality_review — wrong structure from LLM; keeping original")
            return schema
        fallback = _reject_empty_schema(improved, schema, "merge_schema_quality_review")
        if fallback is not None:
            return fallback
        return _normalize_schema(improved)
    except Exception as exc:
        _log.warning("merge_schema_quality_review — failed (%s); keeping original schema", exc)
        return schema
