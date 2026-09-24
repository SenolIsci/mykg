# `--live-eval` — Async Monitoring Boundary Around the Sync Pipeline — Design

Status: proposed, pending review
Date: 2026-09-24

## 1. Problem

The Phoenix/OTel eval tooling built alongside mykg's tracing (the
`mykg-phoenix-eval` skill, `phoenix.client.AsyncClient`) is fully async —
reading spans back and writing annotations is a coroutine-based API end to
end. mykg's own pipeline (`orchestrator.py`, `pass1.py`, `pass2.py`, all 7
LLM adapters) is fully synchronous, parallelized internally via
`ThreadPoolExecutor` (D3, D4, Invariant 12 in `CLAUDE.md`).

Today these are two disconnected worlds by construction: `mykg extract-graph`
runs to completion in one process, exporting spans to Phoenix via OTel as it
goes; a separate `eval.py` script runs afterward, in a separate process, and
reads those spans back. Nothing requires them to share a process or an event
loop for either to work — the pipeline doesn't call into `phoenix.client` at
all, and the eval script never calls into the pipeline.

The concrete gap this closes: there is no way to watch degraded-mode signal
(a `mykg.pass2.batch` span landing with `status_code == ERROR`, or carrying a
`pass2.chunk.*` degraded-mode event) *while a run is still executing*, in the
same terminal session, without a second process. A long Pass 2 run that goes
degraded 20% of the way through currently isn't visible as "went bad" until
someone either watches `run.log` scroll by or opens Phoenix's UI separately.

## 2. Goals

- One `mykg extract-graph --live-eval` invocation runs the pipeline and
  surfaces a running degraded/healthy count for `mykg.pass2.batch` spans as
  they complete, in the same terminal, via the existing logging setup.
- Zero change to pipeline concurrency, structure, or interfaces —
  `orchestrator.py`, `pass1.py`, `pass2.py`, every LLM adapter, and every
  `ThreadPoolExecutor` call site are untouched. D3, D4, and Invariant 12 in
  `CLAUDE.md` remain fully authoritative and unmodified.
- Zero added LLM cost — the live-eval loop is code-only checks
  (`status_code`, span `events`), no LLM-judge calls, no new eval-config
  surface (judge model, threshold, etc).
- Zero risk to users who don't opt in — `--live-eval` is off by default; the
  unflagged path is byte-for-byte the same code that runs today.
- Composes for free with every other `extract-graph` mode flag (`--append`,
  `--sync`, `--grow-schema`, `--pass1-schema-induction-only`,
  `--pass2-kg-extraction-only`) since it never touches `ctx` or step
  selection — it only wraps the existing `run(STEPS, ctx)` call.

## 3. Non-goals

- **Not** a general asyncio migration of the pipeline. No LLM adapter's
  `complete()` becomes async. No `ThreadPoolExecutor` site becomes
  `asyncio.gather`/`TaskGroup`. This was explicitly considered and rejected
  during brainstorming — the actual motivation (architectural consistency
  with the now-async eval tooling) doesn't require it, since the pipeline
  and the eval reader don't need to share a process for either to work
  today; the only real capability this unlocks is *one process, both
  activities interleaved*, which `asyncio.to_thread` gets for free without
  touching pipeline internals.
- **Not** a live LLM-judge quality grader. No prompt, no judge model config,
  no Phoenix annotation writes from inside the pipeline process. That
  remains the `mykg-phoenix-eval` skill's job, run separately, after or
  during a run via its own `eval.py`.
- **Not** a rich terminal UI. No progress bars, no redrawing panel, no new
  UI dependency — periodic `log.info(...)` lines through the existing
  `logging.py` setup, exactly like every other pipeline log line.
- **Not** a replacement for the `mykg-phoenix-eval` skill's live-grading
  polling-loop pattern (`references/phoenix-api-surface.md`, "Worked
  pattern: grading live"). That pattern is for a *separate*, LLM-judge-
  bearing eval script run by the skill on demand. This feature is a much
  smaller, always-available, code-only monitor built into the CLI itself.

## 4. Design

### 4.1 Shape

```
cli.py: extract_graph()
  ├─ builds ctx, adapter, session dirs           (unchanged, sync)
  ├─ opens mykg.extract_graph.run span            (unchanged, sync)
  │    trace_id_hex = format(run_span.get_span_context().trace_id, "032x")
  └─ if live_eval:
       asyncio.run(_run_with_live_eval(ctx, trace_id_hex, poll_seconds))
         via asyncio.gather(
           asyncio.to_thread(run, STEPS, ctx),        # the ENTIRE existing sync pipeline, untouched
           poll_pass2_batches(trace_id_hex, poll_seconds),  # new, cancelled when the pipeline task finishes
         )
     else:
       run(STEPS, ctx)                                # today's exact code path, unchanged
```

`run_span.get_span_context().trace_id` is available at span-open time — it's
assigned when the span is created, not when it finishes exporting — so the
trace_id is known before the pipeline (and therefore before the run span)
completes, which is what makes polling for children of this trace possible
while the run is still in progress. This composes directly with what
`references/span-map.md`'s "Streaming" section already establishes: child
spans (`mykg.pass2.batch`) close and export well before their parent
(`mykg.step.pass2`, `mykg.extract_graph.run`) does.

### 4.2 New module: `src/mykg/live_eval.py`

Holds the polling loop as an importable, independently testable unit —
`cli.py` stays a thin call site rather than growing more inline async logic
in an already-large file.

```python
async def poll_pass2_batches(
    trace_id_hex: str,
    poll_seconds: int,
    base_url: str,
    project_name: str,
) -> None:
    """Poll Phoenix for mykg.pass2.batch spans belonging to this run's
    trace, logging a running healthy/degraded count as new batches land.
    Stops when the mykg.extract_graph.run span for this trace_id appears
    finished. Never raises into the caller — a live-eval failure (Phoenix
    unreachable, a malformed response) is logged once and the loop exits;
    it must never take down the actual pipeline run it's monitoring."""
```

"Degraded" for a given `mykg.pass2.batch` span means: `status_code == ERROR`,
or the span carries any event named `log`, `exception`, or one of the
`pass2.chunk.*` names documented in `references/span-map.md` — i.e. exactly
the signal that section already tells an eval author to check first, reused
here as a live, code-only check with no LLM call.

### 4.3 CLI flag and precondition

- `--live-eval` (bool flag, default off) added to `extract-graph`'s existing
  flag set in `cli.py`.
- Precondition, checked before the pipeline starts, `ClickException` on
  failure (mirrors the existing `--grow-schema`-requires-`--append` shape):
  `--live-eval` requires `otel.enabled: true` (or `--otel` passed this
  invocation) — there is nothing to poll otherwise. Checked once, early,
  alongside mykg's other flag-precondition checks.
- No mutual exclusivity with any other mode flag — `--live-eval` never
  touches `ctx` or step selection, only wraps the existing `run(STEPS, ctx)`
  call, so it composes with `--append`, `--sync`, `--grow-schema`,
  `--pass1-schema-induction-only`, `--pass2-kg-extraction-only` for free.

### 4.4 Config

New key under `otel:` (Invariant 7 — no hardcoded values), added to all 8
profiles in both `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml`
(Invariant 17):

```yaml
otel:
  live_eval_poll_seconds: 5   # --live-eval: interval between polls for new mykg.pass2.batch spans
```

Exposed as `config.OTEL_LIVE_EVAL_POLL_SECONDS`.

### 4.5 Error handling

- **Pipeline exception** — `asyncio.gather` without `return_exceptions=True`
  propagates the pipeline task's exception into the awaiting `asyncio.run`
  call, which also cancels the still-running poll task. The pipeline's own
  failure/exit-code behavior (today, an uncaught exception in
  `orchestrator.run` propagates to `cli.py` and exits non-zero) is
  unchanged — the poll loop being cancelled alongside it is a clean
  teardown, not a new failure mode.
- **Phoenix unreachable / poll error** — caught inside
  `poll_pass2_batches` itself; logs one `WARNING` (not one per failed poll —
  avoid spamming `run.log` on every 5s tick if Phoenix is down for the whole
  run) and returns, letting the pipeline continue uninterrupted. Observability
  tooling failing must never take down real extraction work — same principle
  `suppress_tracing()` embodies for the OTel export path itself.

### 4.6 Testing

- **Wrapper transparency**: a test proving
  `await asyncio.to_thread(run, STEPS, ctx)` produces an identical result
  (same `pipeline_state.json`, same output files) to calling
  `run(STEPS, ctx)` directly against the same fixture corpus — confirms the
  async wrapper is a true no-op around the existing pipeline, not a second
  code path that can drift from the sync one.
- **`poll_pass2_batches` in isolation**: cannot use the existing
  `span_exporter` in-memory-OTel-SDK fixture (`AsyncClient` talks HTTP to a
  running Phoenix server, not the OTel SDK's in-process export path) — mock
  `AsyncClient.spans.get_spans_dataframe` to return a scripted sequence of
  DataFrames (empty → one healthy batch → one degraded batch → the
  `mykg.extract_graph.run` row appearing, ending the loop) and assert the
  expected `log.info`/`log.warning` calls and that the loop actually
  terminates. A real Phoenix dependency in CI is avoided by design.
- **Precondition test**: `--live-eval` without `otel.enabled`/`--otel`
  raises `ClickException` before any pipeline step runs.

## 5. Rejected approaches

- **Full asyncio migration** (every adapter, orchestrator, all
  `ThreadPoolExecutor` sites) — rejected in brainstorming. The stated
  motivation (consistency with async eval tooling) doesn't require it: the
  pipeline and the eval reader are separate processes today and don't need
  to share an event loop for either to function. This option would touch
  dozens of files, overturn D3/D4/Invariant 12, and buy nothing this design
  doesn't already get from `asyncio.to_thread` at the single call site that
  actually needs it.
- **Promote skill evaluators into real importable code for live LLM-judge
  grading** — rejected. Doubles the LLM cost of every `--live-eval` run,
  needs a new judge-model/threshold config surface, and duplicates logic the
  `mykg-phoenix-eval` skill already owns per-invocation. The code-only
  degraded-signal check captures the actually-useful "did this go bad"
  question without any of that.
- **Auto-enable tracing when `--live-eval` is passed** — rejected in favor
  of failing fast. Implicitly turning on OTLP export because of an
  unrelated-looking flag is a surprise; an explicit precondition error that
  names the fix (`--otel` or `otel.enabled: true`) matches the codebase's
  existing fail-fast precondition style.

## 6. Open questions for implementation

None — all sections were reviewed and approved during brainstorming.
