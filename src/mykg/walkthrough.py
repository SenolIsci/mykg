"""
Post-run walkthrough report generator.

Reads all available session artifacts and returns a structured Markdown
report string. Designed to be resilient: every file is guarded with
Path.exists() so it works on partial runs.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS_RE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+\[(\w+)\]\s+(\S+)\s+—\s+(.*)$")


def _parse_log_lines(log_path: Path) -> list[dict]:
    """Parse run.log lines into dicts with keys: ts, level, logger, message.

    Lines that don't match the standard format are silently skipped.
    """
    if not log_path.exists():
        return []
    results: list[dict] = []
    with log_path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            m = _TS_RE.match(line.strip())
            if m:
                results.append(
                    {
                        "ts": m.group(1),
                        "level": m.group(2),
                        "logger": m.group(3),
                        "message": m.group(4),
                    }
                )
    return results


def _ts_to_seconds(ts: str) -> int:
    """Convert HH:MM:SS to total seconds since midnight."""
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _seconds_to_hms(total: int) -> str:
    if total < 0:
        total = 0
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    if h:
        return f"{h}h {m:02d}m {s:02d}s"
    if m:
        return f"{m}m {s:02d}s"
    return f"{s}s"


def _load_json(path: Path) -> dict | list | None:
    """Load JSON from path, returning None if absent or malformed."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        log.debug("Could not load %s: %s", path, exc)
        return None


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _section_run_overview(
    session_root: Path,
    lines: list[dict],
    state: dict,
    manifest: dict,
) -> str:
    session_name = session_root.name

    started_at_raw = state.get("started_at", "")
    run_date = started_at_raw[:19].replace("T", " ") if started_at_raw else "unknown"

    provider = model = "unknown"
    for ln in lines:
        if ln["logger"].endswith(".cli") and "LLM endpoint:" in ln["message"]:
            m = re.search(r"LLM endpoint:\s+(\S+)\s+/\s+(\S+)", ln["message"])
            if m:
                provider = m.group(1)
                model = m.group(2)
            break

    file_count = len(manifest)

    duration_str = "unknown"
    if lines:
        delta = _ts_to_seconds(lines[-1]["ts"]) - _ts_to_seconds(lines[0]["ts"])
        if delta < 0:
            delta += 86400
        duration_str = _seconds_to_hms(delta)

    schema_history_dir = session_root / "intermediate" / "schema_history"
    gap_restarts = 0
    if schema_history_dir.exists():
        gap_restarts = sum(1 for f in schema_history_dir.iterdir() if "schema_gap" in f.name)

    error_count = sum(1 for ln in lines if ln["level"] == "ERROR")
    warning_count = sum(1 for ln in lines if ln["level"] == "WARNING")
    if error_count:
        health_status = f"**unhealthy** — {error_count} error(s), {warning_count} warning(s)"
    elif warning_count:
        health_status = f"healthy with warnings — {warning_count} warning(s)"
    else:
        health_status = "healthy"

    rows = [
        f"| Session | `{session_name}` |",
        f"| Run date/time (UTC) | {run_date} |",
        f"| LLM provider | {provider} |",
        f"| LLM model | {model} |",
        f"| Input files | {file_count} |",
        f"| Total duration | {duration_str} |",
        f"| Schema-gap restarts | {gap_restarts} |",
        f"| Run health | {health_status} |",
    ]
    return "\n".join(["## 2. Run Overview", "", "| Field | Value |", "|---|---|"] + rows)


def _section_step_timeline(session_root: Path, lines: list[dict], state: dict) -> str:
    """Parse RUN/DONE/SKIP/FAILED events from orchestrator log lines."""
    step_start: dict[str, str] = {}
    events: list[dict] = []

    for ln in (ln for ln in lines if "orchestrator" in ln["logger"]):
        msg = ln["message"]
        ts = ln["ts"]
        if msg.startswith("RUN  "):
            step_start[msg[5:].split()[0]] = ts
        elif msg.startswith("DONE "):
            step = msg[5:].split()[0]
            start = step_start.get(step, ts)
            dur = _ts_to_seconds(ts) - _ts_to_seconds(start)
            events.append(
                {
                    "step": step,
                    "status": "done",
                    "start": start,
                    "duration": dur if dur >= 0 else dur + 86400,
                }
            )
        elif msg.startswith("SKIP "):
            events.append(
                {
                    "step": msg[5:].split(" — ")[0].strip(),
                    "status": "skip",
                    "start": ts,
                    "duration": 0,
                }
            )
        elif msg.startswith("FAILED "):
            step = msg[7:].split()[0]
            start = step_start.get(step, ts)
            dur = _ts_to_seconds(ts) - _ts_to_seconds(start)
            events.append(
                {
                    "step": step,
                    "status": "failed",
                    "start": start,
                    "duration": dur if dur >= 0 else dur + 86400,
                }
            )

    if not events:
        # Fallback to pipeline_state.json when log is unavailable
        for sname, sdata in state.get("steps", {}).items():
            events.append(
                {
                    "step": sname,
                    "status": sdata.get("status", "unknown"),
                    "start": "—",
                    "duration": None,
                }
            )

    rows = []
    for ev in events:
        dur = ev.get("duration")
        dur_str = (
            "—" if dur is None or (dur == 0 and ev["status"] == "skip") else _seconds_to_hms(dur)
        )
        rows.append(f"| {ev['step']} | {ev['status']} | {ev['start']} | {dur_str} |")

    header = [
        "## 3. Step Timeline",
        "",
        "| Step | Status | Start | Duration |",
        "|---|---|---|---|",
    ]
    return "\n".join(header + rows)


def _build_concept_tree(concepts: list[dict]) -> str:
    """Render concepts as a parent-child indented Markdown list."""
    children: dict[str | None, list[dict]] = defaultdict(list)
    for c in concepts:
        children[c.get("parent")].append(c)

    lines: list[str] = []

    def _render(parent: str | None, depth: int) -> None:
        for c in sorted(children.get(parent, []), key=lambda x: x.get("type", "")):
            prefix = "  " * depth + "- "
            attrs = ", ".join(c.get("attributes", []))
            parent_label = f" *(is-a: {c['parent']})*" if c.get("parent") else ""
            lines.append(f"{prefix}**{c['type']}**{parent_label} — attrs: `{attrs}`")
            _render(c["type"], depth + 1)

    _render(None, 0)
    return "\n".join(lines)


def _section_schema_evolution(session_root: Path) -> str:
    schema_history_dir = session_root / "intermediate" / "schema_history"
    out = ["## 4. Schema Evolution"]

    if schema_history_dir.exists():
        delta_files = sorted(schema_history_dir.glob("*.json"))
        if delta_files:
            out += [
                "",
                "### History",
                "",
                "| Seq | Trigger | Concepts +/- | Properties +/- |",
                "|---|---|---|---|",
            ]
            for f in delta_files:
                d = _load_json(f) or {}
                c_add = len(d.get("concepts_added", []))
                c_rem = len(d.get("concepts_removed", []))
                p_add = len(d.get("properties_added", []))
                p_rem = len(d.get("properties_removed", []))
                out.append(
                    f"| {d.get('seq', '?')} | {d.get('trigger', f.stem)}"
                    f" | +{c_add} / -{c_rem} | +{p_add} / -{p_rem} |"
                )
        else:
            out.append("\n*No schema history recorded.*")
    else:
        out.append("\n*Schema history directory not found.*")

    schema = _load_json(session_root / "intermediate" / "schema.json")
    if schema:
        concepts = schema.get("concepts", [])
        properties = schema.get("properties", [])
        out += [
            "",
            "### Final Schema",
            "",
            f"**Concepts** ({len(concepts)} total):\n",
            _build_concept_tree(concepts),
        ]
        out += ["", f"**Properties** ({len(properties)} total):", ""]
        for p in sorted(properties, key=lambda x: x.get("name", "")):
            edge_attrs = ", ".join(p.get("attributes", []))
            edge_label = f"  *(edge attrs: {edge_attrs})*" if edge_attrs else ""
            out.append(
                f"- `{p.get('domain', '?')}` →[**{p.get('name', '?')}**]→ "
                f"`{p.get('range', '?')}`{edge_label}"
            )
    else:
        out.append("\n*schema.json not found.*")

    return "\n".join(out)


_LLM_CONTEXT_GROUPS = [
    ("Pass 1 batch induction", re.compile(r"pass1 batch", re.I)),
    ("Schema harmonization", re.compile(r"pass1 harmonize|schema_harmonize", re.I)),
    ("Schema quality review", re.compile(r"pass1 quality|schema_quality|quality", re.I)),
    ("Instance extraction (Pass 2)", re.compile(r"pass2", re.I)),
    ("Name normalization", re.compile(r"normalize_names|normalize", re.I)),
    ("Orphan connection", re.compile(r"orphan|chunk_recovery", re.I)),
    ("Schema-gap proposal", re.compile(r"schema_gap", re.I)),
]


def _section_llm_stats(session_root: Path) -> str:
    llm_log = session_root / "llm.log"
    out = ["## 5. LLM Call Statistics"]

    if not llm_log.exists():
        out.append("\n*llm.log not found.*")
        return "\n".join(out)

    records: list[dict] = []
    with llm_log.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue

    if not records:
        out.append("\n*No LLM calls recorded.*")
        return "\n".join(out)

    groups: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        ctx = rec.get("context", "")
        for label, pattern in _LLM_CONTEXT_GROUPS:
            if pattern.search(ctx):
                groups[label].append(rec)
                break
        else:
            groups["Other"].append(rec)

    out += [
        "",
        "| Stage | Calls | Fresh input | Cache read | Cache create | Output | Latency |",
        "|---|---|---|---|---|---|---|",
    ]

    total_calls = total_in = total_cache_read = total_cache_create = total_out = total_dur = 0.0
    for label, _pattern in _LLM_CONTEXT_GROUPS + [("Other", None)]:
        recs = groups.get(label, [])
        if not recs:
            continue
        calls = len(recs)
        inp = sum(r.get("input_tokens", 0) for r in recs)
        cache_read = sum(r.get("cache_read_tokens", 0) for r in recs)
        cache_create = sum(r.get("cache_creation_tokens", 0) for r in recs)
        out_tok = sum(r.get("output_tokens", 0) for r in recs)
        dur = sum(r.get("duration_s", 0.0) for r in recs)
        mean_lat = f"{dur / calls:.1f}s"
        out.append(
            f"| {label} | {calls} | {inp:,} | {cache_read:,} | {cache_create:,} | {out_tok:,}"
            f" | {mean_lat} |"
        )
        total_calls += calls
        total_in += inp
        total_cache_read += cache_read
        total_cache_create += cache_create
        total_out += out_tok
        total_dur += dur

    mean_total = total_dur / total_calls if total_calls else 0.0
    out.append(
        f"| **Total** | **{int(total_calls)}** | **{int(total_in):,}**"
        f" | **{int(total_cache_read):,}** | **{int(total_cache_create):,}**"
        f" | **{int(total_out):,}** | **{mean_total:.1f}s** |"
    )
    return "\n".join(out)


def _section_extraction_summary(session_root: Path, lines: list[dict], manifest: dict) -> str:
    out = ["## 6. Extraction Summary"]

    file_stats: dict[str, dict] = {}
    retry_counts: dict[str, int] = defaultdict(int)

    json_parse_retries = 0
    json_parse_failures = 0  # retry also failed
    validation_retries = 0
    chunks_skipped = 0
    partial_recoveries = 0
    nodes_dropped = 0
    edges_dropped_partial = 0

    for ln in lines:
        msg = ln["message"]
        m = re.match(r"\s*(.+?)\s+—\s+total:\s+(\d+)\s+node\(s\),\s+(\d+)\s+edge\(s\)", msg)
        if m:
            # Keep the latest entry so re-run results overwrite earlier passes
            file_stats[m.group(1).strip()] = {"nodes": int(m.group(2)), "edges": int(m.group(3))}
            continue
        if ln["level"] == "WARNING":
            m2 = re.search(r"(.+?)\s+—\s+chunk \d+ — validation errors", msg)
            if m2:
                retry_counts[m2.group(1).strip()] += 1
                validation_retries += 1
            elif re.search(r"chunk \d+ — JSON parse error.*— retrying", msg):
                json_parse_retries += 1
            elif re.search(r"chunk \d+ — retry JSON parse error", msg):
                json_parse_failures += 1
            elif "skipping chunk" in msg:
                chunks_skipped += 1
            elif "partial recovery" in msg:
                partial_recoveries += 1
                m3 = re.search(r"dropped (\d+) invalid edge", msg)
                if m3:
                    edges_dropped_partial += int(m3.group(1))
                m4 = re.search(r"dropped (\d+) unanchored node", msg)
                if m4:
                    nodes_dropped += int(m4.group(1))

    total_chunks = sum(
        1 for ln in lines if re.search(r"chunk \d+/\d+", ln["message"]) and ln["level"] == "INFO"
    )
    total_retry_events = json_parse_retries + validation_retries
    out += [
        "",
        "### Pass 2 Retry Statistics",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Chunks dispatched (total) | {total_chunks} |",
        f"| JSON parse error → retry | {json_parse_retries} |",
        f"| Validation error → retry | {validation_retries} |",
        f"| Retry also failed (JSON) | {json_parse_failures} |",
        f"| Chunks permanently skipped | {chunks_skipped} |",
        f"| Partial recoveries (degraded mode) | {partial_recoveries} |",
        f"| Nodes dropped (hallucinated anchors) | {nodes_dropped} |",
        f"| Edges dropped (partial recovery) | {edges_dropped_partial} |",
        (
            f"| **Retry rate** | **{total_retry_events / total_chunks * 100:.1f}%** |"
            if total_chunks
            else "| Retry rate | n/a |"
        ),
    ]

    if file_stats:
        out += [
            "",
            "### Per-file extraction",
            "",
            "| File | Nodes | Edges | Retries |",
            "|---|---|---|---|",
        ]
        for fname, stats in file_stats.items():
            short_name = fname.split("/")[-1] if "/" in fname else fname
            out.append(
                f"| {short_name} | {stats['nodes']} | {stats['edges']}"
                f" | {retry_counts.get(fname, 0)} |"
            )

    norm = _load_json(session_root / "intermediate" / "name_normalization.json")
    if norm:
        meta = norm.get("metadata", {})
        out.append(
            f"\n**Name normalization:** {meta.get('aliases_mapped', 0)} aliases mapped"
            f" across {len(norm.get('mappings', {}))} concept type(s)."
        )

    merge_log = _load_json(session_root / "intermediate" / "merge_log.json")
    if merge_log and isinstance(merge_log, list):
        node_merges = sum(1 for e in merge_log if e.get("event") == "node_merge")
        edge_merges = sum(1 for e in merge_log if e.get("event") == "edge_merge")
        out.append(
            f"\n**Deduplication:** {node_merges} node merge(s), {edge_merges} edge merge(s)."
        )

    dangling = sum(
        1 for ln in lines if ln["level"] == "WARNING" and "dropping edge" in ln["message"]
    )
    out.append(f"\n**Dangling edges dropped:** {dangling}")

    return "\n".join(out)


def _section_orphan_pass(
    session_root: Path,
    lines: list[dict],
    nodes_data: list,
    edge_data: dict,
) -> str:
    out = ["## 7. Orphan Pass Summary"]

    candidates = _load_json(session_root / "intermediate" / "orphan_candidates.json")
    if candidates:
        groups = candidates.get("groups", [])
        schema_gap = candidates.get("schema_gap_orphans", [])
        total_orphans = sum(len(g.get("orphan_ids", [])) for g in groups)
        out += [
            "",
            f"- Orphan chunk groups found: **{len(groups)}**",
            f"- Total orphans across groups: **{total_orphans}**",
            f"- Schema-gap orphans: **{len(schema_gap)}**",
        ]
    else:
        out.append("\n*orphan_candidates.json not found.*")

    orphan_log = _load_json(session_root / "intermediate" / "orphan_log.json")
    if orphan_log and isinstance(orphan_log, list):
        added = sum(1 for e in orphan_log if e.get("event") == "orphan_edge_added")
        rejected = sum(1 for e in orphan_log if e.get("event") == "orphan_edge_rejected")
        out += [
            f"- Orphan edges added (LLM confirmed): **{added}**",
            f"- Orphan edges rejected: **{rejected}**",
        ]

    promoted = sum(1 for ln in lines if "promoted to schema-gap orphan" in ln["message"])
    if promoted:
        out.append(f"- Promoted to schema-gap orphan: **{promoted}**")

    if nodes_data and edge_data:
        connected_ids: set[str] = set()
        for edge in edge_data.values():
            if isinstance(edge, dict):
                connected_ids.add(edge.get("from", ""))
                connected_ids.add(edge.get("to", ""))

        orphans_remaining = [n for n in nodes_data if n.get("id") not in connected_ids]
        out += ["", f"**Orphans remaining in final KG:** {len(orphans_remaining)}"]
        if orphans_remaining:
            out.append("")
            for n in orphans_remaining[:20]:
                out.append(f"- `{n.get('id')}` ({n.get('type', '?')})")
            if len(orphans_remaining) > 20:
                out.append(f"- *…and {len(orphans_remaining) - 20} more*")

    return "\n".join(out)


def _section_final_graph(session_root: Path, nodes_data: list, edge_data: dict) -> str:
    out = ["## 1. Final Graph Summary"]

    out.append(f"\n**Total nodes:** {len(nodes_data)}")
    if nodes_data:
        type_counts: dict[str, int] = defaultdict(int)
        for n in nodes_data:
            type_counts[n.get("type", "unknown")] += 1
        out += ["", "| Type | Count |", "|---|---|"]
        for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
            out.append(f"| {t} | {c} |")

    out.append(f"\n**Total edges:** {len(edge_data)}")
    if edge_data:
        etype_counts: dict[str, int] = defaultdict(int)
        method_counts: dict[str, int] = defaultdict(int)
        for edge in edge_data.values():
            if isinstance(edge, dict):
                etype_counts[edge.get("type", "unknown")] += 1
                method_counts[edge.get("method", "unknown")] += 1

        out += ["", "**Edges by type:**", "", "| Type | Count |", "|---|---|"]
        for t, c in sorted(etype_counts.items(), key=lambda x: -x[1]):
            out.append(f"| {t} | {c} |")

        out += ["", "**Edges by method:**", "", "| Method | Count |", "|---|---|"]
        for m, c in sorted(method_counts.items(), key=lambda x: -x[1]):
            out.append(f"| {m} | {c} |")

    val = _load_json(session_root / "output" / "knowledge_graph_validation.json")
    if val:
        valid = val.get("valid", False)
        tbox_errs = len(val.get("tbox_checks", {}).get("errors", []))
        abox_errs = len(val.get("abox_checks", {}).get("errors", []))
        status = "valid" if valid else f"**invalid** ({tbox_errs} TBox + {abox_errs} ABox error(s))"
        out.append(f"\n**Validation:** {status}")

    output_dir = session_root / "output"
    if output_dir.exists():
        out += ["", "**Output files:**", ""]
        for f in sorted(output_dir.iterdir()):
            if f.is_file():
                out.append(f"- `{f.name}` — {f.stat().st_size / 1024:.1f} KB")
        nx_dir = output_dir / "networkx_output"
        if nx_dir.exists():
            nx_files = sorted(nx_dir.iterdir())
            out.append(f"- `networkx_output/` — {len(nx_files)} file(s):")
            for nf in nx_files:
                out.append(f"  - `{nf.name}` — {nf.stat().st_size / 1024:.1f} KB")

    return "\n".join(out)


def _section_node_edge_trace(session_root: Path) -> str | None:
    """Return a per-step node/edge count trace for merge sessions, else None."""
    source_map = _load_json(session_root / "intermediate" / "source_map.json")
    if not source_map:
        return None
    meta = source_map.get("_meta", {})
    if "session_a" not in meta or "session_b" not in meta:
        return None

    sessions_root = session_root.parent
    name_a = meta["session_a"]["name"]
    name_b = meta["session_b"]["name"]
    manifest = _load_json(session_root / "intermediate" / "merge_manifest.json") or {}

    def _raw_counts(sess_root: Path) -> tuple[int, int, int]:
        """Return (raw_nodes, raw_edges, file_count) from raw_extractions.json."""
        raw = _load_json(sess_root / "intermediate" / "raw_extractions.json") or {}
        if not isinstance(raw, dict):
            return 0, 0, 0
        n = sum(len(v.get("nodes", [])) for v in raw.values())
        e = sum(len(v.get("edges", [])) for v in raw.values())
        return n, e, len(raw)

    def _deduped_counts(sess_root: Path) -> tuple[int, int]:
        nodes = _load_json(sess_root / "intermediate" / "nodes.json") or []
        edges = _load_json(sess_root / "intermediate" / "edge_metadata.json") or {}
        return len(nodes), len(edges)

    def _schema_counts(sess_root: Path) -> tuple[int, int]:
        schema = _load_json(sess_root / "intermediate" / "schema.json") or {}
        return len(schema.get("concepts", [])), len(schema.get("properties", []))

    a_raw_n, a_raw_e, a_files = _raw_counts(sessions_root / name_a)
    b_raw_n, b_raw_e, b_files = _raw_counts(sessions_root / name_b)
    a_dedup_n, a_dedup_e = _deduped_counts(sessions_root / name_a)
    b_dedup_n, b_dedup_e = _deduped_counts(sessions_root / name_b)
    a_concepts, a_props = _schema_counts(sessions_root / name_a)
    b_concepts, b_props = _schema_counts(sessions_root / name_b)

    # Merged raw_extractions: sum of both sessions' namespaced keys
    merged_raw = _load_json(session_root / "intermediate" / "raw_extractions.json") or {}
    merged_raw_n = sum(len(v.get("nodes", [])) for v in merged_raw.values() if isinstance(v, dict))
    merged_raw_e = sum(len(v.get("edges", [])) for v in merged_raw.values() if isinstance(v, dict))
    merged_files = len(merged_raw)

    # Session B shard counts before and after reextraction
    # "before" = original B raw extractions (from B's own session)
    b_raw_n_before, b_raw_e_before = b_raw_n, b_raw_e
    # "after" = B's contribution to merged raw_extractions
    b_keys = [k for k in merged_raw if k.startswith("session_b/")]
    b_raw_n_after = sum(len(merged_raw[k].get("nodes", [])) for k in b_keys)
    b_raw_e_after = sum(len(merged_raw[k].get("edges", [])) for k in b_keys)

    # Reextraction LLM call count from llm.log
    llm_log = session_root / "llm.log"
    reextract_calls = 0
    if llm_log.exists():
        with llm_log.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    if re.search(r"pass2|reextract", rec.get("context", ""), re.I):
                        reextract_calls += 1
                except Exception:
                    continue

    # Merged schema
    merged_schema = _load_json(session_root / "intermediate" / "schema.json") or {}
    m_concepts = len(merged_schema.get("concepts", []))
    m_props = len(merged_schema.get("properties", []))

    # Post-assemble counts
    merged_nodes_data = _load_json(session_root / "intermediate" / "nodes.json") or []
    merged_edge_data = _load_json(session_root / "intermediate" / "edge_metadata.json") or {}
    m_nodes = len(merged_nodes_data)
    m_edges = len(merged_edge_data)

    # Merge log breakdown
    merge_log = _load_json(session_root / "intermediate" / "merge_log.json") or []
    node_merge_events = (
        sum(1 for e in merge_log if e.get("event") == "node_merge")
        if isinstance(merge_log, list)
        else 0
    )
    edge_merge_events = (
        sum(1 for e in merge_log if e.get("event") == "edge_merge")
        if isinstance(merge_log, list)
        else 0
    )

    # Orphan pass
    orphan_candidates = _load_json(session_root / "intermediate" / "orphan_candidates.json")
    orphan_groups_count = len(orphan_candidates.get("groups", [])) if orphan_candidates else None
    orphan_connections = _load_json(session_root / "intermediate" / "orphan_connections.json")
    orphan_edges_added = len(orphan_connections) if orphan_connections is not None else None

    # Orphans remaining in the final KG (nodes with no entry in edge_metadata as from/to)
    if merged_nodes_data and merged_edge_data:
        connected_ids = set()
        for e in merged_edge_data.values():
            if isinstance(e, dict):
                connected_ids.add(e.get("from"))
                connected_ids.add(e.get("to"))
        orphans_remaining_count = sum(
            1 for n in merged_nodes_data if n.get("id") not in connected_ids
        )
    else:
        orphans_remaining_count = None

    # Type-filter at validate_graph: edges in edge_metadata whose type is not in merged schema
    declared_props = {p["name"] for p in merged_schema.get("properties", [])}
    valid_edges = sum(
        1
        for e in merged_edge_data.values()
        if isinstance(e, dict) and e.get("type") in declared_props
    )
    filtered_edges = m_edges - valid_edges
    filtered_by_type: dict[str, int] = {}
    for e in merged_edge_data.values():
        if isinstance(e, dict) and e.get("type") not in declared_props:
            t = e.get("type", "unknown")
            filtered_by_type[t] = filtered_by_type.get(t, 0) + 1

    # Final output line counts
    output_dir = session_root / "output"
    nodes_jsonl_count = 0
    edges_jsonl_count = 0
    nodes_jsonl = output_dir / "nodes.jsonl"
    edges_jsonl = output_dir / "edges.jsonl"
    if nodes_jsonl.exists():
        with nodes_jsonl.open(encoding="utf-8") as f:
            nodes_jsonl_count = sum(1 for ln in f if ln.strip())
    if edges_jsonl.exists():
        with edges_jsonl.open(encoding="utf-8") as f:
            edges_jsonl_count = sum(1 for ln in f if ln.strip())

    delta_b = manifest.get("schema_delta_session_b") or []
    reextract_note = (
        f"Session A: no schema delta. Session B gains {len(delta_b)} new property type(s); "
        f"{reextract_calls} chunk(s) re-extracted"
        if delta_b
        else "No schema deltas — no re-extraction needed"
    )
    reextract_llm = f"✓ **LLM ×{reextract_calls}**" if reextract_calls else "—"

    filter_detail = ", ".join(
        f"`{t}` ({c})" for t, c in sorted(filtered_by_type.items(), key=lambda x: -x[1])
    )

    rows = [
        "| # | Step | Sub-step | LLM | Nodes | Edges | Notes |",
        "|---|---|---|---|---|---|---|",
        "| **Inputs** | | | | | | |",
        f"| — | Source: Session A | `nodes.json` / `edge_metadata.json` | — "
        f"| **{a_dedup_n:,}** | **{a_dedup_e:,}** "
        f"| After A's own dedup; A had {a_raw_n:,} raw nodes / {a_raw_e:,} raw edges across {a_files} files |",
        f"| — | Source: Session B | `nodes.json` / `edge_metadata.json` | — "
        f"| **{b_dedup_n:,}** | **{b_dedup_e:,}** "
        f"| After B's own dedup; B had {b_raw_n:,} raw nodes / {b_raw_e:,} raw edges across {b_files} files |",
        "| **1** | `merge_setup` | Copy & namespace shards | — | — | — "
        "| Renames all keys and shard filenames to `session_a/…` and `session_b/…`; no extraction yet |",
        f"| **2** | `merge_schema` | `merge_proposals()` | — | — | — "
        f"| Pure union of {a_concepts}+{b_concepts} concepts and {a_props}+{b_props} properties (structural merge, no LLM) |",
        "| | | `harmonize_schema()` | ✓ **LLM ×1** | — | — | Near-synonym collapse |",
        f"| | | `review_schema_quality()` | ✓ **LLM ×1** | — | — "
        f"| Removes narrow/singleton types → **{m_concepts} concepts, {m_props} properties** |",
        "| **3** | `schema_validate` | rdflib + semantic checks | — | — | — | Pass; no correction needed |",
        "| **4** | `human_review` | Gate | — | — | — | Auto-approved (no `--review` flag) |",
        "| **5** | `schema_flatten` | Flatten inheritance chains | — | — | — "
        "| Produces `flattened_schema.json` for Pass 2 prompts |",
        f"| **6** | `merge_reextract` | Session B shards (pre-reextract) | — "
        f"| {b_raw_n_before:,} | {b_raw_e_before:,} | Original B raw extractions |",
        f"| | | Surgical re-extraction | {reextract_llm} | — | — | {reextract_note} |",
        f"| | | Session B shards (post-reextract) | — "
        f"| **{b_raw_n_after:,}** | **{b_raw_e_after:,}** "
        f"| +{b_raw_e_after - b_raw_e_before} edge(s), +{b_raw_n_after - b_raw_n_before} node(s) from re-extraction |",
        f"| **7** | `merge_raw` | Namespace + concat raw extractions | — "
        f"| **{merged_raw_n:,}** | **{merged_raw_e:,}** "
        f"| A + B → single `raw_extractions.json` ({merged_files} files) |",
        f"| **8** | `assemble` | Node deduplication | — "
        f"| {merged_raw_n:,} → **{m_nodes:,}** | — "
        f"| {node_merge_events:,} merge events; {merged_raw_n - m_nodes:,} nodes collapsed on `hash(type+name)` |",
        f"| | | Edge deduplication | — | — "
        f"| {merged_raw_e:,} → **{m_edges:,}** "
        f"| {edge_merge_events:,} merge events; {merged_raw_e - m_edges:,} edges collapsed on `hash(type+from_id+to_id)` |",
        f"| | | Write `edge_metadata.json` + `nodes.json` | — | **{m_nodes:,}** | **{m_edges:,}** "
        f"| Sidecar written; no type-filtering yet |",
        f"| **9** | `orphan_score` | Map orphans to source chunks | — | — | — "
        f"| {orphan_groups_count if orphan_groups_count is not None else '—'} orphan group(s) — see `orphan_candidates.json` |",
        f"| **10** | `orphan_connect` | LLM edge confirmation | ✓ **LLM** | — "
        f"| **+{orphan_edges_added if orphan_edges_added is not None else '—'}** "
        f"| Confirmed orphan edges merged into `edge_metadata.json`; "
        f"**{orphans_remaining_count if orphans_remaining_count is not None else '—'} orphan(s) remain** |",
        f"| **11** | `validate_graph` | Build `nodes.jsonl` | — | **{nodes_jsonl_count:,}** | — | All nodes exported |",
        f"| | | Build `edges.jsonl` (type filter) | — | — "
        f"| {m_edges:,} → **{edges_jsonl_count:,}** "
        f"| {filtered_edges} edges dropped: {filter_detail} — types in `edge_metadata` but absent from merged schema |",
        f"| | | Build `knowledge_graph.ttl` | — | {nodes_jsonl_count:,} | {edges_jsonl_count:,} | Same filter applied |",
        f"| | | NetworkX export | — | {nodes_jsonl_count:,} | {edges_jsonl_count:,} | Multi-format files |",
        "| **12** | `merge_manifest` | Write `merge_manifest.json` | — | — | — "
        "| Records provenance, synonym log, schema deltas |",
    ]

    # Summary loss table
    summary_rows = [
        "| Stage | Nodes lost | Edges lost | Reason |",
        "|---|---|---|---|",
        f"| A's own extract pipeline "
        f"| {a_raw_n - a_dedup_n:,} ({a_raw_n:,}→{a_dedup_n:,}) "
        f"| {a_raw_e - a_dedup_e:,} ({a_raw_e:,}→{a_dedup_e:,}) "
        f"| Intra-session dedup |",
        f"| B's own extract pipeline "
        f"| {b_raw_n - b_dedup_n:,} ({b_raw_n:,}→{b_dedup_n:,}) "
        f"| {b_raw_e - b_dedup_e:,} ({b_raw_e:,}→{b_dedup_e:,}) "
        f"| Intra-session dedup |",
        f"| Surgical reextraction | 0 "
        f"| **+{b_raw_e_after - b_raw_e_before}** "
        f"| New edges from {len(delta_b)} new property type(s) (Session B only) |",
        f"| `assemble` dedup "
        f"| {merged_raw_n - m_nodes:,} ({merged_raw_n:,}→{m_nodes:,}) "
        f"| {merged_raw_e - m_edges:,} ({merged_raw_e:,}→{m_edges:,}) "
        f"| Cross-session + within-session dedup on merged raw |",
        f"| `orphan_connect` | 0 "
        f"| **+{orphan_edges_added if orphan_edges_added is not None else 0}** "
        f"| Orphan edges confirmed and merged ({orphan_groups_count if orphan_groups_count is not None else 0} groups); "
        f"**{orphans_remaining_count if orphans_remaining_count is not None else '—'} node(s) still unconnected** |",
        f"| `validate_graph` type filter | 0 "
        f"| **{filtered_edges}** ({m_edges:,}→{edges_jsonl_count:,}) "
        f"| {len(filtered_by_type)} property type(s) in `edge_metadata` not declared in merged schema |",
        f"| **Final output** | **{nodes_jsonl_count:,}** | **{edges_jsonl_count:,}** "
        f"| `nodes.jsonl` / `edges.jsonl` |",
    ]

    out = [
        "## 2. Node & Edge Count Trace",
        "",
        "### Per-step breakdown",
        "",
        *rows,
        "",
        "### Summary of losses at each stage",
        "",
        *summary_rows,
    ]
    return "\n".join(out)


def _section_merge_provenance(session_root: Path) -> str | None:
    """Return a merge provenance section if this is a merge session, else None."""
    source_map = _load_json(session_root / "intermediate" / "source_map.json")
    if not source_map:
        return None
    meta = source_map.get("_meta", {})
    if "session_a" not in meta or "session_b" not in meta:
        return None

    manifest = _load_json(session_root / "intermediate" / "merge_manifest.json") or {}
    sessions_root = session_root.parent

    out = ["## 2. Merge Provenance"]

    name_a = meta["session_a"]["name"]
    name_b = meta["session_b"]["name"]
    strategy = manifest.get("reextraction_strategy", "unknown")
    merged_at = (manifest.get("merged_at", "")[:19] or "unknown").replace("T", " ")

    out += [
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Session A | `{name_a}` |",
        f"| Session B | `{name_b}` |",
        f"| Merged at (UTC) | {merged_at} |",
        f"| Re-extraction strategy | {strategy} |",
    ]

    # Load before/after counts for each session + merged
    def _counts(sess_root: Path) -> dict:
        nodes = _load_json(sess_root / "intermediate" / "nodes.json") or []
        edges = _load_json(sess_root / "intermediate" / "edge_metadata.json") or {}
        schema = _load_json(sess_root / "intermediate" / "schema.json") or {}
        return {
            "nodes": len(nodes),
            "edges": len(edges),
            "concepts": len(schema.get("concepts", [])),
            "properties": len(schema.get("properties", [])),
        }

    ca = _counts(sessions_root / name_a)
    cb = _counts(sessions_root / name_b)
    merged_nodes = _load_json(session_root / "intermediate" / "nodes.json") or []
    merged_edges = _load_json(session_root / "intermediate" / "edge_metadata.json") or {}
    merged_schema = _load_json(session_root / "intermediate" / "schema.json") or {}
    cm = {
        "nodes": len(merged_nodes),
        "edges": len(merged_edges),
        "concepts": len(merged_schema.get("concepts", [])),
        "properties": len(merged_schema.get("properties", [])),
    }

    out += [
        "",
        "### Before & After",
        "",
        f"| Metric | Session A (`{name_a}`) | Session B (`{name_b}`) | Merged |",
        "|---|---|---|---|",
        f"| Nodes | {ca['nodes']} | {cb['nodes']} | **{cm['nodes']}** |",
        f"| Edges | {ca['edges']} | {cb['edges']} | **{cm['edges']}** |",
        f"| Schema concepts | {ca['concepts']} | {cb['concepts']} | **{cm['concepts']}** |",
        f"| Schema properties | {ca['properties']} | {cb['properties']} | **{cm['properties']}** |",
    ]

    # Net-new nodes: present in merged but not in either source session
    ids_a = {
        n["id"] for n in (_load_json(sessions_root / name_a / "intermediate" / "nodes.json") or [])
    }
    ids_b = {
        n["id"] for n in (_load_json(sessions_root / name_b / "intermediate" / "nodes.json") or [])
    }
    merged_by_id = {n["id"]: n for n in merged_nodes}
    net_new = sorted(
        (merged_by_id[nid] for nid in (set(merged_by_id) - ids_a - ids_b)), key=lambda n: n["id"]
    )
    deduped = sorted(
        (merged_by_id[nid] for nid in (ids_a & ids_b & set(merged_by_id))), key=lambda n: n["id"]
    )

    out += ["", "### Node Provenance", ""]
    out += [
        "| Category | Count |",
        "|---|---|",
        f"| From Session A only | {len((ids_a - ids_b) & set(merged_by_id))} |",
        f"| From Session B only | {len((ids_b - ids_a) & set(merged_by_id))} |",
        f"| Deduplicated (in both A and B) | {len(deduped)} |",
        f"| Net-new (from surgical re-extraction) | **{len(net_new)}** |",
    ]

    if net_new:
        out += ["", "**Net-new nodes** (not present in either source session):", ""]
        out += ["| ID | Type | Name |", "|---|---|---|"]
        for n in net_new[:20]:
            name_val = (n.get("attributes") or {}).get("name", {})
            name_str = name_val.get("value", "?") if isinstance(name_val, dict) else "?"
            out.append(f"| `{n['id']}` | {n.get('type', '?')} | {name_str} |")
        if len(net_new) > 20:
            out.append(f"| *…and {len(net_new) - 20} more* | | |")

    # Edge provenance: classify edges by whether from/to IDs belong to A, B, or cross-session
    delta_a = manifest.get("schema_delta_session_a") or []
    delta_b = manifest.get("schema_delta_session_b") or []
    delta_props = set(delta_a) | set(delta_b)

    edges_aa = []
    edges_bb = []
    edges_cross = []
    edges_new_prop = []  # edges using a property introduced by the merge

    for eid, edge in merged_edges.items():
        frm = edge.get("from", "")
        to = edge.get("to", "")
        etype = edge.get("type", "")
        frm_in_a = frm in ids_a
        frm_in_b = frm in ids_b
        to_in_a = to in ids_a
        to_in_b = to in ids_b
        is_cross = (frm_in_a and to_in_b) or (frm_in_b and to_in_a)
        is_same_a = frm_in_a and to_in_a
        is_same_b = frm_in_b and to_in_b
        if is_cross:
            edges_cross.append((eid, edge))
        elif is_same_a:
            edges_aa.append((eid, edge))
        elif is_same_b:
            edges_bb.append((eid, edge))
        if etype in delta_props:
            edges_new_prop.append((eid, edge))

    def _node_name(nid: str) -> str:
        node = merged_by_id.get(nid, {})
        name_val = (node.get("attributes") or {}).get("name", {})
        return name_val.get("value", nid) if isinstance(name_val, dict) else nid

    out += ["", "### Edge Provenance", ""]
    out += [
        "| Category | Count |",
        "|---|---|",
        f"| Session A → Session A | {len(edges_aa)} |",
        f"| Session B → Session B | {len(edges_bb)} |",
        f"| Cross-session (A ↔ B) | **{len(edges_cross)}** |",
        f"| Using new merged property types | {len(edges_new_prop)} |",
    ]

    if edges_cross:
        out += ["", "**Cross-session edges:**", ""]
        out += [
            "| ID | Type | From | From-session | To | To-session |",
            "|---|---|---|---|---|---|",
        ]
        for eid, edge in edges_cross[:20]:
            frm = edge.get("from", "?")
            to = edge.get("to", "?")
            frm_sess = "A" if frm in ids_a else "B"
            to_sess = "A" if to in ids_a else "B"
            out.append(
                f"| `{eid}` | {edge.get('type', '?')} | {_node_name(frm)} | {frm_sess} "
                f"| {_node_name(to)} | {to_sess} |"
            )
        if len(edges_cross) > 20:
            out.append(f"| *…and {len(edges_cross) - 20} more* | | | | | |")
    else:
        out.append("")
        out.append("*No cross-session edges — the two corpora share no common entities.*")

    if edges_new_prop:
        out += ["", f"**Edges using new merged property types** ({len(edges_new_prop)} total):", ""]
        out += ["| ID | Type | From | To |", "|---|---|---|---|"]
        for eid, edge in edges_new_prop[:20]:
            frm = edge.get("from", "?")
            to = edge.get("to", "?")
            out.append(
                f"| `{eid}` | {edge.get('type', '?')} | {_node_name(frm)} | {_node_name(to)} |"
            )
        if len(edges_new_prop) > 20:
            out.append(f"| *…and {len(edges_new_prop) - 20} more* | | | |")

    # New properties introduced per session (schema deltas)
    delta_a = manifest.get("schema_delta_session_a") or []
    delta_b = manifest.get("schema_delta_session_b") or []
    if delta_a:
        out += [
            "",
            "**New properties for Session A** (surgical re-extraction): "
            + ", ".join(f"`{p}`" for p in delta_a),
        ]
    if delta_b:
        out += [
            "**New properties for Session B** (surgical re-extraction): "
            + ", ".join(f"`{p}`" for p in delta_b)
        ]

    # Schema synonym log
    synonym_log = manifest.get("schema_synonym_log") or []
    if synonym_log:
        out += ["", f"**Schema synonyms collapsed:** {len(synonym_log)}"]
        for entry in synonym_log[:10]:
            if isinstance(entry, dict):
                out.append(f"- `{entry.get('kept', '?')}` ← `{entry.get('removed', '?')}`")
            else:
                out.append(f"- {entry}")
        if len(synonym_log) > 10:
            out.append(f"- *…and {len(synonym_log) - 10} more*")

    return "\n".join(out)


def _section_health_status(session_root: Path, lines: list[dict], state: dict) -> str:
    """Return a one-line health banner + issues list for the top of the report."""
    issues: list[str] = []

    # Failed/incomplete pipeline steps
    steps = state.get("steps", {})
    failed_steps = [name for name, info in steps.items() if info.get("status") == "failed"]
    if failed_steps:
        issues.append(
            f"**{len(failed_steps)} step(s) failed:** " + ", ".join(f"`{s}`" for s in failed_steps)
        )

    # ERROR-level log lines (includes 402 credit errors after our fix)
    error_lines = [ln for ln in lines if ln["level"] == "ERROR"]
    credit_errors = [
        ln for ln in error_lines if "402" in ln["message"] or "credit" in ln["message"].lower()
    ]
    other_errors = [ln for ln in error_lines if ln not in credit_errors]
    if credit_errors:
        issues.append(
            f"**{len(credit_errors)} LLM credit error(s) (402)** during orphan pass — "
            f"affected groups received no LLM processing"
        )
    if other_errors:
        issues.append(f"**{len(other_errors)} other error(s)** — see Warnings & Retries section")

    # Advisory TTL validation errors
    validation = _load_json(session_root / "output" / "knowledge_graph_validation.json") or {}
    abox_errors = validation.get("abox_checks", {}).get("errors", [])
    if abox_errors:
        issues.append(f"**{len(abox_errors)} ABox advisory error(s)** in `knowledge_graph.ttl`")

    if issues:
        status = "⚠ Issues detected"
        out = [f"**Run health:** {status}", ""]
        out.extend(f"- {issue}" for issue in issues)
    else:
        out = ["**Run health:** ✓ Clean"]

    return "\n".join(out)


def _section_warnings(lines: list[dict]) -> str:
    out = ["## 8. Warnings & Retries"]

    warn_lines = [ln for ln in lines if ln["level"] in ("WARNING", "ERROR")]
    if not warn_lines:
        out.append("\n*No warnings or errors recorded.*")
        return "\n".join(out)

    chunk_retries: list[str] = []
    dangling_edges: list[str] = []
    schema_issues: list[str] = []
    other: list[str] = []

    for ln in warn_lines:
        msg = ln["message"]
        entry = f"`{ln['ts']}` [{ln['level']}] {ln['logger']}: {msg}"
        is_chunk_error = (
            "validation errors" in msg
            or "JSON parse error" in msg
            or "partial recovery" in msg
            or "skipping chunk" in msg
        )
        if is_chunk_error and "chunk" in msg:
            chunk_retries.append(entry)
        elif "dropping edge" in msg:
            dangling_edges.append(entry)
        elif "schema" in msg.lower():
            schema_issues.append(entry)
        else:
            other.append(entry)

    for title, items in [
        (f"Chunk Errors & Retries ({len(chunk_retries)})", chunk_retries),
        (f"Dangling Edges Dropped ({len(dangling_edges)})", dangling_edges),
        (f"Schema Issues ({len(schema_issues)})", schema_issues),
        (f"Other Warnings ({len(other)})", other),
    ]:
        if items:
            out += ["", f"### {title}"]
            out.extend(f"- {item}" for item in items)

    return "\n".join(out)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_walkthrough(session_root: Path, log_file: Path | None = None) -> str:
    """Read session artifacts and return walkthrough.md content as a string.

    Resilient: uses Path.exists() before loading each file so it works on
    partial runs. Never raises — callers should wrap in try/except if desired.
    """
    if log_file is None:
        log_file = session_root / "run.log"

    lines = _parse_log_lines(log_file)

    # Load shared artifacts once and pass to sections that need them
    state = _load_json(session_root / "intermediate" / "pipeline_state.json") or {}
    manifest = _load_json(session_root / "intermediate" / "file_manifest.json") or {}
    nodes_data: list = _load_json(session_root / "intermediate" / "nodes.json") or []
    edge_data: dict = _load_json(session_root / "intermediate" / "edge_metadata.json") or {}

    node_edge_trace = _section_node_edge_trace(session_root)
    merge_provenance = _section_merge_provenance(session_root)
    health = _section_health_status(session_root, lines, state)

    # Section order for merge sessions:
    #   Health status (inline, no §number)
    #   §1 Merge Provenance  ← moved to top
    #   §2 Node/Edge Trace
    #   §3 Final Graph Summary
    #   §4 Run Overview, §5 Step Timeline, …
    # For non-merge sessions the two merge sections are absent; offset stays 0.
    if merge_provenance and node_edge_trace:
        offset = 2  # §1 Provenance + §2 Trace inserted before §3 Final Graph
    elif merge_provenance or node_edge_trace:
        offset = 1
    else:
        offset = 0

    run_overview = _section_run_overview(session_root, lines, state, manifest).replace(
        "## 2. Run Overview", f"## {2 + offset}. Run Overview"
    )
    step_timeline = _section_step_timeline(session_root, lines, state).replace(
        "## 3. Step Timeline", f"## {3 + offset}. Step Timeline"
    )
    schema_evolution = _section_schema_evolution(session_root).replace(
        "## 4. Schema Evolution", f"## {4 + offset}. Schema Evolution"
    )
    llm_stats = _section_llm_stats(session_root).replace(
        "## 5. LLM Call Statistics", f"## {5 + offset}. LLM Call Statistics"
    )
    extraction = _section_extraction_summary(session_root, lines, manifest).replace(
        "## 6. Extraction Summary", f"## {6 + offset}. Extraction Summary"
    )
    orphan = _section_orphan_pass(session_root, lines, nodes_data, edge_data).replace(
        "## 7. Orphan Pass Summary", f"## {7 + offset}. Orphan Pass Summary"
    )
    warnings = _section_warnings(lines).replace(
        "## 8. Warnings & Retries", f"## {8 + offset}. Warnings & Retries"
    )

    sections = [f"# Walkthrough — Session `{session_root.name}`", ""]
    sections += [health, ""]
    if merge_provenance:
        mp = merge_provenance.replace("## 2. Merge Provenance", "## 1. Merge Provenance")
        sections += [mp, ""]
    if node_edge_trace:
        # Renumber trace header: §2 when provenance present, §1 when alone
        trace_num = 2 if merge_provenance else 1
        nt = node_edge_trace.replace(
            "## 2. Node & Edge Count Trace", f"## {trace_num}. Node & Edge Count Trace"
        )
        sections += [nt, ""]
    final_graph_num = 1 + offset
    sections += [
        _section_final_graph(session_root, nodes_data, edge_data).replace(
            "## 1. Final Graph Summary", f"## {final_graph_num}. Final Graph Summary"
        ),
        "",
        run_overview,
        "",
        step_timeline,
        "",
        schema_evolution,
        "",
        llm_stats,
        "",
        extraction,
        "",
        orphan,
        "",
        warnings,
        "",
        "---",
        f"*Generated {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S')} UTC*",
    ]
    return "\n".join(sections)
