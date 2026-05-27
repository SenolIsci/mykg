from __future__ import annotations

import json
import logging
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

from mykg import config as _cfg
from mykg.llm.config import load_adapter
from mykg.logging import setup
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS


@click.group()
def cli():
    """mykg — Markdown-to-knowledge-graph extractor."""
    load_dotenv()


def _sessions_root() -> Path:
    return Path(getattr(_cfg, "SESSIONS_DIR", "sessions"))


def _make_session_dirs(sessions_root: Path) -> tuple[str, Path, Path]:
    """Create a timestamped session folder. Returns (name, output_dir, intermediate_dir)."""
    name = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    root = sessions_root / name
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "intermediate").mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    return name, root / "output", root / "intermediate"


def _copy_input_files(input_dir: Path, session_root: Path, copy_config: bool = True) -> None:
    """Copy .md files from input_dir into session_root/input/, preserving subfolder structure."""
    dest = session_root / "input"
    dest.mkdir(parents=True, exist_ok=True)
    for f in input_dir.rglob("*.md"):
        rel = f.relative_to(input_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    if copy_config:
        shutil.copy2(_cfg.CONFIG_PATH, session_root / "pipeline_config.yaml")


@cli.command("extract-graph")
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory for final outputs (default: from pipeline_config.yaml)",
)
@click.option(
    "--intermediate-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Intermediate pipeline files dir (default: from pipeline_config.yaml)",
)
@click.option(
    "--log-file",
    default=None,
    type=click.Path(path_type=Path),
    help="Write logs to this file in addition to stdout",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging")
@click.option("--base-schema", default=None, type=click.Path(exists=True), help="Locked TBox TTL")
@click.option("--thesaurus", default=None, type=click.Path(exists=True), help="SKOS TTL thesaurus")
@click.option("--review", is_flag=True, help="Pause for human schema review after Pass 1")
@click.option(
    "--from-step",
    default=None,
    help="Force re-run from this step. Use 'orphan_connect_fullsweep' for a full clean "
         "sweep (deletes prior orphan_connections.json) or 'orphan_connect_incremental' "
         "to preserve it and only re-send unresolved groups to the LLM.",
)
@click.option(
    "--workers",
    default=lambda: _cfg.PASS2_MAX_WORKERS,
    type=int,
    show_default=True,
    help="Number of parallel workers for Pass 2",
)
@click.option(
    "--confidence-agg",
    default=lambda: _cfg.ASSEMBLY_CONFIDENCE_AGG,
    type=click.Choice(["mean", "max"]),
    show_default=True,
    help="How to aggregate confidence scores when deduplicating",
)
@click.option(
    "--append",
    is_flag=True,
    help="Skip Pass 1, re-run only on new/modified files, then re-assemble and re-export",
)
@click.option(
    "--session",
    default=None,
    help="Session name under sessions/ to resume or append; omit to auto-create",
)
def extract_graph(
    input_dir,
    output_dir,
    intermediate_dir,
    log_file,
    verbose,
    base_schema,
    thesaurus,
    review,
    from_step,
    workers,
    confidence_agg,
    append,
    session,
):
    """Extract a knowledge graph from a directory of Markdown files."""
    sessions_root = _sessions_root()

    if session and (output_dir is not None or intermediate_dir is not None):
        raise click.ClickException(
            "--session cannot be combined with --output-dir / --intermediate-dir"
        )

    if (
        from_step
        and not append
        and session is None
        and output_dir is None
        and intermediate_dir is None
    ):
        raise click.ClickException(
            "--from-step requires --session <name> (or --output-dir / --intermediate-dir) "
            "to target an existing pipeline state. "
            "Re-entry without a session would start a new empty run."
        )

    if session:
        session_root = sessions_root / session
        if not session_root.exists():
            raise click.ClickException(
                f"Session '{session}' not found at {session_root}. "
                "Omit --session to start a new run."
            )
        output_dir = session_root / "output"
        intermediate_dir = session_root / "intermediate"
        _copy_input_files(input_dir, session_root, copy_config=not append)
        input_dir = session_root / "input"
    elif output_dir is None and intermediate_dir is None:
        session_name, output_dir, intermediate_dir = _make_session_dirs(sessions_root)
        session_root = sessions_root / session_name
        _copy_input_files(input_dir, session_root, copy_config=not append)
        input_dir = session_root / "input"
        click.echo(f"Session: {session_name}")
    else:
        session_root = None
        output_dir = output_dir or Path(_cfg.OUTPUT_DIR)
        intermediate_dir = intermediate_dir or Path(_cfg.INTERMEDIATE_DIR)

    # Route log file into the session folder (absolute paths are kept as-is).
    if session_root is not None:
        if log_file is None:
            log_file = session_root / "run.log"
        elif not Path(log_file).is_absolute():
            log_file = session_root / Path(log_file).name

    setup(log_file=log_file, verbose=verbose)
    logging.getLogger(__name__).info("Command: %s", " ".join(sys.argv))

    if append and from_step:
        raise click.ClickException("--append and --from-step are mutually exclusive.")

    orphan_incremental = False
    if from_step:
        from_step, orphan_incremental = _resolve_from_step(from_step)
        _delete_from_step(from_step, intermediate_dir, output_dir, incremental=orphan_incremental)

    from mykg.llm.error_gate import ErrorGate

    error_gate = ErrorGate(threshold=_cfg.ERROR_GATE_THRESHOLD) if _cfg.ERROR_GATE_ENABLED else None
    adapter = load_adapter(error_gate=error_gate)
    logging.getLogger(__name__).info("LLM endpoint: %s", adapter.endpoint_label())

    base = None
    if base_schema:
        from mykg.base_schema import parse_base_schema

        base = parse_base_schema(Path(base_schema).read_text())
        base["_source"] = str(base_schema)

    thes = None
    if thesaurus:
        from mykg.thesaurus import parse_thesaurus

        thes = parse_thesaurus(Path(thesaurus).read_text(), source=str(thesaurus))

    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        error_gate=error_gate,
        base_schema=base,
        thesaurus=thes,
        review=review,
        pass2_workers=workers,
        confidence_agg=confidence_agg,
        append=append,
        orphan_incremental=orphan_incremental,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)

    run(STEPS, ctx)

    if _cfg.REPORT_ENABLED and session_root is not None:
        from mykg.steps.step_walkthrough import run_walkthrough

        run_walkthrough(
            session_root,
            log_file=Path(log_file) if log_file else session_root / "run.log",
        )


@cli.command("approve-schema")
@click.option("--intermediate-dir", default=None, type=click.Path(path_type=Path))
@click.option("--log-file", default=None, type=click.Path(path_type=Path))
@click.option("--verbose", "-v", is_flag=True)
@click.option("--session", default=None, help="Session name to find intermediate-dir in")
def approve_schema(intermediate_dir, log_file, verbose, session):
    """Regenerate schema.ttl from schema.json and write the approval flag."""
    setup(log_file=log_file, verbose=verbose)

    if session and intermediate_dir is not None:
        raise click.ClickException("--session cannot be combined with --intermediate-dir")
    if session:
        intermediate_dir = _sessions_root() / session / "intermediate"
    else:
        intermediate_dir = intermediate_dir or Path(_cfg.INTERMEDIATE_DIR)

    schema_path = Path(intermediate_dir) / "schema.json"
    if not schema_path.exists():
        raise click.ClickException(f"schema.json not found in {intermediate_dir}")

    schema = json.loads(schema_path.read_text())

    from mykg.exporter import export_ttl

    ttl = export_ttl(schema, [], {})
    (Path(intermediate_dir) / "schema.ttl").write_text(ttl)

    flag = Path(intermediate_dir) / "schema_approved.flag"
    flag.write_text("approved")
    click.echo("Schema approved. schema.ttl regenerated. Resume with the original extract-graph command.")


@cli.command("walkthrough")
@click.option(
    "--session", "session_name", required=True, help="Session folder name to generate report for"
)
@click.option(
    "--log-file", "log_file", default=None, help="Path to log file (defaults to <session>/run.log)"
)
def walkthrough_cmd(session_name: str, log_file: str | None) -> None:
    """Generate a walkthrough.md report for an existing session."""
    sessions_root = _sessions_root()
    session_root = sessions_root / session_name
    if not session_root.exists():
        raise click.ClickException(f"Session not found: {session_root}")
    lf = Path(log_file) if log_file else session_root / "run.log"
    from mykg.steps.step_walkthrough import run_walkthrough

    run_walkthrough(session_root, log_file=lf)
    click.echo(f"Walkthrough report written to {session_root / 'walkthrough.md'}")


@cli.command("merge-graphs")
@click.argument("session_a")
@click.argument("session_b")
@click.option(
    "--output-session",
    default=None,
    help="Name for the merged session folder (default: auto-timestamped)",
)
@click.option(
    "--thesaurus",
    default=None,
    type=click.Path(exists=True),
    help="SKOS TTL thesaurus for schema synonym matching",
)
@click.option(
    "--base-schema",
    default=None,
    type=click.Path(exists=True),
    help="Locked TBox TTL base schema",
)
@click.option(
    "--log-file",
    default=None,
    type=click.Path(path_type=Path),
    help="Write logs to this file in addition to stdout",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging")
@click.option(
    "--from-step",
    default=None,
    help="Force re-run from this merge step (e.g. orphan_score, orphan_connect). "
         "Requires --output-session targeting an existing merged session.",
)
def merge_graphs(
    session_a, session_b, output_session, thesaurus, base_schema, log_file, verbose, from_step
):
    """Merge two pipeline sessions into a unified knowledge graph."""
    if session_a == session_b:
        raise click.ClickException(
            f"Cannot merge a session with itself: '{session_a}'. Provide two different sessions."
        )

    sessions_root = _sessions_root()

    if from_step and output_session is None:
        raise click.ClickException(
            "--from-step requires --output-session <name> to target an existing merged session. "
            "Re-entry without a named session would start a new empty run."
        )

    # Validate both sessions exist.
    for name in (session_a, session_b):
        session_path = sessions_root / name
        if not session_path.is_dir():
            click.echo(f"Error: session '{name}' not found at {session_path}", err=True)
            sys.exit(1)

    # Create merged session folder.
    if output_session is not None:
        merged_session_root = sessions_root / output_session
        output_dir = merged_session_root / "output"
        intermediate_dir = merged_session_root / "intermediate"
        (merged_session_root / "input").mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        intermediate_dir.mkdir(parents=True, exist_ok=True)
    else:
        session_name, output_dir, intermediate_dir = _make_session_dirs(sessions_root)
        merged_session_root = sessions_root / session_name

    # Route log file into the merged session folder (absolute paths kept as-is).
    if log_file is None:
        log_file = merged_session_root / "run.log"
    elif not Path(log_file).is_absolute():
        log_file = merged_session_root / Path(log_file).name

    setup(log_file=log_file, verbose=verbose)

    if from_step:
        _delete_merge_from_step(from_step, intermediate_dir, output_dir)

    adapter = load_adapter()

    base = None
    if base_schema:
        from mykg.base_schema import parse_base_schema

        base = parse_base_schema(Path(base_schema).read_text())
        base["_source"] = str(base_schema)

    thes = None
    if thesaurus:
        from mykg.thesaurus import parse_thesaurus

        thes = parse_thesaurus(Path(thesaurus).read_text(), source=str(thesaurus))

    from mykg.config import MERGE_GRAPHS_HUMAN_REVIEW
    from mykg.merge_orchestrator import run_merge_graphs

    run_merge_graphs(
        session_a,
        session_b,
        output_dir,
        intermediate_dir,
        adapter,
        thes,
        base,
        review=MERGE_GRAPHS_HUMAN_REVIEW,
        sessions_root=sessions_root,
    )

    if _cfg.REPORT_ENABLED:
        from mykg.steps.step_walkthrough import run_walkthrough

        run_walkthrough(
            merged_session_root,
            log_file=Path(log_file) if log_file else merged_session_root / "run.log",
        )

    click.echo(f"Merged session written to: {merged_session_root}")


# Aliases for --from-step that encode the orphan-connect sweep mode.
# Maps alias → (real_step_name, orphan_incremental)
_FROM_STEP_ALIASES: dict[str, tuple[str, bool]] = {
    "orphan_connect_fullsweep":   ("orphan_connect", False),
    "orphan_connect_incremental": ("orphan_connect", True),
}


def _resolve_from_step(step_name: str) -> tuple[str, bool]:
    """Resolve a --from-step value to (real_step_name, orphan_incremental).

    'orphan_connect_fullsweep' and 'orphan_connect_incremental' both map to
    the real step 'orphan_connect' with different sweep modes. All other step
    names pass through unchanged with orphan_incremental=False.
    """
    if step_name in _FROM_STEP_ALIASES:
        return _FROM_STEP_ALIASES[step_name]
    return step_name, False


def _delete_from_step(
    step_name: str,
    intermediate_dir: Path,
    output_dir: Path,
    *,
    incremental: bool = False,
) -> None:
    from mykg.pipeline import STEPS

    step_names = [s.name for s in STEPS]
    valid_names = [s.name for s in STEPS if s.name != "ingest"]

    if step_name not in valid_names:
        valid = ", ".join(list(valid_names) + list(_FROM_STEP_ALIASES))
        raise click.ClickException(f"Unknown step '{step_name}'. Valid steps: {valid}")

    # Files preserved when doing an incremental orphan sweep so that
    # run_orphan_connect can load them as a seed and skip confirmed groups.
    _INCREMENTAL_PRESERVE = frozenset({"orphan_connections.json", "orphan_log.json"})

    idx = step_names.index(step_name)
    for step in STEPS[idx:]:
        base_dir = output_dir if step.output_location == "output" else intermediate_dir
        for filename in step.outputs:
            if incremental and filename in _INCREMENTAL_PRESERVE:
                click.echo(f"Preserved {base_dir / filename} (incremental sweep)")
                continue
            path = base_dir / filename
            if path.exists():
                path.unlink()
                click.echo(f"Deleted {path}")

    # Shard directories are not listed in Step.outputs but must be cleared when
    # re-running from pass2 or earlier — otherwise step_pass2 loads existing shards
    # and skips all files, making Re-entry B a silent no-op.
    pass2_idx = step_names.index("pass2") if "pass2" in step_names else -1
    if pass2_idx >= 0 and idx <= pass2_idx:
        for shard_dir_name in ("raw_extractions_shards", "chunk_index_shards"):
            shard_path = intermediate_dir / shard_dir_name
            if shard_path.exists():
                shutil.rmtree(shard_path)
                click.echo(f"Deleted {shard_path}")
        concat_map_path = intermediate_dir / "pass2_concat_map.json"
        if concat_map_path.exists():
            concat_map_path.unlink()
            click.echo(f"Deleted {concat_map_path}")

    human_review_idx = step_names.index("human_review") if "human_review" in step_names else -1
    if idx > human_review_idx >= 0:
        flag_path = intermediate_dir / "schema_approved.flag"
        if flag_path.exists():
            flag_path.unlink()
            click.echo(f"Deleted {flag_path}")


def _delete_merge_from_step(
    step_name: str,
    intermediate_dir: Path,
    output_dir: Path,
) -> None:
    from mykg.merge_pipeline import MERGE_STEPS

    step_names = [s.name for s in MERGE_STEPS]
    valid_names = [s.name for s in MERGE_STEPS if s.name != "merge_setup"]

    if step_name not in valid_names:
        valid = ", ".join(valid_names)
        raise click.ClickException(f"Unknown merge step '{step_name}'. Valid steps: {valid}")

    idx = step_names.index(step_name)
    for step in MERGE_STEPS[idx:]:
        base_dir = output_dir if step.output_location == "output" else intermediate_dir
        for filename in step.outputs:
            path = base_dir / filename
            if path.exists():
                path.unlink()
                click.echo(f"Deleted {path}")

    # Shard directories must be cleared when re-running from merge_reextract or
    # earlier, otherwise existing shards are reused and the step is silently skipped.
    merge_reextract_idx = step_names.index("merge_reextract") if "merge_reextract" in step_names else -1
    if merge_reextract_idx >= 0 and idx <= merge_reextract_idx:
        for shard_dir_name in ("raw_extractions_shards", "chunk_index_shards"):
            shard_path = intermediate_dir / shard_dir_name
            if shard_path.exists():
                shutil.rmtree(shard_path)
                click.echo(f"Deleted {shard_path}")

    human_review_idx = step_names.index("human_review") if "human_review" in step_names else -1
    if idx > human_review_idx >= 0:
        flag_path = intermediate_dir / "schema_approved.flag"
        if flag_path.exists():
            flag_path.unlink()
            click.echo(f"Deleted {flag_path}")


def main():
    cli()
