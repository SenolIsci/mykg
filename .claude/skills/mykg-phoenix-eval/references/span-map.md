# mykg OTel span map

Every span mykg's tracing emits, verified against the current source
(`src/mykg/tracing.py`, `orchestrator.py`, `pass1.py`, `pass2.py`,
`orphan_connector.py`, `llm/retry.py`) — not guessed. If the pipeline code
changes, re-grep for `start_as_current_span`/`add_event`/`set_attribute`
rather than trusting this file blindly; it was accurate as of the tracing
implementation added in this project's OTel work.

## Step names come straight from the extraction guide's pipeline table

`mykg.step.<name>` is generic — `orchestrator.py` wraps *every* `Step` in
`pipeline.py`'s `STEPS` list the same way, so the set of step-span names you
can actually query is exactly the 12-row STEPS table in this project's own
`CLAUDE.md` (D39, "Extract pipeline steps"), not a hand-picked subset. Don't
assume a step is untraced just because it isn't called out below — every one
of these 12 gets `mykg.step.<name>`; the tree further down only additionally
documents which steps grow *children* (batch/file/LLM spans), because that's
the part that varies. `mykg merge-graphs` has its own analogous 12-step
`MERGE_STEPS` table in the same CLAUDE.md section — same `mykg.step.<name>`
wrapping, different step names (`merge_setup`, `merge_schema`,
`merge_reextract`, `merge_raw`, `merge_manifest` in place of `pass1`/`pass2`).

| # | `mykg.step.<name>` | Children under this step span? |
|---|---|---|
| 1 | `preprocess` | no — leaf. MinerU/markdownify run without their own span; a failed per-file conversion is non-blocking (D39) and doesn't reach the span at all unless it fails the whole step |
| 2 | `ingest` | no — leaf |
| 3 | `pass1` | **yes** — `mykg.pass1.batch` (per batch) + `mykg.schema_harmonize` + `mykg.schema_quality_review` (see tree below) |
| 4 | `schema_validate` | no — leaf |
| 5 | `human_review` | no — leaf (a wait-state gate, not an LLM call) |
| 6 | `schema_flatten` | no — leaf |
| 7 | `pass2` | **yes** — `mykg.pass2.file` (per_file/concat) or `mykg.pass2.batch` (batch_chunks, shipped default) |
| 8 | `normalize_names` | **yes** — a direct `mykg.llm.call` child, no per-batch span layer (one call is small enough not to need one) |
| 9 | `assemble` | no — leaf |
| 10 | `orphan_score` | no — leaf (Stage 1 co-occurrence heuristic, no LLM call — see D30) |
| 11 | `orphan_connect` | **yes** — `mykg.orphan.confirm` / `mykg.orphan.group` (Stage 2, only if `orphan_pass.enabled`) |
| 12 | `validate_graph` | no — leaf |

A "leaf" step still gets its own `mykg.step.<name>` span with the
attributes/status/events documented below — "no children" just means don't
go looking for a nested batch/file/LLM span under it. If you're evaluating a
leaf step (e.g. checking `preprocess` or `assemble` didn't silently no-op),
the step span's own status, attributes, and (per the new log-bridge section
below) any `log`/`exception` events it picked up are the entire signal —
there's nothing nested to drill into.

## Levels (parent → child)

```
mykg.extract_graph.run                       (cli.py — one per `mykg extract-graph` invocation)
└── mykg.step.<step_name>                    (orchestrator.py — one per pipeline step; all 12 STEPS table rows above, always)
    ├── attempt-1                            (orchestrator.py — first _try_run call; LLM steps only — see below)
    ├── attempt-2                            (bare retry, only if attempt-1 failed; LLM steps only)
    ├── attempt-3-with-feedback              (LLM feedback-correction retry, only for is_llm_step steps)
    ├── mykg.pass1.batch                     (pass1.py — one per Pass 1 batch; only under mykg.step.pass1)
    │   └── mykg.llm.call                    (llm/retry.py — one per llm_complete_with_retry call)
    │       └── ChatCompletion               (OpenInference auto-instrumentation, openai adapter only)
    ├── mykg.schema_harmonize                (schema_merge.py — Pass 1 Stage 3; only under mykg.step.pass1)
    │   └── mykg.llm.call → ChatCompletion   (same nesting as above)
    ├── mykg.schema_quality_review           (schema_merge.py — Pass 1 Stage 4; only under mykg.step.pass1)
    │   └── mykg.llm.call → ChatCompletion   (same nesting as above)
    ├── mykg.pass2.file                      (pass2.py — one per file, per_file/concat prep modes; only under mykg.step.pass2)
    ├── mykg.pass2.batch                     (pass2.py — one per batch, batch_chunks prep mode — the shipped default; only under mykg.step.pass2)
    │   └── mykg.llm.call → ChatCompletion   (same nesting as above)
    ├── mykg.llm.call → ChatCompletion       (normalize_names — direct child, no batch layer; only under mykg.step.normalize_names)
    ├── mykg.orphan.confirm                  (orphan_connector.py — Stage 2 per-candidate; only under mykg.step.orphan_connect, only if orphan_pass.enabled)
    └── mykg.orphan.group                    (orphan_connector.py — Stage 2 per-chunk-group; only under mykg.step.orphan_connect, only if orphan_pass.enabled)
```

`mykg.schema_harmonize`/`mykg.schema_quality_review` sit as direct children of
`mykg.step.pass1`'s `attempt-1` (siblings of `mykg.pass1.batch`, not nested
under it) — they run once each, after all Pass 1 batches have merged, not
per-batch. The `merge-graphs` command's analogous stages
(`harmonize_schema_for_merge`/`review_schema_quality_for_merge`) emit
`mykg.merge_schema_harmonize`/`mykg.merge_schema_quality_review` instead,
nested under `mykg.step.merge_schema` — same shape, different pipeline.

Context propagation across all `ThreadPoolExecutor` sites is handled by
`mykg.tracing.submit_with_context` — batch/file spans correctly nest under
their step span even though they run in worker threads.

## Log events — every WARNING+/exception on the span that was active

Every `mykg.step.<name>` span, and every descendant span active when the log
line fired, can carry `log` events (from ordinary `logger.warning()`/
`.error()`/`.critical()` calls) and `exception` events (from
`logger.exception(...)`, or any log call with `exc_info` set), via
`tracing.OtelSpanLogHandler` — attached to the root logger in
`setup_tracing()`, gated by `otel.log_to_span_events` (default `true`).

**This is a different mechanism from `LoggingInstrumentor`**, which
`setup_tracing()` also wires (`set_logging_format=False,
inject_trace_context=True`). `LoggingInstrumentor` only stamps
`otelTraceID`/`otelSpanID`/`otelServiceName`/`otelTraceSampled` text onto
each `LogRecord`, for correlating a log line with a trace in an *external*
log store — it never touches the span itself, and its `log_hook` extension
point only fires once a full OTel **Logs** SDK pipeline (a separate
`LoggerProvider`) is configured, which mykg deliberately does not set up.
That matters because **Phoenix has no native OTel-logs ingestion at all**
(confirmed via Arize-ai/phoenix#10624, "OTEL Logging Instrumentation
support", still open) — it ingests traces (OTLP) only. So `OtelSpanLogHandler`
is the only path that gets a log line to show up next to the span that
produced it: it calls `span.add_event("log", ...)` / `span.record_exception(...)`
directly, and span events *are* part of the trace signal Phoenix already
renders.

| Event name | Attributes | Fires from |
|---|---|---|
| `log` | `log.level`, `log.logger`, `log.message` | any `logger.warning()`/`.error()`/`.critical()` call made while a span is active |
| `exception` | `exception.type`, `exception.message`, `exception.stacktrace` (OTel's own exception semantic-convention keys, set by `Span.record_exception`) | `logger.exception(...)` or any log call with `exc_info` set, while a span is active |

Filtered to `WARNING`+ only — every step already logs `INFO`-level progress
lines (`RUN pass2`, `SKIP ingest — ...`), and mirroring those onto spans
would bury the actually-interesting signal (retries, validation errors,
schema-gap restarts) under routine noise. **This is additive, not a
replacement** for the structured events `pass2.py` already emits by hand
(`pass2.chunk.json_parse_error` etc., documented under `mykg.pass2.batch`
below) — those remain the higher-signal, purpose-built events for Pass 2
specifically; `log`/`exception` events catch everything else that goes
through `logging.warning`/`.error` anywhere in the pipeline that nobody
wrote a dedicated event for (adapter retries, orphan-connector fallback
branches, a future step that logs a warning nobody thought to trace). When
querying spans for an eval, `[e for e in span.events if e.name in ("log",
"exception")]` is a cheap first-pass signal for "did anything go wrong
during this span," worth checking before reading `status_code` — a step can
log several recoverable warnings and still finish with `status_code == OK`.

If no span is active when a WARNING+ log fires (rare — every `Step` wraps
its own `mykg.step.<name>` span, so this only happens for a log line truly
outside the pipeline, e.g. CLI argument parsing before `extract_graph.run`
opens), `OtelSpanLogHandler` is a silent no-op: nothing to attach to, no
exception raised, and the log line still reaches stdout/`run.log` normally
through the handlers `logging.setup()` already installed — this handler is
additive, never a replacement sink.

**Verification status — unit-tested, not yet observed on a real `log`/
`exception` event from a live run.** A clean end-to-end run against a
well-formed corpus (confirmed: `_test_files/` — `team.pdf`, `projects.xlsx`,
`technologies.md`, 3 files, 36 spans, 25 nodes/23 edges) produces **zero**
`log`/`exception` span events, because nothing in the main process logged a
WARNING+ on an active span that run — the only two WARNINGs it did produce
came from MinerU's own logger inside the separate `mykg parse-docs`
subprocess (rejecting `.xlsx` — "No valid PDF or image files to process"),
which has no active span from the main process's tracer to attach to, so
correctly produced no event. That's expected behavior, not a failure — but
it means a clean run is not a live positive-path check for this mechanism.
`tests/test_tracing.py` unit-tests `OtelSpanLogHandler` directly (attaching
it to a throwaway logger under a real span, asserting the event lands), so
the mechanism itself is proven — what hasn't been separately confirmed is
seeing it fire mid-pipeline, end-to-end, with a real Phoenix instance on
the receiving end. To get a genuine positive-path check, run against a
corpus likely to trigger a real `pass2.chunk.validation_errors`/similar
WARNING (an oddly-formatted or very dense source file tends to trip Pass 2
retries), or temporarily lower `pass2.max_workers`/retry limits to make a
transient failure more likely, then query for
`[e for e in span.events if e.name in ("log", "exception")]` across the
run's spans the way "Reading spans back" (SKILL.md) describes.

## Streaming — what actually appears live in Phoenix, and what can't

`otel.sync_export: false` (default) uses an async `BatchSpanProcessor`,
tuned via `otel.schedule_delay_millis` (default `1000` vs. OTel's own
`5000` default) and `otel.max_export_batch_size` (default `64` vs. OTel's
own `512`) so a finished span reaches Phoenix within roughly a second of
closing rather than up to five. `otel.sync_export: true` swaps in a
blocking `SimpleSpanProcessor` instead — every span exports synchronously
the instant it closes, at the cost of adding real network latency to every
traced call (Phoenix's own docs recommend this for local debugging only,
never for a run whose wall-clock time you care about).

**Neither setting changes *when* a span closes, and Phoenix cannot show a
span before it closes** — a span is a single record covering
`[start_time, end_time]`; nothing is sent to any exporter until the
`with tracer.start_as_current_span(...):` block that owns it exits. This
matters concretely for mykg's own tree: `mykg.extract_graph.run` and
`mykg.step.pass1`/`mykg.step.pass2` wrap the *entire* run or step, so they
will only ever appear in Phoenix once the whole run or the whole step
finishes — no processor tuning changes that, because it isn't an
export-scheduling question, it's what a span fundamentally is. What tuning
*does* buy you is everything below that layer: `mykg.pass1.batch`,
`mykg.pass2.batch`, `mykg.pass2.file`, `mykg.llm.call`, and their
`ChatCompletion` children each close as soon as their one unit of work (one
batch, one file, one LLM call) finishes — so on a long Pass 2 run, each
batch's result genuinely does land in the Phoenix UI within about a second
of that batch completing, well before the overall `mykg.step.pass2` span
closes. **If you want visibility into something still running, watch the
leaf-level batch/file/LLM spans in Phoenix's live trace view, not the step
or run span** — that's where "as it happens" actually applies. Tell the
user this distinction explicitly if they ask why the run-level span "isn't
showing up yet" while a run is in progress — it's expected, not a bug.

## Attributes by span

### `mykg.extract_graph.run`
Root span, one per CLI invocation. Source: `cli.py:1174-1179`.
| Attribute | Type | Notes |
|---|---|---|
| `mykg.session` | str | Session directory name, e.g. `2026-09-20T14-14-48`. **Use this to find the trace_id for a given session.** |
| `mykg.profile` | str | Active LLM profile name, or `"default"` if not resolvable |
| `llm.provider` | str | `adapter.endpoint_label()` — e.g. `"openai / gpt-5.4-mini-2026-03-17 @ https://api.openai.com"` |
| `mykg.append` | bool | |
| `mykg.sync` | bool | |
| `mykg.grow_schema` | bool | |
| `mykg.pass2_only` | bool | |

### `mykg.step.<name>`
One per `Step` execution — see the STEPS table above for the full set of 12
names this actually takes. Source: `orchestrator.py:449-452, 585`.
| Attribute | Type | Notes |
|---|---|---|
| `mykg.step.name` | str | matches `<name>` in the span name, e.g. `pass1`, `pass2`, `assemble`, `ingest`, `validate_graph` |
| `mykg.step.is_llm_step` | bool | |
| `mykg.step.blocking` | bool | |
| `mykg.step.error` | str | only present if the step failed |

Span **events**:
- `schema.updated_restart` (`orchestrator.py:465`) fires when
  `SchemaUpdatedError` triggers an automated Re-entry A restart — a
  control-flow signal, not a failure (the step span's status stays OK, not
  ERROR, when this fires). Attribute: `mykg.restart_count`.
- `log` / `exception` (`tracing.py:OtelSpanLogHandler`, gated by
  `otel.log_to_span_events`) — see "Log events" above. Fires on any
  WARNING+ standard-logging call made while this step span is the active
  span (i.e. any `log.warning(...)`/`log.error(...)` in the step's own
  `run_*` function that isn't itself nested under a more specific child
  span like `mykg.pass2.batch`).

Span **status**: `ERROR` (via `mark_span_error`) when the step ultimately
failed after all retries/feedback.

**`attempt-N` child spans are skipped for non-LLM steps** (`_attempt_span()`,
`orchestrator.py`) — a step with `is_llm_step=False` (`preprocess`, `ingest`,
`schema_validate`, `human_review`, `schema_flatten`, `assemble`,
`orphan_score`, `validate_graph` — cross-reference the STEPS table above,
"Children?" column `no`) makes no LLM call, so its attempt would carry no
attributes and no content-bearing children (`mykg.pass1.batch` /
`mykg.pass2.batch` / `ChatCompletion` only ever appear under LLM steps).
`_try_run` is called directly for those steps instead of inside a span. The
retry control flow itself is unchanged — a non-LLM step still gets a bare
`attempt-2` retry on failure (just without its own span), and
`attempt-3-with-feedback` was already LLM-step-only before this change.

### `mykg.pass1.batch`
Source: `pass1.py:221-223`.
| Attribute | Type |
|---|---|
| `mykg.batch.index` | int |
| `mykg.batch.chunk_count` | int |

Status `ERROR` (with `mykg.error` message) on JSON parse failure or a
missing `concepts`/`properties` key in the LLM response.

### `mykg.pass2.file`
`per_file`/`concat` prep modes. Source: `pass2.py:494-495`.
| Attribute | Type |
|---|---|
| `mykg.file.name` | str |

### `mykg.pass2.batch`
`batch_chunks` prep mode (**the shipped default** —
`pipeline.pass2.prep_mode: batch_chunks` in `mykg_config.yaml`). Source:
`pass2.py:800-805`.
| Attribute | Type |
|---|---|
| `mykg.batch.index` | int |
| `mykg.batch.chunk_count` | int |
| `mykg.batch.source_files` | list[str] |

Status `ERROR` when `_extract_batch` returns `None`.

Span **events** (`pass2.py:316-395`) — these are the highest-signal thing to
read before proposing evaluators, since they're a direct record of where
extraction already struggled within this run:
| Event name | Attributes | Meaning |
|---|---|---|
| `pass2.chunk.json_parse_error` | `mykg.chunk_index`, `mykg.error` | first-attempt response wasn't valid JSON |
| `pass2.chunk.skipped` | `mykg.chunk_index`, `mykg.reason`, `mykg.error` | retry also failed to parse — chunk dropped entirely |
| `pass2.chunk.validation_errors` | `mykg.chunk_index`, `mykg.errors` (list[str]) | schema validation failed, retrying with error context |
| `pass2.chunk.retry_json_parse_error` | `mykg.chunk_index`, `mykg.error`, `mykg.action` | validation-retry response wasn't valid JSON — invalid edges dropped |
| `pass2.chunk.validation_errors_persist` | `mykg.chunk_index`, `mykg.errors` | validation retry still had errors — invalid edges dropped, nodes kept |

Also carries `log`/`exception` events per the "Log events" section above,
for any WARNING+ logging call made anywhere inside batch processing that
isn't already one of the purpose-built `pass2.chunk.*` events.

### `mykg.orphan.confirm` / `mykg.orphan.group`
Only present when `orphan_pass.enabled: true` (default `false` in this
project's config). Source: `orphan_connector.py:583-585, 844-846`.
| Span | Attributes |
|---|---|
| `mykg.orphan.confirm` | `mykg.orphan.orphan_id`, `mykg.orphan.candidate_id` |
| `mykg.orphan.group` | `mykg.orphan.chunk_key`, `mykg.orphan.count` |

### `mykg.llm.call`
One per `llm_complete_with_retry` call (covers Pass 1, Pass 2, orphan,
feedback, normalize_names — every LLM call in the pipeline goes through this
one choke point). Source: `llm/retry.py:107-110`.
| Attribute | Type |
|---|---|
| `mykg.llm.context_label` | str, e.g. `"pass2 chunk 1"`, `"pass1 batch 1/1"` |
| `gen_ai.system` | str, provider label from `adapter.endpoint_label()` |

Status `ERROR` when all empty-response retries are exhausted. **No
prompt/completion content lives on this span** — that's only on the child
`ChatCompletion` span (OpenAI adapter only, via
`openinference-instrumentation-openai`).

### `ChatCompletion` (OpenInference, child of `mykg.llm.call`)
Only present for the `openai` provider profile (auto-instrumented — see
`OpenAIInstrumentor` in `tracing.py`). This is where the actual prompt and
response text live — **use this span, not `mykg.llm.call`, for any
groundedness/hallucination-style evaluator that needs to read what the LLM
actually saw and said.**
| Attribute | Type | Notes |
|---|---|---|
| `attributes.llm.input_messages` | list[dict] | each item is `{"message.role": ..., "message.content": ...}` — **flat dotted keys inside the dict, not a nested `{"message": {"role": ...}}` shape** (confirmed by direct introspection — a plausible-looking nested-access attempt raises `KeyError: 'message'`). Index 0 is system, index 1 is user (contains the source chunk text for Pass 2 calls). |
| `attributes.llm.output_messages` | list[dict] | same flat-key shape as input_messages |
| `attributes.llm.model_name` | str | e.g. `gpt-5.4-mini-2026-03-17` |
| `attributes.llm.token_count.prompt` / `.completion` / `.total` | int | |
| `attributes.input.value` | str | JSON-serialized full request |
| `attributes.output.value` | str | JSON-serialized full response, including `choices[0].message.content` |
| `attributes.openinference.span.kind` | str | `"LLM"` |

**Column-flattening behavior (confirmed by direct introspection, not
docs):** `client.spans.get_spans_dataframe(...)` flattens OpenInference's
*known* namespaces (`llm.*`, `input.*`, `output.*`, `gen_ai.*`) into
individual dotted columns (`attributes.llm.token_count.prompt`, etc.), but
**mykg's own custom `mykg.*` namespace does NOT get the same treatment** —
it stays as a single dict-valued column `attributes.mykg`, whose keys mirror
the dotted attribute name as nested dict levels
(`mykg.llm.context_label` → `row["attributes.mykg"]["llm"]["context_label"]`,
`mykg.session` → `row["attributes.mykg"]["session"]`). There is no
`attributes.mykg.session` column — looking for one returns `KeyError`/an
empty match. Always unpack `attributes.mykg` as a dict, never assume it
flattens the same way as the OpenInference namespaces.
