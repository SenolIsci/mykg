"""
Central configuration for the mykg pipeline.

All values are loaded from ``pipeline_config.yaml`` (searched upward from cwd).
This module exposes named constants that the rest of the codebase imports.
There are no hardcoded fallback values here — every constant is set from the YAML file.

The full configuration file is also stored as ``RAW`` for use by llm/config.py
when it constructs LLM adapters.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# Locate and load pipeline_config.yaml
# ---------------------------------------------------------------------------


def _find_config() -> Path:
    here = Path.cwd()
    for directory in [here, *here.parents]:
        candidate = directory / "pipeline_config.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        "pipeline_config.yaml not found. "
        "Run 'mykg init' in your project directory to create one from the default template."
    )


def _load() -> dict:
    path = _find_config()
    with open(path) as f:
        return yaml.safe_load(f)


def _apply_profile(raw: dict) -> dict:
    """Resolve the active profile into the top-level provider + pipeline keys.

    Each profile is fully self-contained — it has its own `provider` and complete
    `pipeline` block. The active profile replaces the top-level values entirely;
    there is no merging with a base pipeline section.
    """
    profile_name = raw.get("profile")
    if not profile_name:
        return raw
    profiles = raw.get("profiles", {})
    if profile_name not in profiles:
        raise KeyError(
            f"Profile '{profile_name}' not found in pipeline_config.yaml. "
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
    return result


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

# ---------------------------------------------------------------------------
# Pass 2
# ---------------------------------------------------------------------------
PASS2_MAX_WORKERS: int = _get("pass2", "max_workers")
PASS2_STATEFUL_CHUNKS: bool = _get("pass2", "stateful_chunks")
PASS2_PREP_MODE: str = _get_opt("pass2", "prep_mode", "per_file")
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
LOG_CAPTURE_PROMPTS: bool = bool(_get_opt("logging", "capture_prompts", False))
LOG_ERROR_OUTPUT_MAX_CHARS: int = int(_get_opt("logging", "error_output_max_chars", 500))

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
MERGE_ORPHAN_SCHEMA_MAX_RESTARTS: int = _get_opt(
    "merge_graphs", "orphan_pass_max_restarts", 1
)
