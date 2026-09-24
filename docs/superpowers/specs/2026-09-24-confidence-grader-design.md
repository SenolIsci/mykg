# Confidence Grader — Design Spec

Date: 2026-09-24
Status: revised — grader backend + Python SDK details resolved, ready for writing-plans

## Addendum (2026-09-24): grader backend = TypeSafe AI (Jev)

The original spec below assumed a generic chat-completion LLM as the grader,
called through a `TypeSafeAdapter`-style wrapper on `LLMAdapter.complete()`.
Investigation of the actual grader product (https://docs.typesafe.ai)
changes the shape of the implementation; this addendum supersedes the
"Config" and "grader call" mechanics further down, while the pipeline
placement (new `grade_confidence` step, per-chunk granularity, sidecar +
assemble integration, re-entry wiring) is unchanged and still applies.

### What TypeSafe/Jev actually is

TypeSafe AI is **not** a general chat-completion service. Its model, **Jev**
("the first System One model"), is a structured-decision primitive: you call
`client.system_one(state=..., questions={...})` with a `state` blob
(string, object, array, or null — arbitrary JSON is accepted directly, no
manual serialization needed) and a dict of typed questions, each one of:

- **`Choice`** — select from an enumerated `criteria` dict → returns
  `.choice`, `.probabilities`, `.confidence`
- **`Score`** — rate against an ordered `criteria` list of levels → returns
  `.score`, `.legend`, `.probabilities`, `.confidence`
- **`Noul`** — yes/no truthfulness judgment, no criteria required → returns
  `.noul` (a 0–1 probability, this *is* the confidence signal)

All three accept **structured JSON in `instructions`/`criteria`**, not just
plain strings — e.g. a `Choice` criterion can be `{"what": ..., "not_for":
..., "examples": [...]}` instead of a one-line description, and a `Score`
level can be `{"summary": ..., "signals": [...]}`. Every question in one
`questions={...}` dict is evaluated **independently in parallel within a
single API call** — "one question's answer is not hidden context for
another," and the docs' own cookbook pattern for exactly our use case
(the invoice-extraction cascade) is: build one question per extracted
field, all sent in a single call:

```json
{
  "invoice_number_is_correct": {
    "type": "noul",
    "instructions": {
      "field": {
        "name": "invoice_number",
        "type": "string",
        "description": "The identifier printed on the invoice."
      },
      "extracted_value": "4471",
      "question": "Does `extracted_value` match the `field`?"
    }
  }
}
```

`confidence` in TypeSafe's response is a **derived statistic on the shape of
the probability distribution** (concentrated → confident, spread out →
uncertain), not the same thing as the model's own self-assessment — e.g. for
a 3-option `Choice`, `confidence = (3 × top_probability − 1) / 2`. For
`Noul` there is no separate `.confidence` field; the `.noul` value itself
(0–1) is the usable signal, since it's already a probability, not a choice
among options.

### Primitive selection: `Noul`, one per extracted attribute

mykg's per-field confidence question is "is this extracted value correct,"
not a classification among a small enumerated option set — so `Noul` is the
right primitive, not `Choice`/`Score` (those require fixed criteria and are
better suited to routing/severity-tier style judgments, not open-ended value
verification). One `Noul` question per `{entity, attribute, value}` triple
extracted from a chunk, all batched into **one `system_one` call per
chunk** — this both matches the docs' recommended "one question per field,
single call" pattern and preserves the per-chunk call granularity already
chosen in Architecture 1 below (no redesign of chunking/shard/resume needed,
just a different question payload than originally sketched).

Following the invoice cookbook's structured-instructions shape as closely as
mykg's schema allows:

```python
questions[f"{node_id}::{attr_name}"] = Noul(
    instructions={
        "field": {
            "name": attr_name,
            # mykg's schema (D7) stores only attribute *names* — no per-attribute
            # type/description — so "type" and "description" are synthesized
            # (description = attr_name itself) rather than read from schema.json.
            "type": "string",
            "description": attr_name,
        },
        "extracted_value": value,
        "entity_type": node_type,
        "question": "Is `extracted_value` correct for `field`, given the source text in `state`?",
    }
)
```

`state` = the chunk's source text (string) — the evidence Jev judges
`extracted_value` against. One question per attribute across every
node/edge attributed to that chunk (via `chunk_node_index.json`, unchanged
from the original design), all in one `client.system_one(state=chunk_text,
questions={...})` call. Node/edge-level overall confidence (the `__self__`
key from the original design) becomes one additional `Noul` question per
entity: `"Is this {type} entity, as a whole, correctly identified in the
source text?"`.

**Open sizing question for the plan**: a chunk with many entities × many
attributes could produce dozens of `Noul` questions in one call. The docs
state parallel batching has "minimal performance impact" and is markedly
cheaper than serial calls, but neither a hard per-call question-count limit
nor `state` token/size limits were found in the fetched pages — the
implementation plan should either find that limit (SDK docs / rate-limits
page not yet fetched) or impose a conservative `grader.max_questions_per_call`
config cap with automatic splitting across multiple `system_one` calls per
chunk when exceeded, consistent with Invariant 16.

### Adapter shape: new parallel interface, not `LLMAdapter`

Per your decision, this does **not** go through the existing
`LLMAdapter.complete(system, user) -> str` interface — forcing Jev's typed
`system_one(state, questions)` call through a free-text round-trip would
throw away the very things that make it useful (bounded outputs, real
distribution-derived confidence, no JSON-parse brittleness). Instead:

- New module `src/mykg/llm/typesafe_grader.py` with a small, purpose-built
  class, e.g. `TypeSafeGrader`, wrapping `typesafe_sdk.TypeSafeClient` —
  **not** a subclass of `LLMAdapter` and not registered in
  `llm/config.py:load_adapter()`'s provider dispatch.
- Constructed directly by the `grade_confidence` step (or a small
  `build_grader()` factory near it) from the `grader:` config block, reading
  `TYPESAFE_API_KEY` from the environment the same way `openai_adapter.py`
  reads `OPENAI_API_KEY` — sourced via the existing `load_dotenv(".env.mykg")`
  call already in `cli.py`.
- Constructs its own `TypeSafeClient(api_key=..., timeout=grader.timeout,
  retry=RetryPolicy(max_retries=grader.retry_max))` — one instance per
  call site/worker thread (never shared across threads — see the resolved
  thread-safety item above), so `TypeSafeGrader` itself is instantiated
  once per `ThreadPoolExecutor` worker inside `grade_confidence`, not once
  globally.
- One method, shaped after the actual need:
  `grade_chunk(chunk_text: str, entities: list[EntityAttrs]) ->
  dict[str, float]` — internally builds the `Noul` questions dict, calls
  `client.system_one(...)` once (or N times if `max_questions_per_call`
  requires splitting), catches `TypeSafeError` around the call for the
  step's per-chunk graceful-degradation behavior, and returns the flat
  `{f"{id}::{attr}": noul_value}` map the `grade_confidence` step already
  expects to write into `confidence_grades_shards/`.
- `ctx.grader_adapter` (added in the original design below) becomes
  `ctx.grader: TypeSafeGrader | None` instead — same role (None when
  `grader.enabled` is false), different type.
- `typesafe-sdk` (`pip install typesafe-sdk`, Python ≥3.10) is added as an
  **optional** dependency (extras group, e.g. `mykg[grader]`), imported
  lazily inside `grade_confidence`'s step module — mirrors how `mineru`/uv
  venv isolation (D48) keeps a heavy/optional dependency out of mykg's core
  install; TypeSafe's SDK is lighter than MinerU so a venv is unnecessary,
  but it should still not be a hard dependency for users who never enable
  grading.

### Config block, revised

```yaml
profiles:
  openai:
    llm: {...}            # unchanged — the extractor
    grader:
      enabled: false        # opt-in; false ⇒ grade_confidence is a no-op passthrough
      backend: typesafe      # only backend for now; keeps the door open for a future
                              # generic-LLM grader without a breaking config change
      max_questions_per_call: 50   # self-imposed cap (API documents no server-side limit);
                                     # split into multiple system_one calls per chunk above this
      timeout: 600
      retry_max: 2            # passed as a RetryPolicy to system_one — the SDK's own
                               # built-in retry, not a second hand-rolled retry loop
      max_workers: 4         # independent of pass2.max_workers — grader calls run in
                              # their own ThreadPoolExecutor in grade_confidence, one
                              # TypeSafeClient instance constructed per worker thread
                              # (thread-safety of a shared instance is undocumented)
```

No `model:`/`base_url:`/`context_window:` keys — Jev is TypeSafe's one
flagship model, selected implicitly by the SDK/API key, not by a model
string mykg passes. `TYPESAFE_API_KEY` lives in `.env.mykg`, not in YAML
(same secrets-out-of-YAML convention every other provider follows).

### Resolved (previously open items)

Confirmed against the real Python SDK reference pages
(`/sdk/python/api/{exceptions,clients/sync,clients/async,types/questions}.md`,
found via the site's `llms.txt` index rather than guessed paths):

1. **No documented hard limit** on questions-per-`system_one`-call or
   `state` size. `Choice`/`Score`/`Noul` constructors and the `state`
   docs state no numeric caps. `grader.max_questions_per_call` therefore
   stays a **self-imposed, defensive** config cap (Invariant 16 discipline
   — bound cost/blast-radius ourselves rather than discover a server-side
   limit in production) rather than something dictated by the API.
2. **Both a sync and async client exist**: `TypeSafeClient` and
   `AsyncTypeSafeClient` (`from typesafe_sdk import TypeSafeClient,
   AsyncTypeSafeClient`), same constructor shape
   (`api_key`, `model`, `retry: RetryPolicy | None`, `timeout`, `headers`,
   `transport`, `http_client`, `base_url`). **Neither documents
   thread-safety** for concurrent/multi-threaded reuse of one instance.
   Given mykg's uniform `ThreadPoolExecutor` convention (Invariant 12) and
   this documentation gap, `grade_confidence` uses the **sync**
   `TypeSafeClient` (matches every other step's synchronous-adapter-in-a-
   thread-pool pattern — no need to introduce `asyncio` into the
   pipeline for this one step) and constructs **one client instance per
   worker thread** rather than sharing one across threads, sidestepping the
   undocumented thread-safety question entirely.
3. **Exception hierarchy**, all rooted at `TypeSafeError(Exception)`:
   `TypeSafeAPIError` (base for HTTP failures) →
   `TypeSafeBadRequestError` (400), `TypeSafeAuthenticationError` (401),
   `TypeSafePermissionDeniedError` (403), `TypeSafeNotFoundError` (404),
   `TypeSafeUnprocessableEntityError` (422), `TypeSafeRateLimitError` (429),
   `TypeSafeInternalServerError` (5xx); separately,
   `TypeSafeAPIConnectionError(TypeSafeError, ConnectionError)` (no HTTP
   response at all) and `TypeSafeAPITimeoutError(TypeSafeAPIConnectionError,
   TimeoutError)`. `grade_confidence` catches the common base
   `TypeSafeError` for its per-chunk graceful-degradation handling (log +
   leave self-reported confidence in place), the same breadth
   `run_pass2._process_file`'s `except Exception` already uses for pass2
   file failures — no special-casing per exception subtype is needed for
   v1.
4. **`system_one` takes a `retry: RetryPolicy | None` parameter directly**
   — the SDK has its own built-in retry mechanism (mirrors
   `llm_complete_with_retry`'s role for the extractor adapters). The
   implementation plan should pass a `RetryPolicy` here (sized off
   `grader.timeout`/a new `grader.retry_max` knob) rather than hand-rolling
   a second retry loop around `system_one` — `TypeSafeGrader.grade_chunk`
   only needs its own try/except for the *outer* graceful-degradation
   behavior (item 3), not for transient-error retry, which the SDK already
   does internally.

---

## Original spec (pipeline placement — unchanged by the addendum above)

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

**Superseded by the addendum above** — see "Config block, revised" for the
actual shape (`backend: typesafe`, no `model`/`base_url`/`context_window`
keys, `TYPESAFE_API_KEY` via `.env.mykg`). Kept here only for the
surrounding structural point that still holds: the block is a sibling of
`llm:` inside every profile, in both `mykg_config.yaml` and
`src/mykg/data/mykg_config.yaml` (Invariant 17), defaulting to
`enabled: false` everywhere so grading is fully opt-in and the pipeline's
existing self-reported-confidence behavior is unchanged unless a user turns
it on. `ctx` gains `grader: TypeSafeGrader | None = None` (not
`grader_adapter`, not built via `load_adapter` — see addendum's "Adapter
shape" section), populated in `cli.py` alongside the existing
`adapter = load_adapter(...)` call, `None` when `grader.enabled` is false.

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

**When `grader.enabled` is false** (or `ctx.grader is None`):
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
5. One `TypeSafeGrader.grade_chunk(chunk_text, entities)` call per chunk
   (see addendum's "Primitive selection" section) — internally one
   `client.system_one(state=chunk_text, questions={...})` call (or several,
   if `grader.max_questions_per_call` requires splitting a dense chunk),
   with one `Noul` question per `{entity_id, attribute}` pair plus one
   `Noul` question per entity for its own overall confidence.
6. The call returns a flat map:
   `{stable_id: {attr_name: confidence_float, "__self__": confidence_float}}`
   — `__self__` is the entity's own overall confidence (node or edge level,
   from its dedicated `Noul` question), keeping node/edge- and
   attribute-level scores in one response format. `confidence_float` here is
   each question's `.noul` value directly (already a 0–1 probability, no
   further derivation needed).
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

**Failure handling per chunk**: a chunk's grader call fails (connection
error, auth error, rate limit — see addendum item 3 on confirming the
Python SDK's exception classes) or times out → log a warning, that chunk's
entities simply get no entry in the grades map (no
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
