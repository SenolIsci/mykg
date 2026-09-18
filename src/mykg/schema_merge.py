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
                _union_attributes(
                    existing, concept, thesaurus, synonym_log, "concept", match_key
                )
                # Keep existing parent if locked; update only if no existing parent
                incoming_parent = concept.get("parent")
                if existing["parent"] is None and incoming_parent:
                    if match_key not in locked_classes:
                        existing["parent"] = incoming_parent
                elif (
                    incoming_parent
                    and existing["parent"] is not None
                    and incoming_parent != existing["parent"]
                ):
                    _record_parent_conflict(
                        existing,
                        match_key,
                        incoming_parent,
                        match_key in locked_classes,
                        thesaurus,
                        synonym_log,
                    )
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
                _union_attributes(
                    existing, prop, thesaurus, synonym_log, "property", match_key
                )
                _record_domain_range_conflicts(
                    existing, prop, match_key, match_key in locked_properties, synonym_log
                )
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


def _union_attributes(
    existing: dict,
    incoming: dict,
    thesaurus: SynonymIndex | None,
    synonym_log: list[dict],
    kind: str,
    match_key: str,
) -> None:
    """Union incoming attributes into ``existing``, flagging near-duplicates.

    Attributes are never collapsed — the merge prompts forbid dropping any
    attribute from the union — so a synonym pair is recorded and both names
    are kept for a human to reconcile.
    """
    for attr in incoming.get("attributes", []):
        if attr in existing["attributes"]:
            continue
        twin = next(
            (a for a in existing["attributes"] if synonym_match(attr, a, thesaurus)),
            None,
        )
        if twin is not None:
            synonym_log.append(
                {
                    "event": "attribute_synonym",
                    "kind": kind,
                    "owner": match_key,
                    "kept": twin,
                    "added": attr,
                    "reason": "near-duplicate attribute; both retained",
                }
            )
        existing["attributes"].append(attr)


def _record_parent_conflict(
    existing: dict,
    match_key: str,
    incoming_parent: str,
    is_locked: bool,
    thesaurus: SynonymIndex | None,
    synonym_log: list[dict],
) -> None:
    """Log a concept-parent disagreement, resolving it via skos:broader if possible.

    A locked class owns its parent (D27), so the conflict is recorded but never
    arbitrated. Otherwise the thesaurus breaks the tie only when exactly one
    candidate is a declared broader term; anything ambiguous keeps first-seen.
    """
    kept = existing["parent"]
    if not is_locked and thesaurus is not None:
        broader = thesaurus.broader.get(match_key, [])
        kept_ok = any(synonym_match(kept, b, thesaurus) for b in broader)
        incoming_ok = any(synonym_match(incoming_parent, b, thesaurus) for b in broader)
        if kept_ok != incoming_ok:
            winner = kept if kept_ok else incoming_parent
            loser = incoming_parent if kept_ok else kept
            existing["parent"] = winner
            synonym_log.append(
                {
                    "event": "parent_conflict_resolved",
                    "concept": match_key,
                    "resolved_to": winner,
                    "rejected": loser,
                    "via": "skos:broader",
                }
            )
            return

    synonym_log.append(
        {
            "event": "parent_conflict",
            "concept": match_key,
            "kept": kept,
            "discarded": incoming_parent,
            "reason": "locked class owns its parent"
            if is_locked
            else "first-seen wins; not resolved",
        }
    )


def _record_domain_range_conflicts(
    existing: dict,
    incoming: dict,
    match_key: str,
    is_locked: bool,
    synonym_log: list[dict],
) -> None:
    """Log domain/range disagreements between two proposals of the same property.

    Behaviour is unchanged — first-seen still wins — but the discarded value is
    no longer lost silently. A proposal that omits the field is not a conflict.
    """
    for field in ("domain", "range"):
        incoming_value = incoming.get(field)
        if not incoming_value or incoming_value == existing.get(field):
            continue
        synonym_log.append(
            {
                "event": "domain_range_conflict",
                "property": match_key,
                "field": field,
                "kept": existing.get(field),
                "discarded": incoming_value,
                "reason": "locked property owns its domain/range"
                if is_locked
                else "first-seen wins; not resolved",
            }
        )


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


def _sanctioned_collapses(schema: dict, thesaurus: SynonymIndex | None) -> list[tuple[str, str]]:
    """Return concept pairs the thesaurus explicitly relates, as (a, b) tuples.

    These are the only collapses the merge quality stage is permitted to make. A
    concept pair with no SKOS relation is preserved even when a thesaurus is loaded
    for other terms.
    """
    if thesaurus is None:
        return []
    types = [c["type"] for c in schema.get("concepts", []) if isinstance(c, dict) and "type" in c]
    pairs: list[tuple[str, str]] = []
    for i, a in enumerate(types):
        for b in types[i + 1 :]:
            if thesaurus.is_exact(a, b) or thesaurus.is_close(a, b):
                pairs.append((a, b))
    return pairs


def _concept_preservation_block(schema: dict, thesaurus: SynonymIndex | None) -> str:
    """Build the merge-only instruction block naming every concept that must survive.

    Mirrors the D27 locked-block mechanism, but is always present on the merge path
    and derived from the schema under review rather than a base-schema file. The
    wording is conditional: without a thesaurus no concept may be removed at all;
    with one, only the pairs it actually relates may collapse.
    """
    concepts = [c for c in schema.get("concepts", []) if isinstance(c, dict) and "type" in c]
    names = ", ".join(sorted(c["type"] for c in concepts))
    edges = sorted(
        f"{c['type']} is-a {c['parent']}" for c in concepts if c.get("parent")
    )
    hierarchy = "; ".join(edges) if edges else "(no is-a edges yet)"

    lines = [
        "CONCEPTS THAT MUST SURVIVE",
        "==========================",
        f"The input schema has {len(concepts)} concepts: {names}",
        f"Existing is-a hierarchy: {hierarchy}",
        "",
        "Every one of these concept names must appear in the concepts[] you return.",
        "Instances already in the graph carry these names as their type; deleting a",
        "concept strands them with a type that no longer exists in the schema.",
        "If a concept seems too specific or redundant, give it a \"parent\" — never",
        "remove it. You may add new concepts and you may change a \"parent\".",
    ]

    sanctioned = _sanctioned_collapses(schema, thesaurus)
    if sanctioned:
        pair_text = "; ".join(f"{a} / {b}" for a, b in sanctioned)
        lines += [
            "",
            "The single exception: an external SKOS thesaurus declares these pairs",
            f"equivalent, so you may collapse each pair into one concept: {pair_text}.",
            "No other concept may be removed.",
        ]
    return "\n".join(lines)


def _restore_deleted_concepts(
    improved: dict,
    original: dict,
    thesaurus: SynonymIndex | None,
    log: list[dict],
) -> dict:
    """Re-insert concepts the LLM removed unless the thesaurus sanctions the removal.

    Deleting a concept strands every instance whose stable ID carries that type
    (D19), so a removal is only honoured when a SKOS thesaurus explicitly relates
    the missing concept to one that survives.
    """
    original_by_type = {
        c["type"]: c for c in original.get("concepts", []) if isinstance(c, dict) and "type" in c
    }
    surviving = [
        c["type"] for c in improved.get("concepts", []) if isinstance(c, dict) and "type" in c
    ]
    surviving_set = set(surviving)
    missing = [t for t in original_by_type if t not in surviving_set]
    if not missing:
        return improved

    for ctype in missing:
        partner = None
        if thesaurus is not None:
            partner = next(
                (
                    s
                    for s in surviving
                    if thesaurus.is_exact(ctype, s) or thesaurus.is_close(ctype, s)
                ),
                None,
            )
        if partner is not None:
            log.append(
                {
                    "event": "concept_collapsed_by_thesaurus",
                    "concept": ctype,
                    "collapsed_into": partner,
                    "reason": "SKOS thesaurus relates the pair; removal permitted",
                }
            )
            continue

        restored = dict(original_by_type[ctype])
        restored["attributes"] = list(restored.get("attributes", []))
        # A parent that the LLM also removed would dangle; schema_validator requires
        # every non-null parent to be a declared class.
        if restored.get("parent") and restored["parent"] not in surviving_set:
            restored["parent"] = None
        improved["concepts"].append(restored)
        surviving_set.add(ctype)
        log.append(
            {
                "event": "concept_restored",
                "concept": ctype,
                "parent": restored.get("parent"),
                "reason": "quality review removed a concept with no thesaurus sanction",
            }
        )
    return improved


def _flag_attribute_synonyms(
    schema: dict, thesaurus: SynonymIndex | None, log: list[dict]
) -> None:
    """Record near-duplicate attribute names left on a concept by the LLM stages.

    Detection only — both names are kept, since the merge prompts forbid dropping
    any attribute. Complements _union_attributes, which runs before the LLM.
    """
    for concept in schema.get("concepts", []):
        if not isinstance(concept, dict):
            continue
        attrs = [a for a in concept.get("attributes", []) if isinstance(a, str)]
        for i, a in enumerate(attrs):
            for b in attrs[i + 1 :]:
                if synonym_match(a, b, thesaurus):
                    log.append(
                        {
                            "event": "attribute_synonym",
                            "kind": "concept",
                            "owner": concept.get("type"),
                            "kept": a,
                            "added": b,
                            "reason": "near-duplicate attribute; both retained",
                        }
                    )


def harmonize_schema_for_merge(
    schema: dict,
    proposals: list[dict],
    adapter: LLMAdapter,
    thesaurus: SynonymIndex | None = None,
    log: list[dict] | None = None,
) -> dict:
    """LLM harmonization pass for the merge-graphs path.

    Uses a merge-specific prompt that forbids dropping any attributes from the union.
    Sees both the merged schema and the two source session schemas as proposals.
    Concepts the LLM removes are restored unless ``thesaurus`` sanctions the removal.
    Returns the improved schema, or the original if the response is unparseable.
    """
    events = log if log is not None else []
    proposals_block = json.dumps(proposals, indent=2)
    merged_block = json.dumps(schema, indent=2)
    user = "MERGED SCHEMA:\n" + merged_block + "\n\nSESSION SCHEMAS:\n" + proposals_block
    system = (
        _MERGE_HARMONIZE_SYSTEM_PROMPT
        + "\n\n"
        + _concept_preservation_block(schema, thesaurus)
    )
    try:
        raw = llm_complete_with_retry(
            adapter,
            system,
            user,
            context_label="merge_schema_harmonize",
        )
        improved = json.loads(raw)
        if not isinstance(improved.get("concepts"), list) or not isinstance(
            improved.get("properties"), list
        ):
            _log.warning("merge_schema_harmonize — wrong structure from LLM; keeping original")
            return schema
        improved = _restore_deleted_concepts(improved, schema, thesaurus, events)
        return _normalize_schema(improved)
    except Exception as exc:
        _log.warning("merge_schema_harmonize — failed (%s); keeping original schema", exc)
        return schema


def review_schema_quality_for_merge(
    schema: dict,
    adapter: LLMAdapter,
    thesaurus: SynonymIndex | None = None,
    log: list[dict] | None = None,
) -> dict:
    """Quality review pass for the merge-graphs path.

    Uses a merge-specific prompt that has no attribute cap and explicitly forbids
    dropping any attribute present in the input schema. Concepts the LLM removes are
    restored unless ``thesaurus`` sanctions the removal.
    Returns the improved schema, or the original if the response is unparseable.
    """
    events = log if log is not None else []
    user = json.dumps(schema, indent=2)
    system = (
        _MERGE_QUALITY_SYSTEM_PROMPT + "\n\n" + _concept_preservation_block(schema, thesaurus)
    )
    try:
        raw = llm_complete_with_retry(
            adapter,
            system,
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
        improved = _restore_deleted_concepts(improved, schema, thesaurus, events)
        improved = _normalize_schema(improved)
        _flag_attribute_synonyms(improved, thesaurus, events)
        return improved
    except Exception as exc:
        _log.warning("merge_schema_quality_review — failed (%s); keeping original schema", exc)
        return schema
