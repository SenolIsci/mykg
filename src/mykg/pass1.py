from __future__ import annotations

import json
import random as _random
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mykg import config as _cfg
from mykg.chunker import Chunk
from mykg.llm.adapter import LLMAdapter
from mykg.llm.error_gate import ErrorGate, noop_gate
from mykg.llm.retry import llm_complete_with_retry
from mykg.logging import get
from mykg.prompts import load_prompt

log = get("mykg.pass1")

PASS1_SYSTEM_PROMPT = load_prompt("pass1/system")


def _build_batches(chunks: list[Chunk]) -> list[list[Chunk]]:
    if _cfg.PASS1_PER_FILE_BATCHING:
        # Option B mode: one batch per source file — never mix chunks across files.
        # Chunks from the same file may still span multiple batches if the file is
        # large, but file boundaries are always respected as hard split points.
        batches: list[list[Chunk]] = []
        current: list[Chunk] = []
        current_tokens = 0
        current_file: str | None = None
        for chunk in chunks:
            size = chunk.token_end - chunk.token_start
            file_changed = current_file is not None and chunk.source_file != current_file
            token_overflow = current and current_tokens + size > _cfg.PASS1_BATCH_TOKEN_TARGET
            if file_changed or token_overflow:
                batches.append(current)
                current = []
                current_tokens = 0
            current.append(chunk)
            current_tokens += size
            current_file = chunk.source_file
        if current:
            batches.append(current)
        return batches

    batches = []
    current = []
    current_tokens = 0
    for chunk in chunks:
        size = chunk.token_end - chunk.token_start
        if current and current_tokens + size > _cfg.PASS1_BATCH_TOKEN_TARGET:
            batches.append(current)
            current = []
            current_tokens = 0
        current.append(chunk)
        current_tokens += size
    if current:
        batches.append(current)
    return batches


def _write_batch_selection(
    batches: list[list[Chunk]],
    total_batches: int,
    seed: int,
    intermediate_dir: Path,
) -> None:
    """Write intermediate/pass1_batch_selection.json — an audit record of
    exactly which chunks fed which batch index, written unconditionally
    (even when no sampling occurred) before any LLM call is made.
    """
    entries = []
    for i, batch in enumerate(batches, 1):
        entries.append(
            {
                "index": i,
                "chunk_count": len(batch),
                "source_files": sorted({c.source_file for c in batch}),
                "total_tokens": sum(c.token_end - c.token_start for c in batch),
            }
        )
    selection = {
        "seed": seed,
        "total_batches": total_batches,
        "sampled_batch_count": len(batches),
        "selected_batch_indices": list(range(1, len(batches) + 1)),
        "batches": entries,
    }
    path = intermediate_dir / "pass1_batch_selection.json"
    path.write_text(json.dumps(selection, indent=_cfg.JSON_INDENT), encoding="utf-8")


def _batches_match_selection(
    batches: list[list[Chunk]], selection: dict
) -> bool:
    """True if the freshly-built `batches` have the same composition
    (chunk_count + source_files per index) as a previously-written
    pass1_batch_selection.json — i.e. this is genuinely a resume of the same
    logical run, not a second, unrelated run_pass1() call over different
    chunks that happens to share an intermediate_dir (e.g.
    --append-with-grow-schema's second, locked Pass 1 call over only the
    changed files). Shards are only safe to reuse when this holds; otherwise
    stale proposals from a prior, different chunk set would be silently
    substituted for the current run's real result.
    """
    prev_batches = selection.get("batches", [])
    if len(prev_batches) != len(batches):
        return False
    for i, batch in enumerate(batches, 1):
        prev = next((b for b in prev_batches if b.get("index") == i), None)
        if prev is None:
            return False
        if prev.get("chunk_count") != len(batch):
            return False
        if prev.get("source_files") != sorted({c.source_file for c in batch}):
            return False
    return True


def _load_existing_batch_proposals(
    batches: list[list[Chunk]], intermediate_dir: Path
) -> dict[int, dict | None]:
    """Load already-persisted pass1_batch_proposals/<index>.json shards, but
    only when the current batch composition matches the prior
    pass1_batch_selection.json exactly (see _batches_match_selection) — i.e.
    this is a real resume of the same run, not a different run_pass1() call
    that happens to reuse the same intermediate_dir.

    Returns {batch_index: proposal | None} — None for a shard whose status is
    "failed" (recorded so the caller can distinguish "already tried and
    failed" from "never attempted"), keyed same as run_pass1's own results.
    """
    existing: dict[int, dict | None] = {}
    selection_path = intermediate_dir / "pass1_batch_selection.json"
    if not selection_path.exists():
        return existing
    try:
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return existing
    if not _batches_match_selection(batches, selection):
        return existing

    shard_dir = intermediate_dir / "pass1_batch_proposals"
    if not shard_dir.exists():
        return existing
    for shard_file in shard_dir.glob("*.json"):
        try:
            entry = json.loads(shard_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        idx = entry.get("batch_index")
        if idx is None:
            continue
        existing[idx] = entry.get("proposal") if entry.get("status") == "ok" else None
    return existing


def run_pass1(
    chunks: list[Chunk],
    adapter: LLMAdapter,
    locked_schema_block: str,
    error_gate: ErrorGate | None = None,
    intermediate_dir: Path | None = None,
    on_batch_done: Callable[[int, dict | None, str | None], None] | None = None,
) -> list[dict]:
    """Run Pass 1 schema-induction batches.

    intermediate_dir: when provided, persists pass1_batch_selection.json
        before dispatch and skips re-dispatching any batch whose
        pass1_batch_proposals/<index>.json shard already exists AND whose
        batch composition (chunk_count + source_files) matches the prior
        selection exactly (a genuine resume of the same run, not a different
        run_pass1() call over different chunks reusing the same directory).
    on_batch_done(index, proposal, error): called once per batch as its
        result becomes final — proposal is the parsed dict on success, None
        on failure (error holds a message in that case). Callers use this to
        persist per-batch shards incrementally (see step_pass1.py).
    """
    batches = _build_batches(chunks)
    total_batches = len(batches)
    cap = _cfg.PASS1_MAX_SCHEMA_PROPOSALS
    seed = _cfg.PASS1_RANDOM_SEED
    if cap != -1 and len(batches) > cap:
        original_count = len(batches)
        # Fresh, call-scoped RNG — a module-level shared instance would
        # advance its internal state across repeated calls in the same
        # process (e.g. --append-with-grow-schema invokes Pass 1 twice),
        # silently producing a different sample the second time despite the
        # same seed. A fresh instance per call is reproducible regardless of
        # how many times run_pass1() has already been called.
        rng = _random.Random(seed)
        batches = rng.sample(batches, cap)
        log.warning(
            "Pass 1 — %d batches sampled down to %d (pass1.max_schema_proposals)",
            original_count,
            cap,
        )

    # Read any existing proposals against the *prior* selection.json before
    # overwriting it below — this is what lets us distinguish "resuming the
    # same run" (batches match the prior selection exactly) from "a different
    # run_pass1() call that happens to share this intermediate_dir" (e.g.
    # --append-with-grow-schema's second, locked call over different chunks).
    existing_proposals = (
        _load_existing_batch_proposals(batches, intermediate_dir)
        if intermediate_dir is not None
        else {}
    )

    if intermediate_dir is not None:
        _write_batch_selection(batches, total_batches, seed, intermediate_dir)

    system = PASS1_SYSTEM_PROMPT
    if locked_schema_block:
        system = system + "\n\n" + locked_schema_block

    def _process_batch(idx: int, batch: list[Chunk]) -> tuple[int, dict | None, str | None]:
        token_count = sum(c.token_end - c.token_start for c in batch)
        log.info(
            "  batch %d/%d — %d chunk(s), ~%d tokens", idx, len(batches), len(batch), token_count
        )
        user_text = "\n\n".join(c.text for c in batch)
        raw = llm_complete_with_retry(
            adapter,
            system,
            user_text,
            context_label=f"pass1 batch {idx}/{len(batches)}",
        )
        try:
            proposal = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            log.warning("  batch %d — JSON parse error: %s; retrying", idx, exc)
            snippet = (
                raw[max(0, exc.pos - 100) : exc.pos + 50]
                if isinstance(exc, json.JSONDecodeError)
                else raw[:200]
            )
            log.debug("  batch %d — raw response around error: %s", idx, snippet)
            retry_user_text = (
                "Your previous response was not valid JSON. "
                "Return only a JSON object with 'concepts' and 'properties' keys.\n\n" + user_text
            )
            retry_raw = llm_complete_with_retry(
                adapter,
                system,
                retry_user_text,
                context_label=f"pass1 batch {idx}/{len(batches)} json-retry",
            )
            try:
                proposal = json.loads(retry_raw)
            except (json.JSONDecodeError, ValueError) as exc2:
                msg = f"JSON parse error on retry: {exc2}"
                log.warning("  batch %d — %s; skipping", idx, msg)
                return (idx, None, msg)
        if "concepts" not in proposal or "properties" not in proposal:
            msg = "response missing 'concepts'/'properties'"
            log.warning("  batch %d — %s, skipping", idx, msg)
            return (idx, None, msg)
        if not isinstance(proposal["concepts"], list) or not isinstance(
            proposal["properties"], list
        ):
            msg = "'concepts'/'properties' must be lists"
            log.warning("  batch %d — %s, skipping", idx, msg)
            return (idx, None, msg)
        log.debug(
            "  batch %d — %d concept(s), %d property(ies)",
            idx,
            len(proposal["concepts"]),
            len(proposal["properties"]),
        )
        return (idx, proposal, None)

    gate = error_gate if error_gate is not None else noop_gate()
    to_dispatch = [
        (i, batch) for i, batch in enumerate(batches, 1) if i not in existing_proposals
    ]
    if existing_proposals:
        log.info(
            "Pass 1 — %d batch(es) already done, %d remaining",
            len(existing_proposals),
            len(to_dispatch),
        )
    log.info(
        "Pass 1 — %d batch(es) to process (max_workers=%d)",
        len(to_dispatch),
        _cfg.PASS1_MAX_WORKERS,
    )
    results: dict[int, dict | None] = dict(existing_proposals)
    with ThreadPoolExecutor(max_workers=_cfg.PASS1_MAX_WORKERS) as executor:
        futures = [executor.submit(_process_batch, i, batch) for i, batch in to_dispatch]
        for future in as_completed(futures):
            try:
                idx, proposal, error = future.result()
                results[idx] = proposal
                if on_batch_done is not None:
                    on_batch_done(idx, proposal, error)
            except Exception as exc:
                gate.record_error(exc)
                log.warning("Pass 1 — batch failed: %s", exc)
                # batch skipped; no entry added to results.
                # Note: the batch index isn't available here (future.result()
                # raised before returning it), so on_batch_done cannot be
                # called with a specific index for this path — matches the
                # existing behavior where such a batch was already silently
                # dropped from `results` prior to this change.

    proposals = [results[i] for i in sorted(results) if results[i] is not None]
    return proposals
