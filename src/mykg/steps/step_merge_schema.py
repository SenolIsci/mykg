from __future__ import annotations

from mykg.exporter import export_ttl
from mykg.logging import get
from mykg.merge_context import MergeContext
from mykg.merger import harmonize_merged_schema, merge_session_schemas
from mykg.schema_history import TRIGGER_SESSION_MERGE, write_schema

log = get("mykg.steps.merge_schema")


def run_merge_schema(ctx: MergeContext) -> None:
    """Merge both session schemas and run LLM harmonization + quality review.

    Reads:   ctx.session_a.schema, ctx.session_b.schema (set by merge_setup)
    Writes:  intermediate/schema.json, intermediate/schema.ttl
    Populates: ctx.synonym_log
    """
    if ctx.session_a is None or ctx.session_b is None:
        raise RuntimeError(
            "merge_schema requires session_a and session_b on context — "
            "run merge_setup first"
        )

    locked_classes: dict = {}
    locked_properties: dict = {}
    if ctx.base_schema:
        locked_classes = ctx.base_schema.get("locked_classes", {})
        locked_properties = ctx.base_schema.get("locked_properties", {})

    merged_schema, synonym_log = merge_session_schemas(
        ctx.session_a.schema,
        ctx.session_b.schema,
        ctx.thesaurus,
        locked_classes,
        locked_properties,
    )
    merged_schema = harmonize_merged_schema(
        merged_schema,
        [ctx.session_a.schema, ctx.session_b.schema],
        ctx.adapter,
    )

    write_schema(merged_schema, ctx.intermediate_dir, TRIGGER_SESSION_MERGE)

    ttl = export_ttl(merged_schema, [], {})
    (ctx.intermediate_dir / "schema.ttl").write_text(ttl, encoding="utf-8")

    ctx.synonym_log = synonym_log
    log.info(
        "merge_schema — merged schema: %d concepts, %d properties",
        len(merged_schema.get("concepts", [])),
        len(merged_schema.get("properties", [])),
    )
