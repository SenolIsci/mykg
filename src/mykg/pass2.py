from __future__ import annotations

import json
import pathlib
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed

from mykg import config as _cfg
from mykg.chunker import Chunk, chunk_file
from mykg.ids import stable_id as _ids_stable_id
from mykg.llm.adapter import LLMAdapter
from mykg.llm.error_gate import ErrorGate, noop_gate
from mykg.llm.retry import llm_complete_with_retry
from mykg.logging import get
from mykg.pass2_batch import build_pass2_batches, make_batch_map
from mykg.prompts import load_prompt

log = get("mykg.pass2")


class FailedChunkLog:
    """Thread-safe accumulator for chunks that returned None from _extract_chunk."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: list[dict] = []

    def record(self, filename: str, chunk_idx: int, reason: str = "blank_response") -> None:
        with self._lock:
            self._entries.append({"filename": filename, "chunk_idx": chunk_idx, "reason": reason})

    def entries(self) -> list[dict]:
        with self._lock:
            return list(self._entries)


PASS2_SYSTEM_PROMPT = load_prompt("pass2/system")


def validate_extraction(
    extraction: dict,
    schema: dict,
    flat_schema: dict,
    prior_nodes: list[dict] | None = None,
) -> list[str]:
    errors: list[str] = []

    # Check top-level structure first
    expected_keys = {"nodes", "edges"}
    actual_keys = set(extraction.keys())
    unexpected = actual_keys - expected_keys
    missing = expected_keys - actual_keys

    if unexpected:
        errors.append(
            f"Unexpected top-level keys in LLM response: {sorted(unexpected)} — "
            "expected only 'nodes' and 'edges'"
        )

    if missing:
        for key in sorted(missing):
            errors.append(f"Missing required top-level key: '{key}'")

    # Return early if structural problems found
    if errors:
        return errors

    clean = _strip_nulls(extraction)
    valid_types = {c["type"] for c in schema["concepts"]}
    valid_props = {p["name"] for p in schema["properties"]}
    node_ids = {n["id"] for n in clean["nodes"] if n.get("id")}
    if prior_nodes:
        node_ids |= {n["id"] for n in prior_nodes if n and n.get("id")}

    for node in clean["nodes"]:
        if node["type"] not in valid_types:
            errors.append(f"Unknown node type: {node['type']}")
        if not node.get("id"):
            errors.append(f"Node missing or empty 'id' field: type={node.get('type', '?')}")
        if not isinstance(node.get("attributes"), dict):
            errors.append(f"Node 'attributes' must be a dict: id={node.get('id', '?')}")

    for edge in clean["edges"]:
        if edge["type"] not in valid_props:
            errors.append(f"Unknown edge type: {edge['type']}")
        if edge["from"] not in node_ids:
            errors.append(f"Edge from unknown node ID: {edge['from']}")
        if edge["to"] not in node_ids:
            errors.append(f"Edge to unknown node ID: {edge['to']}")
        if "confidence" not in edge:
            errors.append(
                f"Edge missing 'confidence' field: {edge.get('type', '?')} "
                f"{edge.get('from', '?')}→{edge.get('to', '?')}"
            )

    return errors


def _build_extraction_prompt(
    file_content: str,
    schema: dict,
    flat_schema: dict,
    prior_nodes: list[dict] | None = None,
    hint_block: str | None = None,
) -> str:
    # Build per-type edge lookup for the linkage reminder in the schema block
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for prop in schema["properties"]:
        outgoing.setdefault(prop["domain"], []).append(f"{prop['name']} → {prop['range']}")
        incoming.setdefault(prop["range"], []).append(f"{prop['domain']} → {prop['name']}")

    concept_lines = []
    for concept in schema["concepts"]:
        t = concept["type"]
        attrs = flat_schema.get(t, concept.get("attributes", []))
        lines = [f"  - {t}: attributes = {attrs}"]
        if t in outgoing:
            lines.append(f"    Outgoing edges: {', '.join(outgoing[t])}")
        if t in incoming:
            lines.append(f"    Incoming edges: {', '.join(incoming[t])}")
        concept_lines.append("\n".join(lines))

    prop_lines = []
    for prop in schema["properties"]:
        prop_lines.append(
            f"  - {prop['name']} ({prop['domain']} → {prop['range']}): "
            f"edge attributes = {prop.get('attributes', [])}"
        )

    schema_block = "SCHEMA\n======\nConcept types:\n" + "\n".join(concept_lines)
    if prop_lines:
        schema_block += "\n\nRelationship types:\n" + "\n".join(prop_lines)

    prior_block = ""
    if prior_nodes:
        lines = []
        for n in prior_nodes:
            name = n.get("attributes", {}).get("name", {})
            name_val = name.get("value") if isinstance(name, dict) else name
            lines.append(f'  - id={n["id"]} type={n["type"]} name="{name_val}"')
        prior_block = "\n\nNODES ALREADY EXTRACTED\n========================\n" + "\n".join(lines)

    return (
        schema_block + prior_block + (hint_block or "") + "\n\nDOCUMENT\n========\n" + file_content
    )


def _strip_nulls(extraction: dict) -> dict:
    """Return a copy of extraction with null items removed from nodes and edges arrays.

    Some LLMs (e.g. Gemma via OpenRouter) emit null items inside these arrays.
    Callers that need to iterate nodes/edges should call this first.
    """
    return {
        "nodes": [n for n in (extraction.get("nodes") or []) if n is not None],
        "edges": [e for e in (extraction.get("edges") or []) if e is not None],
    }


def _normalize_scalars(extraction: dict) -> dict:
    """Coerce bare scalar attribute values to {value, confidence} without an LLM call.

    Null scalars get confidence 0.0 (value unknown). Non-null scalars get
    CONFIDENCE_SCALAR_OMITTED (LLM knew the value but omitted the wrapper).
    """
    for node in extraction.get("nodes") or []:
        if node is None:
            continue
        attrs = node.get("attributes", {})
        if not isinstance(attrs, dict):
            node["attributes"] = {}
            continue
        for attr, val in attrs.items():
            if not isinstance(val, dict) or "value" not in val:
                conf = 0.0 if val is None else _cfg.CONFIDENCE_SCALAR_OMITTED
                node["attributes"][attr] = {"value": val, "confidence": conf}
    for edge in extraction.get("edges") or []:
        if edge is None:
            continue
        attrs = edge.get("attributes", {})
        if not isinstance(attrs, dict):
            edge["attributes"] = {}
            continue
        for attr, val in attrs.items():
            if not isinstance(val, dict) or "value" not in val:
                conf = 0.0 if val is None else _cfg.CONFIDENCE_SCALAR_OMITTED
                edge["attributes"][attr] = {"value": val, "confidence": conf}
    return extraction


def _backfill_extraction(extraction: dict, schema: dict, flat_schema: dict) -> dict:
    """Enforce Invariant 6: missing attributes backfilled with {value: null, confidence: 0.0}."""
    prop_attrs: dict[str, list[str]] = {
        p["name"]: p.get("attributes", []) for p in schema["properties"]
    }
    for node in extraction.get("nodes") or []:
        if node is None:
            continue
        expected = flat_schema.get(node["type"], [])
        attrs = node.setdefault("attributes", {})
        for attr in expected:
            if attr not in attrs:
                attrs[attr] = {"value": None, "confidence": 0.0}
    for edge in extraction.get("edges") or []:
        if edge is None:
            continue
        expected = prop_attrs.get(edge["type"], [])
        attrs = edge.setdefault("attributes", {})
        for attr in expected:
            if attr not in attrs:
                attrs[attr] = {"value": None, "confidence": 0.0}
    return extraction


def _name_slug(node: dict) -> str:
    """Return the stable ID for a node dict, using ids.stable_id for slug generation."""
    name_attr = node.get("attributes", {}).get("name", {})
    if isinstance(name_attr, dict):
        name_val = name_attr.get("value") or node["id"]
    else:
        name_val = str(name_attr) if name_attr else node["id"]
    return _ids_stable_id(node["type"], str(name_val))


def _dedup_within_file(nodes: list[dict]) -> list[dict]:
    """Deduplicate nodes within a file by type+name slug, keeping highest-confidence attrs."""
    seen: dict[str, dict] = {}
    for node in nodes:
        key = _name_slug(node)
        if key not in seen:
            seen[key] = node
        else:
            existing = seen[key]
            node_attrs = node.get("attributes", {})
            if not isinstance(node_attrs, dict):
                continue
            for attr, val in node_attrs.items():
                existing_attr = existing.get("attributes", {}).get(attr)
                if isinstance(val, dict) and isinstance(existing_attr, dict):
                    if val.get("confidence", 0.0) > existing_attr.get("confidence", 0.0):
                        existing["attributes"][attr] = val
                elif attr not in existing.get("attributes", {}):
                    existing.setdefault("attributes", {})[attr] = val
    return list(seen.values())


def _partial_recover(extraction: dict, schema: dict, prior_nodes: list[dict] | None = None) -> dict:
    """Filter out nodes with undeclared types and edges that reference unknown nodes or properties.

    After edge filtering, also drops nodes that are new to this chunk (not in prior_nodes) and
    are not anchored by any surviving edge — these are hallucinated placeholder nodes whose only
    purpose was to be endpoints for the edges that were just dropped.
    """
    clean = _strip_nulls(extraction)
    valid_types = {c["type"] for c in schema["concepts"]}
    all_nodes = clean["nodes"]
    valid_nodes = [n for n in all_nodes if n.get("type") in valid_types]
    dropped_nodes = len(all_nodes) - len(valid_nodes)
    if dropped_nodes:
        log.warning(
            "    partial recovery — dropped %d node(s) with undeclared type(s)", dropped_nodes
        )

    valid_props = {p["name"] for p in schema["properties"]}
    node_ids = {n["id"] for n in valid_nodes}
    prior_ids = {n["id"] for n in prior_nodes} if prior_nodes else set()
    if prior_ids:
        node_ids |= prior_ids
    all_edges = clean["edges"]
    valid_edges = [
        e
        for e in all_edges
        if e["type"] in valid_props and e["from"] in node_ids and e["to"] in node_ids
    ]
    dropped = len(all_edges) - len(valid_edges)
    if dropped:
        log.warning("    partial recovery — dropped %d invalid edge(s)", dropped)

    # Drop nodes that are new to this chunk and have no surviving edge — hallucinated anchors.
    anchored_ids = {e["from"] for e in valid_edges} | {e["to"] for e in valid_edges}
    final_nodes = [n for n in valid_nodes if n["id"] in prior_ids or n["id"] in anchored_ids]
    dropped_anchors = len(valid_nodes) - len(final_nodes)
    if dropped_anchors:
        log.warning(
            "    partial recovery — dropped %d unanchored node(s) (hallucinated placeholder)",
            dropped_anchors,
        )

    return {"nodes": final_nodes, "edges": valid_edges}


def _extract_chunk(
    text: str,
    schema: dict,
    flat_schema: dict,
    adapter: LLMAdapter,
    chunk_idx: int,
    prior_nodes: list[dict] | None = None,
    hint_block: str | None = None,
) -> dict | None:
    user = _build_extraction_prompt(text, schema, flat_schema, prior_nodes, hint_block)
    raw = llm_complete_with_retry(
        adapter, PASS2_SYSTEM_PROMPT, user, context_label=f"pass2 chunk {chunk_idx}"
    )
    try:
        extraction = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        log.warning("    chunk %d — JSON parse error: %s — retrying", chunk_idx, exc)
        retry_user = (
            "Your previous response was not valid JSON. "
            "Return only a JSON object with 'nodes' and 'edges' keys.\n\n" + user
        )
        raw = llm_complete_with_retry(
            adapter,
            PASS2_SYSTEM_PROMPT,
            retry_user,
            context_label=f"pass2 chunk {chunk_idx} retry-json",
        )
        try:
            extraction = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc2:
            log.warning(
                "    chunk %d — retry JSON parse error: %s — skipping chunk", chunk_idx, exc2
            )
            return None

    # Primary null-guard: some LLMs (e.g. Gemma via OpenRouter) emit null items inside arrays.
    extraction = _strip_nulls(extraction)

    extraction = _normalize_scalars(extraction)
    errors = validate_extraction(extraction, schema, flat_schema, prior_nodes)
    if errors:
        log.warning("    chunk %d — validation errors: %s — retrying", chunk_idx, errors)
        error_context = "Previous attempt had errors:\n" + "\n".join(errors)
        retry_user = error_context + "\n\n" + user
        raw2 = llm_complete_with_retry(
            adapter,
            PASS2_SYSTEM_PROMPT,
            retry_user,
            context_label=f"pass2 chunk {chunk_idx} retry-validation",
        )
        try:
            extraction2 = json.loads(raw2)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning(
                "    chunk %d — retry JSON parse error: %s — dropping invalid edges",
                chunk_idx,
                exc,
            )
            extraction = _partial_recover(extraction, schema, prior_nodes)
            return _backfill_extraction(extraction, schema, flat_schema)

        extraction2 = _strip_nulls(extraction2)
        extraction2 = _normalize_scalars(extraction2)
        errors2 = validate_extraction(extraction2, schema, flat_schema, prior_nodes)
        if errors2:
            log.warning(
                "    chunk %d — retry still has errors — accepting nodes, dropping invalid edges",
                chunk_idx,
            )
            extraction2 = _partial_recover(extraction2, schema, prior_nodes)
        return _backfill_extraction(extraction2, schema, flat_schema)

    return _backfill_extraction(extraction, schema, flat_schema)


def _extract_batch(
    batch: list[Chunk],
    schema: dict,
    flat_schema: dict,
    adapter: LLMAdapter,
    batch_idx: int,
    prior_nodes: list[dict] | None = None,
    hint_block: str | None = None,
) -> dict | None:
    """Call the LLM once for an entire batch of chunks concatenated with blank-line separators."""
    text = "\n\n".join(c.text for c in batch)
    return _extract_chunk(text, schema, flat_schema, adapter, batch_idx, prior_nodes, hint_block)


def _build_schema_hint_block(chunk_key: str, schema_hints: list[dict]) -> str:
    """Return a targeted hint block for chunks that contain schema-gap orphan nodes.

    chunk_key format: "filename::chunk_idx" (e.g. "input.md::1").
    Only hints whose shared_chunks include this chunk_key are included.
    Returns empty string when no hints apply to this chunk.
    """
    applicable = [h for h in schema_hints if chunk_key in h.get("shared_chunks", [])]
    if not applicable:
        return ""

    lines = [
        "\nSCHEMA ADDITION HINT",
        "====================",
        "The following properties were added to the schema after the previous extraction pass.",
        "These specific nodes previously had no edges. Extract relationships for them using",
        "the new property types listed below — even weak evidence counts.\n",
    ]
    for h in applicable:
        props = ", ".join(h["new_properties"])
        lines.append(f"  Node: {h['orphan_name']} (id={h['orphan_id']}, type={h['orphan_type']})")
        lines.append(f"  New property/properties to look for: {props}")
    return "\n".join(lines)


def _fmt_elapsed(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h}h {m:02d}m {s:02d}s" if h else f"{m}m {s:02d}s"


def run_pass2(
    files: dict[str, str],
    schema: dict,
    flat_schema: dict,
    adapter: LLMAdapter,
    max_workers: int | None = None,
    schema_hints: list[dict] | None = None,
    on_file_done: Callable[[str, dict, dict], None] | None = None,
    skip_files: set[str] | None = None,
    error_gate: ErrorGate | None = None,
    reextract_chunks: dict[str, set[int]] | None = None,
    prior_extractions: dict[str, dict] | None = None,
    prior_chunk_index: dict[str, dict[str, list[str]]] | None = None,
    intermediate_dir: pathlib.Path | None = None,
) -> tuple[dict, dict, list[dict]]:
    """Return (raw_extractions, chunk_node_index, failed_chunks).

    chunk_node_index format: {filename: {str(chunk_idx): [stable_id, ...]}}
    stable_ids are computed via _name_slug at pass2 time (before assembler dedup).
    schema_hints: per-orphan hints from a prior schema-gap Re-entry A; injected into
    the prompt only for the chunks where the orphan node was previously found.
    reextract_chunks: when provided, only re-run the specified 1-based chunk indices
    per file; all other chunks are kept from prior_extractions/prior_chunk_index.
    This enables surgical schema-gap restarts without re-extracting the full corpus.
    failed_chunks: list of {filename, chunk_idx, reason} dicts for chunks skipped due
    to blank/unparseable LLM responses; also written to intermediate_dir/failed_chunks.json
    when intermediate_dir is provided.
    """
    if max_workers is None:
        max_workers = _cfg.PASS2_MAX_WORKERS
    if skip_files:
        files = {f: c for f, c in files.items() if f not in skip_files}
    gate = error_gate if error_gate is not None else noop_gate()
    results: dict[str, dict] = {}
    chunk_index: dict[str, dict[str, list[str]]] = {}
    failed_log = FailedChunkLog()

    def _process_file(filename: str, content: str) -> tuple[str, dict, dict[str, list[str]]]:
        chunks = chunk_file(filename, content)
        target_chunks: set[int] | None = (
            reextract_chunks.get(filename) if reextract_chunks else None
        )
        log.info(
            "  %s — %d chunk(s)%s",
            filename,
            len(chunks),
            f" (re-extracting chunks {sorted(target_chunks)})" if target_chunks else "",
        )

        # Seed from prior data when doing targeted re-extraction.
        prior_file_data = (prior_extractions or {}).get(filename, {})
        prior_file_index = (prior_chunk_index or {}).get(filename, {})
        all_nodes: list[dict] = list(prior_file_data.get("nodes", [])) if target_chunks else []
        all_edges: list[dict] = list(prior_file_data.get("edges", [])) if target_chunks else []
        file_chunk_index: dict[str, list[str]] = dict(prior_file_index) if target_chunks else {}
        stateful = _cfg.PASS2_STATEFUL_CHUNKS

        for i, chunk in enumerate(chunks, 1):
            if target_chunks is not None and i not in target_chunks:
                continue
            log.info("    chunk %d/%d …", i, len(chunks))
            prior = _dedup_within_file(all_nodes) if stateful and all_nodes else None
            chunk_key = f"{filename}::{i}"
            hint_block = _build_schema_hint_block(chunk_key, schema_hints or [])
            extraction = _extract_chunk(
                chunk.text, schema, flat_schema, adapter, i, prior, hint_block or None
            )
            if extraction is None:
                failed_log.record(filename, i, "blank_response")
                continue
            chunk_nodes = extraction.get("nodes", [])
            all_nodes.extend(chunk_nodes)
            all_edges.extend(extraction.get("edges", []))
            file_chunk_index[str(i)] = [_name_slug(n) for n in chunk_nodes]

        all_nodes = _dedup_within_file(all_nodes)
        surviving_ids = {n["id"] for n in all_nodes}
        valid_edges = []
        for e in all_edges:
            if e.get("from") in surviving_ids and e.get("to") in surviving_ids:
                valid_edges.append(e)
            else:
                log.warning(
                    "  %s — dropping edge %s→%s (dangling after dedup)",
                    filename,
                    e.get("from"),
                    e.get("to"),
                )
        all_edges = valid_edges
        log.info("  %s — total: %d node(s), %d edge(s)", filename, len(all_nodes), len(all_edges))
        chunks_in_file = len(chunks)
        return filename, {"nodes": all_nodes, "edges": all_edges}, file_chunk_index, chunks_in_file

    # Pre-count total chunks across all files so ETA is weighted by actual LLM work, not file count.
    file_chunk_counts = {fname: len(chunk_file(fname, content)) for fname, content in files.items()}
    total_chunks = sum(file_chunk_counts.values())
    total_files = len(files)
    done_files = 0
    done_chunks = 0
    pass2_start = time.monotonic()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_process_file, fname, content): fname
            for fname, content in files.items()
        }
        for future in as_completed(futures):
            candidate_fname = futures[future]
            file_chunks = file_chunk_counts[candidate_fname]
            try:
                fname, result, file_idx, file_chunks = future.result()
                results[fname] = result
                chunk_index[fname] = file_idx
                if on_file_done is not None:
                    on_file_done(fname, result, file_idx)
            except Exception as exc:
                gate.record_error(exc)
                log.error("Pass 2 — file %s failed: %s", candidate_fname, exc)

            done_files += 1
            done_chunks += file_chunks
            elapsed = time.monotonic() - pass2_start
            pct = done_chunks / total_chunks * 100 if total_chunks else 0.0
            remaining_secs = (
                (elapsed / done_chunks) * (total_chunks - done_chunks) if done_chunks else 0.0
            )
            eta_h = int(remaining_secs // 3600)
            eta_m = int((remaining_secs % 3600) // 60)
            log.info(
                "Pass 2 progress — %d/%d files, %d/%d chunks (%.1f%%) "
                "— elapsed %s — ETA ~%dh %02dm",
                done_files,
                total_files,
                done_chunks,
                total_chunks,
                pct,
                _fmt_elapsed(elapsed),
                eta_h,
                eta_m,
            )

    failed_entries = failed_log.entries()
    if intermediate_dir is not None:
        (intermediate_dir / "failed_chunks.json").write_text(
            json.dumps(failed_entries, indent=_cfg.JSON_INDENT), encoding="utf-8"
        )

    return results, chunk_index, failed_entries


def run_pass2_batched(
    files: dict[str, str],
    schema: dict,
    flat_schema: dict,
    adapter: LLMAdapter,
    batch_token_target: int,
    per_file: bool = False,
    max_workers: int | None = None,
    schema_hints: list[dict] | None = None,
    on_file_done: Callable[[str, dict, dict], None] | None = None,
    error_gate: ErrorGate | None = None,
    intermediate_dir: pathlib.Path | None = None,
    batch_retry_max: int = 1,
) -> tuple[dict, dict, list[dict], dict]:
    """Chunk-batch variant of run_pass2 — mirrors Pass 1's batching model.

    Chunks from all files are pooled and packed into token-bounded batches; each
    batch is dispatched as a single LLM call via ThreadPoolExecutor. Results are
    merged back into per-file structures compatible with the standard shard format.

    Returns (raw_extractions, chunk_node_index, failed_chunks, batch_map) where
    batch_map is the {batch_name: entry} dict for pass2_batch_map.json.

    When intermediate_dir is provided, writes pass2_progress.json before any LLM
    call and updates it atomically after each batch completes — advisory only,
    never read back by the pipeline.
    """
    if max_workers is None:
        max_workers = _cfg.PASS2_MAX_WORKERS
    gate = error_gate if error_gate is not None else noop_gate()
    failed_log = FailedChunkLog()

    # Chunk all files upfront to build the batch plan.
    all_chunks: list[Chunk] = []
    for fname, content in files.items():
        all_chunks.extend(chunk_file(fname, content))

    batches = build_pass2_batches(all_chunks, batch_token_target, per_file=per_file)
    batch_map = make_batch_map(batches)

    total_batches = len(batches)
    total_files = len(files)
    log.info(
        "Pass 2 batched — %d file(s), %d chunk(s) → %d batch(es)",
        total_files,
        len(all_chunks),
        total_batches,
    )

    # Initialize progress file if intermediate_dir is provided.
    progress_path = intermediate_dir / "pass2_progress.json" if intermediate_dir else None
    if progress_path:
        progress: dict = {
            "total_batches": total_batches,
            "completed": 0,
            "failed": 0,
            "batches": {name: {**entry, "status": "pending"} for name, entry in batch_map.items()},
        }
        progress_path.write_text(json.dumps(progress, indent=2), encoding="utf-8")

    # Accumulated per-file results (keyed by source_file).
    file_nodes: dict[str, list[dict]] = {f: [] for f in files}
    file_edges: dict[str, list[dict]] = {f: [] for f in files}
    # chunk_node_index: {filename: {str(chunk_idx): [stable_id, ...]}}
    chunk_node_index: dict[str, dict[str, list[str]]] = {f: {} for f in files}

    # prior_nodes per file for stateful chunk processing across batches.
    prior_nodes_by_file: dict[str, list[dict]] = {f: [] for f in files}
    stateful = _cfg.PASS2_STATEFUL_CHUNKS

    # Process batches in order so stateful prior_nodes flow correctly when per_file=True.
    # When per_file=False (mixed), prior_nodes are still threaded per source file.
    def _process_batch(batch_idx: int, batch: list[Chunk]) -> tuple[int, dict | None, list[Chunk]]:
        # Collect per-file prior_nodes for files appearing in this batch.
        # For mixed batches we aggregate prior_nodes from all files in the batch.
        batch_files = {c.source_file for c in batch}
        prior: list[dict] | None = None
        if stateful:
            combined: list[dict] = []
            for f in batch_files:
                combined.extend(prior_nodes_by_file.get(f, []))
            prior = _dedup_within_file(combined) if combined else None

        # Build hint block for chunks in this batch.
        hint_lines: list[str] = []
        for chunk in batch:
            chunk_key = f"{chunk.source_file}::{chunk.chunk_index + 1}"
            block = _build_schema_hint_block(chunk_key, schema_hints or [])
            if block:
                hint_lines.append(block)
        hint_block = "\n".join(hint_lines) if hint_lines else None

        token_count = sum(c.token_end - c.token_start for c in batch)
        log.info(
            "  batch %d/%d — %d chunk(s), ~%d tokens",
            batch_idx + 1,
            total_batches,
            len(batch),
            token_count,
        )
        extraction = _extract_batch(
            batch, schema, flat_schema, adapter, batch_idx + 1, prior, hint_block
        )
        if extraction is not None:
            clean = _strip_nulls(extraction)
            log.debug(
                "  batch %d — %d node(s), %d edge(s)",
                batch_idx + 1,
                len(clean["nodes"]),
                len(clean["edges"]),
            )
        return batch_idx, extraction, batch

    def _flush_progress(batch_name: str, extraction: dict | None, error: str | None) -> None:
        """Update the batch entry and atomically overwrite pass2_progress.json."""
        if not progress_path:
            return
        entry = progress["batches"][batch_name]
        if extraction is not None:
            entry["status"] = "done"
            entry["nodes"] = len(extraction.get("nodes") or [])
            entry["edges"] = len(extraction.get("edges") or [])
            progress["completed"] += 1
        else:
            entry["status"] = "failed"
            if error is not None:
                entry["error"] = error
            progress["failed"] += 1
        tmp = progress_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(progress, indent=2), encoding="utf-8")
        tmp.replace(progress_path)

    batch_start = time.monotonic()
    done_batches = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_batch, i, batch): i for i, batch in enumerate(batches)}
        # Sort completed futures by batch index before merging so stateful
        # prior_nodes are updated sequentially.
        completed: list[tuple[int, dict | None, list[Chunk]]] = []
        for future in as_completed(futures):
            batch_idx_from_future = futures[future]
            batch_name = f"batch_{batch_idx_from_future:04d}"
            try:
                result = future.result()
                completed.append(result)
                _flush_progress(batch_name, result[1], None)
            except Exception as exc:
                gate.record_error(exc)
                log.error("Pass 2 batched — batch %d failed: %s", batch_idx_from_future, exc)
                completed.append((batch_idx_from_future, None, batches[batch_idx_from_future]))
                _flush_progress(batch_name, None, str(exc))

            done_batches += 1
            elapsed = time.monotonic() - batch_start
            remaining_secs = (
                (elapsed / done_batches) * (total_batches - done_batches) if done_batches else 0.0
            )
            eta_h = int(remaining_secs // 3600)
            eta_m = int((remaining_secs % 3600) // 60)
            log.info(
                "Pass 2 batched progress — %d/%d batches (%.1f%%) — elapsed %s — ETA ~%dh %02dm",
                done_batches,
                total_batches,
                done_batches / total_batches * 100 if total_batches else 0.0,
                _fmt_elapsed(elapsed),
                eta_h,
                eta_m,
            )

        # Merge results in batch order so stateful prior_nodes are updated sequentially.
        completed.sort(key=lambda t: t[0])

        # In-run retry of failed batches — up to batch_retry_max rounds.
        for retry_round in range(batch_retry_max):
            failed_items = [(bi, b) for bi, ext, b in completed if ext is None]
            if not failed_items:
                break
            log.info(
                "Pass 2 batched — retry round %d/%d: %d failed batch(es): %s",
                retry_round + 1,
                batch_retry_max,
                len(failed_items),
                [bi for bi, _ in failed_items],
            )
            retry_completed: list[tuple[int, dict | None, list[Chunk]]] = []
            with ThreadPoolExecutor(max_workers=max_workers) as retry_executor:
                retry_futures = {
                    retry_executor.submit(_process_batch, bi, b): bi for bi, b in failed_items
                }
                for future in as_completed(retry_futures):
                    bi = retry_futures[future]
                    bname = f"batch_{bi:04d}"
                    try:
                        result = future.result()
                        retry_completed.append(result)
                        _flush_progress(bname, result[1], None)
                        log.info(
                            "Pass 2 batched — retry round %d batch %d succeeded",
                            retry_round + 1,
                            bi,
                        )
                    except Exception as exc:
                        gate.record_error(exc)
                        log.error(
                            "Pass 2 batched — retry round %d batch %d still failed: %s",
                            retry_round + 1,
                            bi,
                            exc,
                        )
                        retry_completed.append((bi, None, batches[bi]))
                        _flush_progress(bname, None, str(exc))

            retry_by_idx = {entry[0]: entry for entry in retry_completed}
            completed = [retry_by_idx.get(orig[0], orig) for orig in completed]
            completed.sort(key=lambda t: t[0])

        for batch_idx, extraction, batch in completed:
            if extraction is None:
                for chunk in batch:
                    failed_log.record(chunk.source_file, chunk.chunk_index + 1, "blank_response")
                continue

            clean = _strip_nulls(extraction)
            batch_nodes = clean["nodes"]
            batch_edges = clean["edges"]

            # Update per-file accumulations and chunk_node_index.
            # All nodes/edges from a mixed batch are attributed to each constituent file.
            # The file_chunk_index records which stable IDs came from which chunk slot.
            for chunk in batch:
                fname = chunk.source_file
                chunk_idx_1based = chunk.chunk_index + 1
                # Attribute all batch nodes to the file they came from.
                # (For mixed batches this is approximate; dedup in assembler handles it.)
                chunk_node_index[fname][str(chunk_idx_1based)] = [
                    _name_slug(n) for n in batch_nodes
                ]

            for fname in {c.source_file for c in batch}:
                file_nodes[fname].extend(batch_nodes)
                file_edges[fname].extend(batch_edges)

                if stateful:
                    prior_nodes_by_file[fname] = _dedup_within_file(file_nodes[fname])

    # Finalize per-file results: dedup nodes and drop dangling edges.
    results: dict[str, dict] = {}
    for fname in files:
        nodes = _dedup_within_file(file_nodes[fname])
        surviving_ids = {n["id"] for n in nodes}
        edges = [
            e
            for e in file_edges[fname]
            if e.get("from") in surviving_ids and e.get("to") in surviving_ids
        ]
        log.info("  %s — total: %d node(s), %d edge(s)", fname, len(nodes), len(edges))
        results[fname] = {"nodes": nodes, "edges": edges}
        if on_file_done is not None:
            on_file_done(fname, results[fname], chunk_node_index[fname])

    failed_entries = failed_log.entries()
    return results, chunk_node_index, failed_entries, batch_map
