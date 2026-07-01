from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.llm.retry import llm_complete_with_retry
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.prompts import load_prompt

log = get("mykg.feedback")

FEEDBACK_PROMPT = load_prompt("feedback/user_template")

_SCHEMA_SYSTEM = load_prompt("feedback/schema_system")
_SCHEMA_EXTEND_SYSTEM = load_prompt("feedback/schema_extend_system")
_NORMALIZE_SYSTEM = load_prompt("feedback/normalize_system")
_ORPHAN_CONNECT_SYSTEM = load_prompt("feedback/orphan_connect_system")


def apply(step_name: str, error: str, ctx: PipelineContext) -> bool:
    """Call the feedback handler for *step_name*.

    Returns True if a handler ran, False if none is registered (advisory only).
    """
    handler = _HANDLERS.get(step_name)
    if handler is None:
        log.warning("No feedback handler for step '%s' — advisory only: %s", step_name, error)
        return False
    handler(error, ctx)
    return True


def _validate_schema_response(corrected: object) -> None:
    if (
        not isinstance(corrected, dict)
        or not isinstance(corrected.get("concepts"), list)
        or not isinstance(corrected.get("properties"), list)
    ):
        raise ValueError(
            f"LLM returned invalid schema structure — expected "
            f'{{"concepts": [...], "properties": [...]}}, got: {str(corrected)[:200]}'
        )


def _fix_schema(error: str, ctx: PipelineContext) -> None:
    schema_path = ctx.intermediate_dir / "schema.json"
    current = schema_path.read_text(encoding="utf-8") if schema_path.exists() else "{}"
    prompt = FEEDBACK_PROMPT.format(
        step_name="schema",
        error=error,
        file_contents=current,
        output_format="JSON",
    )
    raw = llm_complete_with_retry(
        ctx.adapter, _SCHEMA_SYSTEM, prompt, context_label="feedback fix-schema"
    )
    corrected = json.loads(raw)
    _validate_schema_response(corrected)
    from mykg.schema_merge import _normalize_schema

    _normalize_schema(corrected)
    from mykg.schema_history import TRIGGER_SCHEMA_VALIDATE, write_schema

    write_schema(corrected, ctx.intermediate_dir, TRIGGER_SCHEMA_VALIDATE)
    _regenerate_schema_ttl(corrected, ctx)
    flattened_path = ctx.intermediate_dir / "flattened_schema.json"
    if flattened_path.exists():
        flattened_path.unlink()
        log.debug("Deleted stale flattened_schema.json (schema corrected by feedback)")
    log.info("Feedback applied to schema.json and schema.ttl")


def _regenerate_schema_ttl(schema: dict, ctx: PipelineContext) -> None:
    from mykg.exporter import export_ttl

    ttl = export_ttl(schema, [], {})
    (ctx.intermediate_dir / "schema.ttl").write_text(ttl, encoding="utf-8")


def _fix_schema_extend(error: str, ctx: PipelineContext) -> None:
    """Correct schema.json+schema.ttl after a schema-gap proposal introduced invalid RDFS.

    Reads schema_gap_proposals.json (written by step_orphan_connect) plus the current
    schema.json, asks the LLM to fix the combined result, and writes corrected files.
    """
    schema_path = ctx.intermediate_dir / "schema.json"
    proposals_path = ctx.intermediate_dir / "schema_gap_proposals.json"
    current_schema = schema_path.read_text(encoding="utf-8") if schema_path.exists() else "{}"
    proposals = proposals_path.read_text(encoding="utf-8") if proposals_path.exists() else "{}"
    prompt = FEEDBACK_PROMPT.format(
        step_name="schema_extend",
        error=error,
        file_contents=f"CURRENT SCHEMA:\n{current_schema}\n\nPROPOSED ADDITIONS:\n{proposals}",
        output_format="JSON",
    )
    raw = llm_complete_with_retry(
        ctx.adapter, _SCHEMA_EXTEND_SYSTEM, prompt, context_label="feedback fix-schema-extend"
    )
    corrected = json.loads(raw)
    _validate_schema_response(corrected)
    from mykg.schema_merge import _normalize_schema

    _normalize_schema(corrected)
    from mykg.schema_history import TRIGGER_SCHEMA_GAP_CORRECT, write_schema

    write_schema(corrected, ctx.intermediate_dir, TRIGGER_SCHEMA_GAP_CORRECT)
    _regenerate_schema_ttl(corrected, ctx)
    log.info("Feedback applied to schema.json and schema.ttl via schema_extend handler")


def _fix_normalization(error: str, ctx: PipelineContext) -> None:
    norm_path = ctx.intermediate_dir / "name_normalization.json"
    current = norm_path.read_text(encoding="utf-8") if norm_path.exists() else "{}"
    prompt = FEEDBACK_PROMPT.format(
        step_name="normalize_names",
        error=error,
        file_contents=current[: _cfg.FEEDBACK_MAX_FILE_CHARS],
        output_format="JSON",
    )
    raw = llm_complete_with_retry(
        ctx.adapter, _NORMALIZE_SYSTEM, prompt, context_label="feedback fix-normalization"
    )
    corrected = json.loads(raw)
    if not isinstance(corrected, dict) or not isinstance(corrected.get("mappings"), dict):
        raise ValueError(
            f"LLM returned invalid normalization structure — expected "
            f'{{"mappings": {{...}}}}, got: {str(corrected)[:200]}'
        )
    norm_path.write_text(json.dumps(corrected, indent=_cfg.JSON_INDENT), encoding="utf-8")
    log.info("Feedback applied to name_normalization.json")


def _fix_orphan_connect(error: str, ctx: PipelineContext) -> None:
    candidates_path = ctx.intermediate_dir / "orphan_candidates.json"
    connections_path = ctx.intermediate_dir / "orphan_connections.json"
    candidates = candidates_path.read_text(encoding="utf-8") if candidates_path.exists() else "{}"
    current = connections_path.read_text(encoding="utf-8") if connections_path.exists() else "{}"
    prompt = FEEDBACK_PROMPT.format(
        step_name="orphan_connect",
        error=error,
        file_contents=(
            f"ORPHAN CANDIDATES:\n{candidates[: _cfg.FEEDBACK_MAX_FILE_CHARS]}\n\n"
            f"CURRENT CONNECTIONS:\n{current[: _cfg.FEEDBACK_MAX_FILE_CHARS]}"
        ),
        output_format="JSON",
    )
    raw = llm_complete_with_retry(
        ctx.adapter, _ORPHAN_CONNECT_SYSTEM, prompt, context_label="feedback fix-orphan-connect"
    )
    corrected = json.loads(raw)
    if not isinstance(corrected, dict):
        raise ValueError(
            f"LLM returned invalid orphan_connections structure — expected a dict, "
            f"got: {str(corrected)[:200]}"
        )
    connections_path.write_text(json.dumps(corrected, indent=_cfg.JSON_INDENT), encoding="utf-8")
    log.info("Feedback applied to orphan_connections.json")


_HANDLERS = {
    "pass1": _fix_schema,
    "schema_validate": _fix_schema,
    "schema_extend": _fix_schema_extend,
    "normalize_names": _fix_normalization,
    "orphan_connect": _fix_orphan_connect,
    # TTL validation (Step 12b) is advisory per D25 — no LLM correction applied.
}
