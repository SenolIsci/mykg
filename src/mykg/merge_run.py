from __future__ import annotations

from mykg import config as _cfg
from mykg.logging import get
from mykg.merge_context import MergeContext
from mykg.merge_pipeline import MERGE_STEPS
from mykg.orchestrator import (
    PipelineHaltError,
    PipelineState,
    SchemaUpdatedError,
    Step,
    _is_done,
    _review_flag_exists,
    _try_run,
)

log = get("mykg.merge_run")

# Merge-step-specific re-entry hints shown on failure.
_MERGE_REENTRY_HINTS: dict[str, str] = {
    "merge_setup": "Delete intermediate/source_map.json and re-run from the beginning",
    "merge_schema": "Delete intermediate/schema.json and re-run from the beginning",
    "schema_validate": (
        "Edit intermediate/schema.json then re-run: "
        "mykg merge-graphs <A> <B> --output-session <name> --from-step schema_validate"
    ),
    "human_review": "Approve via: mykg approve-schema --session <name>",
    "schema_flatten": (
        "mykg merge-graphs <A> <B> --output-session <name> --from-step schema_flatten"
    ),
    "merge_reextract": (
        "mykg merge-graphs <A> <B> --output-session <name> --from-step merge_reextract"
    ),
    "merge_raw": ("mykg merge-graphs <A> <B> --output-session <name> --from-step merge_raw"),
    "assemble": ("mykg merge-graphs <A> <B> --output-session <name> --from-step assemble"),
    "orphan_score": ("mykg merge-graphs <A> <B> --output-session <name> --from-step orphan_score"),
    "orphan_connect": (
        "mykg merge-graphs <A> <B> --output-session <name> --from-step orphan_connect"
    ),
    "validate_graph": (
        "mykg merge-graphs <A> <B> --output-session <name> --from-step validate_graph"
    ),
    "merge_manifest": (
        "mykg merge-graphs <A> <B> --output-session <name> --from-step merge_manifest"
    ),
}

# Steps whose outputs must be deleted when SchemaUpdatedError fires during
# orphan_connect so that merge_reextract and all downstream steps re-run with
# the updated schema (mirrors _SCHEMA_RESTART_INVALIDATE in orchestrator.py).
_MERGE_SCHEMA_RESTART_INVALIDATE = {
    "schema_validate",
    "schema_flatten",
    "merge_reextract",
    "merge_raw",
    "assemble",
    "orphan_score",
    "orphan_connect",
    "validate_graph",
}


def _log_merge_advisory(step: Step, error: str, ctx: MergeContext) -> None:
    log.error("FAILED: %s — %s", step.name, error)
    log.error("Check intermediate files in: %s", ctx.intermediate_dir)
    hint = _MERGE_REENTRY_HINTS.get(step.name, "Re-run merge-graphs from the beginning")
    log.error("Hint: %s", hint)


def run_merge(ctx: MergeContext) -> None:
    """Step-based orchestrator for the merge-graphs pipeline.

    Mirrors orchestrator.run() including the SchemaUpdatedError restart loop
    triggered when orphan_connect finds schema-gap orphans and proposes new
    RDFS properties. On restart, outputs of all steps in
    _MERGE_SCHEMA_RESTART_INVALIDATE are deleted and the step loop restarts
    from merge_reextract. Restarts are capped at
    MERGE_ORPHAN_SCHEMA_MAX_RESTARTS.

    Features inherited from the extract-graph orchestrator:
    - Skip steps whose output files already exist (resumability)
    - Retry each step up to 3 times (attempt 1 → attempt 2 → LLM feedback → attempt 3)
    - Persist step status to pipeline_state.json after every transition
    - Non-blocking steps log warnings and continue on failure
    - Human review gate honours ctx.review and requires_review_flag
    """
    # Deferred import breaks the merge_run ↔ feedback circular dependency
    # (feedback.py imports PipelineContext from orchestrator.py, which is a
    # base class of MergeContext — moving this import to module scope would
    # create a circular import chain at load time).
    import mykg.feedback as feedback

    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    step_names = [s.name for s in MERGE_STEPS]
    state = PipelineState.load(ctx.intermediate_dir, step_names)

    # Iterative restart loop — SchemaUpdatedError causes a `continue` that
    # restarts the step iterator from the top without adding a new stack frame.
    while True:
        schema_restart_triggered = False

        for step in MERGE_STEPS:
            if _is_done(step, ctx):
                log.info("SKIP %s — outputs exist", step.name)
                state.mark_done(step.name)
                continue

            if step.requires_review_flag and ctx.review and not _review_flag_exists(ctx):
                log.info("WAITING at %s — schema review required", step.name)
                log.info("  1. Review intermediate/schema.json")
                log.info("  2. Edit intermediate/schema.json if needed")
                log.info(
                    "  3. Run: mykg approve-schema --intermediate-dir %s",
                    ctx.intermediate_dir,
                )
                log.info("  4. Re-run merge-graphs with --session <name> to continue")
                state.mark_waiting(step.name)
                state.save(ctx.intermediate_dir)
                return

            log.info("RUN  %s", step.name)
            state.mark_running(step.name)
            state.save(ctx.intermediate_dir)

            try:
                error, non_retryable = _try_run(step, ctx)
            except (KeyboardInterrupt, SystemExit) as exc:
                state.mark_failed(step.name, repr(exc), attempts=1, llm_correction=False)
                state.save(ctx.intermediate_dir)
                log.error("INTERRUPTED %s — %s", step.name, type(exc).__name__)
                raise
            except SchemaUpdatedError as schema_exc:
                if ctx.schema_restart_count >= _cfg.MERGE_ORPHAN_SCHEMA_MAX_RESTARTS:
                    log.warning(
                        "SCHEMA UPDATED — %s — but restart limit (%d) reached; "
                        "schema.json has been updated but merge_reextract will NOT re-run. "
                        "Re-run manually with --from-step merge_reextract to apply the new properties.",
                        schema_exc,
                        _cfg.MERGE_ORPHAN_SCHEMA_MAX_RESTARTS,
                    )
                    ctx.schema_hints = []
                    state.mark_failed(
                        step.name, "schema_restart_limit_reached", attempts=1, llm_correction=False
                    )
                    state.save(ctx.intermediate_dir)
                    continue

                # schema.json was updated during orphan_connect; invalidate
                # downstream outputs so merge_reextract and all later steps
                # re-run with the new schema.
                ctx.schema_restart_count += 1
                log.warning(
                    "SCHEMA UPDATED — %s; invalidating outputs and restarting from merge_reextract "
                    "(restart %d/%d)",
                    schema_exc,
                    ctx.schema_restart_count,
                    _cfg.MERGE_ORPHAN_SCHEMA_MAX_RESTARTS,
                )
                ctx.schema_hints = [
                    {
                        "new_properties": schema_exc.new_property_names,
                        "orphan_id": g.orphan_id,
                        "orphan_type": g.orphan_type,
                        "orphan_name": g.orphan_name,
                        "shared_chunks": g.shared_chunks,
                    }
                    for g in schema_exc.gap_orphans
                ]
                for s in MERGE_STEPS:
                    if s.name in _MERGE_SCHEMA_RESTART_INVALIDATE:
                        for output in s.outputs:
                            for loc in (ctx.intermediate_dir, ctx.output_dir):
                                p = loc / output
                                if p.exists():
                                    p.unlink()
                                    log.debug("Deleted stale output: %s", p)
                        state.steps[s.name] = {"status": "pending"}
                # Regenerate schema.ttl so merge_reextract uses the updated schema.
                _schema_json_path = ctx.intermediate_dir / "schema.json"
                if _schema_json_path.exists():
                    import json

                    from mykg.exporter import export_ttl as _export_ttl

                    _updated_schema = json.loads(_schema_json_path.read_text(encoding="utf-8"))
                    _ttl_text = _export_ttl(_updated_schema, [], {})
                    (ctx.intermediate_dir / "schema.ttl").write_text(_ttl_text, encoding="utf-8")
                    log.info(
                        "Schema-gap restart — regenerated schema.ttl "
                        "(%d concept(s), %d property/properties)",
                        len(_updated_schema.get("concepts", [])),
                        len(_updated_schema.get("properties", [])),
                    )
                # Remove the review approval flag so the human_review gate
                # doesn't skip on restart with the old (pre-update) schema.
                _flag = ctx.intermediate_dir / "schema_approved.flag"
                if _flag.exists():
                    _flag.unlink()
                ctx.nodes = None
                ctx.edge_metadata = None
                ctx.chunk_node_index = None
                state.save(ctx.intermediate_dir)
                schema_restart_triggered = True
                break  # restart the for-loop via the outer while

            if error and non_retryable:
                log.warning(
                    "PRECONDITION FAILED %s — %s (skipping retry and LLM feedback; "
                    "this is a usage/precondition error, not a transient or content error)",
                    step.name,
                    error,
                )

            if error and not non_retryable:
                log.warning("RETRY %s — attempt 1 failed: %s", step.name, error)
                error, non_retryable = _try_run(step, ctx)

            llm_correction = False
            if error and not non_retryable and step.is_llm_step:
                log.warning("FEEDBACK %s — requesting LLM correction", step.name)
                try:
                    llm_correction = feedback.apply(step.name, error, ctx)
                except Exception as fb_exc:
                    log.warning("Feedback handler failed: %s", fb_exc)
                error, non_retryable = _try_run(step, ctx)

            if error:
                if non_retryable:
                    attempts = 1
                elif step.is_llm_step and llm_correction:
                    attempts = 3
                else:
                    attempts = 2
                state.mark_failed(
                    step.name, error, attempts=attempts, llm_correction=llm_correction
                )
                state.save(ctx.intermediate_dir)
                _log_merge_advisory(step, error, ctx)
                if step.blocking:
                    raise PipelineHaltError(step.name, error)
                else:
                    log.warning("NON-BLOCKING: continuing past %s", step.name)
                    continue

            state.mark_done(step.name)
            state.save(ctx.intermediate_dir)
            log.info("DONE %s", step.name)

        if not schema_restart_triggered:
            break  # all steps completed (or we returned early); exit the while loop
