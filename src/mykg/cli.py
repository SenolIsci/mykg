from __future__ import annotations

import json
import logging
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv


def _cfg():
    from mykg import config

    return config


@click.group()
def cli():
    """mykg — Markdown-to-knowledge-graph extractor."""
    load_dotenv(".env.mykg")


def _sessions_root() -> Path:
    return Path(getattr(_cfg(), "SESSIONS_DIR", "sessions"))


def _make_session_dirs(sessions_root: Path) -> tuple[str, Path, Path]:
    """Create a timestamped session folder. Returns (name, output_dir, intermediate_dir)."""
    name = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    root = sessions_root / name
    (root / "output").mkdir(parents=True, exist_ok=True)
    (root / "intermediate").mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    return name, root / "output", root / "intermediate"


def _copy_input_files(input_dir: Path, session_root: Path, copy_config: bool = True) -> None:
    """Copy all files from input_dir into session_root/input/, preserving subfolder structure.

    Non-Markdown files are copied so the optional preprocess step (D39–D48) can
    convert them via MinerU. The ingest step still only reads ``*.md``.
    """
    dest = session_root / "input"
    dest.mkdir(parents=True, exist_ok=True)
    for f in input_dir.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(input_dir)
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
    if copy_config:
        shutil.copy2(_cfg().CONFIG_PATH, session_root / "mykg_config.yaml")


_PROFILE_META = {
    "openrouter-free": {
        "label": "OpenRouter (default — many free models, one API key)",
        "key_var": "OPENROUTER_API_KEY",
        "key_hint": "sk-or-...",
        "key_url": "https://openrouter.ai/keys",
        "default_model": "google/gemini-3.5-flash",
    },
    "anthropic-claude": {
        "label": "Anthropic Claude (highest quality)",
        "key_var": "ANTHROPIC_API_KEY",
        "key_hint": "sk-ant-...",
        "key_url": "https://console.anthropic.com/account/keys",
        "default_model": "claude-sonnet-4-5",
    },
    "openai": {
        "label": "OpenAI (GPT-4o and friends)",
        "key_var": "OPENAI_API_KEY",
        "key_hint": "sk-...",
        "key_url": "https://platform.openai.com/api-keys",
        "default_model": "gpt-4o",
    },
    "ollama-local": {
        "label": "Ollama (local inference, no API key needed)",
        "key_var": None,
        "key_hint": None,
        "key_url": None,
        "default_model": "llama3.3",
    },
    "claude-cli": {
        "label": "Claude CLI (uses claude -p, no API key needed)",
        "key_var": None,
        "key_hint": None,
        "key_url": None,
        "default_model": "sonnet",
    },
}


@cli.command("init")
@click.option("--force", is_flag=True, help="Overwrite existing mykg_config.yaml")
@click.option("--profile", default=None, help="LLM profile to activate (skips interactive prompt)")
@click.option(
    "--model",
    default=None,
    help="Model name to set in the active profile (skips interactive prompt)",
)
@click.option(
    "--api-key", default=None, help="API key to write to .env.mykg (skips interactive prompt)"
)
def init_config(force: bool, profile: str | None, model: str | None, api_key: str | None) -> None:
    """Create mykg_config.yaml and optionally configure LLM provider, model, and API key."""
    dest = Path.cwd() / "mykg_config.yaml"
    if dest.exists() and not force:
        click.echo("mykg_config.yaml already exists. Use --force to overwrite.")
        return

    # --- Profile selection ---------------------------------------------------
    profiles = list(_PROFILE_META.keys())
    if profile is None:
        click.echo("\nSelect an LLM profile:")
        for i, p in enumerate(profiles, 1):
            marker = " (default)" if p == "openrouter-free" else ""
            click.echo(f"  [{i}] {_PROFILE_META[p]['label']}{marker}")
        choice = click.prompt("Enter number", default="1", show_default=True)
        try:
            idx = int(choice) - 1
            if not 0 <= idx < len(profiles):
                raise ValueError
            profile = profiles[idx]
        except ValueError:
            click.echo("Invalid choice — using default: openrouter-free")
            profile = "openrouter-free"

    if profile not in _PROFILE_META:
        click.echo(f"Unknown profile '{profile}'. Valid options: {', '.join(profiles)}")
        return

    meta = _PROFILE_META[profile]

    # --- Model selection -----------------------------------------------------
    if model is None:
        default_model = meta["default_model"]
        model_input = click.prompt(
            "Model name (press Enter for default)",
            default=default_model,
            show_default=True,
        ).strip()
        model = model_input if model_input != default_model else None

    # --- Write mykg_config.yaml with selected profile and optional model -
    import re

    template = Path(__file__).parent / "data" / "mykg_config.yaml"
    content = template.read_text()
    content = re.sub(r"^profile:.*$", f"profile: {profile}", content, count=1, flags=re.MULTILINE)
    if model:
        content = _patch_profile_model(content, profile, model)
    dest.write_text(content)
    model_note = f", model: {model}" if model else ""
    click.echo(f"\nCreated mykg_config.yaml in {Path.cwd()} (profile: {profile}{model_note})")

    # --- API key setup -------------------------------------------------------
    if meta["key_var"] is None:
        click.echo(f"No API key required for '{profile}'.")
        _print_next_steps(profile)
        return

    env_file = Path.cwd() / ".env.mykg"
    var = meta["key_var"]

    # Check if key is already set
    existing_key = None
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f"{var}=") and line[len(var) + 1 :].strip():
                existing_key = line[len(var) + 1 :].strip()
                break

    if existing_key:
        click.echo(f"\n{var} is already set in .env.mykg.")
    else:
        if api_key is None:
            click.echo(f"\nYou need an API key for {profile}.")
            if meta["key_url"]:
                click.echo(f"Get one at: {meta['key_url']}")
            api_key = click.prompt(
                f"Paste your {var} (or press Enter to skip)",
                default="",
                show_default=False,
            ).strip()

        if api_key:
            _write_env_key(env_file, var, api_key)
            click.echo(f"Written {var} to .env.mykg")
        else:
            click.echo(f"Skipped — set {var} in .env.mykg before running.")

    _print_next_steps(profile)


def _patch_profile_model(content: str, profile: str, model: str) -> str:
    """Replace the model: line inside a specific profile block in the YAML text."""
    import re

    # Find the profile block start, then replace the first `      model:` line within it.
    # Profile blocks are indented with two spaces; llm.model is indented with six.
    profile_pattern = re.compile(
        rf"(  {re.escape(profile)}:.*?)(\n      model:\s*\S[^\n]*)",
        re.DOTALL,
    )
    result = profile_pattern.sub(rf"\1\n      model: {model}", content, count=1)
    return result


def _write_env_key(env_file: Path, var: str, value: str) -> None:
    """Write or update a single key in .env.mykg, preserving other lines."""
    lines = env_file.read_text().splitlines() if env_file.exists() else []
    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{var}="):
            lines[i] = f"{var}={value}"
            updated = True
            break
    if not updated:
        lines.append(f"{var}={value}")
    env_file.write_text("\n".join(lines) + "\n")


def _print_next_steps(profile: str) -> None:
    click.echo("\nNext steps:")
    click.echo("  mykg extract-graph <your_notes_directory>/")
    if profile == "ollama-local":
        click.echo("  (make sure Ollama is running: ollama serve)")
    elif profile == "claude-cli":
        click.echo(
            "  (make sure the claude CLI is installed: npm install -g @anthropic-ai/claude-code)"
        )


@cli.command("extract-graph")
@click.argument("input_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option(
    "--output-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Directory for final outputs (default: from mykg_config.yaml)",
)
@click.option(
    "--intermediate-dir",
    default=None,
    type=click.Path(path_type=Path),
    help="Intermediate pipeline files dir (default: from mykg_config.yaml)",
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
    default=lambda: _cfg().PASS2_MAX_WORKERS,
    type=int,
    show_default=True,
    help="Number of parallel workers for Pass 2",
)
@click.option(
    "--confidence-agg",
    default=lambda: _cfg().ASSEMBLY_CONFIDENCE_AGG,
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
@click.option(
    "--obsidian-vault",
    is_flag=True,
    default=False,
    help="Write an Obsidian vault to output/obsidian_vault/ (overrides config obsidian_enabled)",
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
    obsidian_vault,
):
    """Extract a knowledge graph from a directory of Markdown files."""
    from mykg.llm.config import load_adapter
    from mykg.logging import setup
    from mykg.orchestrator import PipelineContext, run
    from mykg.pipeline import STEPS

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
        output_dir = output_dir or Path(_cfg().OUTPUT_DIR)
        intermediate_dir = intermediate_dir or Path(_cfg().INTERMEDIATE_DIR)

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

    if obsidian_vault:
        import mykg.config as _config_mod

        _config_mod.OBSIDIAN_ENABLED = True

    from mykg.llm.error_gate import ErrorGate

    error_gate = (
        ErrorGate(threshold=_cfg().ERROR_GATE_THRESHOLD) if _cfg().ERROR_GATE_ENABLED else None
    )
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

    if _cfg().REPORT_ENABLED and session_root is not None:
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
    from mykg.logging import setup

    setup(log_file=log_file, verbose=verbose)

    if session and intermediate_dir is not None:
        raise click.ClickException("--session cannot be combined with --intermediate-dir")
    if session:
        intermediate_dir = _sessions_root() / session / "intermediate"
    else:
        intermediate_dir = intermediate_dir or Path(_cfg().INTERMEDIATE_DIR)

    schema_path = Path(intermediate_dir) / "schema.json"
    if not schema_path.exists():
        raise click.ClickException(f"schema.json not found in {intermediate_dir}")

    schema = json.loads(schema_path.read_text())

    from mykg.exporter import export_ttl

    ttl = export_ttl(schema, [], {})
    (Path(intermediate_dir) / "schema.ttl").write_text(ttl)

    flag = Path(intermediate_dir) / "schema_approved.flag"
    flag.write_text("approved")
    click.echo(
        "Schema approved. schema.ttl regenerated. Resume with the original extract-graph command."
    )


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

    from mykg.llm.config import load_adapter
    from mykg.logging import setup

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

    if _cfg().REPORT_ENABLED:
        from mykg.steps.step_walkthrough import run_walkthrough

        run_walkthrough(
            merged_session_root,
            log_file=Path(log_file) if log_file else merged_session_root / "run.log",
        )

    click.echo(f"Merged session written to: {merged_session_root}")


@cli.command(
    "parse-docs",
    context_settings={"ignore_unknown_options": True},
)
@click.option(
    "--input",
    "input_path",
    required=True,
    type=click.Path(exists=True, path_type=Path),
    help="Input file or directory of non-Markdown documents to convert.",
)
@click.option(
    "--output",
    "output_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Output directory (will be created) to receive converted Markdown.",
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def parse_docs(input_path: Path, output_path: Path, extra_args: tuple[str, ...]) -> None:
    """Convert non-Markdown documents (PDF, DOCX, images, etc.) to Markdown using MinerU.

    Wraps `mineru -p -i INPUT -o OUTPUT`. Requires `pip install "mykg[mineru]"`.
    Extra arguments are passed through to mineru.
    """
    if shutil.which("mineru") is None:
        raise click.ClickException(
            'mineru CLI not found on PATH. Install with: pip install "mykg[mineru]"'
        )

    output_path.mkdir(parents=True, exist_ok=True)

    cmd = ["mineru", "-p", "-i", str(input_path), "-o", str(output_path)] + list(extra_args)
    click.echo(f"Running: {' '.join(cmd)}")

    proc = subprocess.run(cmd, check=False)
    if proc.returncode != 0:
        raise click.ClickException(f"mineru exited with code {proc.returncode}")

    click.echo(f"Done. Output written to: {output_path}")


# Aliases for --from-step that encode the orphan-connect sweep mode.
# Maps alias → (real_step_name, orphan_incremental)
_FROM_STEP_ALIASES: dict[str, tuple[str, bool]] = {
    "orphan_connect_fullsweep": ("orphan_connect", False),
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
    valid_names = [s.name for s in STEPS if s.name not in ("ingest", "preprocess")]

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
            path = base_dir / filename.rstrip("/")
            if path.exists():
                if path.is_dir():
                    shutil.rmtree(path)
                else:
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

    # obsidian_vault/ is written by validate_graph but not tracked in Step.outputs
    # (it is optional; omitting it prevents _is_done from breaking when disabled).
    # Delete it when re-running from validate_graph or any earlier step.
    validate_graph_idx = (
        step_names.index("validate_graph") if "validate_graph" in step_names else -1
    )
    if validate_graph_idx >= 0 and idx <= validate_graph_idx:
        obsidian_path = output_dir / _cfg().OBSIDIAN_VAULT_DIR
        if obsidian_path.exists():
            shutil.rmtree(obsidian_path)
            click.echo(f"Deleted {obsidian_path}")

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
    merge_reextract_idx = (
        step_names.index("merge_reextract") if "merge_reextract" in step_names else -1
    )
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
