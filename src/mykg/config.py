"""
Central configuration for the mykg pipeline.

All values are loaded from ``mykg_config.yaml`` (searched upward from cwd).
This module exposes named constants that the rest of the codebase imports.
There are no hardcoded fallback values here — every constant is set from the YAML file.

The full configuration file is also stored as ``RAW`` for use by llm/config.py
when it constructs LLM adapters.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Run-only profile/model overrides (set by the CLI --profile / --model flags).
#
# These live in os.environ rather than module globals because activate_profile()
# re-resolves the whole module via importlib.reload(), which re-executes the
# module body and would reset any plain module global back to its default. The
# environment survives the reload, so _apply_profile() can read the override on
# the reloaded copy. They are never written to mykg_config.yaml — the on-disk
# config is untouched.
# ---------------------------------------------------------------------------
_PROFILE_OVERRIDE_ENV = "MYKG_PROFILE_OVERRIDE"
_MODEL_OVERRIDE_ENV = "MYKG_MODEL_OVERRIDE"

# ---------------------------------------------------------------------------
# Locate and load mykg_config.yaml
# ---------------------------------------------------------------------------


def _find_config() -> Path:
    here = Path.cwd()
    for directory in [here, *here.parents]:
        candidate = directory / "mykg_config.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "mykg_config.yaml not found. "
        "Run 'mykg init' in your project directory to create one from the default template."
    )


def _load() -> dict:
    path = _find_config()
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _apply_profile(raw: dict) -> dict:
    """Resolve the active profile into the top-level provider + pipeline keys.

    Each profile is fully self-contained — it has its own `provider` and complete
    `pipeline` block. The active profile replaces the top-level values entirely;
    there is no merging with a base pipeline section.
    """
    # A run-only --profile override (set by the CLI) wins over the YAML profile:.
    profile_name = os.environ.get(_PROFILE_OVERRIDE_ENV) or raw.get("profile")
    if not profile_name:
        return raw
    profiles = raw.get("profiles", {})
    if profile_name not in profiles:
        raise KeyError(
            f"Profile '{profile_name}' not found in mykg_config.yaml. "
            f"Available profiles: {list(profiles.keys())}"
        )
    import copy

    result = copy.deepcopy(raw)
    profile = profiles[profile_name]
    if "provider" in profile:
        result["provider"] = profile["provider"]
    if "pipeline" in profile:
        result["pipeline"] = profile["pipeline"]
    if "llm" in profile:
        result["llm"] = profile["llm"]
    if "llm_retry" in profile:
        result["llm_retry"] = profile["llm_retry"]
    if "agent" in profile:
        result["agent"] = profile["agent"]
    if "mcp" in profile:
        result["mcp"] = profile["mcp"]

    # A run-only --model override replaces just the model inside the resolved llm block.
    model_override = os.environ.get(_MODEL_OVERRIDE_ENV)
    if model_override and "llm" in result:
        result["llm"] = {**result["llm"], "model": model_override}

    return result


def activate_profile(profile_name: str, model: str | None = None) -> None:
    """Re-resolve every config constant against ``profile_name`` for this run only.

    This is the backing implementation of ``extract-graph --profile/--model``. It
    records the override in the environment, then reloads this module so the whole
    flat block of constants (RAW, PASS2_MAX_WORKERS, chunking, timeouts, …) is
    rebuilt from the selected profile — exactly as if ``profile: <name>`` were set
    in mykg_config.yaml. It never writes to disk.

    Raises ``ValueError`` if the profile is not declared in ``profiles:``.
    """
    profiles = _load().get("profiles", {})
    if profile_name not in profiles:
        raise ValueError(
            f"Profile '{profile_name}' not found in mykg_config.yaml. "
            f"Available profiles: {list(profiles.keys())}"
        )
    os.environ[_PROFILE_OVERRIDE_ENV] = profile_name
    if model:
        os.environ[_MODEL_OVERRIDE_ENV] = model
    else:
        os.environ.pop(_MODEL_OVERRIDE_ENV, None)
    try:
        importlib.reload(sys.modules[__name__])
    finally:
        # The reloaded module has already baked the override into its constants,
        # so the env vars have done their job. Clear them so an unrelated later
        # reload (e.g. an embedded second run in the same process) falls back to
        # the YAML-default profile instead of silently re-applying this override.
        os.environ.pop(_PROFILE_OVERRIDE_ENV, None)
        os.environ.pop(_MODEL_OVERRIDE_ENV, None)


CONFIG_PATH: Path = _find_config()
RAW: dict = _apply_profile(_load())

_p = RAW.get("pipeline", {})


def _get(section: str, key: str):
    return _p[section][key]


def _get_opt(section: str, key: str, default):
    return _p.get(section, {}).get(key, default)


# ---------------------------------------------------------------------------
# Chunking (D1, D20)
# ---------------------------------------------------------------------------
CHUNK_WINDOW_TOKENS: int = _get("chunking", "window_tokens")
CHUNK_OVERLAP_TOKENS: int = _get("chunking", "overlap_tokens")
CHUNK_TIKTOKEN_ENCODING: str = _get("chunking", "tiktoken_encoding")

# ---------------------------------------------------------------------------
# Pass 1
# ---------------------------------------------------------------------------
PASS1_BATCH_TOKEN_TARGET: int = _get("pass1", "batch_token_target")
PASS1_MAX_WORKERS: int = _get("pass1", "max_workers")
PASS1_PER_FILE_BATCHING: bool = _get_opt("pass1", "per_file_batching", False)
PASS1_MAX_SCHEMA_PROPOSALS: int = _get_opt("pass1", "max_schema_proposals", 50)
PASS1_RANDOM_SEED: int = _get_opt("pass1", "random_seed", 0)

# ---------------------------------------------------------------------------
# Pass 2
# ---------------------------------------------------------------------------
PASS2_MAX_WORKERS: int = _get("pass2", "max_workers")
PASS2_STATEFUL_CHUNKS: bool = _get("pass2", "stateful_chunks")
PASS2_PREP_MODE: str = _get_opt("pass2", "prep_mode", "batch_chunks")
PASS2_CONCAT_BATCH_TOKEN_TARGET: int = _get_opt("pass2", "concat_batch_token_target", 100000)
PASS2_BATCH_TOKEN_TARGET: int = _get_opt("pass2", "batch_token_target", 100000)
PASS2_BATCH_PER_FILE: bool = _get_opt("pass2", "batch_per_file", False)
PASS2_BATCH_RETRY_MAX: int = _get_opt("pass2", "batch_retry_max", 1)

# ---------------------------------------------------------------------------
# Ingest (Invariant 12)
# ---------------------------------------------------------------------------
INGEST_MAX_WORKERS: int = _get("ingest", "max_workers")

# ---------------------------------------------------------------------------
# Assembly (D9, D10, D19, D22)
# ---------------------------------------------------------------------------
ASSEMBLY_CONFIDENCE_AGG: str = _get("assembly", "confidence_agg")
ASSEMBLY_EDGE_ID_PREFIX: str = _get("assembly", "edge_id_prefix")
ASSEMBLY_EDGE_ID_HEX_LENGTH: int = _get("assembly", "edge_id_hex_length")
ASSEMBLY_EDGE_DEDUP_SEPARATOR: str = _get("assembly", "edge_dedup_separator")
CONFIDENCE_FALLBACK: float = _get("assembly", "confidence_fallback")
CONFIDENCE_SCALAR_OMITTED: float = _get("assembly", "confidence_scalar_omitted")

# ---------------------------------------------------------------------------
# RDF / Turtle namespaces (D14, D15, exporter + validator + base_schema)
# ---------------------------------------------------------------------------
TTL_NAMESPACE_SCHEMA: str = _get("export", "schema_namespace")
TTL_NAMESPACE_DATA: str = _get("export", "data_namespace")
TTL_NAMESPACE_RDF: str = _get("export", "rdf_namespace")
TTL_NAMESPACE_RDFS: str = _get("export", "rdfs_namespace")
TTL_SCHEMA_PREFIX_LABEL: str = _get("export", "schema_prefix_label")
TTL_DATA_PREFIX_LABEL: str = _get("export", "data_prefix_label")
TTL_COMMENT_WIDTH: int = _get("export", "comment_width")
TTL_NAMESPACE_SKOS: str = _get("export", "skos_namespace")
NETWORKX_ENABLED: bool = _get("export", "networkx_enabled")
OBSIDIAN_ENABLED: bool = _get_opt("export", "obsidian_enabled", False)
OBSIDIAN_VAULT_DIR: str = _get_opt("export", "obsidian_vault_dir", "obsidian_vault")
NEO4J_CSV_ENABLED: bool = _get_opt("export", "neo4j_csv_enabled", False)
NEO4J_CSV_DIR: str = _get_opt("export", "neo4j_csv_dir", "neo4j_csv")

# ---------------------------------------------------------------------------
# Output / intermediate paths (D16, D18)
# ---------------------------------------------------------------------------
OUTPUT_DIR: str = _get("paths", "output_dir")
INTERMEDIATE_DIR: str = _get("paths", "intermediate_dir")
SESSIONS_DIR: str = _get("paths", "sessions_dir")

# ---------------------------------------------------------------------------
# Name normalization — Step 6b (D29)
# ---------------------------------------------------------------------------
NORMALIZE_NAMES_ENABLED: bool = _get("normalize_names", "enabled")
NORMALIZE_NAMES_MAX_PER_TYPE: int = _get("normalize_names", "max_names_per_type")
NORMALIZE_NAMES_BATCH_TOKEN_TARGET: int = _get_opt("normalize_names", "batch_token_target", 60000)

# ---------------------------------------------------------------------------
# Orphan-connection pass (two-stage: co-occurrence heuristic + LLM confirmation)
# ---------------------------------------------------------------------------
ORPHAN_PASS_ENABLED: bool = _get("orphan_pass", "enabled")
ORPHAN_MIN_COOCCURRENCE: int = _get("orphan_pass", "min_cooccurrence")
ORPHAN_TOP_K_PER_ORPHAN: int = _get("orphan_pass", "top_k_per_orphan")
ORPHAN_CONFIDENCE_BASE: float = _get("orphan_pass", "confidence_base")
ORPHAN_CONFIDENCE_WEIGHT: float = _get("orphan_pass", "confidence_weight")
ORPHAN_MAX_WORKERS: int = _get("orphan_pass", "max_workers")
ORPHAN_SCHEMA_MAX_RESTARTS: int = _get("orphan_pass", "schema_max_restarts")
ORPHAN_EXCERPT_WINDOW: int = _get("orphan_pass", "excerpt_window")
ORPHAN_EXCERPT_CONTEXT: int = _get("orphan_pass", "excerpt_context")
ORPHAN_EXCERPT_MAX_TOTAL: int = _get("orphan_pass", "excerpt_max_total")
ORPHAN_BLANK_RECOVERY_ENABLED: bool = _get("orphan_pass", "blank_recovery_enabled")
ORPHAN_CONNECTED_SAMPLE_SIZE: int = _get("orphan_pass", "connected_sample_size")

# ---------------------------------------------------------------------------
# LLM retry — empty-response retry (all call sites); top-level key in YAML
# ---------------------------------------------------------------------------
LLM_RETRY_MAX_RETRIES: int = RAW["llm_retry"]["max_retries"]

# ---------------------------------------------------------------------------
# LLM 429 retry — exponential backoff on rate-limit errors (D13 / to-do #123)
# ---------------------------------------------------------------------------
LLM_RETRY_429_MAX: int = RAW["llm"]["retry_429_max"]
LLM_RETRY_429_BASE_DELAY: float = RAW["llm"]["retry_429_base_delay"]

# ---------------------------------------------------------------------------
# Feedback (D17)
# ---------------------------------------------------------------------------
FEEDBACK_MAX_FILE_CHARS: int = _get("feedback", "max_file_chars")

# ---------------------------------------------------------------------------
# Logging — log file rotation
# ---------------------------------------------------------------------------
LOG_MAX_BYTES: int = _get("logging", "max_bytes")
LOG_BACKUP_COUNT: int = _get("logging", "backup_count")
LOG_LLM_LOG: bool = bool(_get_opt("logging", "llm_log", True))
LOG_CAPTURE_PROMPTS: bool = bool(_get_opt("logging", "capture_prompts", False))
LOG_ERROR_OUTPUT_MAX_CHARS: int = int(_get_opt("logging", "error_output_max_chars", 500))

# ---------------------------------------------------------------------------
# Preprocess — optional document conversion before ingest (D39–D48)
# MinerU runs in an ephemeral uv-managed venv created per parse-docs call;
# nothing about MinerU is installed into mykg's own interpreter. The four
# PREPROCESS_UV_* / _MINERU_SPEC / _INSTALL_TIMEOUT keys control that venv.
# ---------------------------------------------------------------------------
PREPROCESS_ENABLED: bool = bool(_get_opt("preprocess", "enabled", False))
PREPROCESS_SUBDIR: str = _get_opt("preprocess", "subdir", "_preprocessed")
PREPROCESS_KEEP_ARTIFACTS: bool = bool(_get_opt("preprocess", "keep_artifacts", False))
PREPROCESS_EXTRA_ARGS: list = list(_get_opt("preprocess", "extra_args", []) or [])
PREPROCESS_TIMEOUT_SECONDS: int = int(_get_opt("preprocess", "timeout_seconds", 1800))
PREPROCESS_UV_PATH: str = _get_opt("preprocess", "uv_path", "uv")
PREPROCESS_UV_PYTHON_VERSION: str = _get_opt("preprocess", "uv_python_version", "3.12")
PREPROCESS_MINERU_SPEC: str = _get_opt("preprocess", "mineru_spec", "mineru[all]")
PREPROCESS_INSTALL_TIMEOUT_SECONDS: int = int(
    _get_opt("preprocess", "install_timeout_seconds", 1800)
)
# Allowlist of file extensions the preprocess step is permitted to convert.
# `.md` is the pipeline's native format and never appears here. Suffixes in
# this list are routed to the appropriate backend by step_preprocess based on
# an internal mapping (HTML → markdownify in-process; everything else →
# MinerU subprocess). Anything outside this list is logged + recorded in
# preprocess_manifest.json under "skipped_files" and left untouched on disk.
# Suffixes are matched case-insensitively and must include the leading dot.
PREPROCESS_EXTENSIONS: frozenset[str] = frozenset(
    str(ext).lower()
    for ext in _get_opt(
        "preprocess",
        "extensions",
        [".pdf", ".docx", ".doc", ".pptx", ".png", ".jpg", ".jpeg", ".html", ".htm", ".txt"],
    )
)

# ---------------------------------------------------------------------------
# Fetch-web — standalone website crawler (Crawlee in an ephemeral uv venv).
# Mirrors the preprocess MinerU venv pattern (D48): nothing about Crawlee is
# installed into mykg's own interpreter. The crawler writes raw HTML + a
# fetch_manifest.json into a folder that `extract-graph` then consumes.
# The asset allowlist reuses PREPROCESS_EXTENSIONS — no separate fetch list.
# ---------------------------------------------------------------------------
FETCH_ENABLED: bool = bool(_get_opt("fetch", "enabled", True))
FETCH_OUTPUT_DIR: str = _get_opt("fetch", "output_dir", "mykg_web_fetch")
FETCH_STRATEGY: str = _get_opt("fetch", "strategy", "same-domain")
FETCH_MAX_PAGES: int = int(_get_opt("fetch", "max_pages", 500))
FETCH_MAX_DEPTH: int = int(_get_opt("fetch", "max_depth", 10))
FETCH_RESPECT_ROBOTS: bool = bool(_get_opt("fetch", "respect_robots", True))
FETCH_REQUEST_DELAY_SECONDS: float = float(_get_opt("fetch", "request_delay_seconds", 0.5))
FETCH_CONCURRENCY: int = int(_get_opt("fetch", "concurrency", 4))
FETCH_DOWNLOAD_ASSETS: bool = bool(_get_opt("fetch", "download_assets", True))
FETCH_TIMEOUT_SECONDS: int = int(_get_opt("fetch", "timeout_seconds", 1800))
FETCH_UV_PATH: str = _get_opt("fetch", "uv_path", "uv")
FETCH_UV_PYTHON_VERSION: str = _get_opt("fetch", "uv_python_version", "3.12")
FETCH_CRAWLEE_SPEC: str = _get_opt("fetch", "crawlee_spec", "crawlee[beautifulsoup]")
FETCH_INSTALL_TIMEOUT_SECONDS: int = int(_get_opt("fetch", "install_timeout_seconds", 1800))
FETCH_GITHUB_CLONE_ENABLED: bool = bool(_get_opt("fetch", "github_clone_enabled", True))
FETCH_GITHUB_CLONE_DEPTH: int = int(_get_opt("fetch", "github_clone_depth", 1))
FETCH_GITHUB_CLONE_TIMEOUT_SECONDS: int = int(
    _get_opt("fetch", "github_clone_timeout_seconds", 1800)
)
FETCH_MAX_WORKERS: int = int(_get_opt("fetch", "max_workers", 2))

# ---------------------------------------------------------------------------
# JSON pretty-print (all intermediate files)
# ---------------------------------------------------------------------------
JSON_INDENT: int = _get("output", "json_indent")

# ---------------------------------------------------------------------------
# Error gate — pause pipeline on accumulated API errors (429s, timeouts)
# ---------------------------------------------------------------------------
_eg = _p.get("error_gate", {})
ERROR_GATE_ENABLED: bool = _eg.get("enabled", True)
ERROR_GATE_THRESHOLD: int = _eg.get("threshold", 3)

# ---------------------------------------------------------------------------
# Post-run walkthrough report (D32-adjacent)
# ---------------------------------------------------------------------------
REPORT_ENABLED: bool = bool(_get_opt("report", "enabled", True))

# ---------------------------------------------------------------------------
# Merge-graphs CLI command (D38)
# ---------------------------------------------------------------------------
MERGE_GRAPHS_REEXTRACTION_STRATEGY: str = _get("merge_graphs", "reextraction_strategy")
_VALID_REEXTRACTION_STRATEGIES = {"none", "surgical", "full"}
if MERGE_GRAPHS_REEXTRACTION_STRATEGY not in _VALID_REEXTRACTION_STRATEGIES:
    raise ValueError(
        f"merge_graphs.reextraction_strategy must be one of "
        f"{sorted(_VALID_REEXTRACTION_STRATEGIES)}, "
        f"got: {MERGE_GRAPHS_REEXTRACTION_STRATEGY!r}"
    )
MERGE_GRAPHS_HUMAN_REVIEW: bool = bool(_get_opt("merge_graphs", "human_review", False))
MERGE_SURGICAL_TOP_K_CHUNKS_PER_PROPERTY: int = _get_opt(
    "merge_graphs", "surgical_top_k_chunks_per_property", 0
)
MERGE_ORPHAN_SCHEMA_MAX_RESTARTS: int = _get_opt("merge_graphs", "orphan_pass_max_restarts", 1)

# ---------------------------------------------------------------------------
# Append — incremental schema growth (--append-with-grow-schema, D52)
# ---------------------------------------------------------------------------
# Cap on how many old chunks are surgically re-extracted per newly added
# concept/property when the locked Pass 1 grows the schema. 0 = disable
# back-fill entirely. Mirrors merge_graphs.surgical_top_k_chunks_per_property.
APPEND_GROW_SCHEMA_BACKFILL_TOP_K_CHUNKS_PER_TYPE: int = _get_opt(
    "append", "grow_schema_backfill_top_k_chunks_per_type", 10
)

# ---------------------------------------------------------------------------
# Agent provider (D49) — inbox/outbox filesystem contract with host skill
# ---------------------------------------------------------------------------
# These are only consumed when the active profile sets `provider: agent`.
# Defaults are used when the active profile has no `agent:` block (other
# providers do not need them).
_agent = RAW.get("agent") or {}
AGENT_INBOX_DIR: str = _agent.get("inbox_dir", "agent_inbox")
AGENT_OUTBOX_DIR: str = _agent.get("outbox_dir", "agent_outbox")
AGENT_POLL_INTERVAL_SECONDS: float = float(_agent.get("poll_interval_seconds", 2))

# ---------------------------------------------------------------------------
# MCP server — `mykg mcp-serve` settings (top-level, not profile-scoped)
# ---------------------------------------------------------------------------
_mcp = RAW.get("mcp") or {}
MCP_ENABLED: bool = bool(_mcp.get("enabled", False))
MCP_HOST: str = _mcp.get("host", "localhost")
MCP_PORT: int = int(_mcp.get("port", 3100))
MCP_TRANSPORT: str = _mcp.get("transport", "stdio")