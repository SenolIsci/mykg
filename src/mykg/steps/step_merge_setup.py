from __future__ import annotations

import json

from mykg import config as _cfg
from mykg.logging import get
from mykg.merge_context import MergeContext
from mykg.merger import (
    build_merged_manifest,
    build_source_map,
    copy_session_into_merged,
    load_session,
)

log = get("mykg.steps.merge_setup")


def run_merge_setup(ctx: MergeContext) -> None:
    """Load both sessions, namespace and copy their shards, write source_map.json."""
    log.info(
        "merge_setup — loading sessions %s and %s",
        ctx.session_a_name,
        ctx.session_b_name,
    )
    ctx.session_a = load_session(ctx.session_a_name, ctx.sessions_root)
    ctx.session_b = load_session(ctx.session_b_name, ctx.sessions_root)

    copy_session_into_merged(ctx.session_a, ctx.intermediate_dir, "session_a")
    copy_session_into_merged(ctx.session_b, ctx.intermediate_dir, "session_b")

    merged_manifest = build_merged_manifest(ctx.session_a, ctx.session_b)
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps(merged_manifest, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )
    log.info(
        "merge_setup — file_manifest.json written (%d file(s))",
        len(merged_manifest),
    )

    ctx.source_map = build_source_map(ctx.session_a, ctx.session_b)
    (ctx.intermediate_dir / "source_map.json").write_text(
        json.dumps(ctx.source_map, indent=_cfg.JSON_INDENT), encoding="utf-8"
    )
    log.info(
        "merge_setup — source_map.json written (%d file entries)",
        len(ctx.source_map) - 1,  # exclude _meta key
    )
