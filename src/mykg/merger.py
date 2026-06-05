from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from copy import deepcopy
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict

from mykg import config as _cfg
from mykg.chunker import chunk_file
from mykg.llm.adapter import LLMAdapter
from mykg.logging import get
from mykg.pass2 import run_pass2, run_pass2_batched
from mykg.schema_merge import (
    harmonize_schema_for_merge,
    merge_proposals,
    review_schema_quality_for_merge,
)
from mykg.thesaurus import SynonymIndex

log = get("mykg.merger")


# ---------------------------------------------------------------------------
# SessionData model (Unit 1)
# ---------------------------------------------------------------------------


class SessionData(BaseModel):
    """All data loaded from one pipeline session."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str  # session folder name, e.g. "2026-05-10T14-32-00"
    path: Path  # path to session root (mykg_sessions/<name>)
    schema: dict  # parsed schema.json content
    raw_extractions: dict  # parsed raw_extractions.json content (file-keyed)
    shards: dict[str, dict]  # filename -> shard data from raw_extractions_shards/
    manifest: dict  # parsed file_manifest.json (may be empty dict if missing)
    prep_mode: str  # pass2.prep_mode from the session's mykg_config.yaml snapshot


# ---------------------------------------------------------------------------
# load_session (Unit 1)
# ---------------------------------------------------------------------------


def load_session(session_name: str, sessions_root: Path) -> SessionData:
    """Load all data for one pipeline session.

    Parameters
    ----------
    session_name:
        Folder name under sessions_root, e.g. "2026-05-10T14-32-00".
    sessions_root:
        Parent directory that contains session folders.

    Returns
    -------
    SessionData
        Fully populated model with schema, extractions, shards, manifest, and
        prep_mode.

    Raises
    ------
    FileNotFoundError
        If schema.json or raw_extractions.json are absent (session incomplete).
    """
    session_path = sessions_root / session_name
    intermediate = session_path / "intermediate"

    # Required: schema.json
    schema_path = intermediate / "schema.json"
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Session {session_name} has no schema.json — run `mykg extract-graph` first"
        )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    log.debug(
        "merger: loaded schema.json from session %s (%d concepts)",
        session_name,
        len(schema.get("concepts", [])),
    )

    # Required: raw_extractions.json
    extractions_path = intermediate / "raw_extractions.json"
    if not extractions_path.exists():
        raise FileNotFoundError(
            f"Session {session_name} has no raw_extractions.json — run `mykg extract-graph` first"
        )
    raw_extractions = json.loads(extractions_path.read_text(encoding="utf-8"))
    log.debug(
        "merger: loaded raw_extractions.json from session %s (%d files)",
        session_name,
        len(raw_extractions),
    )

    # Shards: raw_extractions_shards/*.json keyed by shard _fname
    shards: dict[str, dict] = {}
    shards_dir = intermediate / "raw_extractions_shards"
    if shards_dir.is_dir():
        for shard_file in sorted(shards_dir.glob("*.json")):
            try:
                shard_data = json.loads(shard_file.read_text(encoding="utf-8"))
                fname = shard_data.get("_fname", shard_file.stem)
                shards[fname] = shard_data
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("merger: could not read shard %s — %s", shard_file, exc)
    log.debug("merger: loaded %d shard(s) from session %s", len(shards), session_name)

    # Optional: file_manifest.json
    manifest: dict = {}
    manifest_path = intermediate / "file_manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning(
                "merger: could not read file_manifest.json for session %s — %s",
                session_name,
                exc,
            )
    log.debug("merger: manifest has %d file(s) for session %s", len(manifest), session_name)

    # Optional: prep_mode from mykg_config.yaml snapshot
    prep_mode = _read_prep_mode(session_path)
    log.debug("merger: prep_mode=%s for session %s", prep_mode, session_name)

    return SessionData(
        name=session_name,
        path=session_path,
        schema=schema,
        raw_extractions=raw_extractions,
        shards=shards,
        manifest=manifest,
        prep_mode=prep_mode,
    )


def _read_prep_mode(session_path: Path) -> str:
    """Extract pass2.prep_mode from the session's mykg_config.yaml snapshot.

    Tries the active profile first, then top-level pipeline block. Returns
    ``"unknown"`` when the file is absent or the key is missing.
    """
    config_path = session_path / "mykg_config.yaml"
    if not config_path.exists():
        return "unknown"
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        log.warning("merger: could not parse mykg_config.yaml at %s — %s", session_path, exc)
        return "unknown"

    profile_name = raw.get("profile")
    if profile_name:
        profile = raw.get("profiles", {}).get(profile_name, {})
        mode = profile.get("pipeline", {}).get("pass2", {}).get("prep_mode")
        if mode is not None:
            return str(mode)

    mode = raw.get("pipeline", {}).get("pass2", {}).get("prep_mode")
    return str(mode) if mode is not None else "unknown"


# ---------------------------------------------------------------------------
# build_source_map (Unit 1)
# ---------------------------------------------------------------------------


def build_source_map(session_a: SessionData, session_b: SessionData) -> dict:
    """Build a unified source map describing every input file from both sessions.

    Returns a dict with a ``_meta`` key and one entry per source file, keyed as
    ``"session_a/<original_filename>"`` or ``"session_b/<original_filename>"``.
    The ``sha256`` comes from ``manifest[filename]["sha256"]`` if present, else
    ``null``.
    """
    source_map: dict = {
        "_meta": {
            "session_a": {"name": session_a.name, "prep_mode": session_a.prep_mode},
            "session_b": {"name": session_b.name, "prep_mode": session_b.prep_mode},
        }
    }
    for alias, session, role in (
        ("session_a", session_a, "input_a"),
        ("session_b", session_b, "input_b"),
    ):
        for filename in session.raw_extractions:
            sha256 = session.manifest.get(filename, {}).get("sha256")
            source_map[f"{alias}/{filename}"] = {
                "session": session.name,
                "session_alias": alias,
                "original_path": str(session.path / "input" / filename),
                "sha256": sha256,
                "role": role,
            }
    log.debug(
        "merger: build_source_map — %d files from session_a, %d from session_b",
        len(session_a.raw_extractions),
        len(session_b.raw_extractions),
    )
    return source_map


# ---------------------------------------------------------------------------
# copy_session_into_merged (Unit 1)
# ---------------------------------------------------------------------------


def copy_session_into_merged(
    source: SessionData,
    merged_intermediate: Path,
    alias: str,
) -> None:
    """Copy shard files and schema_history entries from a source session into
    the merged session's intermediate directory.

    Namespacing:

    - ``raw_extractions_shards/`` and ``chunk_index_shards/``: shard ``_fname``
      is rewritten to ``<alias>/<original_fname>``; disk filename becomes
      ``<alias>_<original_slug>.json``
    - ``schema_history/``: each entry is copied to
      ``<merged_intermediate>/schema_history/<alias>_<original_filename>``
    """
    source_intermediate = source.path / "intermediate"
    _copy_shard_dir(
        src_dir=source_intermediate / "raw_extractions_shards",
        dst_dir=merged_intermediate / "raw_extractions_shards",
        alias=alias,
    )
    _copy_shard_dir(
        src_dir=source_intermediate / "chunk_index_shards",
        dst_dir=merged_intermediate / "chunk_index_shards",
        alias=alias,
    )
    src_history = source_intermediate / "schema_history"
    if src_history.is_dir():
        dst_history = merged_intermediate / "schema_history"
        dst_history.mkdir(parents=True, exist_ok=True)
        for entry in sorted(src_history.iterdir()):
            shutil.copy2(entry, dst_history / f"{alias}_{entry.name}")
            log.debug(
                "merger: copied schema_history entry %s → %s_%s",
                entry.name,
                alias,
                entry.name,
            )
    log.info(
        "merger: copy_session_into_merged — alias=%s source=%s → %s",
        alias,
        source.path,
        merged_intermediate,
    )


def _copy_shard_dir(src_dir: Path, dst_dir: Path, alias: str) -> None:
    """Copy shards from *src_dir* to *dst_dir* with ``_fname`` namespaced under *alias*.

    No-op if *src_dir* does not exist.
    """
    if not src_dir.is_dir():
        return
    dst_dir.mkdir(parents=True, exist_ok=True)
    for shard_file in sorted(src_dir.glob("*.json")):
        try:
            shard_data = json.loads(shard_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("merger: could not read shard %s — %s", shard_file, exc)
            continue
        original_fname = shard_data.get("_fname", shard_file.stem)
        shard_data["_fname"] = f"{alias}/{original_fname}"
        candidate = f"{alias}_{shard_file.name}"
        if len(candidate.encode()) > 240:
            h = hashlib.sha1(candidate.encode()).hexdigest()[:16]
            candidate = f"{alias}_{h}.json"
        dst_file = dst_dir / candidate
        dst_file.write_text(json.dumps(shard_data, indent=_cfg.JSON_INDENT), encoding="utf-8")
        log.debug(
            "merger: shard %s → %s (_fname=%s)",
            shard_file.name,
            dst_file.name,
            shard_data["_fname"],
        )


def build_merged_manifest(session_a: SessionData, session_b: SessionData) -> dict:
    """Build a merged file_manifest with namespaced keys for both sessions.

    Keys are ``"session_a/<original_filename>"`` and ``"session_b/<original_filename>"``
    so they align with the namespaced chunk_node_index keys used by orphan_score and
    orphan_connect.
    """
    merged: dict = {}
    for alias, session in (("session_a", session_a), ("session_b", session_b)):
        for filename, value in session.manifest.items():
            merged[f"{alias}/{filename}"] = value
    return merged


def _rewrite_source_files(items: list, key_map: dict[str, str]) -> None:
    """Rewrite ``source_files`` on each item in-place using *key_map*."""
    for item in items:
        src = item.get("source_files")
        if isinstance(src, list):
            item["source_files"] = [key_map.get(s, s) for s in src]


def namespace_raw_extractions(raw: dict, alias: str) -> dict:
    """Rewrite every file key in a raw_extractions dict to ``<alias>/<original_key>``.

    Also updates ``source_files`` lists on every node and edge so they reference
    the namespaced key rather than the original key.  The input dict is never
    mutated.

    Args:
        raw: File-keyed raw extractions dict, e.g.
            ``{"notes.md": {"nodes": [...], "edges": [...]}, ...}``.
        alias: Session alias prefix, e.g. ``"session_a"``.

    Returns:
        A new dict with every key rewritten to ``"<alias>/<original_key>"`` and
        all ``source_files`` references updated accordingly.
    """
    key_map: dict[str, str] = {orig: f"{alias}/{orig}" for orig in raw}
    result: dict = {}
    for orig_key, file_data in raw.items():
        file_data_copy = deepcopy(file_data)
        _rewrite_source_files(file_data_copy.get("nodes") or [], key_map)
        _rewrite_source_files(file_data_copy.get("edges") or [], key_map)
        result[key_map[orig_key]] = file_data_copy

    log.debug(
        "namespace_raw_extractions: alias=%r rewrote %d file keys",
        alias,
        len(result),
    )
    return result


def merge_raw_extractions(a_namespaced: dict, b_namespaced: dict) -> dict:
    """Merge two already-namespaced raw_extractions dicts.

    Because both dicts have been produced by :func:`namespace_raw_extractions`
    with different alias prefixes, key collisions are structurally impossible.
    This function validates that invariant and raises :class:`ValueError` if it
    is violated.

    Args:
        a_namespaced: First namespaced raw extractions dict (keys like
            ``"session_a/notes.md"``).
        b_namespaced: Second namespaced raw extractions dict (keys like
            ``"session_b/notes.md"``).

    Returns:
        A merged dict containing all entries from both inputs.

    Raises:
        ValueError: If any key appears in both dicts (should never happen with
            properly namespaced inputs).
    """
    collisions = set(a_namespaced) & set(b_namespaced)
    if collisions:
        sample = next(iter(collisions))
        raise ValueError(
            f"merge_raw_extractions: key collision detected — key {sample!r} appears in "
            f"both inputs. Ensure both dicts were produced by namespace_raw_extractions "
            f"with distinct alias prefixes."
        )

    merged = {**a_namespaced, **b_namespaced}
    log.debug(
        "merge_raw_extractions: merged %d + %d = %d file keys",
        len(a_namespaced),
        len(b_namespaced),
        len(merged),
    )
    return merged


def merge_session_schemas(
    schema_a: dict,
    schema_b: dict,
    thesaurus: SynonymIndex | None,
    locked_classes: dict,
    locked_properties: dict,
) -> tuple[dict, list[dict]]:
    """Merge two session schemas into one using the existing merge_proposals logic.

    Returns (merged_schema, synonym_log).
    """
    log.info(
        "Merging schemas: session A (%d concepts, %d properties), "
        "session B (%d concepts, %d properties)",
        len(schema_a.get("concepts", [])),
        len(schema_a.get("properties", [])),
        len(schema_b.get("concepts", [])),
        len(schema_b.get("properties", [])),
    )

    merged_schema, synonym_log = merge_proposals(
        [schema_a, schema_b], locked_classes, locked_properties, thesaurus
    )

    log.info(
        "Merged schema: %d concepts, %d properties",
        len(merged_schema.get("concepts", [])),
        len(merged_schema.get("properties", [])),
    )
    return merged_schema, synonym_log


def harmonize_merged_schema(
    schema: dict,
    proposals: list[dict],
    adapter: LLMAdapter | None,
) -> dict:
    """Harmonize the merged schema using merge-specific LLM prompts.

    Uses merge-specific prompts that preserve the full attribute union from both
    source sessions. Calls harmonize_schema_for_merge then review_schema_quality_for_merge.
    If adapter is None, skips both LLM calls and returns schema unchanged (dry-run mode).
    """
    if adapter is None:
        log.info("No adapter provided — skipping LLM harmonization (dry-run)")
        return schema

    return review_schema_quality_for_merge(
        harmonize_schema_for_merge(schema, proposals, adapter), adapter
    )


def compute_schema_delta(original_schema: dict, merged_schema: dict) -> set[str]:
    """Return property names present in merged_schema but absent in original_schema."""
    original_names = {p["name"] for p in original_schema.get("properties", [])}
    merged_names = {p["name"] for p in merged_schema.get("properties", [])}
    new_properties = merged_names - original_names

    log.info(
        "New properties introduced by merge: %s",
        sorted(new_properties) if new_properties else "none",
    )
    return new_properties


def _build_targeted_reextract_chunks(
    delta: set[str],
    merged_schema: dict,
    prior_extractions: dict[str, dict],
    prior_chunk_index: dict[str, dict],
    top_k: int,
) -> dict[str, set[int]] | None:
    """Return targeted chunk map, or None if prior_chunk_index is empty (caller falls back).

    Returns an empty dict if no chunks contain affected-type nodes (caller should skip
    re-extraction entirely).

    Parameters
    ----------
    delta:
        Names of new properties introduced by the merge (absent from original schema).
    merged_schema:
        The merged schema dict containing ``"properties": [...]``.
    prior_extractions:
        ``{fname: {"nodes": [...], "edges": [...]}}`` loaded from shards.
    prior_chunk_index:
        ``{fname: {"1": [stable_id, ...], "2": [...], ...}}`` loaded from chunk_index_shards.
        String chunk-index keys, 1-based.
    top_k:
        When > 0, for each new property keep only the top-K chunks ranked by count of
        domain/range nodes in that chunk. 0 means disabled — returns an empty map
        (caller skips re-extraction entirely).
    """
    if not prior_chunk_index:
        return None

    if top_k == 0:
        return {}

    # Step 1 — affected_types: union of domain + range for every new property
    affected_types: set[str] = set()
    for prop in merged_schema.get("properties", []):
        if prop["name"] in delta:
            if prop.get("domain"):
                affected_types.add(prop["domain"])
            if prop.get("range"):
                affected_types.add(prop["range"])
    log.debug(
        "_build_targeted_reextract_chunks: delta=%s affected_types=%s",
        sorted(delta),
        sorted(affected_types),
    )

    # Step 2 — node_type_map: stable_id → type across all files
    node_type_map: dict[str, str] = {}
    for file_data in prior_extractions.values():
        for node in file_data.get("nodes", []):
            nid = node.get("id")
            ntype = node.get("type")
            if nid and ntype:
                node_type_map[nid] = ntype

    # Step 3 — find chunks with at least one affected-type node
    chunk_score: dict[str, dict[int, int]] = defaultdict(dict)
    for fname, chunk_map in prior_chunk_index.items():
        for chunk_idx_str, stable_ids in chunk_map.items():
            try:
                chunk_idx = int(chunk_idx_str)
            except (ValueError, TypeError):
                continue
            score = sum(1 for sid in stable_ids if node_type_map.get(sid) in affected_types)
            if score > 0:
                chunk_score[fname][chunk_idx] = score

    if not chunk_score:
        log.info(
            "_build_targeted_reextract_chunks: no chunks contain affected-type nodes "
            "(affected_types=%s); returning empty map",
            sorted(affected_types),
        )
        return {}

    # Step 4 — top-K cap per new property (scored by co-occurrence count)
    targeted: dict[str, set[int]] = defaultdict(set)
    for prop in merged_schema.get("properties", []):
        if prop["name"] not in delta:
            continue
        prop_types = {t for t in (prop.get("domain"), prop.get("range")) if t}
        prop_scores: list[tuple[int, str, int]] = []
        for fname, ci_map in prior_chunk_index.items():
            for chunk_idx_str, stable_ids in ci_map.items():
                try:
                    chunk_idx = int(chunk_idx_str)
                except (ValueError, TypeError):
                    continue
                s = sum(1 for sid in stable_ids if node_type_map.get(sid) in prop_types)
                if s > 0:
                    prop_scores.append((-s, fname, chunk_idx))
        prop_scores.sort()
        for _, fname, chunk_idx in prop_scores[:top_k]:
            targeted[fname].add(chunk_idx)
    return dict(targeted)


def _namespace_shards(intermediate_dir: Path, session_alias: str) -> None:
    """Rewrite shard _fname fields to include the session namespace prefix.

    run_pass2/run_pass2_batched write shards with un-namespaced _fname values
    (e.g. "notes.md"). After merge re-extraction, those shards must carry the
    namespaced key (e.g. "session_a/notes.md") so that merge_raw and the orphan
    pass can match them against the rest of the merged session's data.
    """
    for shard_subdir in ("raw_extractions_shards", "chunk_index_shards"):
        shard_path = intermediate_dir / shard_subdir
        if not shard_path.is_dir():
            continue
        prefix = f"{session_alias}/"
        for shard_file in shard_path.glob("*.json"):
            try:
                data = json.loads(shard_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("_namespace_shards — could not read %s: %s", shard_file, exc)
                continue
            fname = data.get("_fname", "")
            if fname and not fname.startswith(prefix):
                data["_fname"] = f"{prefix}{fname}"
                shard_file.write_text(json.dumps(data, indent=_cfg.JSON_INDENT), encoding="utf-8")


def reextract_for_merge(
    session_alias: str,
    session_path: Path,
    raw_extractions_namespaced: dict,
    merged_schema: dict,
    flattened_schema: dict,
    intermediate_dir: Path,
    adapter,
    config: dict,
    strategy: str,
    original_schema: dict | None = None,
) -> dict:
    """Dispatch re-extraction based on strategy.

    Parameters
    ----------
    session_alias:
        Alias for this session (``"session_a"`` or ``"session_b"``).
    session_path:
        Path to the session root folder (``mykg_sessions/<name>/``). Used to locate
        original input files under ``session_path/input/``.
    raw_extractions_namespaced:
        Already-namespaced raw extractions dict for this session.
    merged_schema:
        The merged schema (may contain properties absent from original_schema).
    flattened_schema:
        Flattened attribute lists per concept type.
    intermediate_dir:
        Merged session's intermediate directory (pass2 runs from here).
    adapter:
        LLM adapter (used by surgical/full strategies; unused by none).
    config:
        Extra config dict (reserved for future use).
    strategy:
        One of ``"none"``, ``"surgical"``, ``"full"``.
    original_schema:
        The session's pre-merge schema. Required for ``"surgical"`` strategy to
        compute which properties are new.

    Returns
    -------
    dict
        Updated namespaced raw extractions dict.

    Raises
    ------
    ValueError
        If strategy is not one of the three supported values.
    """
    _VALID = {"none", "surgical", "full"}
    if strategy not in _VALID:
        raise ValueError(
            f"Unknown reextraction_strategy: {strategy!r}. Must be one of: {sorted(_VALID)}"
        )

    if strategy == "none":
        log.info(
            "reextract_for_merge: strategy=none — skipping re-extraction for %s",
            session_alias,
        )
        return raw_extractions_namespaced

    if strategy == "surgical":
        if original_schema is not None:
            delta = compute_schema_delta(original_schema, merged_schema)
        else:
            delta = set()
        if not delta:
            log.info(
                "reextract_for_merge: strategy=surgical — no new properties for %s, "
                "skipping re-extraction",
                session_alias,
            )
            return raw_extractions_namespaced
        log.info(
            "reextract_for_merge: strategy=surgical — new properties for %s: %s",
            session_alias,
            sorted(delta),
        )
        # Load prior extractions and chunk index from the merged session's shards.
        # Phase 0 already namespaced these shards under <alias>/<original_fname>.
        prior_extractions: dict[str, dict] = {}
        prior_chunk_index: dict[str, dict] = {}
        shard_dir = intermediate_dir / "raw_extractions_shards"
        chunk_shard_dir = intermediate_dir / "chunk_index_shards"
        if shard_dir.is_dir():
            for sf in shard_dir.glob("*.json"):
                try:
                    sd = json.loads(sf.read_text(encoding="utf-8"))
                    namespaced_fname = sd.get("_fname", sf.stem)
                    # Strip "session_a/" or "session_b/" prefix for pass2 keying.
                    if "/" in namespaced_fname:
                        plain = namespaced_fname.split("/", 1)[1]
                    else:
                        plain = namespaced_fname
                    if namespaced_fname.startswith(f"{session_alias}/"):
                        prior_extractions[plain] = sd.get("data", {})
                except (json.JSONDecodeError, OSError) as exc:
                    log.warning("reextract_for_merge: could not read shard %s — %s", sf, exc)
        if chunk_shard_dir.is_dir():
            for sf in chunk_shard_dir.glob("*.json"):
                try:
                    sd = json.loads(sf.read_text(encoding="utf-8"))
                    namespaced_fname = sd.get("_fname", sf.stem)
                    if "/" in namespaced_fname:
                        plain = namespaced_fname.split("/", 1)[1]
                    else:
                        plain = namespaced_fname
                    if namespaced_fname.startswith(f"{session_alias}/"):
                        prior_chunk_index[plain] = sd.get("data", {})
                except (json.JSONDecodeError, OSError) as exc:
                    log.warning("reextract_for_merge: could not read chunk shard %s — %s", sf, exc)

        # Load file contents from the session's input directory.
        input_dir = session_path / "input"
        if not input_dir.exists():
            log.warning(
                "reextract_for_merge: strategy=surgical — input dir not found at %s; "
                "returning existing extractions for %s",
                input_dir,
                session_alias,
            )
            return raw_extractions_namespaced

        file_contents: dict[str, str] = {}
        for namespaced_key in raw_extractions_namespaced:
            original_fname = (
                namespaced_key.split("/", 1)[1] if "/" in namespaced_key else namespaced_key
            )
            file_path = input_dir / original_fname
            if file_path.exists():
                file_contents[original_fname] = file_path.read_text(encoding="utf-8")
            else:
                log.warning(
                    "reextract_for_merge: strategy=surgical — input file not found: %s (skipping)",
                    file_path,
                )

        if not file_contents:
            log.warning(
                "reextract_for_merge: strategy=surgical — no input files resolved for %s; "
                "returning existing extractions",
                session_alias,
            )
            return raw_extractions_namespaced

        top_k = _cfg.MERGE_SURGICAL_TOP_K_CHUNKS_PER_PROPERTY
        reextract_chunks = _build_targeted_reextract_chunks(
            delta=delta,
            merged_schema=merged_schema,
            prior_extractions=prior_extractions,
            prior_chunk_index=prior_chunk_index,
            top_k=top_k,
        )

        if reextract_chunks is None:
            # prior_chunk_index empty — fall back to full chunk enumeration
            log.warning(
                "reextract_for_merge: strategy=surgical — prior_chunk_index is empty for %s; "
                "falling back to full chunk enumeration",
                session_alias,
            )
            reextract_chunks = {
                fname: set(range(1, len(chunk_file(fname, content)) + 1))
                for fname, content in file_contents.items()
            }
        elif not reextract_chunks:
            log.info(
                "reextract_for_merge: strategy=surgical — no affected chunks for %s "
                "(new properties: %s); skipping re-extraction",
                session_alias,
                sorted(delta),
            )
            return raw_extractions_namespaced

        # Narrow file_contents to only files with at least one targeted chunk.
        # Critical: run_pass2 re-extracts ALL chunks of any file in `files` that
        # has no entry in reextract_chunks (target_chunks=None path in pass2).
        file_contents = {
            fname: content for fname, content in file_contents.items() if fname in reextract_chunks
        }

        total_targeted = sum(len(v) for v in reextract_chunks.values())
        log.info(
            "reextract_for_merge: strategy=surgical — %s: targeting %d chunk(s) across "
            "%d file(s) (new properties: %s, top_k=%s)",
            session_alias,
            total_targeted,
            len(file_contents),
            sorted(delta),
            top_k if top_k > 0 else "unlimited",
        )

        new_raw, _chunk_idx, _failed = run_pass2(
            files=file_contents,
            schema=merged_schema,
            flat_schema=flattened_schema,
            adapter=adapter,
            max_workers=_cfg.PASS2_MAX_WORKERS,
            reextract_chunks=reextract_chunks,
            prior_extractions=prior_extractions,
            prior_chunk_index=prior_chunk_index,
            intermediate_dir=intermediate_dir,
        )

        log.info(
            "reextract_for_merge: strategy=surgical — re-extraction complete for %s: %d file(s)",
            session_alias,
            len(new_raw),
        )
        # Namespace shard _fname fields written by run_pass2 so that merge_raw and
        # the orphan pass can match them against the rest of the merged session's data.
        _namespace_shards(intermediate_dir, session_alias)
        # Merge re-extracted files back into the full namespaced dict.
        # new_raw keys are un-namespaced; namespace them before updating.
        namespaced_new = namespace_raw_extractions(new_raw, session_alias)
        raw_extractions_namespaced.update(namespaced_new)
        return raw_extractions_namespaced

    # strategy == "full"
    input_dir = session_path / "input"
    if not input_dir.exists():
        log.warning(
            "reextract_for_merge: strategy=full — input dir not found at %s; "
            "returning existing extractions for %s",
            input_dir,
            session_alias,
        )
        return raw_extractions_namespaced

    # Load file contents from session input dir; keys match original (un-namespaced) filenames
    file_contents: dict[str, str] = {}
    for namespaced_key in raw_extractions_namespaced:
        # Strip the "session_a/" or "session_b/" prefix
        original_fname = (
            namespaced_key.split("/", 1)[1] if "/" in namespaced_key else namespaced_key
        )
        file_path = input_dir / original_fname
        if file_path.exists():
            file_contents[original_fname] = file_path.read_text(encoding="utf-8")
        else:
            log.warning(
                "reextract_for_merge: strategy=full — input file not found: %s (skipping)",
                file_path,
            )

    if not file_contents:
        log.warning(
            "reextract_for_merge: strategy=full — no input files resolved for %s; "
            "returning existing extractions",
            session_alias,
        )
        return raw_extractions_namespaced

    log.info(
        "reextract_for_merge: strategy=full — re-extracting %d file(s) for %s with merged schema",
        len(file_contents),
        session_alias,
    )

    new_raw, _chunk_idx, _failed, _batch_map = run_pass2_batched(
        files=file_contents,
        schema=merged_schema,
        flat_schema=flattened_schema,
        adapter=adapter,
        batch_token_target=_cfg.PASS2_BATCH_TOKEN_TARGET,
        per_file=_cfg.PASS2_BATCH_PER_FILE,
        max_workers=_cfg.PASS2_MAX_WORKERS,
        intermediate_dir=intermediate_dir,
    )

    log.info(
        "reextract_for_merge: strategy=full — re-extraction complete for %s: %d file(s)",
        session_alias,
        len(new_raw),
    )
    _namespace_shards(intermediate_dir, session_alias)
    return namespace_raw_extractions(new_raw, session_alias)
