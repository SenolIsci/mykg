# Confidence Grader — Design Spec

Date: 2026-09-24
Status: approved for planning

## Problem

Every attribute value, node, and edge in the graph carries a confidence score
(D9), but today that score is entirely **self-reported by the Pass 2
extraction LLM in the same call that produces the value** — there is no
independent check. `_normalize_scalars` coerces bare scalars to a fallback
confidence when the LLM omits the wrapper, and `_backfill_extraction` fills
genuinely missing attributes with `{value: null, confidence: 0.0}`, but
neither of these is a *measurement* — they're defaults for absent data. A
value the extractor hallucinated gets whatever confidence the extractor
felt like reporting for it, with nothing downstream to catch the mismatch.

## Goal

Introduce an independent **grader** — a second LLM, separately configured,
that re-scores confidence for each extracted node/edge attribute against the
source text it was extracted from. The grader's context window is 32K
tokens. Its score replaces the extractor's self-reported confidence before
the graph is assembled.

## Current state (as found)

- **Pass 2** (`src/mykg/pass2.py`) chunks each file (`chunker.chunk_file`,
  default ~6,400 tokens/chunk, well under 32K) and makes one LLM call per
  chunk (`_extract_chunk`) via the single adapter at `ctx.adapter`. The
  extractor is asked to emit `{value, confidence}` per attribute in the same
  response that produces the value.
- **`chunk_node_index.json`** already records, per file and per chunk index,
  the stable IDs of every node extracted from that chunk — this is the exact
  join key needed to re-associate a value with its source chunk after the
  fact.
- **`raw_extractions.json`** (assembled from `raw_extractions_shards/`) holds
  the per-file `{nodes, edges}` with their attribute values and self-reported
  confidence.
- **`step_assemble.run_assemble`** loads `raw_extractions.json`, assigns
  stable IDs, then calls `assembler.deduplicate_nodes` /
  `deduplicate_edges`, which aggregate confidence across duplicate
  occurrences (mean/max, D10/D19) purely by reading whatever `confidence`
  value already sits on each attribute dict. Assembler logic has **no
  awareness of how confidence was produced** — it just trusts the field.
- **One LLM adapter for the whole pipeline.** `load_adapter()`
  (`src/mykg/llm/config.py`) builds a single `LLMAdapter` from the active
  profile's flat `llm:` block; `cli.py` constructs it once and threads it
  through `PipelineContext.adapter`, used by pass1, pass2, normalize, orphan,
  and feedback alike. There is no existing precedent for a second,
  independently-configured model in the pipeline — but `load_adapter`
  already accepts an override dict (`_raw` param), so pointing it at a
  different config section requires no adapter-layer changes.
- **Re-entry / resumability machinery** that any new LLM step must plug
  into: per-file shard directories flushed incrementally inside the
  `ThreadPoolExecutor` `as_completed` loop (D57 pattern); `_is_done` step
  skipping; `_SCHEMA_RESTART_INVALIDATE` / `_APPEND_INVALIDATE` sets in
  `orchestrator.py` that list which steps' outputs get deleted on a
  schema-gap restart or `--append`; and the shard-clearing block in
  `cli.py:_delete_from_step` that clears pass2's shard dirs whenever
  `--from-step` targets pass2 or an earlier step.

## Chosen architecture: per-chunk re-grading

Considered against two axes — what evidence the grader sees (source chunk
text vs. structured JSON only vs. full file) and call granularity (per
chunk, per node/edge, per file) — three real architectures emerged:

1. **Per-chunk, chunk text + values (chosen).** Mirrors Pass 2's own unit of
   work exactly. Chunks are already sized (~6,400 tokens) to comfortably fit
   inside a 32K grader window alongside a compact value listing. Call count
   is the same order of magnitude as Pass 2 itself.
2. **Per-node/edge, chunk text + single entity's values.** Finest-grained
   (no dilution across sibling entities in one call) but scales LLM call
   count with extracted-entity count rather than chunk count — typically
   3–10x more calls than (1) on a dense corpus. Would need an explicit
   Invariant-16-style cost cap to justify.
3. **Structure-only, batched per file, no source text.** Cheapest by far,
   but the grader can only judge internal plausibility/consistency, not
   whether a value is actually supported by the source — the one thing an
   independent grader most needs to catch. Rejected as a weak fit for the
   stated goal.

(1) is selected: it re-uses the exact chunk/shard/resume machinery pass2
already has, keeps grader prompts well within the 32K budget, and directly
tests groundedness against source text.

## Design

### Config — new `grader:` block per profile

Added as a sibling of the existing `llm:` block inside every profile in both
`mykg_config.yaml` and `src/mykg/data/mykg_config.yaml` (Invariant 17):

```yaml
profiles:
  openai:
    llm: {...}            # unchanged — the extractor
    grader:
      enabled: false        # opt-in; false ⇒ grade_confidence is a no-op passthrough
      provider: openai
      model: gpt-4o-mini
      context_window: 32000
      max_output_tokens: 4096
      base_url: https://api.openai.com/v1
      timeout: 600
      max_workers: 4         # independent of pass2.max_workers
      temperature: 0.0        # same D3 reproducibility rationale as the extractor
```

Built via the existing `load_adapter(_raw={"provider": ..., "llm":
grader_section})` — `llm/config.py` requires no changes; it already accepts
an override dict and reads `provider`/`llm` from whatever is passed. `ctx`
gains a second field, `grader_adapter: Any = None`, populated in `cli.py`
alongside the existing `adapter = load_adapter(...)` call, `None` when
`grader.enabled` is false or the section is absent.

`enabled: false` is the shipped default in every profile — grading is fully
opt-in; the pipeline's existing self-reported-confidence behavior is
unchanged unless a user turns it on.

### New pipeline step: `grade_confidence`

Registered in `STEPS` (`src/mykg/pipeline.py`) immediately after `pass2` and
before `normalize_names`:

```python
Step(
    name="grade_confidence",
    fn=run_grade_confidence,
    outputs=["confidence_grades.json", "confidence_grades.done"],
    is_llm_step=True,
)
```

`is_llm_step=True` so it participates in the existing Tier-1 per-step retry
and feedback-loop machinery (D31) like pass1/pass2/normalize/orphan_connect.

**When `grader.enabled` is false** (or `ctx.grader_adapter is None`):
`run_grade_confidence` writes `confidence_grades.json` as `{}` plus the
`.done` sentinel and returns immediately. This keeps `_is_done` semantics
uniform (the step always produces its declared outputs) with no
special-casing in the orchestrator or in `step_assemble`.

**When enabled**, the step mirrors `run_pass2`'s structure:

1. Load `raw_extractions.json` (or its shards, matching whichever
   `raw_extractions_shards/` are present, same as `step_pass2._run` does).
2. Load `chunk_node_index.json` — `{filename: {chunk_idx: [stable_ids]}}`.
3. For each file, re-derive its chunks via `chunk_file` (identical call
   pass2 made, so chunk text is reproduced exactly — chunk boundaries are
   deterministic given the same content and `pipeline.chunking` config).
4. For each chunk, resolve its stable IDs → pull each node's/edge's current
   `type` + `attributes` (value only, not confidence) from that file's raw
   extraction.
5. One grader call per chunk: system prompt explains the grading task
   (score how well-supported each value is by the given text, 0.0–1.0);
   user prompt = chunk text + a compact `{id, type, attribute: value}`
   listing for every node/edge attributed to that chunk.
6. Grader returns a flat map:
   `{stable_id: {attr_name: confidence_float, "__self__": confidence_float}}`
   — `__self__` is the entity's own overall confidence (node or edge level),
   keeping node/edge- and attribute-level scores in one response format.
7. Files with zero chunks needing grading (e.g. produced zero nodes) are
   skipped without a call.

**Shard format** — `intermediate/confidence_grades_shards/<slug>.json`, one
per file, same shape as pass2's `{"_fname": fname, "data": {...grades...}}`,
flushed via an `on_file_done`-style callback inside the per-file
`ThreadPoolExecutor(max_workers=grader.max_workers)` loop — same
incremental-flush pattern as D57, so a crash mid-run only loses files still
in flight. On resume, a shard is reused as-is (grading is pure re-scoring
of already-extracted values; no composition-fingerprint check is needed
the way pass1/pass2 batches need one, since chunk content for a given
filename+chunk_idx is deterministic and unaffected by dispatch order).
Final merge writes `intermediate/confidence_grades.json`.

**Failure handling per chunk**: a chunk's grader call fails, times out, or
returns unparseable JSON after `llm_complete_with_retry`'s one retry → log a
warning, that chunk's entities simply get no entry in the grades map (no
cascading retry logic beyond what `llm_complete_with_retry` already
provides). Downstream, an entity absent from the grades map keeps its
self-reported confidence (see below) — grading degrades gracefully to
today's behavior per-entity, never blocks the pipeline.

### Consumption at assemble time

In `step_assemble.run_assemble`, immediately after loading
`raw_extractions.json` and before `assign_stable_ids`:

```python
grades_path = ctx.intermediate_dir / "confidence_grades.json"
if grades_path.exists():
    grades = json.loads(grades_path.read_text(encoding="utf-8"))
    _apply_grades(raw, grades)
```

`_apply_grades` (new helper in `step_assemble.py`): for every node/edge
whose stable ID appears in `grades`, overwrite `attr["confidence"]` with the
graded value for each attribute present in the grade entry, and overwrite
the entity's own top-level `confidence` from `__self__` when present. The
prior self-reported value is preserved as `attr["self_reported_confidence"]`
(a new, additive field — never dropped, per the spirit of D9's "never
silently drop" pattern) so both signals stay auditable. An entity/attribute
with no grade entry is left untouched — self-reported confidence is the
value that flows onward for it, exactly as today.

`assembler.py`'s dedup/aggregation logic (`deduplicate_nodes`,
`deduplicate_edges`) is **unchanged** — it only ever reads whatever sits in
`attr["confidence"]` / `node["confidence"]`, which is now the graded value
where available. No changes to confidence aggregation, merge-log, or export
logic anywhere downstream of assemble.

### Re-entry / invalidation wiring

- `orchestrator.py`: add `"grade_confidence"` to both
  `_SCHEMA_RESTART_INVALIDATE` and `_APPEND_INVALIDATE` — a schema-gap
  restart or `--append` run that re-extracts chunks must also re-grade
  them, or stale/missing grades would silently fall back to self-reported
  confidence for re-extracted entities.
- `cli.py:_delete_from_step`: extend the existing pass2-shard-clearing block
  (currently keyed off `pass2_idx`) to also clear
  `confidence_grades_shards/` and `confidence_grades.json` whenever
  `--from-step` targets `grade_confidence`, `pass2`, or any earlier step —
  otherwise a re-run would silently keep stale grades for chunks that get
  re-extracted with different content.
- D16 intermediate-files table gains two rows:
  `intermediate/confidence_grades.json` (after `grade_confidence`) and
  `intermediate/confidence_grades_shards/` (during the step, per-file).
- No change needed to `--pass2-kg-extraction-only` /
  `--pass1-schema-induction-only` (D56) skip sets — `grade_confidence`
  naturally runs as part of the normal post-`pass2` sequence in both cases
  since it isn't in `PASS2_ONLY_SKIP_STEPS`/`APPEND_SKIP_STEPS`.

### Cost shape

One grader call per chunk pass2 already made — same order of magnitude in
call count as pass2 itself when enabled (opt-in, default off). Grader
prompts are materially smaller than pass2's (no schema block, no
prior-nodes block — just chunk text + a compact value listing), so token
cost per call is lower even though call count roughly doubles. This is a
fixed 1:1 relationship with an already-linear pass (no multiplicative
blow-up with corpus size or restart count), satisfying Invariant 16 by
construction.

## Out of scope (this spec)

- Fusing grader + self-reported scores (e.g. min/weighted-mean) — rejected
  in favor of straight replacement per the design discussion; can be
  revisited later as a `grader.fusion_strategy` config knob without
  changing the architecture above.
- Per-node/edge (finer-grained) or per-file (coarser) grading granularity —
  documented above as considered alternatives, not built.
- A `grading_quality` marker mirroring D33's `blank_response`/
  `blank_recovered` pattern for ungraded entities — worth adding later but
  not required for the core feature to work correctly.
- Surfacing grader rationale/explanation text — output contract is a bare
  float per attribute, not `{confidence, rationale}`, to keep grader output
  tokens minimal.
