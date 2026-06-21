#!/usr/bin/env python3
"""Live end-to-end test of mykg `--append-with-grow-schema` against OpenRouter.

Runs two real pipeline stages and emits a reusable, idempotent report:

  STAGE 1  initial `extract-graph <input_dir>` (auto-creates a session)
  STAGE 2  copy <new_file> into <input_dir>, then
           `extract-graph <input_dir> --append-with-grow-schema --session <s1>`

It reports the stage-2 schema delta, back-fill evidence (whether the OLD
file's shard was rewritten), and node/edge changes.

Key behaviours / safety:
  * There is NO `--profile` flag on extract-graph. The active profile is the
    top-level `profile:` key in mykg_config.yaml. This script rewrites that
    one line to the chosen profile (exactly like `mykg init`), and ALWAYS
    restores the original value via try/finally + atexit.
  * Must be run from the repo root so `.env.mykg` (OPENROUTER_API_KEY) is
    picked up by the CLI's load_dotenv(".env.mykg").
  * An EMPTY schema delta is a VALID success: grow mode correctly collapses
    to a plain append when nothing new is induced.
  * Exits non-zero only on real failure (CLI non-zero exit, missing outputs,
    0 or >1 new sessions in stage 1).

Usage:
    uv run python scripts/live_test_grow_schema.py
    uv run python scripts/live_test_grow_schema.py --profile openrouter-free \
        --input-dir _input_files --new-file tech_stack.md --config mykg_config.yaml
"""
from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo root = parent of this script's directory (scripts/ lives at the root).
REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
def _log(msg: str) -> None:
    print(f"[live-test] {msg}", flush=True)


def _sha256_path(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _wc_l(path: Path) -> int:
    """Count non-empty lines in a JSONL file (0 if missing)."""
    if not path.exists():
        return 0
    n = 0
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                n += 1
    return n


def _load_schema(schema_path: Path) -> dict:
    if not schema_path.exists():
        return {"concepts": [], "properties": []}
    with schema_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _concept_names(schema: dict) -> set[str]:
    return {c.get("type", "") for c in schema.get("concepts", []) if c.get("type")}


def _property_names(schema: dict) -> set[str]:
    return {p.get("name", "") for p in schema.get("properties", []) if p.get("name")}


def _session_names(sessions_root: Path) -> set[str]:
    if not sessions_root.exists():
        return set()
    return {p.name for p in sessions_root.iterdir() if p.is_dir()}


def _run_cli(args: list[str]) -> int:
    """Run `uv run mykg ...` from the repo root, streaming output live."""
    cmd = ["uv", "run", "mykg", *args]
    _log("$ " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT))
    return proc.returncode


def _tail_run_log(session_root: Path, n: int = 60) -> str:
    log_path = session_root / "run.log"
    if not log_path.exists():
        return f"(no run.log at {log_path})"
    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-n:])


# --------------------------------------------------------------------------- #
# Profile rewrite (restored via try/finally AND atexit)
# --------------------------------------------------------------------------- #
class ProfileGuard:
    """Rewrite the top-level `profile:` line; guarantee restoration."""

    def __init__(self, config_path: Path, new_profile: str) -> None:
        self.config_path = config_path
        self.new_profile = new_profile
        self.original_text = config_path.read_text(encoding="utf-8")
        m = re.search(r"^profile:[ \t]*(\S+)", self.original_text, flags=re.M)
        if not m:
            raise RuntimeError(f"No top-level `profile:` line found in {config_path}")
        self.original_profile = m.group(1)
        self._restored = False

    def apply(self) -> None:
        new_text = re.sub(
            r"^profile:.*$",
            f"profile: {self.new_profile}",
            self.original_text,
            count=1,
            flags=re.M,
        )
        self.config_path.write_text(new_text, encoding="utf-8")
        _log(f"profile: {self.original_profile} -> {self.new_profile} (in {self.config_path.name})")

    def restore(self) -> None:
        if self._restored:
            return
        # Restore the ORIGINAL full text so no incidental edits leak.
        self.config_path.write_text(self.original_text, encoding="utf-8")
        self._restored = True
        _log(f"profile restored to: {self.original_profile}")


# --------------------------------------------------------------------------- #
# Resolve the configured model slug for the chosen profile (best-effort).
# --------------------------------------------------------------------------- #
def _resolve_model(config_path: Path, profile: str) -> str:
    """Parse the `model:` under the given profile block. Best-effort, no YAML dep."""
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return "(unknown)"
    lines = text.splitlines()
    in_profile = False
    profile_indent = None
    for line in lines:
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if re.match(rf"^{re.escape(profile)}:\s*$", stripped):
            in_profile = True
            profile_indent = indent
            continue
        if in_profile:
            # A line at the same indent as the profile key (and not blank/comment)
            # ends the profile block.
            if stripped and not stripped.startswith("#") and indent <= (profile_indent or 0):
                break
            m = re.match(r"model:\s*(\S+)", stripped)
            if m:
                return m.group(1)
    return "(unknown)"


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(
        description="Live e2e test of mykg --append-with-grow-schema against OpenRouter."
    )
    parser.add_argument("--profile", default="openrouter-free",
                        help="LLM profile to activate (default: openrouter-free)")
    parser.add_argument("--input-dir", default="_input_files",
                        help="Input dir for extraction (default: _input_files)")
    parser.add_argument("--new-file", default="tech_stack.md",
                        help="File at repo root to add in stage 2 (default: tech_stack.md)")
    parser.add_argument("--config", default="mykg_config.yaml",
                        help="Config file holding the `profile:` key (default: mykg_config.yaml)")
    args = parser.parse_args()

    config_path = (REPO_ROOT / args.config).resolve()
    input_dir = (REPO_ROOT / args.input_dir).resolve()
    new_file_src = (REPO_ROOT / args.new_file).resolve()
    sessions_root = REPO_ROOT / "mykg_sessions"
    report_path = REPO_ROOT / "scripts" / "live_test_report.md"

    # Pre-flight checks.
    for p, label in [(config_path, "config"), (input_dir, "input dir"),
                     (new_file_src, "new file")]:
        if not p.exists():
            _log(f"FATAL: {label} not found: {p}")
            return 2

    model = _resolve_model(config_path, args.profile)
    _log(f"profile={args.profile}  model={model}")

    # ----- Profile rewrite with guaranteed restore -----
    guard = ProfileGuard(config_path, args.profile)
    atexit.register(guard.restore)
    guard.apply()

    report: dict = {"errors": []}

    try:
        # ================= STAGE 1 =================
        _log("STAGE 1: initial extract-graph")
        before = _session_names(sessions_root)
        stage1_cmd = [args.input_dir, "--obsidian-vault"]
        rc1 = _run_cli(["extract-graph", *stage1_cmd])
        after = _session_names(sessions_root)
        new_sessions = sorted(after - before)

        if rc1 != 0:
            _log(f"STAGE 1 CLI exited {rc1}")
            # Try to surface the run.log of the new session, if any.
            for s in new_sessions:
                _log(f"--- tail run.log of {s} ---")
                print(_tail_run_log(sessions_root / s))
            report["errors"].append(f"stage1 CLI exit {rc1}")
            _write_report(report_path, report)
            return 1

        if len(new_sessions) != 1:
            _log(f"STAGE 1 expected exactly 1 new session, got {len(new_sessions)}: {new_sessions}")
            report["errors"].append(f"stage1 produced {len(new_sessions)} new sessions")
            _write_report(report_path, report)
            return 1

        s1 = new_sessions[0]
        s1_root = sessions_root / s1
        _log(f"STAGE 1 session: {s1}")

        s1_schema_path = s1_root / "intermediate" / "schema.json"
        s1_nodes = s1_root / "output" / "nodes.jsonl"
        s1_edges = s1_root / "output" / "edges.jsonl"

        if not s1_nodes.exists() or _wc_l(s1_nodes) == 0:
            _log("STAGE 1 nodes.jsonl missing or empty")
            print(_tail_run_log(s1_root))
            report["errors"].append("stage1 nodes.jsonl missing/empty")
            _write_report(report_path, report)
            return 1
        if not s1_edges.exists() or _wc_l(s1_edges) == 0:
            _log("STAGE 1 edges.jsonl missing or empty")
            print(_tail_run_log(s1_root))
            report["errors"].append("stage1 edges.jsonl missing/empty")
            _write_report(report_path, report)
            return 1

        s1_schema = _load_schema(s1_schema_path)
        s1_concepts = _concept_names(s1_schema)
        s1_props = _property_names(s1_schema)
        s1_node_count = _wc_l(s1_nodes)
        s1_edge_count = _wc_l(s1_edges)

        report.update({
            "profile": args.profile,
            "model": model,
            "stage1_cmd": "mykg extract-graph " + " ".join(stage1_cmd),
            "stage2_cmd": (
                f"mykg extract-graph {args.input_dir} --append-with-grow-schema "
                f"--session {s1} --obsidian-vault"
            ),
            "stage1_session": s1,
            "stage1_concepts": len(s1_concepts),
            "stage1_properties": len(s1_props),
            "stage1_nodes": s1_node_count,
            "stage1_edges": s1_edge_count,
        })
        _log(f"STAGE 1: concepts={len(s1_concepts)} properties={len(s1_props)} "
             f"nodes={s1_node_count} edges={s1_edge_count}")

        # ----- Locate OLD file's shard; snapshot mtime+sha BEFORE stage 2 -----
        # NOTE: under `concat`/`batch_chunks` prep modes the OLD file is folded
        # into a single virtual batch shard (e.g. concat_batch_0000.md.json), so
        # an "Active_Projects" shard may not exist by name. We therefore also
        # track raw_extractions.json (always rewritten when Pass 2 re-runs) and
        # the orchestrator's "invalidated pass2 ... for N changed file(s)" log
        # line as prep-mode-independent back-fill evidence.
        intermediate = s1_root / "intermediate"
        shard_dir = intermediate / "raw_extractions_shards"
        old_shard = _find_old_shard(shard_dir, "Active_Projects")
        old_shard_sha_before = _sha256_path(old_shard) if old_shard else None
        old_shard_mtime_before = old_shard.stat().st_mtime if old_shard else None
        report["old_shard_path"] = str(old_shard.relative_to(REPO_ROOT)) if old_shard else None

        raw_extractions = intermediate / "raw_extractions.json"
        raw_sha_before = _sha256_path(raw_extractions)
        raw_mtime_before = raw_extractions.stat().st_mtime if raw_extractions.exists() else None

        # Snapshot schema_history files BEFORE stage 2 (to identify new deltas).
        history_dir = s1_root / "intermediate" / "schema_history"
        history_before = (
            {p.name for p in history_dir.iterdir()} if history_dir.exists() else set()
        )

        # ================= STAGE 2 =================
        _log("STAGE 2: copy new file + append-with-grow-schema")
        new_file_dst = input_dir / new_file_src.name
        if new_file_dst.exists() and _sha256_path(new_file_dst) == _sha256_path(new_file_src):
            _log(f"new file already present and identical: {new_file_dst.name}")
            report["new_file_state"] = "already present (identical)"
        else:
            shutil.copy2(new_file_src, new_file_dst)
            _log(f"copied {new_file_src.name} -> {new_file_dst}")
            report["new_file_state"] = "copied"

        stage2_args = [
            args.input_dir, "--append-with-grow-schema",
            "--session", s1, "--obsidian-vault",
        ]
        rc2 = _run_cli(["extract-graph", *stage2_args])
        if rc2 != 0:
            _log(f"STAGE 2 CLI exited {rc2}")
            print(_tail_run_log(s1_root))
            report["errors"].append(f"stage2 CLI exit {rc2}")
            _write_report(report_path, report)
            return 1

        # ----- Stage-2 schema delta -----
        s2_schema = _load_schema(s1_schema_path)  # same path, rewritten in place
        s2_concepts = _concept_names(s2_schema)
        s2_props = _property_names(s2_schema)

        concepts_added = sorted(s2_concepts - s1_concepts)
        concepts_removed = sorted(s1_concepts - s2_concepts)
        props_added = sorted(s2_props - s1_props)
        props_removed = sorted(s1_props - s2_props)

        empty_delta = not (concepts_added or concepts_removed or props_added or props_removed)
        report.update({
            "delta_concepts_added": concepts_added,
            "delta_concepts_removed": concepts_removed,
            "delta_properties_added": props_added,
            "delta_properties_removed": props_removed,
            "delta_empty": empty_delta,
        })

        # ----- schema_history new files (stage-2 deltas) -----
        history_after = (
            {p.name for p in history_dir.iterdir()} if history_dir.exists() else set()
        )
        new_history = sorted(history_after - history_before)
        report["schema_history_new_files"] = new_history
        history_summaries = []
        for name in new_history:
            try:
                hp = history_dir / name
                hd = json.loads(hp.read_text(encoding="utf-8"))
                history_summaries.append({
                    "file": name,
                    "trigger": hd.get("trigger"),
                    "concepts_added": hd.get("concepts_added"),
                    "concepts_removed": hd.get("concepts_removed"),
                    "properties_added": hd.get("properties_added"),
                    "properties_removed": hd.get("properties_removed"),
                })
            except Exception as exc:  # noqa: BLE001 - report parse issues, don't crash
                history_summaries.append({"file": name, "parse_error": str(exc)})
        report["schema_history_summaries"] = history_summaries

        # ----- Back-fill evidence -----
        # (a) Per-file shard rewrite — only meaningful in `per_file` prep mode.
        old_shard_sha_after = _sha256_path(old_shard) if old_shard else None
        old_shard_mtime_after = old_shard.stat().st_mtime if old_shard else None
        shard_rewritten = (
            old_shard is not None
            and (old_shard_sha_before != old_shard_sha_after
                 or old_shard_mtime_before != old_shard_mtime_after)
        )
        report["old_shard_rewritten"] = bool(shard_rewritten)
        report["old_shard_sha_changed"] = (
            old_shard is not None and old_shard_sha_before != old_shard_sha_after
        )

        # (b) raw_extractions.json rewrite — prep-mode-independent proof that
        #     Pass 2 re-ran (and therefore re-extracted the OLD file's content).
        raw_sha_after = _sha256_path(raw_extractions)
        raw_mtime_after = raw_extractions.stat().st_mtime if raw_extractions.exists() else None
        raw_rewritten = (
            raw_mtime_before != raw_mtime_after or raw_sha_before != raw_sha_after
        )
        report["raw_extractions_rewritten"] = bool(raw_rewritten)
        report["raw_extractions_sha_changed"] = (raw_sha_before != raw_sha_after)

        # (c) Orchestrator log line: how many files were invalidated/re-extracted.
        invalidated = _scan_invalidated_files(s1_root)
        report["pass2_invalidated_files"] = invalidated
        old_file_reextracted = any("Active_Projects" in f for f in invalidated)
        report["old_file_reextracted"] = old_file_reextracted

        # Does any node of a newly-added concept type list the OLD file in source_files?
        backfill_nodes = []
        if props_added or concepts_added:
            backfill_nodes = _backfill_node_evidence(
                s1_nodes, set(concepts_added), "Active_Projects"
            )
        report["backfill_node_evidence"] = backfill_nodes

        if empty_delta:
            report["backfill_summary"] = (
                "no back-fill — empty schema delta, collapsed to plain append (valid)"
            )
        else:
            report["backfill_summary"] = (
                f"OLD file re-extracted under grown schema: {old_file_reextracted} "
                f"(pass2 invalidated {len(invalidated)} file(s): {invalidated}); "
                f"raw_extractions.json rewritten: {raw_rewritten}; "
                f"per-file shard rewritten: {shard_rewritten} "
                f"(shard absent/stale under concat/batch prep modes — "
                f"raw_extractions.json + invalidation log are the authoritative signals); "
                f"new-concept nodes citing OLD file: {len(backfill_nodes)}"
            )

        # ----- Stage-2 final counts + net change -----
        s2_node_count = _wc_l(s1_nodes)
        s2_edge_count = _wc_l(s1_edges)
        report.update({
            "stage2_nodes": s2_node_count,
            "stage2_edges": s2_edge_count,
            "net_nodes": s2_node_count - s1_node_count,
            "net_edges": s2_edge_count - s1_edge_count,
        })

        # ----- failed chunks / 429 notes -----
        failed_chunks_path = s1_root / "intermediate" / "failed_chunks.json"
        failed = []
        if failed_chunks_path.exists():
            try:
                failed = json.loads(failed_chunks_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                failed = [{"parse_error": str(exc)}]
        report["failed_chunks"] = failed
        report["rate_limit_notes"] = _scan_429(s1_root)

        _write_report(report_path, report)
        _log("DONE. Report written to scripts/live_test_report.md")
        _log(f"  schema delta empty? {empty_delta}")
        _log(f"  concepts +{concepts_added} -{concepts_removed}")
        _log(f"  properties +{props_added} -{props_removed}")
        _log(f"  nodes {s1_node_count}->{s2_node_count}  edges {s1_edge_count}->{s2_edge_count}")
        return 0

    finally:
        guard.restore()


def _find_old_shard(shard_dir: Path, needle: str) -> Path | None:
    """Find the shard for the OLD file by glob, then by _fname content."""
    if not shard_dir.exists():
        return None
    # 1) filename glob
    for p in sorted(shard_dir.glob("*.json")):
        if needle.lower() in p.name.lower():
            return p
    # 2) content _fname match
    for p in sorted(shard_dir.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        fname = str(data.get("_fname", ""))
        if needle.lower() in fname.lower():
            return p
    return None


def _backfill_node_evidence(nodes_jsonl: Path, new_concepts: set[str], old_needle: str):
    """Return nodes of new concept types whose source_files include the OLD file."""
    out = []
    if not nodes_jsonl.exists() or not new_concepts:
        return out
    with nodes_jsonl.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                node = json.loads(line)
            except Exception:  # noqa: BLE001
                continue
            if node.get("type") not in new_concepts:
                continue
            src = node.get("source_files", []) or []
            if any(old_needle.lower() in str(s).lower() for s in src):
                out.append({
                    "id": node.get("id"),
                    "type": node.get("type"),
                    "source_files": src,
                })
    return out


def _scan_invalidated_files(session_root: Path) -> list[str]:
    """Parse the orchestrator's append-invalidation log line.

    Matches e.g.::

        append: invalidated pass2 and downstream outputs for 2 changed
        file(s): ['Active_Projects_Q2_Q3_2026.md', 'tech_stack.md']

    Returns the list of changed filenames from the LAST such line (stage 2).
    """
    log_path = session_root / "run.log"
    if not log_path.exists():
        return []
    files: list[str] = []
    for line in log_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "invalidated pass2" not in line:
            continue
        # The line also contains a leading "[INFO]" tag, so anchor on the
        # bracketed file list that follows "file(s):" and extract quoted names.
        m = re.search(r"file\(s\):\s*\[([^\]]*)\]", line)
        if m:
            files = re.findall(r"'([^']+)'", m.group(1))
    return files


def _scan_429(session_root: Path) -> list[str]:
    """Grep run.log + llm.log for 429 / rate-limit / 402 signals."""
    notes = []
    for name in ("run.log", "llm.log"):
        lp = session_root / name
        if not lp.exists():
            continue
        for line in lp.read_text(encoding="utf-8", errors="replace").splitlines():
            low = line.lower()
            if "429" in low or "rate limit" in low or "rate-limit" in low or " 402" in low:
                notes.append(f"{name}: {line.strip()[:200]}")
    return notes[:30]


def _write_report(path: Path, r: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    def fmt_list(xs):
        return ", ".join(xs) if xs else "(none)"

    lines = [
        "# mykg `--append-with-grow-schema` live test report",
        "",
        f"_Generated: {now}_",
        "",
        f"- **Profile:** `{r.get('profile', '?')}`",
        f"- **Model:** `{r.get('model', '?')}`",
        "",
        "## Commands run",
        "",
        "```",
        r.get("stage1_cmd", "(not run)"),
        r.get("stage2_cmd", "(not run)"),
        "```",
        "",
        "## Stage 1 — initial extract",
        "",
        f"- Session: `{r.get('stage1_session', '(none)')}`",
        f"- Concepts: {r.get('stage1_concepts', '-')}",
        f"- Properties: {r.get('stage1_properties', '-')}",
        f"- Nodes: {r.get('stage1_nodes', '-')}",
        f"- Edges: {r.get('stage1_edges', '-')}",
        "",
        "## Stage 2 — append-with-grow-schema",
        "",
        f"- New file: {r.get('new_file_state', '-')}",
        f"- **Schema delta empty?** {r.get('delta_empty', '-')}",
        f"- Concepts added: {fmt_list(r.get('delta_concepts_added', []))}",
        f"- Concepts removed: {fmt_list(r.get('delta_concepts_removed', []))}",
        f"- Properties added: {fmt_list(r.get('delta_properties_added', []))}",
        f"- Properties removed: {fmt_list(r.get('delta_properties_removed', []))}",
        "",
        "### schema_history (stage-2 deltas)",
        "",
        f"- New history files: {fmt_list(r.get('schema_history_new_files', []))}",
    ]
    for h in r.get("schema_history_summaries", []):
        lines.append(
            f"  - `{h.get('file')}` trigger=`{h.get('trigger')}` "
            f"+concepts={h.get('concepts_added')} -concepts={h.get('concepts_removed')} "
            f"+props={h.get('properties_added')} -props={h.get('properties_removed')}"
        )
    lines += [
        "",
        "### Back-fill evidence",
        "",
        f"- Pass 2 invalidated/re-extracted files (stage 2): "
        f"{fmt_list(r.get('pass2_invalidated_files', []))}",
        f"- **OLD file re-extracted under grown schema:** {r.get('old_file_reextracted', '-')}",
        f"- raw_extractions.json rewritten: {r.get('raw_extractions_rewritten', '-')} "
        f"(sha changed: {r.get('raw_extractions_sha_changed', '-')})",
        f"- Old file shard: `{r.get('old_shard_path', '(not found — concat/batch prep mode)')}`",
        f"- Per-file shard rewritten: {r.get('old_shard_rewritten', '-')} "
        f"(sha changed: {r.get('old_shard_sha_changed', '-')}) "
        f"— only meaningful in per_file prep mode",
        f"- New-concept nodes citing OLD file: "
        f"{len(r.get('backfill_node_evidence', []))}",
    ]
    for n in r.get("backfill_node_evidence", [])[:20]:
        lines.append(f"  - `{n.get('id')}` ({n.get('type')}) <- {n.get('source_files')}")
    net_nodes = r.get("net_nodes")
    net_edges = r.get("net_edges")
    nodes_line = f"- Stage-2 nodes: {r.get('stage2_nodes', '-')}"
    if isinstance(net_nodes, int):
        nodes_line += f" (net {net_nodes:+d})"
    edges_line = f"- Stage-2 edges: {r.get('stage2_edges', '-')}"
    if isinstance(net_edges, int):
        edges_line += f" (net {net_edges:+d})"
    lines += [
        f"- Summary: {r.get('backfill_summary', '-')}",
        "",
        "## Node / edge change",
        "",
        nodes_line,
        edges_line,
        "",
        "## Diagnostics",
        "",
        f"- failed_chunks entries: {len(r.get('failed_chunks', []) or [])}",
        f"- rate-limit / 429 / 402 notes: {len(r.get('rate_limit_notes', []) or [])}",
    ]
    for note in (r.get("rate_limit_notes", []) or [])[:20]:
        lines.append(f"  - {note}")
    if r.get("errors"):
        lines += ["", "## Errors", ""]
        for e in r["errors"]:
            lines.append(f"- {e}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
