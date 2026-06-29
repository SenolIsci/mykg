"""schema_history — write schema.json and append a delta entry to schema_history/.

Every place that mutates schema.json calls write_schema() instead of writing
directly. This gives a full audit trail of what changed, when, and why.

Delta file format (schema_history/<seq>_<trigger>.json):
{
    "seq":        1,
    "trigger":    "pass1_merge",          # see TRIGGERS below
    "timestamp":  "2026-05-19T10:23:45Z",
    "concepts_added":   ["MilitaryUnit"],
    "concepts_removed": [],
    "properties_added": ["commands"],
    "properties_removed": [],
    "concepts_total":   10,
    "properties_total": 12
}

TRIGGERS
    pass1_merge         — initial schema produced by Pass 1 merge step
    schema_validate     — LLM correction after RDFS validation failure
    schema_gap          — new properties added by orphan schema-gap loop
    schema_gap_correct  — LLM correction after schema-gap proposal introduced invalid RDFS
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from mykg import config as _cfg
from mykg.logging import get

log = get("mykg.schema_history")

SCHEMA_HISTORY_DIR = "schema_history"

TRIGGER_PASS1_MERGE = "pass1_merge"
TRIGGER_SCHEMA_HARMONIZE = "schema_harmonize"
TRIGGER_SCHEMA_VALIDATE = "schema_validate"
TRIGGER_SCHEMA_GAP = "schema_gap"
TRIGGER_SCHEMA_GAP_CORRECT = "schema_gap_correct"
TRIGGER_SCHEMA_QUALITY = "schema_quality"
TRIGGER_SESSION_MERGE = "session_merge"
TRIGGER_FREEZE_SCHEMA = "freeze_schema"


def write_schema(
    schema: dict,
    intermediate_dir: Path,
    trigger: str,
    *,
    extra: dict | None = None,
) -> None:
    """Write schema.json and append a delta entry to schema_history/.

    Reads the previous schema.json (if any) to compute the delta.
    extra: optional dict merged into the delta entry (e.g. new property names).
    """
    schema_path = intermediate_dir / "schema.json"

    # Compute delta vs previous schema on disk.
    prev: dict = {}
    if schema_path.exists():
        try:
            prev = json.loads(schema_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    prev_concepts = {c["type"] for c in prev.get("concepts", [])}
    prev_props = {p["name"] for p in prev.get("properties", [])}
    curr_concepts = {c["type"] for c in schema.get("concepts", [])}
    curr_props = {p["name"] for p in schema.get("properties", [])}

    concepts_added = sorted(curr_concepts - prev_concepts)
    concepts_removed = sorted(prev_concepts - curr_concepts)
    properties_added = sorted(curr_props - prev_props)
    properties_removed = sorted(prev_props - curr_props)

    # Write schema.json.
    schema_path.write_text(json.dumps(schema, indent=_cfg.JSON_INDENT))

    # Write delta entry.
    history_dir = intermediate_dir / SCHEMA_HISTORY_DIR
    history_dir.mkdir(exist_ok=True)

    # Sequence number = number of existing delta files + 1.
    existing = sorted(history_dir.glob("*.json"))
    seq = len(existing) + 1

    delta: dict = {
        "seq": seq,
        "trigger": trigger,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "concepts_added": concepts_added,
        "concepts_removed": concepts_removed,
        "properties_added": properties_added,
        "properties_removed": properties_removed,
        "concepts_total": len(curr_concepts),
        "properties_total": len(curr_props),
    }
    if extra:
        delta.update(extra)

    delta_path = history_dir / f"{seq:04d}_{trigger}.json"
    delta_path.write_text(json.dumps(delta, indent=_cfg.JSON_INDENT))

    log.debug(
        "schema_history — delta %04d (%s): +%d concept(s), +%d property(ies)",
        seq,
        trigger,
        len(concepts_added),
        len(properties_added),
    )
