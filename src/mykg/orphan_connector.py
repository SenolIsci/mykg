"""
Two-stage orphan-connection pass.

Stage 1 — co-occurrence heuristic (no LLM):
  Find nodes with zero edges in edge_metadata. For each orphan, scan
  chunk_node_index to find other nodes that appear in the same chunk(s).
  Score each co-occurring pair by normalized co-occurrence count, filter by
  min_cooccurrence, keep top-k per orphan. Output: list[OrphanCandidate].

Stage 2 — LLM confirmation:
  For each OrphanCandidate, ask the LLM whether a real schema relationship
  exists between the two nodes. Return confirmed edges to be merged into
  edge_metadata.

Schema feedback loop:
  Orphans whose type has no compatible schema properties (schema-gap orphans)
  are passed to propose_schema_additions(), which asks the LLM to propose
  new properties to close the gap. Callers merge proposals into schema.json
  and trigger Re-entry A (re-run from pass2).

Public API
----------
  score_orphan_candidates(nodes, edge_metadata, chunk_node_index, schema) -> list[OrphanCandidate]
  confirm_orphan_edges(candidates, schema, adapter) -> tuple[list[dict], list[dict]]
  propose_schema_additions(gap_orphans, schema, adapter, chunk_texts) -> dict | None
  build_chunk_texts(file_manifest) -> dict[str, str]
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from pydantic import BaseModel, Field

from mykg import config as _cfg
from mykg.chunker import chunk_file
from mykg.llm.adapter import LLMAdapter
from mykg.llm.error_gate import ErrorGate, noop_gate
from mykg.llm.retry import llm_complete_with_retry
from mykg.logging import get
from mykg.prompts import load_prompt

log = get("mykg.orphan_connector")


# ---------------------------------------------------------------------------
# Inter-stage data models
# ---------------------------------------------------------------------------


class SchemaGapOrphan(BaseModel):
    """An orphan whose type has no compatible schema property pairs.

    These nodes cannot produce Stage 1 candidates because the schema lacks
    any property where the orphan's type appears as domain or range.
    """

    orphan_id: str
    orphan_type: str
    orphan_name: str
    cooccurring_types: list[str]  # types of nodes co-occurring in chunks
    shared_chunks: list[str]  # chunk keys where this orphan appears


class OrphanCandidate(BaseModel):
    orphan_id: str
    orphan_type: str
    orphan_name: str
    candidate_id: str
    candidate_type: str
    candidate_name: str
    cooccurrence_count: int
    heuristic_score: float = Field(ge=0.0, le=1.0)
    shared_chunks: list[str] = Field(default_factory=list)


class OrphanChunkGroup(BaseModel):
    """All orphan nodes from a single source chunk, grouped for one LLM call."""

    chunk_key: str  # "filename::chunk_idx"
    filename: str
    chunk_idx: int
    is_blank_response: bool  # True if this chunk was skipped in pass2
    orphan_ids: list[str]  # stable IDs of orphan nodes from this chunk
    connected_ids: list[str]  # connected nodes that also appear in this chunk


# ---------------------------------------------------------------------------
# Stage 1 — co-occurrence heuristic
# ---------------------------------------------------------------------------


def _get_node_attr(node: dict, attr: str) -> str:
    val = node.get("attributes", {}).get(attr, {})
    if isinstance(val, dict):
        return str(val.get("value", "")) or node.get("id", "")
    return str(val) if val else node.get("id", "")


def _best_display_name(node: dict) -> str:
    """Return the best human-readable name for a node for excerpt matching.

    Tries 'name', then 'subject' (Documents), then 'title', falling back to the ID.
    """
    attrs = node.get("attributes", {})
    for key in ("name", "subject", "title"):
        val = attrs.get(key, {})
        if isinstance(val, dict):
            v = str(val.get("value", "") or "")
        else:
            v = str(val or "")
        if v:
            return v
    return node.get("id", "")


def _get_type_ancestors(type_name: str, concept_map: dict) -> set[str]:
    """Return type_name and all ancestor types by walking parent links."""
    ancestors: set[str] = {type_name}
    current = type_name
    while current in concept_map:
        parent = concept_map[current].get("parent")
        if not parent or parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def _is_schema_compatible(
    orphan_type: str, peer_type: str, concept_map: dict, valid_pairs: set[tuple[str, str]]
) -> bool:
    """Check compatibility considering the full inheritance hierarchy."""
    if not valid_pairs:
        return True
    for ot in _get_type_ancestors(orphan_type, concept_map):
        for pt in _get_type_ancestors(peer_type, concept_map):
            if (ot, pt) in valid_pairs:
                return True
    return False


def score_orphan_candidates(
    nodes: list[dict],
    edge_metadata: dict,
    chunk_node_index: dict,
    schema: dict,
    min_cooccurrence: int | None = None,
    top_k: int | None = None,
) -> tuple[list[OrphanCandidate], list[SchemaGapOrphan]]:
    """Stage 1: score orphan-candidate pairs by chunk co-occurrence.

    Returns (candidates, schema_gap_orphans) where:
    - candidates: sorted by (orphan_id, heuristic_score desc)
    - schema_gap_orphans: orphans with chunk appearances but no compatible schema
      property pairs — they cannot produce any candidates via type filtering
    """
    if min_cooccurrence is None:
        min_cooccurrence = _cfg.ORPHAN_MIN_COOCCURRENCE
    if top_k is None:
        top_k = _cfg.ORPHAN_TOP_K_PER_ORPHAN

    # Identify orphans: nodes with zero edge endpoints
    connected: set[str] = set()
    for edge in edge_metadata.values():
        connected.add(edge["from"])
        connected.add(edge["to"])

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    orphan_ids: set[str] = {n["id"] for n in nodes if n["id"] not in connected}

    if not orphan_ids:
        log.info("Stage 1 — no orphan nodes found")
        return [], []

    log.info("Stage 1 — %d orphan node(s) identified", len(orphan_ids))

    # Build inverted index: stable_id → list of (filename, chunk_idx) chunk keys
    id_to_chunks: dict[str, list[str]] = defaultdict(list)
    for filename, chunks in chunk_node_index.items():
        for chunk_idx, ids in chunks.items():
            chunk_key = f"{filename}::{chunk_idx}"
            for sid in ids:
                id_to_chunks[sid].append(chunk_key)

    # Build chunk → ids forward index for fast pair scoring
    chunk_to_ids: dict[str, set[str]] = defaultdict(set)
    for sid, chunk_keys in id_to_chunks.items():
        for ck in chunk_keys:
            chunk_to_ids[ck].add(sid)

    concept_map: dict[str, dict] = {c["type"]: c for c in schema.get("concepts", [])}

    # Valid property pairs for quick domain/range lookup
    valid_pairs: set[tuple[str, str]] = set()
    # Also track which types appear in any schema property (domain or range)
    schema_types: set[str] = set()
    for prop in schema.get("properties", []):
        valid_pairs.add((prop["domain"], prop["range"]))
        valid_pairs.add((prop["range"], prop["domain"]))
        schema_types.add(prop["domain"])
        schema_types.add(prop["range"])

    # For normalization: max chunks any node appears in
    max_chunks = max((len(v) for v in id_to_chunks.values()), default=1)

    candidates: list[OrphanCandidate] = []
    schema_gap_orphans: list[SchemaGapOrphan] = []

    for orphan_id in orphan_ids:
        orphan_chunks = set(id_to_chunks.get(orphan_id, []))
        if not orphan_chunks:
            log.debug("Stage 1 — orphan %s has no chunk appearances; skipping", orphan_id)
            continue

        orphan_node = node_by_id[orphan_id]
        orphan_type = orphan_node.get("type", "")

        # Count co-occurrences with every other node
        cooc: dict[str, list[str]] = defaultdict(list)
        for ck in orphan_chunks:
            for peer_id in chunk_to_ids[ck]:
                if peer_id != orphan_id and peer_id in node_by_id:
                    cooc[peer_id].append(ck)

        # Filter by min_cooccurrence and schema compatibility
        scored: list[tuple[float, str, list[str]]] = []
        all_cooccurring_types: set[str] = set()
        for peer_id, shared in cooc.items():
            peer_type = node_by_id[peer_id].get("type", "")
            all_cooccurring_types.add(peer_type)
            if len(shared) < min_cooccurrence:
                continue
            if valid_pairs and not _is_schema_compatible(
                orphan_type, peer_type, concept_map, valid_pairs
            ):
                continue
            # Normalize by max possible co-occurrence
            norm_score = min(1.0, len(shared) / max(max_chunks, 1))
            scored.append((norm_score, peer_id, shared))

        # If schema type-pair filter eliminated all co-occurring nodes, this is a
        # schema-gap orphan: the schema has no property compatible with any peer type
        # actually present in the corpus (e.g. Organization co-occurs with MilitaryOffice
        # but the only Organization property requires MilitaryUnit, which has no nodes).
        if not scored and cooc:
            log.debug(
                "Stage 1 — orphan %s (type=%s) filtered to zero candidates by schema type-pair; "
                "co-occurring types: %s",
                orphan_id,
                orphan_type,
                sorted(all_cooccurring_types),
            )
            schema_gap_orphans.append(
                SchemaGapOrphan(
                    orphan_id=orphan_id,
                    orphan_type=orphan_type,
                    orphan_name=_best_display_name(orphan_node),
                    cooccurring_types=sorted(all_cooccurring_types),
                    shared_chunks=sorted(orphan_chunks),
                )
            )
            continue

        # Top-k by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        for score, peer_id, shared in scored[:top_k]:
            peer_node = node_by_id[peer_id]
            candidates.append(
                OrphanCandidate(
                    orphan_id=orphan_id,
                    orphan_type=orphan_type,
                    orphan_name=_best_display_name(orphan_node),
                    candidate_id=peer_id,
                    candidate_type=peer_node.get("type", ""),
                    candidate_name=_best_display_name(peer_node),
                    cooccurrence_count=len(shared),
                    heuristic_score=round(score, 4),
                    shared_chunks=sorted(shared),
                )
            )

    if schema_gap_orphans:
        log.warning(
            "Stage 1 — %d schema-gap orphan(s) found "
            "(all co-occurring peers eliminated by schema type-pair filter): %s",
            len(schema_gap_orphans),
            [g.orphan_id for g in schema_gap_orphans],
        )
    log.info("Stage 1 — %d candidate pair(s) produced", len(candidates))
    return (
        sorted(candidates, key=lambda c: (c.orphan_id, -c.heuristic_score)),
        schema_gap_orphans,
    )


def score_orphan_candidates_v2(
    nodes: list[dict],
    edge_metadata: dict,
    chunk_node_index: dict,
    schema: dict,
    failed_chunks: list[dict] | None = None,
    file_manifest: dict | None = None,
) -> tuple[list[OrphanChunkGroup], list[SchemaGapOrphan]]:
    """Stage 1 (redesigned): group orphans by source chunk.

    Unlike score_orphan_candidates, this function:
    - Filters connected_ids by schema type-pair compatibility (per orphan in the group)
    - Ranks connected_ids by co-occurrence frequency across all orphans in the group
    - Handles blank-response orphans via failed_chunks + string search
    - Returns one OrphanChunkGroup per (filename, chunk_idx) instead of per candidate pair
    """
    failed_chunks = failed_chunks or []

    # Index failed chunks: {filename: [chunk_idx, ...]}
    failed_by_file: dict[str, list[int]] = defaultdict(list)
    for fc in failed_chunks:
        failed_by_file[fc["filename"]].append(fc["chunk_idx"])

    # Identify orphans
    connected: set[str] = set()
    for edge in edge_metadata.values():
        connected.add(edge["from"])
        connected.add(edge["to"])

    node_by_id: dict[str, dict] = {n["id"]: n for n in nodes}
    orphan_ids: set[str] = {n["id"] for n in nodes if n["id"] not in connected}

    if not orphan_ids:
        log.info("Stage 1 — no orphan nodes found")
        return [], []

    log.info("Stage 1 — %d orphan node(s) identified", len(orphan_ids))

    # Build inverted index: stable_id → list of chunk_keys
    id_to_chunks: dict[str, list[str]] = defaultdict(list)
    for filename, chunks in chunk_node_index.items():
        for chunk_idx_str, ids in chunks.items():
            chunk_key = f"{filename}::{chunk_idx_str}"
            for sid in ids:
                id_to_chunks[sid].append(chunk_key)

    # Build chunk → ids forward index
    chunk_to_ids: dict[str, set[str]] = defaultdict(set)
    for sid, chunk_keys in id_to_chunks.items():
        for ck in chunk_keys:
            chunk_to_ids[ck].add(sid)

    # Schema structures for type-pair compatibility filtering
    concept_map: dict[str, dict] = {c["type"]: c for c in schema.get("concepts", [])}
    valid_pairs: set[tuple[str, str]] = set()
    for prop in schema.get("properties", []):
        valid_pairs.add((prop["domain"], prop["range"]))
        valid_pairs.add((prop["range"], prop["domain"]))

    # Group orphans by chunk_key
    # connected_scores: {connected_id: count} — incremented each time a compatible
    # orphan in this group co-occurs with the connected node.
    chunk_groups: dict[str, dict] = {}
    unresolvable_orphans: list[str] = []

    for orphan_id in orphan_ids:
        orphan_chunks = id_to_chunks.get(orphan_id, [])
        orphan_type = node_by_id[orphan_id].get("type", "")

        if orphan_chunks:
            # Normal orphan: has index entry
            for ck in orphan_chunks:
                if ck not in chunk_groups:
                    fn, ci = ck.rsplit("::", 1)
                    chunk_groups[ck] = {
                        "filename": fn,
                        "chunk_idx": int(ci),
                        "is_blank_response": False,
                        "orphan_ids": [],
                        "connected_scores": defaultdict(int),
                    }
                chunk_groups[ck]["orphan_ids"].append(orphan_id)
                for sid in chunk_to_ids.get(ck, set()):
                    if sid == orphan_id or sid not in connected:
                        continue
                    peer_type = node_by_id[sid].get("type", "") if sid in node_by_id else ""
                    if _is_schema_compatible(orphan_type, peer_type, concept_map, valid_pairs):
                        chunk_groups[ck]["connected_scores"][sid] += 1
        else:
            # No index entry — check failed_chunks
            source_files = node_by_id[orphan_id].get("source_files", [])
            found_chunk = None
            for src_file in source_files:
                failed_idxs = failed_by_file.get(src_file, [])
                if not failed_idxs or file_manifest is None:
                    continue
                content = file_manifest.get(src_file, {})
                if isinstance(content, dict):
                    content = content.get("content", "")
                orphan_name = _best_display_name(node_by_id[orphan_id]).lower()
                chunks_list = list(chunk_file(src_file, content))
                for fidx in failed_idxs:
                    chunk_text = chunks_list[fidx - 1].text if fidx - 1 < len(chunks_list) else ""
                    if orphan_name and orphan_name in chunk_text.lower():
                        found_chunk = (src_file, fidx, chunk_text)
                        break
                if found_chunk:
                    break

            if found_chunk:
                src_file, fidx, _ = found_chunk
                ck = f"{src_file}::{fidx}"
                if ck not in chunk_groups:
                    chunk_groups[ck] = {
                        "filename": src_file,
                        "chunk_idx": fidx,
                        "is_blank_response": True,
                        "orphan_ids": [],
                        "connected_scores": defaultdict(int),
                    }
                chunk_groups[ck]["orphan_ids"].append(orphan_id)
                node_by_id[orphan_id]["extraction_quality"] = "blank_response"
                node_by_id[orphan_id]["blank_chunk_file"] = src_file
                node_by_id[orphan_id]["blank_chunk_idx"] = fidx
                log.debug(
                    "Stage 1 — orphan %s flagged as blank_response (chunk %s::%d)",
                    orphan_id,
                    src_file,
                    fidx,
                )
            else:
                log.debug("Stage 1 — orphan %s has no resolvable source chunk; skipping", orphan_id)
                unresolvable_orphans.append(orphan_id)

    if unresolvable_orphans:
        log.warning(
            "Stage 1 — %d orphan(s) with unknown provenance (no resolvable source chunk): %s",
            len(unresolvable_orphans),
            unresolvable_orphans,
        )

    groups = []
    for ck, g in chunk_groups.items():
        scores = g["connected_scores"]
        ranked_connected = sorted(scores, key=lambda k: scores[k], reverse=True)
        groups.append(
            OrphanChunkGroup(
                chunk_key=ck,
                filename=g["filename"],
                chunk_idx=g["chunk_idx"],
                is_blank_response=g["is_blank_response"],
                orphan_ids=sorted(set(g["orphan_ids"])),
                connected_ids=ranked_connected,
            )
        )

    log.info(
        "Stage 1 — %d chunk group(s) produced (%d orphan(s) total)",
        len(groups),
        sum(len(g.orphan_ids) for g in groups),
    )
    return groups, unresolvable_orphans


# ---------------------------------------------------------------------------
# Stage 2 — LLM confirmation
# ---------------------------------------------------------------------------

_ORPHAN_SYSTEM_PROMPT = load_prompt("orphan/pair_confirm_system")


def _extract_relevant_excerpt(
    text: str,
    names: list[str],
    window: int = _cfg.ORPHAN_EXCERPT_WINDOW,
    context: int = _cfg.ORPHAN_EXCERPT_CONTEXT,
    max_total: int = _cfg.ORPHAN_EXCERPT_MAX_TOTAL,
) -> str:
    """Return excerpts around ALL mentions of any of the given names in text.

    Each mention contributes one window. Overlapping windows are merged.
    Falls back to the first `window` characters if none of the names are found.
    Total output is capped at max_total characters.
    """
    text_lower = text.lower()

    # Collect all mention positions for all names
    positions: list[int] = []
    for name in names:
        name_lower = name.lower()
        start = 0
        while True:
            pos = text_lower.find(name_lower, start)
            if pos == -1:
                break
            positions.append(pos)
            start = pos + 1

    if not positions:
        excerpt = text[:window]
        return excerpt + ("…" if len(text) > window else "")

    # Build non-overlapping spans sorted by position
    positions.sort()
    spans: list[tuple[int, int]] = []
    for pos in positions:
        s = max(0, pos - context)
        e = min(len(text), s + window)
        if spans and s <= spans[-1][1]:
            # Merge with previous span
            spans[-1] = (spans[-1][0], max(spans[-1][1], e))
        else:
            spans.append((s, e))

    # Assemble excerpts up to budget
    parts: list[str] = []
    total = 0
    for s, e in spans:
        chunk = text[s:e]
        if total + len(chunk) > max_total:
            remaining = max_total - total
            if remaining > 80:
                parts.append(("…" if s > 0 else "") + chunk[:remaining] + "…")
            break
        parts.append(("…" if s > 0 else "") + chunk + ("…" if e < len(text) else ""))
        total += len(chunk)

    return "\n---\n".join(parts)


def _build_confirmation_prompt(
    candidate: OrphanCandidate,
    schema: dict,
    chunk_texts: dict[str, str],
) -> str:
    prop_lines = [
        f"  - {p['name']} ({p['domain']} → {p['range']})"
        for p in schema.get("properties", [])
        if (p["domain"], p["range"])
        in {
            (candidate.orphan_type, candidate.candidate_type),
            (candidate.candidate_type, candidate.orphan_type),
        }
    ]
    props_block = (
        "\n".join(prop_lines) if prop_lines else "  (no direct schema property for this type pair)"
    )

    # Build source excerpts: find relevant window around name mentions rather than
    # blindly taking the first N chars (chunks may start in overlap/junk regions).
    names_to_find = [candidate.orphan_name, candidate.candidate_name]
    excerpt_parts = []
    for ck in candidate.shared_chunks:
        text = chunk_texts.get(ck, "")
        if text:
            excerpt = _extract_relevant_excerpt(text, names_to_find)
            excerpt_parts.append(f"[{ck}]\n{excerpt}")
    excerpts_block = "\n\n".join(excerpt_parts) if excerpt_parts else "  (no source text available)"

    return (
        f"NODE A\n"
        f"  id:   {candidate.orphan_id}\n"
        f"  type: {candidate.orphan_type}\n"
        f"  name: {candidate.orphan_name}\n\n"
        f"NODE B\n"
        f"  id:   {candidate.candidate_id}\n"
        f"  type: {candidate.candidate_type}\n"
        f"  name: {candidate.candidate_name}\n\n"
        f"ALLOWED RELATIONSHIP TYPES (between these two node types)\n"
        f"{props_block}\n\n"
        f"SOURCE TEXT (excerpts from chunks where both nodes co-occur)\n"
        f"{excerpts_block}"
    )


def _confirm_one(
    candidate: OrphanCandidate,
    schema: dict,
    adapter: LLMAdapter,
    chunk_texts: dict[str, str],
) -> dict | None:
    prompt = _build_confirmation_prompt(candidate, schema, chunk_texts)
    raw = llm_complete_with_retry(
        adapter,
        _ORPHAN_SYSTEM_PROMPT,
        prompt,
        context_label=f"orphan stage2 {candidate.orphan_id}↔{candidate.candidate_id}",
    )
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning(
            "Stage 2 — JSON parse error for %s↔%s: %s",
            candidate.orphan_id,
            candidate.candidate_id,
            exc,
        )
        return None

    if not result.get("connected"):
        return None

    edge_type = result.get("type")
    if not edge_type:
        log.warning(
            "Stage 2 — connected=true but no type for %s↔%s",
            candidate.orphan_id,
            candidate.candidate_id,
        )
        return None

    valid_props = {
        p["name"]
        for p in schema.get("properties", [])
        if (p["domain"], p["range"])
        in {
            (candidate.orphan_type, candidate.candidate_type),
            (candidate.candidate_type, candidate.orphan_type),
        }
    }
    if edge_type not in valid_props:
        log.warning(
            "Stage 2 — '%s' incompatible with %s↔%s type pair, rejecting",
            edge_type,
            candidate.orphan_type,
            candidate.candidate_type,
        )
        return None

    matched_prop = next(
        (p for p in schema.get("properties", []) if p["name"] == edge_type),
        None,
    )
    from_id = candidate.orphan_id
    to_id = candidate.candidate_id
    if matched_prop:
        if (matched_prop["domain"], matched_prop["range"]) == (
            candidate.candidate_type,
            candidate.orphan_type,
        ):
            # LLM returned a property whose direction is candidate→orphan; flip
            from_id, to_id = candidate.candidate_id, candidate.orphan_id

    # Backfill edge attributes per Invariant 6: missing → {value: null, confidence: 0.0}
    prop_attrs = matched_prop.get("attributes", []) if matched_prop else []
    attributes = {attr: {"value": None, "confidence": 0.0} for attr in prop_attrs}

    llm_conf = max(0.0, min(1.0, float(result.get("confidence", _cfg.CONFIDENCE_FALLBACK))))
    heuristic = candidate.heuristic_score
    final_conf = round(
        llm_conf
        * min(1.0, _cfg.ORPHAN_CONFIDENCE_BASE + _cfg.ORPHAN_CONFIDENCE_WEIGHT * heuristic),
        4,
    )

    return {
        "type": edge_type,
        "from": from_id,
        "to": to_id,
        "confidence": final_conf,
        "method": "orphan_inferred",
        "attributes": attributes,
        "source_files": list({ck.split("::")[0] for ck in candidate.shared_chunks}),
        "_orphan_id": candidate.orphan_id,
        "_rationale": result.get("rationale", ""),
        "_heuristic_score": heuristic,
        "_llm_confidence": llm_conf,
    }


def build_chunk_texts(file_manifest: dict[str, str | dict]) -> dict[str, str]:
    """Re-chunk all files from the manifest and return a {filename::1-based-idx: text} map.

    pass2 stores chunk keys as str(i) with enumerate(chunks, 1), so chunk_index=0
    in chunk_file() corresponds to key "1" in the index. We map accordingly.

    Accepts both the legacy format (plain string values) and the current format
    (dict values with a "content" key written by step_ingest after the sha256 migration).
    """
    result: dict[str, str] = {}
    for filename, value in file_manifest.items():
        content = value["content"] if isinstance(value, dict) else value
        for chunk in chunk_file(filename, content):
            key = f"{filename}::{chunk.chunk_index + 1}"
            result[key] = chunk.text
    return result


def confirm_orphan_edges(
    candidates: list[OrphanCandidate],
    schema: dict,
    adapter: LLMAdapter,
    file_manifest: dict[str, str] | None = None,
    max_workers: int | None = None,
    chunk_texts: dict[str, str] | None = None,
    error_gate: ErrorGate | None = None,
) -> tuple[list[dict], list[dict]]:
    """Stage 2: ask LLM to confirm each candidate.

    Returns (confirmed, rejections) where:
    - confirmed: edge dicts ready to merge into edge_metadata
    - rejections: dicts with {orphan_id, candidate_id, reason} for audit logging
    """
    if max_workers is None:
        max_workers = _cfg.ORPHAN_MAX_WORKERS

    if chunk_texts is None:
        chunk_texts = build_chunk_texts(file_manifest) if file_manifest else {}
    if not chunk_texts:
        log.warning("Stage 2 — no file_manifest provided; LLM will receive no source text context")

    gate = error_gate if error_gate is not None else noop_gate()
    confirmed: list[dict] = []
    rejections: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures: dict[Any, OrphanCandidate] = {
            executor.submit(_confirm_one, c, schema, adapter, chunk_texts): c for c in candidates
        }
        for future in as_completed(futures):
            candidate = futures[future]
            try:
                edge = future.result()
                if edge is not None:
                    confirmed.append(edge)
                else:
                    rejections.append(
                        {
                            "orphan_id": candidate.orphan_id,
                            "candidate_id": candidate.candidate_id,
                            "reason": "llm_rejected",
                        }
                    )
            except Exception as exc:
                gate.record_error(exc)
                log.warning("Stage 2 — candidate %s failed: %s", candidate.candidate_id, exc)
                rejections.append(
                    {
                        "orphan_id": candidate.orphan_id,
                        "candidate_id": candidate.candidate_id,
                        "reason": "error",
                    }
                )

    log.info("Stage 2 — %d/%d candidate(s) confirmed as edges", len(confirmed), len(candidates))
    return confirmed, rejections


# ---------------------------------------------------------------------------
# Stage 2 (redesigned) — chunk-level batch LLM confirmation
# ---------------------------------------------------------------------------

_CHUNK_RECOVERY_SYSTEM_PROMPT = load_prompt("orphan/chunk_recovery_system")


def _build_chunk_recovery_prompt(
    group: OrphanChunkGroup,
    nodes: list[dict],
    schema: dict,
    chunk_texts: dict[str, str],
    connected_sample_size: int | None = None,
    node_by_id: dict[str, dict] | None = None,
) -> str:
    if connected_sample_size is None:
        connected_sample_size = getattr(_cfg, "ORPHAN_CONNECTED_SAMPLE_SIZE", 20)

    if node_by_id is None:
        node_by_id = {n["id"]: n for n in nodes}
    chunk_text = chunk_texts.get(group.chunk_key, "")

    orphan_lines = []
    for oid in group.orphan_ids:
        n = node_by_id.get(oid)
        if n:
            name = _best_display_name(n)
            orphan_lines.append(f"  - id: {oid}, type: {n.get('type', '?')}, name: {name}")

    connected_lines = []
    for cid in group.connected_ids[:connected_sample_size]:
        n = node_by_id.get(cid)
        if n:
            name = _best_display_name(n)
            connected_lines.append(f"  - id: {cid}, type: {n.get('type', '?')}, name: {name}")

    prop_lines = [
        f"  - {p['name']} ({p['domain']} → {p['range']})" for p in schema.get("properties", [])
    ]

    return (
        "ORPHAN NODES (find relationships for these)\n"
        "============================================\n"
        + ("\n".join(orphan_lines) or "  (none)")
        + "\n\n"
        "ALREADY-CONNECTED GRAPH NODES (cross-reference targets)\n"
        "=========================================================\n"
        + ("\n".join(connected_lines) or "  (none)")
        + "\n\n"
        "SCHEMA PROPERTIES\n"
        "=================\n" + ("\n".join(prop_lines) or "  (none)") + "\n\n"
        f"CHUNK SOURCE TEXT\n"
        f"=================\n"
        f"{chunk_text}"
    )


def confirm_orphan_chunk_groups(
    groups: list[OrphanChunkGroup],
    nodes: list[dict],
    schema: dict,
    adapter: LLMAdapter,
    chunk_texts: dict[str, str] | None = None,
    max_workers: int | None = None,
    error_gate: ErrorGate | None = None,
) -> tuple[list[dict], list[dict]]:
    """Stage 2 (redesigned): one LLM call per OrphanChunkGroup.

    Returns (confirmed_edges, rejections).
    Updates extraction_quality on nodes in-place:
      blank_response → blank_recovered  (if ≥1 edge found)
      blank_response → blank_unresolved (if no edges found after attempt)
    """
    if max_workers is None:
        max_workers = _cfg.ORPHAN_MAX_WORKERS
    if chunk_texts is None:
        chunk_texts = {}

    gate = error_gate if error_gate is not None else noop_gate()
    node_by_id = {n["id"]: n for n in nodes}
    prop_by_name = {p["name"]: p for p in schema.get("properties", [])}
    valid_edge_types = set(prop_by_name)
    all_node_ids = {n["id"] for n in nodes}

    confirmed: list[dict] = []
    rejections: list[dict] = []

    def _process_group(group: OrphanChunkGroup) -> tuple[list[dict], list[dict]]:
        prompt = _build_chunk_recovery_prompt(
            group, nodes, schema, chunk_texts, node_by_id=node_by_id
        )
        raw = llm_complete_with_retry(
            adapter,
            _CHUNK_RECOVERY_SYSTEM_PROMPT,
            prompt,
            context_label=f"orphan chunk_recovery {group.chunk_key}",
        )
        try:
            result = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("chunk_recovery — JSON parse error for %s: %s", group.chunk_key, exc)
            return [], [
                {"orphan_id": oid, "candidate_id": None, "reason": "parse_error"}
                for oid in group.orphan_ids
            ]

        if not isinstance(result, list):
            log.warning(
                "chunk_recovery — expected list for %s, got %s",
                group.chunk_key,
                type(result),
            )
            return [], [
                {"orphan_id": oid, "candidate_id": None, "reason": "wrong_type"}
                for oid in group.orphan_ids
            ]

        group_confirmed: list[dict] = []
        confirmed_orphan_ids: set[str] = set()

        for edge in result:
            etype = edge.get("type", "")
            from_id = edge.get("from", "")
            to_id = edge.get("to", "")

            if etype not in valid_edge_types:
                log.debug(
                    "chunk_recovery — unknown edge type %s in %s; dropping", etype, group.chunk_key
                )
                continue
            if from_id not in all_node_ids or to_id not in all_node_ids:
                log.debug(
                    "chunk_recovery — dangling edge %s→%s in %s; dropping",
                    from_id,
                    to_id,
                    group.chunk_key,
                )
                continue

            matched_prop = prop_by_name.get(etype)
            prop_attrs = matched_prop.get("attributes", []) if matched_prop else []
            attributes = {attr: {"value": None, "confidence": 0.0} for attr in prop_attrs}

            llm_conf = max(0.0, min(1.0, float(edge.get("confidence", _cfg.CONFIDENCE_FALLBACK))))

            group_confirmed.append(
                {
                    "type": etype,
                    "from": from_id,
                    "to": to_id,
                    "confidence": round(llm_conf, 4),
                    "method": "orphan_inferred",
                    "attributes": attributes,
                    "source_files": [group.filename],
                    "_rationale": edge.get("rationale", ""),
                    "_llm_confidence": llm_conf,
                    "_chunk_key": group.chunk_key,
                }
            )

            if from_id in group.orphan_ids:
                confirmed_orphan_ids.add(from_id)
            if to_id in group.orphan_ids:
                confirmed_orphan_ids.add(to_id)

        if group.is_blank_response:
            for oid in group.orphan_ids:
                node = node_by_id.get(oid)
                if node and node.get("extraction_quality") == "blank_response":
                    if oid in confirmed_orphan_ids:
                        node["extraction_quality"] = "blank_recovered"
                    else:
                        node["extraction_quality"] = "blank_unresolved"

        group_rejections = [
            {"orphan_id": oid, "candidate_id": None, "reason": "llm_rejected"}
            for oid in group.orphan_ids
            if oid not in confirmed_orphan_ids
        ]
        return group_confirmed, group_rejections

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_group, g): g for g in groups}
        for future in as_completed(futures):
            group = futures[future]
            try:
                gc, gr = future.result()
                confirmed.extend(gc)
                rejections.extend(gr)
            except Exception as exc:
                gate.record_error(exc)
                log.error("chunk_recovery — group %s failed: %s", group.chunk_key, exc)
                rejections.extend(
                    [
                        {"orphan_id": oid, "candidate_id": None, "reason": "error"}
                        for oid in group.orphan_ids
                    ]
                )

    log.info(
        "chunk_recovery — %d edge(s) confirmed across %d group(s)", len(confirmed), len(groups)
    )
    return confirmed, rejections


# ---------------------------------------------------------------------------
# Schema feedback loop — propose additions for schema-gap orphans
# ---------------------------------------------------------------------------

_SCHEMA_PROPOSAL_SYSTEM_PROMPT = load_prompt("orphan/schema_gap_system")


def propose_schema_additions(
    gap_orphans: list[SchemaGapOrphan],
    schema: dict,
    adapter: LLMAdapter,
    chunk_texts: dict[str, str],
) -> dict | None:
    """Ask the LLM to propose new schema properties for schema-gap orphans.

    Returns the parsed JSON proposal dict (with "new_properties" key) or None
    if the LLM response cannot be parsed or proposes nothing.
    """
    if not gap_orphans:
        return None

    concept_names = [c["type"] for c in schema.get("concepts", [])]
    existing_props = [
        f"  {p['name']} ({p['domain']} → {p['range']})" for p in schema.get("properties", [])
    ]

    orphan_blocks = []
    source_blocks = []
    for gap in gap_orphans:
        names_to_find = [gap.orphan_name]
        excerpt_parts = []
        for ck in gap.shared_chunks[:5]:  # limit chunks per orphan
            text = chunk_texts.get(ck, "")
            if text:
                excerpt = _extract_relevant_excerpt(text, names_to_find)
                excerpt_parts.append(f"  [{ck}]\n  {excerpt[:600]}")
        source_block = "\n".join(excerpt_parts) if excerpt_parts else "  (no source text available)"
        orphan_blocks.append(
            f"ORPHAN NODE\n"
            f"  id:   {gap.orphan_id}\n"
            f"  type: {gap.orphan_type}\n"
            f"  name: {gap.orphan_name}\n"
            f"  co-occurring types: {', '.join(gap.cooccurring_types) or '(none)'}\n"
        )
        source_blocks.append(f"SOURCE TEXT [{gap.orphan_id}]\n{source_block}")

    existing_block = "\n".join(existing_props) if existing_props else "  (none)"
    prompt = (
        f"EXISTING CONCEPTS\n"
        f"  {', '.join(concept_names)}\n\n"
        f"EXISTING PROPERTIES\n"
        f"{existing_block}\n\n"
        + "\n\n".join(orphan_blocks)
        + "\n\nPropose new properties to connect the orphan types above from the source text."
        + "\n\n"
        + "\n\n".join(source_blocks)
    )

    log.info(
        "Schema feedback — calling LLM to propose properties for %d schema-gap orphan(s): %s",
        len(gap_orphans),
        [g.orphan_id for g in gap_orphans],
    )
    raw = llm_complete_with_retry(
        adapter,
        _SCHEMA_PROPOSAL_SYSTEM_PROMPT,
        prompt,
        context_label="orphan schema-gap proposal",
    )
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("Schema feedback — JSON parse error: %s", exc)
        return None

    new_props = result.get("new_properties", [])
    if not new_props:
        log.info("Schema feedback — LLM proposed no new properties")
        return None

    # Filter out properties whose domain or range aren't declared concepts (#92)
    declared_types = {c["type"] for c in schema.get("concepts", [])}
    valid_props = []
    for prop in new_props:
        domain, range_ = prop.get("domain"), prop.get("range")
        if domain not in declared_types or range_ not in declared_types:
            log.warning(
                "Schema feedback — dropping proposed property '%s': domain '%s' or range '%s' "
                "not in declared concepts %s",
                prop.get("name"),
                domain,
                range_,
                sorted(declared_types),
            )
        else:
            valid_props.append(prop)

    if not valid_props:
        log.info("Schema feedback — all proposed properties dropped after domain/range validation")
        return {"new_properties": []}

    log.info(
        "Schema feedback — LLM proposed %d new property/properties (%d kept after validation): %s",
        len(new_props),
        len(valid_props),
        [p.get("name") for p in valid_props],
    )
    return {"new_properties": valid_props}
