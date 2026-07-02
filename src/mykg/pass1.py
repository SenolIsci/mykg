from __future__ import annotations

import json
import random as _random
from concurrent.futures import ThreadPoolExecutor, as_completed

from mykg import config as _cfg
from mykg.chunker import Chunk
from mykg.llm.adapter import LLMAdapter
from mykg.llm.error_gate import ErrorGate, noop_gate
from mykg.llm.retry import llm_complete_with_retry
from mykg.logging import get
from mykg.prompts import load_prompt

log = get("mykg.pass1")

PASS1_SYSTEM_PROMPT = load_prompt("pass1/system")

_BATCHES_RNG = _random.Random(0)


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


def run_pass1(
    chunks: list[Chunk],
    adapter: LLMAdapter,
    locked_schema_block: str,
    error_gate: ErrorGate | None = None,
) -> list[dict]:
    batches = _build_batches(chunks)
    cap = _cfg.PASS1_MAX_SCHEMA_PROPOSALS
    if cap != -1 and len(batches) > cap:
        original_count = len(batches)
        batches = _BATCHES_RNG.sample(batches, cap)
        log.warning(
            "Pass 1 — %d batches sampled down to %d (pass1.max_schema_proposals)",
            original_count,
            cap,
        )

    system = PASS1_SYSTEM_PROMPT
    if locked_schema_block:
        system = system + "\n\n" + locked_schema_block

    def _process_batch(idx: int, batch: list[Chunk]) -> tuple[int, dict | None]:
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
                log.warning("  batch %d — JSON parse error on retry: %s; skipping", idx, exc2)
                return (idx, None)
        if "concepts" not in proposal or "properties" not in proposal:
            log.warning("  batch %d — response missing 'concepts'/'properties', skipping", idx)
            return (idx, None)
        if not isinstance(proposal["concepts"], list) or not isinstance(
            proposal["properties"], list
        ):
            log.warning("  batch %d — 'concepts'/'properties' must be lists, skipping", idx)
            return (idx, None)
        log.debug(
            "  batch %d — %d concept(s), %d property(ies)",
            idx,
            len(proposal["concepts"]),
            len(proposal["properties"]),
        )
        return (idx, proposal)

    gate = error_gate if error_gate is not None else noop_gate()
    log.info(
        "Pass 1 — %d batch(es) to process (max_workers=%d)", len(batches), _cfg.PASS1_MAX_WORKERS
    )
    results: dict[int, dict | None] = {}
    with ThreadPoolExecutor(max_workers=_cfg.PASS1_MAX_WORKERS) as executor:
        futures = [executor.submit(_process_batch, i, batch) for i, batch in enumerate(batches, 1)]
        for future in as_completed(futures):
            try:
                idx, proposal = future.result()
                results[idx] = proposal
            except Exception as exc:
                gate.record_error(exc)
                log.warning("Pass 1 — batch failed: %s", exc)
                # batch skipped; no entry added to results

    proposals = [results[i] for i in sorted(results) if results[i] is not None]
    return proposals
