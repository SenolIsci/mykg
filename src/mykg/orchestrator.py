from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

if TYPE_CHECKING:
    pass

from mykg import config as _cfg
from mykg.logging import get

log = get("mykg.orchestrator")


class PipelineHaltError(Exception):
    def __init__(self, step_name: str, error: str):
        self.step_name = step_name
        self.error = error
        super().__init__(f"Pipeline halted at step '{step_name}': {error}")


class SchemaUpdatedError(Exception):
    """Raised by orphan_connect when it updates schema.json.

    The orchestrator catches this and re-runs all steps from pass2 onward so
    the new schema properties are applied to fresh extractions (Re-entry A).

    gap_orphans: the SchemaGapOrphan objects that triggered the schema addition.
    Carried through so the orchestrator can store them on PipelineContext and
    pass2 can inject targeted extraction hints for the affected chunks.
    """

    def __init__(self, new_property_names: list[str], gap_orphans: list | None = None):
        self.new_property_names = new_property_names
        self.gap_orphans = gap_orphans or []
        super().__init__(
            f"Schema updated with {len(new_property_names)} new property/properties: "
            + ", ".join(new_property_names)
        )


class PipelineContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    input_dir: Path
    output_dir: Path
    intermediate_dir: Path
    adapter: Any
    error_gate: Any = None  # ErrorGate | None — Any to avoid circular import
    base_schema: dict | None = None
    thesaurus: Any = None  # SynonymIndex | None — Any to avoid forward-ref issues
    review: bool = False
    append: bool = False
    # --append --grow-schema (D52): run locked Pass 1 over changed files only so the
    # LLM may ADD new concepts/properties to the existing (locked) schema, then
    # surgically back-fill old files when the schema actually grows.
    grow_schema: bool = False
    # Runtime fields populated by steps
    all_chunks: list | None = None
    file_contents: dict[str, str] | None = None
    nodes: list | None = None
    edge_metadata: dict | None = None
    raw_extractions: dict | None = None
    chunk_node_index: dict | None = None
    # None = ingest hasn't run yet / not in append mode.
    # set() = ingest ran in append mode and found no changes (nothing-to-do).
    # non-empty set = ingest ran and found new/modified files.
    append_new_files: set[str] | None = None
    pass2_workers: int = Field(default_factory=lambda: _cfg.PASS2_MAX_WORKERS)
    ingest_workers: int = Field(default_factory=lambda: _cfg.INGEST_MAX_WORKERS)
    confidence_agg: str = Field(default_factory=lambda: _cfg.ASSEMBLY_CONFIDENCE_AGG)
    # times Re-entry A has fired this run; capped at ORPHAN_SCHEMA_MAX_RESTARTS
    schema_restart_count: int = 0
    # Hints injected into pass2 chunk prompts after a schema-gap Re-entry A.
    # Dict keys: new_properties, orphan_id, orphan_type, orphan_name, shared_chunks
    schema_hints: list[dict] = Field(default_factory=list)
    # Set by --from-step orphan_connect_incremental: load prior orphan_connections.json
    # as a seed and only re-send unresolved groups to the LLM.
    orphan_incremental: bool = False


class Step(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    fn: Callable[[PipelineContext], None]
    outputs: list[str] = Field(default_factory=list)
    is_llm_step: bool = False
    blocking: bool = True
    requires_review_flag: bool = False
    output_location: Literal["intermediate", "output"] = "intermediate"


def _is_done(step: Step, ctx: PipelineContext) -> bool:
    if not step.outputs:
        return False
    for output in step.outputs:
        p = ctx.intermediate_dir / output
        if not p.exists():
            p = ctx.output_dir / output
        if not p.exists():
            return False
    return True


class PipelineState(BaseModel):
    step_names: list[str]
    steps: dict = Field(default_factory=dict)
    errors: dict = Field(default_factory=dict)
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @model_validator(mode="after")
    def _init_steps(self) -> "PipelineState":
        for name in self.step_names:
            if name not in self.steps:
                self.steps[name] = {"status": "pending"}
        return self

    def mark_done(self, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.steps[name] = {"status": "done", "completed_at": now}

    def mark_running(self, name: str) -> None:
        self.steps[name] = {"status": "running"}

    def mark_waiting(self, name: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.steps[name] = {"status": "waiting", "waiting_since": now}

    def mark_failed(self, name: str, error: str, attempts: int, llm_correction: bool) -> None:
        self.steps[name] = {"status": "failed"}
        self.errors[name] = {
            "error": error,
            "attempts": attempts,
            "llm_correction_applied": llm_correction,
            "resolved": False,
        }

    def save(self, intermediate_dir: Path) -> None:
        intermediate_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": "running",
            "started_at": self.started_at,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "steps": self.steps,
            "errors": self.errors,
        }
        (intermediate_dir / "pipeline_state.json").write_text(
            json.dumps(payload, indent=_cfg.JSON_INDENT)
        )

    @classmethod
    def load(cls, intermediate_dir: Path, step_names: list[str]) -> "PipelineState":
        path = intermediate_dir / "pipeline_state.json"
        if not path.exists():
            return cls(step_names=step_names)
        data = json.loads(path.read_text())
        state = cls(step_names=step_names)
        state.steps = data.get("steps", {})
        state.errors = data.get("errors", {})
        state.started_at = data.get("started_at", state.started_at)
        # Ensure all current step names are present
        for name in step_names:
            state.steps.setdefault(name, {"status": "pending"})
        return state


def _try_run(step: Step, ctx: PipelineContext) -> str | None:
    try:
        step.fn(ctx)
        return None
    except SchemaUpdatedError:
        raise  # propagate; orchestrator handles restart
    except Exception as exc:
        return str(exc)


def _log_advisory(step: Step, error: str, ctx: PipelineContext) -> None:
    log.error("FAILED: %s — %s", step.name, error)
    log.error("Check intermediate files in: %s", ctx.intermediate_dir)
    reentry = {
        "pass1": "Re-entry A: delete intermediate/schema.json and re-run",
        "schema_validate": "Re-entry A: edit intermediate/schema.json and re-run",
        "pass2": (
            "Re-entry B: delete intermediate/raw_extractions.done "
            "(and optionally raw_extractions.json) and re-run"
        ),
        "normalize_names": (
            "Re-entry C (normalization): edit intermediate/name_normalization.json "
            "and re-run from --from-step assemble"
        ),
        "assemble": "Re-entry C: delete intermediate/edge_metadata.json and re-run",
        "validate_graph": "Re-entry C: delete intermediate/edge_metadata.json and re-run",
        "ttl_validate": "Advisory only — check output/knowledge_graph_validation.json",
        "orphan_score": (
            "Re-entry D: delete intermediate/orphan_candidates.json "
            "and re-run from --from-step orphan_score"
        ),
        "orphan_connect": (
            "Re-entry D: delete intermediate/orphan_connections.json "
            "and re-run from --from-step orphan_connect"
        ),
    }
    hint = reentry.get(step.name, "Re-run from the beginning")
    log.error("Hint: %s", hint)


def _review_flag_exists(ctx: PipelineContext) -> bool:
    return (ctx.intermediate_dir / "schema_approved.flag").exists()


_SCHEMA_RESTART_FROM = "pass2"
# Steps to invalidate when schema.json is updated during the orphan pass so
# that pass2 (and all downstream steps) are re-run with the new schema.
_SCHEMA_RESTART_INVALIDATE = {
    "schema_validate",
    "schema_flatten",
    "pass2",
    "normalize_names",
    "assemble",
    "orphan_score",
    "orphan_connect",
    "validate_graph",
}

# Re-entry B: steps whose outputs must be deleted when --append detects new/modified
# files so that pass2 re-runs against the existing schema (D26).
_APPEND_INVALIDATE = {
    "pass2",
    "normalize_names",
    "assemble",
    "orphan_score",
    "orphan_connect",
    "validate_graph",
}
# Pass 2 outputs that must NOT be deleted during append invalidation — the append
# mode merge logic in _run_append_mode reads them to merge old + new extractions.
_APPEND_PRESERVE_OUTPUTS = {"raw_extractions.json", "chunk_node_index.json", "raw_extractions.done"}

APPEND_SKIP_STEPS: frozenset[str] = frozenset({"pass1", "schema_validate", "human_review"})


def _invalidate_append_downstream(
    steps: list[Step], ctx: PipelineContext, state: "PipelineState"
) -> None:
    """Delete pass2 and downstream outputs so they re-run for the new files (Re-entry B)."""
    for s in steps:
        if s.name not in _APPEND_INVALIDATE:
            continue
        for output in s.outputs:
            if output in _APPEND_PRESERVE_OUTPUTS:
                log.debug("append: preserving %s for merge", output)
                continue
            for loc in (ctx.intermediate_dir, ctx.output_dir):
                p = loc / output
                if p.exists():
                    p.unlink()
                    log.debug("append: deleted stale output %s", p)
        state.steps[s.name] = {"status": "pending"}
    ctx.nodes = None
    ctx.edge_metadata = None
    ctx.raw_extractions = None
    ctx.chunk_node_index = None
    log.info(
        "append: invalidated pass2 and downstream outputs for %d changed file(s): %s",
        len(ctx.append_new_files),
        sorted(ctx.append_new_files),
    )


def run(steps: list[Step], ctx: PipelineContext) -> None:
    # Deferred import breaks the orchestrator ↔ feedback circular dependency
    # (feedback.py imports PipelineContext from this module).
    import mykg.feedback as feedback

    if ctx.append and not (ctx.intermediate_dir / "schema.json").exists():
        raise RuntimeError(
            f"No existing pipeline found in {ctx.intermediate_dir}. Run without --append first."
        )

    step_names = [s.name for s in steps]
    state = PipelineState.load(ctx.intermediate_dir, step_names)

    # Iterative restart loop — SchemaUpdatedError causes a `continue` that restarts
    # the step iterator from the top without adding a new stack frame.
    while True:
        schema_restart_triggered = False

        # In --grow-schema mode, pass1/schema_validate must run again so the locked
        # Pass 1 can add new concepts/properties. human_review stays skipped unless
        # --review is also set, in which case it is un-skipped so the gate (handled
        # below via requires_review_flag) can pause for review of the grown schema.
        # All other append skips remain in force (D52).
        append_skip = APPEND_SKIP_STEPS
        if ctx.grow_schema:
            append_skip = APPEND_SKIP_STEPS - {"pass1", "schema_validate"}
            if ctx.review:
                append_skip = append_skip - {"human_review"}

        for step in steps:
            if ctx.append and step.name in append_skip:
                log.info("SKIP %s — append mode", step.name)
                continue

            # In append mode, ingest must always run (detect new files) and pass2
            # must always run when new files exist (raw_extractions.json is preserved
            # for merge but still needs updating — _is_done would skip it otherwise).
            # In --grow-schema mode, pass1 must also be force-run so a stale schema.json
            # does not cause _is_done to skip the locked re-induction.
            _append_force = ctx.append and step.name in (
                "ingest",
                *(("pass1", "schema_validate", "schema_flatten") if ctx.grow_schema else ()),
                *(("pass2",) if ctx.append_new_files else ()),
            )
            if _is_done(step, ctx) and not _append_force:
                log.info("SKIP %s — outputs exist", step.name)
                state.mark_done(step.name)
                continue

            if step.requires_review_flag and ctx.review and not _review_flag_exists(ctx):
                log.info("WAITING at %s — schema review required", step.name)
                log.info("  1. Review intermediate/schema.json (and schema.ttl in Protégé)")
                log.info("  2. Edit intermediate/schema.json if needed")
                log.info(
                    "  3. Run: mykg approve-schema --intermediate-dir %s",
                    ctx.intermediate_dir,
                )
                log.info("  4. Re-run this command to continue from Step 5")
                state.mark_waiting(step.name)
                state.save(ctx.intermediate_dir)
                return

            # Append-mode early exit: ingest ran and found no new or modified files,
            # so there is nothing to do — skip all remaining steps.
            # ctx.append_new_files is None until the ingest step actually sets it;
            # distinguishes "not yet determined" (None) from "empty result" (set()).
            if (
                ctx.append
                and step.name != "ingest"
                and ctx.append_new_files is not None
                and not ctx.append_new_files
            ):
                log.info("SKIP %s — append mode: no new or modified files detected", step.name)
                state.mark_done(step.name)
                continue

            log.info("RUN  %s", step.name)
            state.mark_running(step.name)
            state.save(ctx.intermediate_dir)

            try:
                error = _try_run(step, ctx)
            except (KeyboardInterrupt, SystemExit) as exc:
                # Signal or Ctrl-C — save failure before the process exits so
                # pipeline_state.json doesn't stay stuck as "running".
                state.mark_failed(step.name, repr(exc), attempts=1, llm_correction=False)
                state.save(ctx.intermediate_dir)
                log.error("INTERRUPTED %s — %s", step.name, type(exc).__name__)
                raise
            except SchemaUpdatedError as schema_exc:
                if ctx.schema_restart_count >= _cfg.ORPHAN_SCHEMA_MAX_RESTARTS:
                    log.warning(
                        "SCHEMA UPDATED — %s — but restart limit (%d) reached; "
                        "schema.json has been updated but pass2 will NOT re-run. "
                        "Re-run manually with --from-step pass2 to apply the new properties.",
                        schema_exc,
                        _cfg.ORPHAN_SCHEMA_MAX_RESTARTS,
                    )
                    ctx.schema_hints = []
                    state.mark_failed(
                        step.name, "schema_restart_limit_reached", attempts=1, llm_correction=False
                    )
                    state.save(ctx.intermediate_dir)
                    continue

                # schema.json was updated during orphan_connect; invalidate downstream
                # outputs so pass2 and all later steps re-run (Re-entry A).
                ctx.schema_restart_count += 1
                log.warning(
                    "SCHEMA UPDATED — %s; invalidating outputs and restarting from %s "
                    "(restart %d/%d)",
                    schema_exc,
                    _SCHEMA_RESTART_FROM,
                    ctx.schema_restart_count,
                    _cfg.ORPHAN_SCHEMA_MAX_RESTARTS,
                )
                # Build per-chunk hints so pass2 can inject targeted prompts for the
                # orphan nodes whose schema gap triggered this restart.
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
                for s in steps:
                    if s.name in _SCHEMA_RESTART_INVALIDATE:
                        for output in s.outputs:
                            for loc in (ctx.intermediate_dir, ctx.output_dir):
                                p = loc / output
                                if p.exists():
                                    p.unlink()
                                    log.debug("Deleted stale output: %s", p)
                        state.steps[s.name] = {"status": "pending"}
                # Shards are intentionally preserved — step_pass2 will re-extract only
                # the specific chunks named in schema_hints.shared_chunks, merging new
                # edges back into the existing shards. Deleting all shards here would
                # force a full re-extraction of every file for every schema-gap restart,
                # paying O(files × restarts) LLM cost instead of O(affected_chunks).
                flag_path = ctx.intermediate_dir / "schema_approved.flag"
                if flag_path.exists():
                    flag_path.unlink()
                    log.debug(
                        "Deleted stale schema_approved.flag (schema updated by schema-gap restart)"
                    )
                # Regenerate schema.ttl immediately — schema_validate is skipped on
                # restart (append mode) or would skip regeneration (non-append, file
                # still exists). Deferred import avoids circular dependency.
                _schema_json_path = ctx.intermediate_dir / "schema.json"
                if _schema_json_path.exists():
                    from mykg.exporter import export_ttl as _export_ttl

                    _updated_schema = json.loads(_schema_json_path.read_text())
                    _ttl_text = _export_ttl(_updated_schema, [], {})
                    (ctx.intermediate_dir / "schema.ttl").write_text(_ttl_text)
                    log.info(
                        "Schema-gap restart — regenerated schema.ttl "
                        "(%d concept(s), %d property/properties)",
                        len(_updated_schema.get("concepts", [])),
                        len(_updated_schema.get("properties", [])),
                    )
                # Reset in-memory state that pass2 populates
                ctx.nodes = None
                ctx.edge_metadata = None
                ctx.raw_extractions = None
                ctx.chunk_node_index = None
                state.save(ctx.intermediate_dir)
                schema_restart_triggered = True
                break  # restart the for-loop via the outer while

            if error:
                log.warning("RETRY %s — attempt 1 failed: %s", step.name, error)
                error = _try_run(step, ctx)

            llm_correction = False
            if error and step.is_llm_step:
                log.warning("FEEDBACK %s — requesting LLM correction", step.name)
                try:
                    llm_correction = feedback.apply(step.name, error, ctx)
                except Exception as fb_exc:
                    log.warning("Feedback handler failed: %s", fb_exc)
                error = _try_run(step, ctx)

            if error:
                attempts = 3 if (step.is_llm_step and llm_correction) else 2
                state.mark_failed(
                    step.name, error, attempts=attempts, llm_correction=llm_correction
                )
                state.save(ctx.intermediate_dir)
                _log_advisory(step, error, ctx)
                if step.blocking:
                    raise PipelineHaltError(step.name, error)
                else:
                    log.warning("NON-BLOCKING: continuing past %s", step.name)
                    continue

            # Re-entry B: ingest found new/modified files in append mode — delete
            # pass2 and all downstream outputs so they re-run against the existing
            # schema (D26). Must happen after ingest writes the updated manifest.
            if ctx.append and step.name == "ingest" and ctx.append_new_files:
                _invalidate_append_downstream(steps, ctx, state)

            state.mark_done(step.name)
            state.save(ctx.intermediate_dir)
            log.info("DONE %s", step.name)

        if not schema_restart_triggered:
            break  # all steps completed (or we returned early); exit the while loop
