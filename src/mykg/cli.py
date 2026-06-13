from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import click
from dotenv import load_dotenv

from mykg.uv_venv import ephemeral_venv


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

    Only ``.md`` files and files whose suffix is in ``PREPROCESS_EXTENSIONS``
    (the allowlist from ``mykg_config.yaml → preprocess.extensions``) are
    copied. Files inside the sessions directory are silently skipped so that
    passing the project root as input_dir does not cause a recursive copy loop.
    Hidden directories (any path component starting with ``.``) are skipped so
    that ``.venv``, ``.git``, and similar tool directories are never copied.
    ``mykg_config.yaml`` is skipped here because it is written separately below
    when ``copy_config=True``.
    """
    dest = session_root / "input"
    dest.mkdir(parents=True, exist_ok=True)
    sessions_root = _sessions_root().resolve()
    config_path = _cfg().CONFIG_PATH.resolve()
    allowed_exts = _cfg().PREPROCESS_EXTENSIONS | {".md"}
    for f in input_dir.rglob("*"):
        if not f.is_file():
            continue
        if f.suffix.lower() not in allowed_exts:
            continue  # only copy md + preprocess-eligible formats
        resolved = f.resolve()
        try:
            resolved.relative_to(sessions_root)
            continue  # inside sessions dir — skip to avoid recursive copy
        except ValueError:
            pass
        if resolved == config_path:
            continue  # copied separately below
        rel = f.relative_to(input_dir)
        if any(part.startswith(".") for part in rel.parts):
            continue  # skip hidden dirs/files (.venv, .git, .DS_Store, …)
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
        "default_model": "openrouter/free",
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
        "label": "Claude CLI (uses claude -p)",
        "key_var": None,
        "key_hint": None,
        "key_url": None,
        "default_model": "sonnet",
    },
    "agent-claude-code": {
        "label": "Agent (Claude Code skill — runs inside this session, no API key)",
        "key_var": None,
        "key_hint": None,
        "key_url": None,
        "default_model": None,  # agent mode has no model concept — the host is the LLM
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
@click.option(
    "--reinstall-skill",
    is_flag=True,
    default=False,
    help=(
        "Re-install the bundled Claude Code skill into ~/.claude/skills/mykg, "
        "overwriting any existing copy. Use after `pip install -U mykg` to "
        "refresh a stale install. Only meaningful with --profile agent-claude-code."
    ),
)
@click.option(
    "--reinstall-claude-md",
    is_flag=True,
    default=False,
    help=(
        "Refresh the `<!-- BEGIN mykg-section -->` block in the project's "
        "CLAUDE.md to match the version bundled with the current mykg "
        "package. Existing user content outside the markers is preserved. "
        "Only meaningful with --profile agent-claude-code."
    ),
)
def init_config(
    force: bool,
    profile: str | None,
    model: str | None,
    api_key: str | None,
    reinstall_skill: bool,
    reinstall_claude_md: bool,
) -> None:
    """Create mykg_config.yaml and optionally configure LLM provider, model, and API key."""
    dest = Path.cwd() / "mykg_config.yaml"
    if dest.exists() and not force:
        # Short-circuit: --reinstall-skill on an existing agent-mode config refreshes the
        # bundled skill without touching the config. The canonical upgrade flow after
        # `pip install -U mykg`.
        if reinstall_skill or reinstall_claude_md:
            try:
                existing = dest.read_text()
            except OSError:
                existing = ""
            if "profile: agent-claude-code" in existing:
                if reinstall_skill:
                    _install_agent_skill(force=True)
                if reinstall_claude_md:
                    claude_status = _write_claude_md_snippet(Path.cwd(), refresh=True)
                    click.echo(f"[claude.md] {claude_status}")
                return
            click.echo(
                "--reinstall-skill / --reinstall-claude-md are only meaningful "
                "when the active profile is `agent-claude-code`. mykg_config.yaml "
                "uses a different profile; skipping refresh."
            )
            return
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
    if model is None and meta["default_model"] is not None:
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
        _print_next_steps(
            profile,
            reinstall_skill=reinstall_skill,
            reinstall_claude_md=reinstall_claude_md,
            force=force,
        )
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

    _print_next_steps(
        profile,
        reinstall_skill=reinstall_skill,
        reinstall_claude_md=reinstall_claude_md,
        force=force,
    )


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


_SKILL_VERSION_STAMP = ".mykg_skill_version"


def _claude_skills_dir() -> Path:
    """Return the user-level Claude Code skills folder.

    Resolution order:
      1. ``$CLAUDE_CONFIG_DIR/skills`` — explicit override (graphify-style).
      2. ``~/.claude/skills`` — macOS / Linux / Windows-Desktop default.
      3. ``%APPDATA%/Claude/skills`` — Windows fallback if it already exists
         on disk and ``~/.claude/skills`` does not (some Windows Claude Code
         builds put their config under ``%APPDATA%`` instead of ``%USERPROFILE%``).
      4. ``~/.claude/skills`` — final fallback (created by mkdir at install).

    The Windows fallback is only used when ``%APPDATA%/Claude/skills``
    actually exists; we never invent it just because we're on Windows.
    """
    override = os.environ.get("CLAUDE_CONFIG_DIR")
    if override:
        return Path(override) / "skills"

    home_claude = Path.home() / ".claude" / "skills"
    if home_claude.exists():
        return home_claude

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            appdata_claude = Path(appdata) / "Claude" / "skills"
            if appdata_claude.exists():
                return appdata_claude

    return home_claude  # the default — created by mkdir during install


def _manual_copy_hint(source: Path, target: Path) -> str:
    """Return a platform-appropriate manual-copy command for the fallback message."""
    if sys.platform == "win32":
        return f'xcopy /E /I "{source}" "{target}"'
    return f"cp -R {source} {target}"


def _install_agent_skill(*, force: bool = False) -> None:
    """Copy the bundled mykg skill into ~/.claude/skills/mykg.

    Uses graphify v8's atomic install pattern: copy to ``<target>.tmp``, then
    ``os.replace`` over the final destination. A ``.mykg_skill_version`` stamp
    file is written next to the skill so a future ``mykg init`` invocation can
    detect a stale install (package upgraded but skill not refreshed).

    Symlinks are intentionally NOT used — they break on Windows without
    Developer Mode, dangle if mykg is uninstalled, and don't sync through
    OneDrive. ``--reinstall-skill`` (force=True) is the canonical refresh
    path after ``pip install -U mykg``.
    """
    import mykg

    source = Path(mykg.__file__).parent / "data" / "skills" / "mykg"
    target_dir = _claude_skills_dir()
    target = target_dir / "mykg"
    stamp = target / _SKILL_VERSION_STAMP

    if not source.is_dir():
        click.echo(f"\n[skill] WARNING: bundled skill not found at {source}; skipping install.")
        return

    try:
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        click.echo(f"\n[skill] Could not create {target_dir}: {exc}")
        click.echo(f"        Copy manually: {_manual_copy_hint(source, target)}")
        return

    # Pre-existing target: decide between idempotent skip, version warning, or refusal.
    if target.exists() or target.is_symlink():
        if target.is_symlink():
            # Legacy installs created a symlink; replace it on --force.
            if not force:
                click.echo(
                    f"\n[skill] {target} is a legacy symlink. Re-run with --reinstall-skill "
                    "to replace it with a copy (the new default — safer on Windows / "
                    "OneDrive / after `pip uninstall mykg`)."
                )
                return
        elif stamp.is_file():
            try:
                installed_version = stamp.read_text().strip()
            except OSError:
                installed_version = "(unreadable)"
            if installed_version == mykg.__version__ and not force:
                click.echo(
                    f"\n[skill] Already installed at {target} (version {installed_version})."
                )
                return
            if installed_version != mykg.__version__ and not force:
                click.echo(
                    f"\n[skill] {target} is from mykg {installed_version}, package is "
                    f"{mykg.__version__}. Re-run with --reinstall-skill to update."
                )
                return
        elif not force:
            click.echo(
                f"\n[skill] {target} already exists but has no version stamp — it may be a "
                "hand-edited copy. Leaving it untouched. Re-run with --reinstall-skill to "
                f"overwrite, or remove it manually: rm -rf {target}"
            )
            return

    # Atomic copy: write to <target>.tmp, then os.replace.
    tmp = target.with_name(target.name + ".tmp")
    try:
        if tmp.exists() or tmp.is_symlink():
            if tmp.is_symlink() or tmp.is_file():
                tmp.unlink()
            else:
                shutil.rmtree(tmp)
        shutil.copytree(source, tmp)
    except OSError as exc:
        click.echo(f"\n[skill] Failed to copy {source} → {tmp}: {exc}")
        click.echo(f"        Copy manually: {_manual_copy_hint(source, target)}")
        return

    try:
        if target.exists() or target.is_symlink():
            if target.is_symlink() or target.is_file():
                target.unlink()
            else:
                shutil.rmtree(target)
        os.replace(tmp, target)
    except OSError as exc:
        click.echo(f"\n[skill] Failed to install {tmp} → {target}: {exc}")
        shutil.rmtree(tmp, ignore_errors=True)
        return

    try:
        (target / _SKILL_VERSION_STAMP).write_text(mykg.__version__)
    except OSError as exc:
        click.echo(f"[skill] Warning: could not write version stamp: {exc}")

    click.echo(f"\n[skill] Installed: {target} (version {mykg.__version__})")


_CLAUDE_MD_BEGIN = "<!-- BEGIN mykg-section (managed by `mykg init`; safe to edit) -->"
_CLAUDE_MD_END = "<!-- END mykg-section -->"


def _write_claude_md_snippet(target_dir: Path, *, refresh: bool) -> str:
    """Write or refresh the mykg-managed block in ``target_dir/CLAUDE.md``.

    Only call for the ``agent-claude-code`` profile — the snippet is tailored
    to Claude Code with the agent skill installed.

    Returns a one-line status string suitable for echo.
    """
    snippet_path = Path(__file__).parent / "data" / "claude_md_snippet.md"
    body = snippet_path.read_text(encoding="utf-8").rstrip("\n")
    block = f"{_CLAUDE_MD_BEGIN}\n{body}\n{_CLAUDE_MD_END}\n"

    claude_md = target_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(block, encoding="utf-8")
        return "wrote CLAUDE.md"

    existing = claude_md.read_text(encoding="utf-8", errors="replace")
    begin_idx = existing.find(_CLAUDE_MD_BEGIN)
    end_idx = existing.find(_CLAUDE_MD_END)

    if begin_idx == -1 or end_idx == -1 or end_idx < begin_idx:
        separator = "" if existing.endswith("\n\n") else "\n" if existing.endswith("\n") else "\n\n"
        claude_md.write_text(existing + separator + block, encoding="utf-8")
        return "appended mykg section to CLAUDE.md"

    end_line_end = existing.find("\n", end_idx)
    if end_line_end == -1:
        end_line_end = len(existing)
    current_block = existing[begin_idx : end_line_end + 1]
    expected_block = block if block.endswith("\n") else block + "\n"

    if current_block == expected_block:
        return "CLAUDE.md already has up-to-date mykg section"

    if not refresh:
        return (
            "CLAUDE.md mykg section is out of date — "
            "re-run `mykg init --reinstall-claude-md` to refresh"
        )

    new_content = existing[:begin_idx] + expected_block + existing[end_line_end + 1 :]
    claude_md.write_text(new_content, encoding="utf-8")
    return "refreshed mykg section in CLAUDE.md"


def _print_next_steps(
    profile: str,
    *,
    reinstall_skill: bool = False,
    reinstall_claude_md: bool = False,
    force: bool = False,
) -> None:
    if reinstall_skill and profile != "agent-claude-code":
        click.echo(
            "\n[skill] --reinstall-skill ignored: only meaningful with --profile agent-claude-code."
        )
    if reinstall_claude_md and profile != "agent-claude-code":
        click.echo(
            "\n[claude.md] --reinstall-claude-md ignored: only meaningful with --profile agent-claude-code."
        )

    click.echo("\nNext steps:")
    click.echo("  mykg extract-graph <your_notes_directory>/")
    if profile == "ollama-local":
        click.echo("  (make sure Ollama is running: ollama serve)")
    elif profile == "claude-cli":
        click.echo(
            "  (make sure the claude CLI is installed: npm install -g @anthropic-ai/claude-code)"
        )
    elif profile == "agent-claude-code":
        _install_agent_skill(force=reinstall_skill)
        claude_status = _write_claude_md_snippet(
            Path.cwd(), refresh=force or reinstall_claude_md
        )
        click.echo(f"[claude.md] {claude_status}")
        click.echo("\nThen, in Claude Code:")
        click.echo("  1. Restart the app so the skill loader picks up the new entry.")
        click.echo("  2. Type:  /mykg <your_notes_directory>")
        click.echo("\nUpgrade later with:  mykg init --reinstall-skill --reinstall-claude-md")
        click.echo("See docs/agent-mode.md for the full inbox/outbox contract.")


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
    help="Session name under mykg_sessions/ to resume or append; omit to auto-create",
)
@click.option(
    "--obsidian-vault",
    is_flag=True,
    default=False,
    help="Write an Obsidian vault to output/obsidian_vault/ (overrides config obsidian_enabled)",
)
@click.option(
    "--neo4j-csv",
    is_flag=True,
    default=False,
    help="Write a Neo4j LOAD CSV bundle to output/neo4j_csv/ (overrides config neo4j_csv_enabled)",
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
    neo4j_csv,
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

    if neo4j_csv:
        import mykg.config as _config_mod

        _config_mod.NEO4J_CSV_ENABLED = True

    from mykg.llm.error_gate import ErrorGate

    error_gate = (
        ErrorGate(threshold=_cfg().ERROR_GATE_THRESHOLD) if _cfg().ERROR_GATE_ENABLED else None
    )
    adapter = load_adapter(error_gate=error_gate, intermediate_dir=intermediate_dir)
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

    adapter = load_adapter(intermediate_dir=intermediate_dir)

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


# MinerU cannot convert HTML; the pipeline's `step_preprocess` routes HTML
# files through markdownify instead. `parse-docs` is MinerU-only and therefore
# always skips these suffixes regardless of `preprocess.extensions`.
_PARSE_DOCS_HARDCODED_SKIP: frozenset[str] = frozenset({".html", ".htm"})


def _build_parse_docs_targets(
    input_path: Path,
    output_path: Path,
    files: tuple[Path, ...],
    allowed_exts: frozenset[str] | None,
) -> tuple[list[tuple[Path, Path]], list[tuple[Path, str]]]:
    """Build (source, per-file-output-dir) targets for parse-docs.

    `allowed_exts` is the suffix allowlist from `preprocess.extensions`
    (lowercased, leading dot). Pass `None` to disable the allowlist and convert
    every non-`.md` candidate — the HTML hard-skip still applies. Returns
    `(targets, skipped)` where `skipped` is `[(path, reason), ...]` for files
    filtered out.

    Pure function: no I/O beyond `Path.is_file()` and `rglob()`; no mkdir.
    The caller creates output dirs after deciding what to act on.
    """
    targets: list[tuple[Path, Path]] = []
    skipped: list[tuple[Path, str]] = []

    def _passes_filter(p: Path) -> tuple[bool, str]:
        suffix = p.suffix.lower()
        if suffix == ".md":
            return False, "markdown is the native format"
        if suffix in _PARSE_DOCS_HARDCODED_SKIP:
            return (
                False,
                f"{suffix} is not supported by parse-docs (MinerU cannot convert HTML); "
                "use `mykg extract-graph` for HTML support via markdownify",
            )
        if allowed_exts is not None and suffix not in allowed_exts:
            return False, f"extension {suffix or '(none)'} not in preprocess.extensions"
        return True, ""

    if files:
        for f in files:
            resolved = f if f.is_absolute() else (input_path / f)
            ok, reason = _passes_filter(resolved)
            rel_parent = (
                f.parent if not f.is_absolute() and f.parent != Path(".") else Path()
            )
            per_file_out = output_path / rel_parent
            if ok:
                targets.append((resolved, per_file_out))
            else:
                skipped.append((resolved, reason))
    elif input_path.is_file():
        ok, reason = _passes_filter(input_path)
        if ok:
            targets.append((input_path, output_path))
        else:
            skipped.append((input_path, reason))
    else:
        # Recursive directory mode: rglob every candidate; filter; preserve
        # subfolder structure at the output.
        for src in sorted(input_path.rglob("*")):
            if not src.is_file():
                continue
            ok, reason = _passes_filter(src)
            if not ok:
                # Don't list .md files as "skipped" — they're trivially not
                # candidates and logging every one would be noise.
                if src.suffix.lower() != ".md":
                    skipped.append((src, reason))
                continue
            rel_parent = src.relative_to(input_path).parent
            per_file_out = output_path / rel_parent
            targets.append((src, per_file_out))

    return targets, skipped


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
@click.option(
    "--file",
    "files",
    multiple=True,
    type=click.Path(path_type=Path),
    help=(
        "Process only these files (relative to --input when --input is a directory). "
        "Repeatable. When omitted and --input is a directory, every non-md file "
        "under the directory is processed recursively."
    ),
)
@click.option(
    "--file-list",
    "file_list",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help=(
        "Read one file path per line from this file. Same semantics as --file "
        "but avoids the OS argv-size limit on large corpora. Mutually exclusive "
        "with --file."
    ),
)
@click.option(
    "--no-filter",
    is_flag=True,
    default=False,
    help=(
        "Disable the preprocess.extensions allowlist; send every non-.md file "
        "to MinerU. .html/.htm are still hard-skipped (MinerU cannot convert "
        "HTML). Use when you've already curated the input and want MinerU "
        "to attempt every other file regardless of suffix."
    ),
)
@click.argument("extra_args", nargs=-1, type=click.UNPROCESSED)
def parse_docs(
    input_path: Path,
    output_path: Path,
    files: tuple[Path, ...],
    file_list: Path | None,
    no_filter: bool,
    extra_args: tuple[str, ...],
) -> None:
    """Convert non-Markdown documents (PDF, DOCX, images, etc.) to Markdown using MinerU.

    Wraps `mineru -p INPUT -o OUTPUT`. MinerU runs inside an ephemeral
    Python venv created via `uv` (pinned to preprocess.uv_python_version)
    and deleted on exit; no MinerU bits are installed into mykg's own
    interpreter. Extra arguments after --output are passed through to mineru.

    Input shape:
      * `--input <file>` — process that single file.
      * `--input <dir>` — recursive: every non-md file under the directory
        is converted, subfolder structure preserved at the output.
      * `--file <rel>` (repeatable) — restrict to the named files,
        relative to --input when --input is a directory.
      * `--file-list <path>` — read one rel-path per line from a text file.
        Use this for large corpora to avoid the OS argv-size limit.

    File-extension filter:
      By default, candidate files are filtered against `preprocess.extensions`
      from mykg_config.yaml — the same allowlist `step_preprocess` applies
      upstream of pipeline-driven calls. Files whose suffix is not on the list
      (e.g. `.DS_Store`, `.css`, `.svg` sidecars) are logged and skipped
      before MinerU is invoked. `.html` and `.htm` are always hard-skipped
      because MinerU cannot convert HTML — use `mykg extract-graph` if you
      need HTML support via markdownify. Pass `--no-filter` to disable the
      allowlist (the HTML hard-skip still applies). When the filter empties
      the target list, `parse-docs` exits clean before building the
      multi-GB ephemeral venv.

    All files share a single ephemeral venv — MinerU is invoked once per file
    inside that venv, so the multi-GB install cost is paid at most once per
    `parse-docs` call regardless of file count.

    Per-file MinerU failures are logged and the loop continues; parse-docs
    exits non-zero at the end if any file failed. Timeouts remain fatal.
    """
    from mykg import config as _cfg
    from mykg.uv_venv import ephemeral_mineru_venv

    if files and file_list is not None:
        raise click.UsageError("--file and --file-list are mutually exclusive.")
    if file_list is not None:
        files = tuple(
            Path(line)
            for line in file_list.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    allowed_exts = None if no_filter else _cfg.PREPROCESS_EXTENSIONS
    targets, skipped = _build_parse_docs_targets(
        input_path, output_path, files, allowed_exts
    )

    if skipped:
        for src, reason in skipped:
            click.echo(f"Skipping {src}: {reason}", err=True)
        click.echo(f"Skipped {len(skipped)} file(s) — see lines above.", err=True)

    if not targets:
        # Nothing to do — exit clean rather than build the ephemeral venv.
        # Without this guard a `parse-docs` against a directory of only
        # `.DS_Store` files would pay the multi-GB MinerU install for nothing.
        click.echo(
            f"No files to convert{' after filtering' if skipped else ''}.",
            err=True,
        )
        return

    with ephemeral_mineru_venv(
        _cfg.PREPROCESS_UV_PYTHON_VERSION,
        _cfg.PREPROCESS_MINERU_SPEC,
        _cfg.PREPROCESS_UV_PATH,
        _cfg.PREPROCESS_INSTALL_TIMEOUT_SECONDS,
    ) as mineru_bin:
        output_path.mkdir(parents=True, exist_ok=True)
        for _, dst in targets:
            dst.mkdir(parents=True, exist_ok=True)

        failures: list[tuple[Path, int | str]] = []
        for src, dst in targets:
            cmd = [str(mineru_bin), "-p", str(src), "-o", str(dst)] + list(extra_args)
            click.echo(f"Running: {' '.join(cmd)}")

            try:
                proc = subprocess.run(
                    cmd,
                    check=False,
                    timeout=_cfg.PREPROCESS_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                # Timeouts are still fatal — they signal the venv or the
                # underlying process is stuck, not a per-file format issue.
                raise click.ClickException(
                    f"mineru timed out after {_cfg.PREPROCESS_TIMEOUT_SECONDS}s"
                ) from exc

            if proc.returncode != 0:
                click.echo(
                    f"mineru exited with code {proc.returncode} on {src} — continuing",
                    err=True,
                )
                failures.append((src, proc.returncode))

    if failures:
        click.echo(
            f"Done. {len(targets) - len(failures)}/{len(targets)} files converted. "
            f"{len(failures)} failed — output under: {output_path}",
            err=True,
        )
        raise click.ClickException(
            f"{len(failures)} of {len(targets)} files failed conversion"
        )
    click.echo(f"Done. Output written to: {output_path}")


@cli.command("fetch-web")
@click.argument("url")
@click.option("--output", default=None, type=click.Path(path_type=Path),
              help="Target folder (default: ./fetched_web/<domain>/).")
@click.option("--max-pages", default=None, type=int, help="Cap on total fetched pages.")
@click.option("--max-depth", default=None, type=int, help="Max crawl depth from seed.")
@click.option("--strategy", default=None,
              type=click.Choice(["same-domain", "same-origin", "all"]),
              help="Link-following scope (default from config; 'all' leaves the domain).")
@click.option("--download-assets/--no-download-assets", default=None,
              help="Download linked binaries in preprocess.extensions (default from config).")
@click.option("--delay", default=None, type=float, help="Per-request delay seconds.")
@click.option("--concurrency", default=None, type=int, help="Max concurrent requests.")
@click.option("--no-robots", is_flag=True, help="Disable robots.txt compliance.")
@click.option("--force", is_flag=True, help="Ignore prior manifest; re-fetch everything.")
@click.option("--verbose", "-v", is_flag=True, help="Enable DEBUG-level logging.")
def fetch_web(url, output, max_pages, max_depth, strategy, download_assets,
              delay, concurrency, no_robots, force, verbose):
    """Crawl a website and save raw HTML + fetch_manifest.json into a folder.

    The folder is a normal `extract-graph` input: the preprocess step converts
    the saved HTML to Markdown (and any downloaded PDFs/DOCX via MinerU). Crawlee
    runs inside an ephemeral uv venv that is destroyed on exit — nothing about
    the crawler is installed into mykg's own interpreter.

    Example:
        mykg fetch-web https://example.com
        mykg extract-graph ./fetched_web/example.com/
    """
    from mykg.logging import setup

    setup(log_file=None, verbose=verbose)

    from mykg import config as _cfg
    from mykg import fetch_web as fw

    if not _cfg.FETCH_ENABLED:
        raise click.ClickException(
            "fetch-web is disabled (fetch.enabled: false in mykg_config.yaml)"
        )

    out_dir = Path(output) if output else fw.default_output_dir(url)
    out_dir.mkdir(parents=True, exist_ok=True)

    prior = {} if force else fw.load_manifest(out_dir)

    strat = strategy or _cfg.FETCH_STRATEGY
    dl_assets = _cfg.FETCH_DOWNLOAD_ASSETS if download_assets is None else download_assets
    allowed = sorted(_cfg.PREPROCESS_EXTENSIONS) if dl_assets else []

    crawl_cfg = fw.build_crawl_config(
        seed_url=url,
        output_dir=str(out_dir),
        strategy=strat,
        max_pages=max_pages if max_pages is not None else _cfg.FETCH_MAX_PAGES,
        max_depth=max_depth if max_depth is not None else _cfg.FETCH_MAX_DEPTH,
        respect_robots=(False if no_robots else _cfg.FETCH_RESPECT_ROBOTS),
        request_delay_seconds=delay if delay is not None else _cfg.FETCH_REQUEST_DELAY_SECONDS,
        concurrency=concurrency if concurrency is not None else _cfg.FETCH_CONCURRENCY,
        allowed_asset_exts=allowed,
    )
    crawl_cfg["already_fetched"] = {u: e.get("sha256") for u, e in prior.items()}

    config_path = out_dir / ".fetch_config.json"
    config_path.write_text(json.dumps(crawl_cfg, indent=2), encoding="utf-8")

    runner = Path(__file__).parent / "data" / "_crawl_runner.py"

    click.echo(f"Crawling {url} → {out_dir} (strategy={strat}, max_pages={crawl_cfg['max_pages']})")
    with ephemeral_venv(
        _cfg.FETCH_UV_PYTHON_VERSION,
        _cfg.FETCH_CRAWLEE_SPEC,
        _cfg.FETCH_UV_PATH,
        _cfg.FETCH_INSTALL_TIMEOUT_SECONDS,
        bin_name="python",
        prefix="mykg-crawl-venv-",
    ) as venv_python:
        try:
            proc = subprocess.run(
                [str(venv_python), str(runner), str(config_path)],
                check=False,
                timeout=_cfg.FETCH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise click.ClickException(
                f"crawl timed out after {_cfg.FETCH_TIMEOUT_SECONDS}s"
            ) from exc
        if proc.returncode != 0:
            raise click.ClickException(f"crawl runner failed with exit code {proc.returncode}")

    results_path = out_dir / ".fetch_results.json"
    if not results_path.exists():
        raise click.ClickException("crawl runner produced no results file")
    results = json.loads(results_path.read_text(encoding="utf-8"))

    merged = dict(prior)
    merged.update(results.get("pages", {}))
    fw.write_manifest(
        out_dir, seed_url=url, strategy=strat,
        pages=merged, stats=results.get("stats", {}),
        crawlee_version=results.get("crawlee_version", ""),
    )
    # Manifest is durable; the runner's transient I/O files are not — drop them
    # so they don't leak into the extract-graph input folder. Only removed after
    # the manifest write succeeds, so earlier failures leave them for debugging.
    config_path.unlink(missing_ok=True)
    results_path.unlink(missing_ok=True)
    click.echo(
        f"Done. {results.get('stats', {}).get('pages', 0)} pages, "
        f"{results.get('stats', {}).get('assets', 0)} assets → {out_dir}\n"
        f"Next: mykg extract-graph {out_dir}/"
    )


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

    # obsidian_vault/ and neo4j_csv/ are written by validate_graph but not tracked in
    # Step.outputs (they are optional; omitting them prevents _is_done from breaking
    # when disabled). Delete them when re-running from validate_graph or any earlier step.
    validate_graph_idx = (
        step_names.index("validate_graph") if "validate_graph" in step_names else -1
    )
    if validate_graph_idx >= 0 and idx <= validate_graph_idx:
        obsidian_path = output_dir / _cfg().OBSIDIAN_VAULT_DIR
        if obsidian_path.exists():
            shutil.rmtree(obsidian_path)
            click.echo(f"Deleted {obsidian_path}")
        neo4j_csv_path = output_dir / _cfg().NEO4J_CSV_DIR
        if neo4j_csv_path.exists():
            shutil.rmtree(neo4j_csv_path)
            click.echo(f"Deleted {neo4j_csv_path}")

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
