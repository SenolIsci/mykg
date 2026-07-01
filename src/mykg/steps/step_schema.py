from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.exporter import export_ttl
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.schema_validator import validate_schema_ttl

log = get("mykg.steps.schema")


def _apply_llm_correction(ctx: PipelineContext, errors: list[dict]) -> None:
    """Ask the LLM to fix the schema and regenerate schema.ttl."""
    import mykg.feedback as feedback

    error_str = "; ".join(e["message"] for e in errors)
    feedback.apply("schema_validate", error_str, ctx)


def run_schema_validate(ctx: PipelineContext) -> None:
    schema_ttl_path = ctx.intermediate_dir / "schema.ttl"
    if not schema_ttl_path.exists():
        schema_json_path = ctx.intermediate_dir / "schema.json"
        if not schema_json_path.exists():
            raise FileNotFoundError(
                "Neither schema.ttl nor schema.json found in intermediate dir "
                "— cannot run schema validation"
            )
        schema = json.loads(schema_json_path.read_text(encoding="utf-8"))
        schema_ttl_path.write_text(export_ttl(schema, [], {}), encoding="utf-8")
        log.info("Step 3b — regenerated schema.ttl from schema.json")
    schema_ttl = schema_ttl_path.read_text(encoding="utf-8")

    # First attempt
    first = validate_schema_ttl(schema_ttl)
    if first.valid:
        log.info("Step 3b — schema.ttl valid")
    else:
        log.warning(
            "Step 3b — schema.ttl has %d error(s) — attempting LLM correction",
            len(first.errors),
        )

        # LLM correction attempt
        try:
            _apply_llm_correction(ctx, first.errors)
            llm_attempted = True
        except Exception as exc:
            log.warning("Step 3b — LLM correction failed: %s", exc)
            llm_attempted = False

        # Second attempt (re-read schema.ttl in case correction rewrote it)
        schema_ttl2 = (ctx.intermediate_dir / "schema.ttl").read_text(encoding="utf-8")
        second = validate_schema_ttl(schema_ttl2)

        record = {
            "first_attempt": {"errors": first.errors, "passed": first.valid},
            "llm_correction_attempted": llm_attempted,
            "second_attempt": {"errors": second.errors, "passed": second.valid},
        }
        (ctx.intermediate_dir / "schema_validation_errors.json").write_text(
            json.dumps(record, indent=_cfg.JSON_INDENT), encoding="utf-8"
        )

        if second.valid:
            log.info("Step 3b — schema.ttl valid after LLM correction")
        else:
            log.warning(
                "Step 3b — schema.ttl still has %d error(s) after correction — "
                "proceeding to human review gate (D17). "
                "Review intermediate/schema_validation_errors.json.",
                len(second.errors),
            )

    # Write sentinel file to mark that this step has run
    from datetime import datetime, timezone

    sentinel_content = datetime.now(timezone.utc).isoformat()
    (ctx.intermediate_dir / "schema_validate.done").write_text(sentinel_content, encoding="utf-8")


def run_human_review(ctx: PipelineContext) -> None:
    flag = ctx.intermediate_dir / "schema_approved.flag"
    if not ctx.review:
        flag.write_text("auto-approved", encoding="utf-8")
        log.info("Step 4 — review gate skipped (--review not set)")
        return
    if flag.exists():
        log.info("Step 4 — schema already approved")
        return
    raise RuntimeError(
        "run_human_review reached with ctx.review=True and no schema_approved.flag — "
        "the orchestrator should have halted before calling this function"
    )
