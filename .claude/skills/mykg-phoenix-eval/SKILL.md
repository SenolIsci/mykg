---
name: mykg-phoenix-eval
description: Evaluate mykg extract-graph pipeline runs using Arize Phoenix — and, if the target project has no OpenTelemetry tracing yet (or only partial/broken instrumentation), first plans and proposes the spans needed to make evaluation possible at all, before grading anything. Grades individual pipeline steps (schema induction, extraction, name normalization, ingestion) and the end-to-end assembled graph by querying spans captured via OTel tracing and writing scores back as Phoenix span annotations. Use this whenever the user wants to evaluate, grade, benchmark, or check the quality of a mykg extraction run (or any Python pipeline they want graded with Phoenix), wants to know "is this extraction any good", asks about hallucinated nodes/edges, wants an LLM-as-judge check on schema or extraction quality, wants to set up regression testing / a golden dataset, or wants to add tracing/spans so a pipeline CAN be evaluated. Trigger even if they just say "eval the pipeline," "check the last run," or "we need tracing so we can grade this" without naming Phoenix or OpenTelemetry explicitly.
---

# Pipeline Evaluation with Phoenix (mykg + general Python pipelines)

## What this is for

Evaluating a pipeline with Phoenix requires spans to already exist — you
can't grade what was never captured. This skill covers **both halves**:

- **Phase A — Instrument (only when needed).** If the target project has no
  OTel tracing, or has some but not enough to evaluate what the user cares
  about, plan the missing spans and propose them for approval before writing
  any code. See "Phase A: Detecting and Planning Instrumentation" below.
- **Phase B — Evaluate.** Once spans exist (in this project, already true —
  see `references/span-map.md`), read them back out of Phoenix and grade
  them, so you get an actual quality signal per pipeline step and for the
  whole output, instead of only a trace waterfall.

This project (mykg) already has Phase A done — `src/mykg/tracing.py`,
`orchestrator.py`, `pass1.py`, `pass2.py`, `orphan_connector.py`,
`llm/retry.py` all emit real spans (`references/span-map.md` documents every
one, verified against source, including a table cross-referencing every
step span name against the 12-step pipeline table in this project's own
CLAUDE.md — see "Step names come straight from the extraction guide's
pipeline table" in that file). **Always check first** (see Phase A's
detection step) rather than assuming — a project can regress (someone
deletes `tracing.py`), or the user might invoke this skill in a *different*
Python project that has nothing yet. Don't skip straight to Phase B just
because it worked last time.

mykg's tracing also covers two things easy to assume are automatic and
aren't, both documented in `references/span-map.md`:
- **Standard-logging WARNING+/exceptions land on spans as events**, via
  `tracing.OtelSpanLogHandler` — see "Log events" in `span-map.md` for why
  this needs a purpose-built handler rather than OTel's own
  `LoggingInstrumentor` (Phoenix has no native OTel-logs ingestion at all).
- **Batch/file/LLM-call spans stream to Phoenix within ~1s of finishing**,
  tuned via `otel.schedule_delay_millis`/`otel.max_export_batch_size`
  (`otel.sync_export: true` for a blocking, immediate-per-span debug mode).
  But the top-level run/step spans (`mykg.extract_graph.run`,
  `mykg.step.pass1`, ...) only ever appear once they close — see
  "Streaming" in `span-map.md` for why that's inherent to what a span is,
  not a processor setting, and which spans to actually watch live instead.

This is genuinely two to three different pipelines glued together:

- **The target pipeline** — mykg's own extraction pipeline, or whatever
  other Python pipeline the user wants evaluated. Phase A instruments it (if
  needed); Phase B never modifies it.
- **The eval pipeline** — a *separate* piece of code (`eval.py`, built
  per-invocation of this skill, not a fixed script this skill ships) that
  queries Phoenix for a completed run's spans, runs evaluators over them,
  and writes the scores back as Phoenix span annotations.

Running the eval pipeline never re-runs the target pipeline. It reads
what's already in Phoenix (`http://localhost:6006`, OTLP receiver on
`localhost:4317`), grades it, and writes annotations back.

## Prerequisites

1. **Spans exist for what the user wants graded** — see Phase A if not.
2. **Phoenix running.** `curl -s -o /dev/null -w '%{http_code}' http://localhost:6006`
   should return `200`. If not, tell the user to run `uvx arize-phoenix serve`
   in a separate terminal (this project's README documents this under
   "Tracing (OpenTelemetry)") — don't try to start it yourself in the
   background unless asked, since it's meant to be a long-running process the
   user watches.
3. **`arize-phoenix-client` + `arize-phoenix-evals` installed.** These are
   *not* part of mykg's own `[otel]` extra (that extra is for *producing*
   traces; this skill is for *consuming* them). Check with
   `uv run python -c "import phoenix.client, phoenix.evals"` and if missing,
   run `uv pip install arize-phoenix-client arize-phoenix-evals` — small,
   fast install, no server component.

## Phase A: Detecting and Planning Instrumentation

Skip this phase entirely once you've confirmed real spans already exist for
what the user wants graded (Step 1 below returns "instrumented"). Never
write instrumentation code as a reflex — only when detection shows it's
actually missing or actually insufficient for the eval the user is asking
for.

### Step 1: Detect what's already there — don't assume, check

A project can have full tracing, none, or something partial (e.g. it traces
HTTP calls generically but never wraps the pipeline's own logical steps, so
you can see *that* an LLM was called but not *which stage* of the pipeline
called it — exactly the gap that makes step-level grading impossible even
though *some* spans exist). Detect this with a project-agnostic search
before concluding anything:

```bash
# Any OTel usage at all?
grep -rl "opentelemetry" --include="*.py" . 
# Manual span creation (the thing that actually produces gradable structure)?
grep -rn "start_as_current_span\|start_span" --include="*.py" .
# A tracer being fetched anywhere?
grep -rn "get_tracer\b" --include="*.py" .
```
Then read what you find. "Some `opentelemetry` import exists" is not the
same as "there's a span per pipeline stage" — an auto-instrumentation-only
setup (just `HTTPXClientInstrumentor` or similar, no manual
`start_as_current_span` calls) gives you HTTP-call spans but nothing that
maps to the pipeline's own logical steps, which is usually what "evaluate
step X" actually needs. Classify what you found as one of:
- **Not instrumented** — no OTel at all. Full Phase A needed.
- **Partially instrumented** — some spans exist (e.g. HTTP auto-instrumentation,
  or spans for some stages but not others) but not enough to grade what the
  user is asking about. Only the missing piece needs planning — read what
  exists first and match its conventions rather than redesigning the whole
  thing.
- **Fully instrumented** — spans already cover what's being asked. Skip to
  Phase B (Prerequisites/verified API surface below).

### Step 2: Understand the pipeline's own shape before proposing spans

Span boundaries should mirror the pipeline's real structure, not be
sprinkled arbitrarily. Read the entry point and follow the call chain far
enough to answer: what are the logical stages (the things a user would
naturally call "step 1, step 2, ..." when describing this pipeline out
loud)? Where does parallelism happen (thread pools, async gather, subprocess
fan-out)? Where do the expensive/uncertain calls happen (LLM calls, external
API calls, anything with retries)? These three questions map directly onto
the span-level structure that worked for mykg (see
`references/span-map.md` for the concrete, already-built example) and
generalize to most pipelines:

1. **A run-level span** — one per invocation of the whole pipeline, wrapping
   the top-level entry point. Carries whatever identifying metadata
   distinguishes one run from another (a session/job/request ID, key
   config flags) as attributes.
2. **A step-level span per logical stage** — one per stage in the pipeline's
   own vocabulary (not "line 47 to line 92" — the *name* the pipeline's own
   code or docs already use for that stage). This is what makes
   "evaluate step X" answerable at all.
3. **A unit-of-work span inside any parallelized/looped stage** — one per
   item processed (per file, per batch, per record) so failures/successes
   are attributable to a specific unit, not just "the step as a whole
   partially failed."
4. **A call-level span around the actual expensive/judged operation** — LLM
   calls above all, since that's almost always what an eval needs to grade
   (prompt in, response out). If the pipeline already funnels every such
   call through one function (mykg's `llm_complete_with_retry` is the model
   case — one wrap point covers every call site), wrap that single choke
   point rather than every call site individually.

**The propagation trap — check for this explicitly, it's easy to miss and
silently breaks grading later.** If step 3 involves a thread pool
(`ThreadPoolExecutor`, `multiprocessing`, or similar) or an async
`gather`/`create_task`, a span started inside a worker will NOT
automatically nest under the span active on the submitting thread —
OpenTelemetry's context is `contextvars`-based, and `ThreadPoolExecutor
.submit()` does not snapshot/restore context for you the way
`asyncio.create_task` does. mykg hit this directly and fixed it with one
shared helper (`submit_with_context` in `tracing.py`) used at every
`.submit()` call site instead of duplicating `contextvars.copy_context()`
by hand each time — propose the same shape (one helper, swapped in
everywhere `ThreadPoolExecutor.submit` appears) rather than a per-call-site
fix, since a fix that only covers one thread pool and misses another
produces spans that silently have the wrong parent with no error to catch it.

### Step 3: Propose the plan, then STOP — do not write code yet

Write out, in the chat (not as a file yet): the exact list of spans you'd
add (name, parent, level, attributes), which existing files each would go
in, and — if step 3 above applies — where the propagation fix is needed.
Reference concrete file:line locations you actually read, not guessed ones.
Then **wait for the user to approve before touching any file.** This is a
deliberate choice for this skill: tracing code, once wired through a whole
pipeline's call sites, is the kind of change worth a specific look before
it happens, even though the underlying pattern (span levels,
`contextvars` propagation) is well-established — a specific pipeline's
existing conventions (naming, where a module-level tracer lives, how errors
already get logged) still deserve a human's eyes before you touch them.

### Step 4: Write it, following the pipeline's own conventions, once approved

Once the plan is approved, read `references/instrumentation-guide.md` for
the actual module template, the two real bug classes to watch for
(`opentelemetry-api` needing to be a core dependency, not optional; the
thread-pool context-propagation trap from Step 2), and how to test what you
built with an in-memory span exporter. Both bug classes were caught the
hard way while building mykg's own tracing — they don't announce themselves
with an exception, they just silently produce broken or missing spans, so
the guide's verification steps aren't optional polish.

## Phase B: The verified API surface (read this before writing any eval code)

Phoenix's own docs (`arize.com/docs/phoenix`) currently mix examples from
**Arize AX** (the commercial SaaS product, package `arize`) into pages that
look like they're describing OSS Phoenix (package `phoenix`). They are
different SDKs. **Never import from `arize.experiments`, `ArizeClient`, or
call `.experiments.run(...)`** (that's AX's method name) — for OSS Phoenix
the function is `run_experiment`, from `phoenix.client.experiments`.

Every signature below was directly introspected against the installed
version in this project (`arize-phoenix-client==3.5.0`,
`arize-phoenix-evals==3.8.0`) — not copied from docs. The readthedocs client
API reference (https://arize-phoenix.readthedocs.io/projects/client/) is a
better starting point than arize.com/docs/phoenix for finding *which*
method/class exists (it's a real API map: `Client` and its
`spans`/`datasets`/`experiments`/`prompts`/`projects`/`sessions` resources,
plus `phoenix.client.types.spans.SpanQuery` and the
`phoenix.client.helpers.spans` module) — but still re-verify the exact
signature by introspection before using it, same as everything else in this
file; it's a lead, not ground truth, for the same reasons given below. If a
newer version is installed when you read this, re-verify with
`python -c "import inspect; from phoenix.X import Y; print(inspect.signature(Y))"`
rather than trusting this table blindly; Phoenix ships new releases every
1–3 days and has already renamed things once (the old `SpanEvaluations`/
`log_evaluations` API from Phoenix 0.x/4.x is gone — don't use it, don't
suggest it, use `add_span_annotation`/`log_span_annotations_dataframe`
instead, confirmed present in the current client). Also gone with that
same older major: the top-level `import phoenix as px; px.Client()` form
and `phoenix.evals.llm_classify`/`OpenAIModel` — confirmed absent from
`phoenix.evals` here (`dir(phoenix.evals)` has no `llm_classify` at all).
If you see any of these four names in a tutorial or a pasted example
(course notebooks in particular tend to run an older, fuller `arize-phoenix`
install than the `arize-phoenix-client`/`arize-phoenix-evals` pair this
skill installs), translate rather than copy: `px.Client()` →
`phoenix.client.Client()`, `llm_classify(...)` → `ClassificationEvaluator`
(Phase B's "Writing evaluators" below), `SpanEvaluations`/`log_evaluations`
→ `add_span_annotation`/`log_span_annotations_dataframe`.

**`suppress_tracing()` — real, confirmed present** (from
`openinference.instrumentation`, pulled in transitively by
`openinference-instrumentation-openai`, which is already installed if
mykg's `[otel]` extra is). A context manager that pauses OTel
instrumentation for its block:
```python
from openinference.instrumentation import suppress_tracing

with suppress_tracing():
    # any LLM call here produces no spans, even if something in this
    # process IS instrumented
    ...
```
Use this as defense-in-depth around every judge LLM call your eval script
makes — not because it's usually load-bearing (an eval script that never
imports/calls whatever triggers instrumentation in the target pipeline
produces no spans anyway, since instrumentation only patches SDK classes
when explicitly told to), but because "this script happens to never trigger
instrumentation" is a structural argument that can silently stop being true
if the script's imports change later, while `suppress_tracing()` makes the
guarantee explicit at the call site regardless of what else is true about
the process. This is also the same pattern Phoenix's own tutorials use
around `llm_classify()` calls, for the same reason.

### Reading spans back and writing annotations — read `references/phoenix-api-surface.md` before writing eval.py

That file has the confirmed signatures and worked examples for:
- `Client(base_url=..., api_key=..., ...)` and `get_spans_dataframe(...)` —
  including the `PHOENIX_ENDPOINT`/`PHOENIX_API_KEY` env-var fallbacks and
  why they're distinct from `PHOENIX_COLLECTOR_ENDPOINT` (that one's the
  OTel exporter target, not the client's REST target).
- **`SpanQuery().where(condition)`** for server-side filtering instead of
  pulling everything and filtering in pandas — field names (`name`,
  `context.trace_id`, `status_code`, ...) confirmed valid against a live
  Phoenix instance.
- Which columns actually exist on mykg's structural spans vs. the
  OpenInference `ChatCompletion` spans, and the `attributes.mykg` dict-column
  gotcha (there is no `attributes.mykg.session` column — it's nested).
  **Also check `events` on every row** — `log`/`exception` events (from the
  standard-logging bridge) and pass2's own `pass2.chunk.*` events are a
  direct record of where the run struggled, independent of `status_code`.
- **`add_span_annotation`/`log_span_annotations_dataframe`** for writing
  scores back — including the ⚠️ **annotation upsert collision**: writing a
  second annotation with the same `annotation_name` to a span that already
  has one silently overwrites it unless you pass a distinct `identifier`.
  This matters a lot for mykg specifically, since one `ChatCompletion` span
  commonly backs many extracted nodes/edges — always ask "can more than one
  thing I'm grading map to the same span_id?" before skipping `identifier`.

### Writing evaluators

Three shapes, all from `phoenix.evals`, confirmed working end-to-end. Full
code patterns for each are in `references/writing-evaluators.md` — read it
before writing any evaluator. The decision rule for which shape to reach
for:

1. **Code-based** — the check is a real assertion (does this ID exist, is
   this in range), not a judgment call. Cheap, exact, deterministic, no LLM
   call. Try this first for anything that qualifies.
2. **LLM-as-judge, binary or simple multi-class** (`plausible`/
   `implausible`, or a 3-way `fully_grounded`/`partially_grounded`/
   `hallucinated`) — the default once a check needs judgment rather than
   assertion. Cheaper to write and run, and easier to read in aggregate
   (a pass rate) than a rubric for the same question — most per-item checks
   genuinely are one question and should stay this simple.
3. **Rubric (multiple dimensions, each with its own `ClassificationEvaluator`
   and written criteria)** — the fallback, reached for only when you can
   name more than one axis the same input could independently succeed or
   fail on (e.g. schema *completeness* vs. schema *precision* — a schema can
   score high on one while scoring low on the other, and collapsing both
   into one plausible/implausible judgment throws away exactly the
   information that makes the eval actionable). Don't reach for a rubric as
   a default upgrade over binary judging — only when binary would genuinely
   hide a real distinction.

## How to propose evaluators for a component (do this explicitly, don't skip it)

When asked to evaluate a step, **don't reach for a fixed checklist** — reason
about what could actually go wrong at that step, the way a careful reviewer
of the pipeline's own output would, then decide per check whether it's a
**code assertion** or an **LLM judgment call**. The rule of thumb: if you
could write the check as a Python `==`/`in`/regex without needing to
understand meaning, it's code — cheaper, exact, deterministic, run it first.
If deciding requires reading text and judging plausibility, correctness, or
groundedness, it's an LLM judge — and needs `explanation=True` so a failure
is debuggable, not just a number.

This mirrors what evaluation platforms like LangSmith and Phoenix itself
call "hallucination", "correctness", "relevance" evaluators — those are
built for RAG/chat-agent pipelines (context → question → answer), which
mykg's shape doesn't match (source chunk → extracted graph elements against
a schema). Don't import Phoenix's generic `phoenix.evals.metrics` classes
(`HallucinationEvaluator`, `CorrectnessEvaluator`, `FaithfulnessEvaluator`,
etc.) as-is — they expect an `input`/`context`/`output` RAG shape. Instead
**borrow the underlying concept and re-target it at mykg's actual data**:

| RAG concept | What it's really checking | mykg's equivalent question |
|---|---|---|
| Faithfulness / Hallucination | Is the answer grounded in the given context, or invented? | Is this extracted node/edge actually supported by its source chunk text, or did the LLM invent an entity/relationship not present in it? |
| Correctness (vs. reference) | Does the answer match a known-correct answer? | Does this extraction match a golden-dataset expected node/edge (once one exists — see below)? |
| Relevance | Is the retrieved context relevant to the question? | Is this induced schema concept/property actually relevant to what's in the corpus, or is it over-general/off-topic? |
| Conciseness / Toxicity / PII | Safety/quality guardrails on generated prose | Low relevance for a structured extractor — skip unless the user specifically wants a safety net |

Below is a *starting point*, not a fixed list — read the actual span/output
data for the run being evaluated first, notice what's actually failing or
suspicious in it, and propose checks for that, same as you would when
reviewing someone's PR by reading the diff rather than running a linter.

### Ingestion (`mykg.step.ingest`, no LLM call — code only)
No LLM call happens here, so there's nothing for an LLM judge to grade —
grade the mechanics instead:
- **code**: step span has `status_code == "OK"` (no exception)
- **code**: chunk count is > 0 and reasonable relative to corpus size (catches
  silent all-file-skipped bugs)
- **code**: every input file that exists on disk appears in at least one
  chunk's `source_file` (catches a file being silently dropped)

### Pass 1 — schema induction (`mykg.step.pass1`, `mykg.pass1.batch`)
- **code**: `schema.json` has ≥1 concept, ≥1 property, every property's
  `domain`/`range` refers to a declared concept (this is literally what
  mykg's own `schema_validate` step already checks — reuse the idea, not the
  step, since you're grading independently of the pipeline's own gate)
- **LLM judge**: given the corpus text and the induced concept list, is each
  concept type meaningfully distinct and not an overly-narrow named-entity
  masquerading as a type (mykg's own Pass 1 quality-review stage tries to
  catch this — an independent judge is a second opinion, not a duplicate of
  the same LLM call)
- **LLM judge**: is the property list reasonably complete for the kinds of
  relationships visible in the source text, or does it look thin/generic?

### Pass 2 — extraction (`mykg.pass2.batch` / `mykg.pass2.file`, child `ChatCompletion` spans)
This is the highest-value component to grade — it's the step with retries
already being traced (`pass2.chunk.validation_errors` events — read those
first, they're a free signal of where extraction already struggled).
- **code**: every edge's `from`/`to` resolves to a node ID that exists in the
  same extraction (mykg's assembler already drops dangling edges — grading
  this independently tells you how *often* that happens, which the assembler
  itself doesn't surface as a metric)
- **code**: every node's declared `type` is one of `schema.json`'s concepts
- **LLM judge**: given the chunk's source text (`attributes.llm.input_messages`
  on the `ChatCompletion` span) and one extracted node/edge, is it actually
  grounded in that text, or does it look invented? This is the mykg-native
  version of a hallucination check.
- **LLM judge**: for edges specifically — given the edge type's schema
  definition and the two endpoint node names/types, is this relationship
  type plausible (not just "does it exist" but "does it make sense")?

### Name normalization (`mykg.step.normalize_names`)
- **code**: no alias maps to itself (`name_normalization.json` entries where
  key == value — mykg's own code shouldn't produce these, but worth checking)
- **LLM judge**: for each alias→canonical mapping, are these genuinely the
  same real-world entity (catches over-merging — e.g. two different people
  named "Alice" incorrectly collapsed), or genuinely different surface forms
  of one entity (catches under-merging — obvious duplicates left unmerged)

### Final assembled graph (end-to-end, `nodes.jsonl`/`edges.jsonl` from the session's `output/`)
Read these directly from the session's `output_dir`, not from spans — the
assembled graph is a pipeline *output artifact*, not something with its own
span. Cross-reference against the `mykg.extract_graph.run` root span's
`mykg.session` attribute to find the right session directory.
- **code**: every node referenced by an edge exists in `nodes.jsonl`
  (the D14/D25 validation the pipeline already runs — an independent check
  here is a regression guard, not redundant, since it catches a bug in the
  pipeline's *own* validator, not just in extraction)
- **code**: confidence scores are all in `[0.0, 1.0]`
- **LLM judge**: read a sample of nodes/edges and the original source
  document(s) together — does the assembled graph capture the salient
  entities/relationships a careful human reader would extract, or does it
  miss/misrepresent something significant? This is the only check that
  looks at *completeness* rather than *correctness of what's there* — code
  and per-extraction judges can't catch "the graph is technically all
  correct but missed something obvious."

## Building `eval.py`

There's no fixed template to copy verbatim — build it per invocation, shaped
around what the user actually wants evaluated this time (one component? the
whole pipeline? one session or comparing two?). But the skeleton is always
the same three phases:

1. **Load** — resolve the session (ask which one, or default to
   `ls -td mykg_sessions/*/ | head -1` per this project's own CLAUDE.md
   convention), find its `trace_id` by matching `mykg.session` on the root
   span, pull the relevant spans into a DataFrame(s) shaped for the
   component(s) being graded.
2. **Evaluate** — run the code + LLM evaluators proposed above (or others,
   if the run's actual data suggests different checks matter more) via
   `evaluate_dataframe`.
3. **Write back + report** — `add_span_annotation`/
   `log_span_annotations_dataframe` so scores are visible in Phoenix's UI
   next to the spans they grade, AND print/save a summary the user can read
   without opening Phoenix (a pass-rate table per component is usually
   enough — see `scripts/summarize_annotations.py` for a starting point that
   reads annotations back and formats them).

See `references/eval-py-skeleton.py` for a fuller worked skeleton (not a
black box to run unmodified — read it, adapt the evaluators to what this
specific run's data actually shows, then run it).

## Golden dataset (tier 2 — regression testing, not required for a first eval)

LLM-judge evals give a continuous quality signal on any corpus, but they
can't catch "this specific known-good extraction regressed" the way a fixed
expected-output comparison can. Once you (or the user) have looked at a run
and confirmed a particular extraction is correct, promote it into a Phoenix
dataset so future runs can be checked against it:

```python
from phoenix.client import Client

client = Client(base_url="http://localhost:6006")
dataset = client.datasets.create_dataset(
    name="mykg-golden-technologies-md",
    examples=[
        {
            "input": {"text": "...chunk text from technologies.md...", "schema": schema_dict},
            "output": {"nodes": [...], "edges": [...]},  # the hand-confirmed-correct extraction
        },
        # one example per hand-verified chunk
    ],
)
```
Then grade future runs against it with `run_experiment`:
```python
from phoenix.client.experiments import run_experiment

def extract_task(example):
    # call the same extraction logic (or replay a captured ChatCompletion span's
    # output for this example) and return it in the same shape as `output` above
    ...

experiment = run_experiment(
    dataset=dataset,
    task=extract_task,
    evaluators=[node_set_matches, edge_set_matches],  # code evaluators comparing task output to example.expected
    experiment_name="pass2-regression-2026-09-21",
)
```
Confirmed `run_experiment` params (beyond `dataset`/`task`/`evaluators`):
`experiment_name`, `experiment_description`, `experiment_metadata`,
`repetitions` (run each example N times — useful for measuring how
non-deterministic the extraction is across repeated calls),
`dry_run`, `timeout`, `retries`. Each call creates a new named experiment
run against the same dataset, so `experiment_name` is what lets you compare
across pipeline versions/prompt changes in Phoenix's UI later.

Start this dataset small (1–2 documents' worth of hand-confirmed chunks) and
grow it opportunistically — every time an LLM-judge eval flags something the
user confirms is actually correct or actually wrong, that's a candidate
example to add. Don't try to build a comprehensive golden set upfront; it's
not required to run any eval in this skill.

## Reference files

- `references/instrumentation-guide.md` — **Phase A only.** The module
  template for a `tracing.py` from scratch, including `OtelSpanLogHandler`
  (bridging standard-logging WARNING+/exceptions onto spans as events) and
  the `BatchSpanProcessor`/`SimpleSpanProcessor` streaming trade-off; the
  two real bug classes to verify against (opentelemetry-api as a core
  dependency, thread-pool context propagation); and the
  in-memory-span-exporter testing pattern, including how to test the log
  bridge itself. Read this only after a Phase A plan has been proposed and
  approved.
- `references/writing-evaluators.md` — the three evaluator shapes (code,
  LLM-judge, rubric) with full working code for each. Read before writing
  any evaluator function.
- `references/span-map.md` — every span name mykg emits, its attributes, and
  which file/line produces it, cross-referenced against this project's own
  12-step (and 12-step merge) pipeline table in CLAUDE.md so every step name
  is accounted for — plus the log-events-on-spans mechanism and what
  "streaming" does and doesn't get you for the top-level run/step spans
  specifically. Read this before writing any span-querying code so you know
  exactly what's queryable. (mykg-specific — for a different target
  project, Phase A's own detection step is what tells you what's queryable
  instead.)
- `references/phoenix-api-surface.md` — the confirmed `Client` method
  signatures for reading spans back and writing annotations, including the
  annotation-upsert collision warning. Read this right before writing the
  actual `get_spans_dataframe`/`add_span_annotation` calls in `eval.py`.
- `references/eval-py-skeleton.py` — a worked-through skeleton showing the
  load/evaluate/write-back phases wired together against real mykg span
  shapes. Adapt, don't run unmodified.
- `scripts/summarize_annotations.py` — reads annotations back from Phoenix
  for a session's trace_id and prints a pass-rate table per component/eval
  name. Reusable across every invocation of this skill without rewriting it.
