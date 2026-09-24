# Phoenix client API surface — reading spans, writing annotations

The detailed, reference-table part of Phase B's verified API surface.
SKILL.md keeps the AX-vs-OSS warning, `suppress_tracing()`, and the
evaluator-shape decision rule inline (those are things to *reason about*
each time); this file holds the parts that are pure lookup — read it when
you're about to write the actual `get_spans_dataframe`/`add_span_annotation`
calls in `eval.py`, not before.

Every signature here was directly introspected against the installed
version in this project (`arize-phoenix-client==3.5.0`,
`arize-phoenix-evals==3.8.0`) — not copied from docs, per the same
verification discipline SKILL.md's Phase B intro describes. The readthedocs
client API reference (https://arize-phoenix.readthedocs.io/projects/client/)
is a good map of *which* classes/methods exist (`Client` and its
`spans`/`datasets`/`experiments`/`prompts`/`projects`/`sessions`
resources), but still re-verify exact signatures by introspection before
relying on it — same reasoning as SKILL.md's warning about Phoenix renaming
things across its frequent releases.

## Reading spans back

```python
from phoenix.client import Client

client = Client(base_url="http://localhost:6006")  # or omit base_url — falls back to PHOENIX_ENDPOINT env, then http://localhost:6006
df = client.spans.get_spans_dataframe(project_name="default", limit=1000)
```
Confirmed signature (`Client.__init__`, `Spans.get_spans_dataframe`, both
introspected against the installed `arize-phoenix-client==3.5.0`):
`Client(*, base_url=None, api_key=None, headers=None, http_client=None)` —
`api_key`, if passed, goes in the `Authorization: Bearer` header; also
settable via the `PHOENIX_API_KEY` env var, and `base_url` via
`PHOENIX_ENDPOINT` (not `PHOENIX_COLLECTOR_ENDPOINT` — that env var is for
the OTel SDK's exporter target, a separate concern from the client's REST
API target, even though they typically point at the same Phoenix instance).
`get_spans_dataframe(*, query=None, start_time=None, end_time=None,
limit=1000, root_spans_only=None, project_identifier=None,
project_name=None, timeout=5)`.

**Filtering server-side instead of in a pandas `.query()`/list-comprehension
after the fact** — `query` takes a `SpanQuery`, confirmed present
(`phoenix.client.types.spans.SpanQuery`), chainable via `.where(condition:
str)` where `condition` is Phoenix's own filter-expression string. Field
names confirmed valid by executing all three against a live local Phoenix
instance (`name == '...'`, `context.trace_id == '...'`,
`status_code == '...'` all parsed and ran cleanly — 0 rows back since no
spans existed yet to match, but no query-syntax error either, which a wrong
field name does raise). Worth using once a trace has enough spans that
pulling everything and filtering client-side is wasteful — e.g. pulling
only `mykg.pass2.batch` spans that errored:
```python
from phoenix.client.types.spans import SpanQuery

df = client.spans.get_spans_dataframe(
    project_name="default",
    query=SpanQuery().where("name == 'mykg.pass2.batch' and status_code == 'ERROR'"),
)
```
For most single-run evals the full session's span count is small enough
that pulling everything and filtering in pandas (as most of the rest of
this skill does) is simpler and fine — reach for `SpanQuery` when the trace
is large or you're querying across many runs at once.

- `project_name` — mykg doesn't set a custom OTel resource `service.name`
  beyond `config.OTEL_SERVICE_NAME` (default `"mykg"`), but Phoenix buckets
  by *project*, not service name, and nothing in mykg's `setup_tracing()`
  currently sets a Phoenix project — traces land in Phoenix's `"default"`
  project unless the user has configured otherwise. Check with
  `client.projects.list()` if unsure, don't assume.
- Real columns confirmed on mykg's own structural spans (`mykg.step.*`,
  `mykg.pass1.batch`, etc.): `name`, `span_kind`, `parent_id`, `start_time`,
  `end_time`, `status_code`, `events`, `context.span_id`, `context.trace_id`,
  and a flattened `attributes.mykg.*`/`attributes.gen_ai.*` per whatever
  `span.set_attribute(...)` calls that span made (see
  `references/span-map.md` for the exact attribute names per span).
- Real columns confirmed on the auto-instrumented `ChatCompletion` spans
  (OpenInference format, children of `mykg.llm.call`):
  `attributes.llm.input_messages`, `attributes.llm.output_messages`,
  `attributes.llm.model_name`, `attributes.llm.token_count.*`,
  `attributes.input.value`, `attributes.output.value`. These carry the
  **actual prompt/completion text** — this is where you pull real extraction
  content from, not from `mykg.llm.call` itself (which only carries
  `context_label` and `gen_ai.system`, no content).
- Filter to one run by `context.trace_id`. Get it from the
  `mykg.extract_graph.run` root span — **but `attributes.mykg.session` does
  not exist as a column.** mykg's own `mykg.*` attribute namespace stays as
  one dict-valued `attributes.mykg` column (unlike OpenInference's `llm.*`/
  `input.*`/`output.*`, which do get dotted-flattened) — read it as
  `row["attributes.mykg"]["session"]`, confirmed by direct introspection.
  See `references/span-map.md` for the full explanation and worked example.
- `events` on any row is a list of `{name, attributes, timestamp}` dicts.
  Before writing any evaluator, it's worth a cheap first pass over
  `[e for e in row["events"] if e["name"] in ("log", "exception",
  "pass2.chunk.json_parse_error", "pass2.chunk.skipped",
  "pass2.chunk.validation_errors", "pass2.chunk.validation_errors_persist")]`
  across all spans in the trace — `log`/`exception` events come from
  standard-logging WARNING+ calls bridged onto the active span (see
  `references/span-map.md`, "Log events"); the `pass2.chunk.*` ones are
  pass2's own purpose-built degraded-mode events. Both are a direct record
  of where the run already struggled, independent of whether the step's
  own `status_code` ended up `OK` (a step can log several recoverable
  warnings and retries and still finish successfully) — read these before
  designing evaluators, the same way you'd read error logs before writing
  test assertions.

## Writing scores back onto spans

```python
client.spans.add_span_annotation(
    span_id=span_id,               # from context.span_id
    annotation_name="edge_type_plausible",
    annotator_kind="LLM",          # or "CODE" for a deterministic check
    label="plausible",
    score=1.0,
    explanation="...",
    identifier="alice->works_at->acme",  # see warning below — required whenever >1 thing you're grading maps to the same span_id
    sync=True,                     # wait for the write to complete before returning
)
```
Confirmed signature (`Spans.add_span_annotation`):
`span_id, annotation_name, annotator_kind: Literal["LLM","CODE","HUMAN"], label=None, score=None, explanation=None, metadata=None, identifier=None, sync=False`.

**⚠️ Annotations upsert by `(span_id, annotation_name[, identifier])` —
writing a second annotation with the same name to a span that already has
one SILENTLY OVERWRITES it rather than accumulating.** Confirmed directly:
writing two `add_span_annotation` calls with the same `annotation_name` to
the same `span_id` and no `identifier` leaves only the second write behind
— no error, no warning, the first score just vanishes. **This matters a lot
for mykg's data shape specifically**: one `ChatCompletion` span (one Pass 2
batch call) commonly produces many nodes/edges in a single response, so if
you're grading per-edge but multiple edges share one span_id, every edge
but the last will silently disappear unless you set a distinct `identifier`
per row (e.g. `f"{from_id}->{edge_type}->{to_id}"`). Always ask: "can more
than one thing I'm grading map to the same span_id?" — if yes, `identifier`
is not optional.

For grading many rows at once, batch via a DataFrame instead of one call per
row (`identifier` is a supported optional column — pass it whenever the
per-span-collision concern above applies):
```python
client.spans.log_span_annotations_dataframe(
    dataframe=annotation_df,   # span_id column/index + score/label/explanation/identifier columns
    annotation_name="edge_type_plausible",
    annotator_kind="LLM",
)
```
Reading annotations back requires `project_identifier` (easy to miss —
confirmed by hitting a `TypeError` without it):
`client.spans.get_span_annotations(span_ids=[...], project_identifier="default")`.
