"""End-to-end coverage for the merge-graphs schema merge over real session data.

The unit tests in test_schema_merge.py exercise merge_proposals() against small
inline dicts. These tests run it against the two committed example sessions under
docs/examples/blog_demo_run/ — real schemas induced by real pipeline runs.

Note what real data can and cannot show. Neither example schema disagrees with the
other on a structural field, so the conflict events correctly stay silent: that is
the false-positive guard, and it matters because merge_proposals() runs on every
ordinary extract-graph run, not only on merge-graphs. To reach the conflict path
with realistic input, the perturbation tests below deep-copy a real schema and
change exactly one field.
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from mykg.merge_context import MergeContext
from mykg.merge_run import run_merge
from mykg.schema_merge import merge_proposals
from mykg.thesaurus import SynonymIndex

# ---------------------------------------------------------------------------
# Real example sessions (git-tracked via a !docs/examples/** negation in
# .gitignore, so these are available in CI; mykg_sessions/ is NOT)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _REPO_ROOT / "docs" / "examples" / "blog_demo_run"
_SESSION_A = "2026-06-07T21-24-38"
_SESSION_B = "session_output"

# Exact result of merge_proposals([A, B], {}, {}, None) — verified deterministic
# across repeated runs. (type, parent) pairs, in insertion order.
_EXPECTED_CONCEPTS = [
    ("Person", None),
    ("Organization", None),
    ("Team", "Organization"),
    ("Project", None),
    ("Technology", None),
    ("Location", None),
    ("Company", "Organization"),
    ("Employee", "Person"),
    ("Product", "Technology"),
    ("Agreement", None),
]

# (name, domain, range) triples, in insertion order.
_EXPECTED_PROPERTIES = [
    ("works_at", "Person", "Organization"),
    ("member_of", "Person", "Team"),
    ("manages", "Person", "Team"),
    ("reports_to", "Person", "Person"),
    ("contributes_to", "Person", "Project"),
    ("owns_project", "Team", "Project"),
    ("depends_on", "Project", "Project"),
    ("uses_technology", "Project", "Technology"),
    ("partners_with", "Organization", "Organization"),
    ("provides_technology", "Organization", "Technology"),
    ("located_in", "Organization", "Location"),
    ("part_of", "Team", "Organization"),
    ("leads", "Person", "Project"),
    ("owns", "Team", "Project"),
    ("provides", "Organization", "Product"),
    ("has_partnership", "Organization", "Organization"),
    ("vendor_for", "Organization", "Organization"),
    ("has_agreement", "Organization", "Agreement"),
    ("account_manager_for", "Person", "Organization"),
    ("co_founded", "Person", "Organization"),
    ("supports", "Agreement", "Project"),
]

_OLLAMA_PROFILE = "ollama-local"
_OLLAMA_PROBE_TIMEOUT = 3


def _example_session_dir(name: str) -> Path:
    return _EXAMPLES / name


def _load_example_schema(name: str) -> dict:
    """Load a committed example session's schema.json, skipping if absent."""
    path = _example_session_dir(name) / "intermediate" / "schema.json"
    if not path.is_file():
        pytest.skip(f"example session data missing: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _concept(schema: dict, ctype: str) -> dict:
    return next(c for c in schema["concepts"] if c["type"] == ctype)


def _prop(schema: dict, name: str) -> dict:
    return next(p for p in schema["properties"] if p["name"] == name)


# ---------------------------------------------------------------------------
# Unit 1 — deterministic snapshot over the real schemas (no LLM)
# ---------------------------------------------------------------------------


def test_real_sessions_merge_to_exact_expected_schema():
    """merge_proposals over both real example schemas yields an exact known result."""
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)

    schema, _ = merge_proposals([a, b], {}, {}, None)

    assert [(c["type"], c.get("parent")) for c in schema["concepts"]] == _EXPECTED_CONCEPTS
    assert [
        (p["name"], p.get("domain"), p.get("range")) for p in schema["properties"]
    ] == _EXPECTED_PROPERTIES


def test_real_sessions_produce_no_conflict_events():
    """The false-positive guard: real corpora must not emit spurious conflicts.

    merge_proposals runs on every extract-graph run, so a conflict event firing
    here would mean noise in the audit log of ordinary, non-merge pipelines.
    """
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)

    _, synonym_log = merge_proposals([a, b], {}, {}, None)

    assert synonym_log == []


def test_real_sessions_merge_is_order_independent_for_membership():
    """Reversing the sources changes insertion order but not the merged vocabulary."""
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)

    forward, _ = merge_proposals([a, b], {}, {}, None)
    reverse, _ = merge_proposals([b, a], {}, {}, None)

    assert {c["type"] for c in forward["concepts"]} == {c["type"] for c in reverse["concepts"]}
    assert {p["name"] for p in forward["properties"]} == {p["name"] for p in reverse["properties"]}


def test_real_sessions_attribute_union_is_lossless():
    """Every attribute from either source survives on the merged concept."""
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)

    schema, _ = merge_proposals([a, b], {}, {}, None)

    for source in (a, b):
        for concept in source["concepts"]:
            merged_attrs = set(_concept(schema, concept["type"])["attributes"])
            assert set(concept["attributes"]) <= merged_attrs


def test_real_sessions_null_parent_is_filled_not_conflicted():
    """Session B's Team has parent=null — an absence, not a competing value.

    Filling a null parent is the pre-existing behaviour and must not be reported
    as a conflict; this is the exact case that distinguishes 'absent' from
    'disagreeing'.
    """
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)
    assert _concept(a, "Team")["parent"] == "Organization"
    assert _concept(b, "Team")["parent"] is None

    schema, synonym_log = merge_proposals([a, b], {}, {}, None)

    assert _concept(schema, "Team")["parent"] == "Organization"
    assert [e for e in synonym_log if e["event"] == "parent_conflict"] == []


# ---------------------------------------------------------------------------
# Unit 2 — conflict events on minimally perturbed real data (no LLM)
# ---------------------------------------------------------------------------


def test_perturbed_parent_logs_conflict_and_keeps_first_seen():
    """A real schema with one flipped parent produces exactly one parent_conflict."""
    a = _load_example_schema(_SESSION_A)
    b = deepcopy(_load_example_schema(_SESSION_B))
    _concept(b, "Team")["parent"] = "Company"

    schema, synonym_log = merge_proposals([a, b], {}, {}, None)

    conflicts = [e for e in synonym_log if e["event"] == "parent_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["concept"] == "Team"
    assert conflicts[0]["kept"] == "Organization"
    assert conflicts[0]["discarded"] == "Company"
    # Behaviour unchanged: first-seen still wins
    assert _concept(schema, "Team")["parent"] == "Organization"


def test_perturbed_range_logs_domain_range_conflict():
    """A real property with one flipped range produces one domain_range_conflict."""
    a = _load_example_schema(_SESSION_A)
    b = deepcopy(_load_example_schema(_SESSION_B))
    assert _prop(a, "works_at")["range"] == "Organization"
    _prop(b, "works_at")["range"] = "Team"

    schema, synonym_log = merge_proposals([a, b], {}, {}, None)

    conflicts = [e for e in synonym_log if e["event"] == "domain_range_conflict"]
    assert len(conflicts) == 1
    assert conflicts[0]["property"] == "works_at"
    assert conflicts[0]["field"] == "range"
    assert conflicts[0]["kept"] == "Organization"
    assert conflicts[0]["discarded"] == "Team"
    assert _prop(schema, "works_at")["range"] == "Organization"


def test_thesaurus_broader_arbitrates_perturbed_parent_conflict():
    """skos:broader resolves the perturbed Team conflict in favour of Company."""
    a = _load_example_schema(_SESSION_A)
    b = deepcopy(_load_example_schema(_SESSION_B))
    _concept(b, "Team")["parent"] = "Company"

    idx = SynonymIndex(term_count=2)
    idx._add_directed(idx.broader, "Team", "Company")

    schema, synonym_log = merge_proposals([a, b], {}, {}, idx)

    resolved = [e for e in synonym_log if e["event"] == "parent_conflict_resolved"]
    assert len(resolved) == 1
    assert resolved[0]["resolved_to"] == "Company"
    assert resolved[0]["rejected"] == "Organization"
    assert resolved[0]["via"] == "skos:broader"
    assert _concept(schema, "Team")["parent"] == "Company"


def test_thesaurus_arbitration_is_order_independent_on_real_data():
    """The thesaurus verdict wins regardless of which session is listed first."""
    a = _load_example_schema(_SESSION_A)
    b = deepcopy(_load_example_schema(_SESSION_B))
    _concept(b, "Team")["parent"] = "Company"

    idx = SynonymIndex(term_count=2)
    idx._add_directed(idx.broader, "Team", "Company")

    forward, _ = merge_proposals([a, b], {}, {}, idx)
    reverse, _ = merge_proposals([b, a], {}, {}, idx)

    assert _concept(forward, "Team")["parent"] == "Company"
    assert _concept(reverse, "Team")["parent"] == "Company"


# ---------------------------------------------------------------------------
# Unit 3 — full merge pipeline over real sessions against a live Ollama server
# ---------------------------------------------------------------------------

_MERGE_CFG = (
    "profile: test\n"
    "profiles:\n"
    "  test:\n"
    "    pipeline:\n"
    "      pass2:\n"
    "        prep_mode: per_file\n"
    "      merge_graphs:\n"
    "        reextraction_strategy: none\n"
)


def _ollama_reachable(base_url: str) -> bool:
    try:
        with urllib.request.urlopen(  # noqa: S310 - fixed localhost URL from config
            f"{base_url.rstrip('/')}/api/tags", timeout=_OLLAMA_PROBE_TIMEOUT
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def _ollama_adapter():
    """Build an Ollama adapter from the ollama-local profile, skipping if unusable."""
    config_path = _REPO_ROOT / "mykg_config.yaml"
    if not config_path.is_file():
        pytest.skip(f"mykg_config.yaml not found at {config_path}")

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    profile = (raw.get("profiles") or {}).get(_OLLAMA_PROFILE)
    if not profile:
        pytest.skip(f"profile {_OLLAMA_PROFILE!r} not present in mykg_config.yaml")

    llm_block = profile.get("llm") or {}
    base_url = llm_block.get("base_url", "")
    if not _ollama_reachable(base_url):
        pytest.skip(f"Ollama not reachable at {base_url}")

    from mykg.llm.config import load_adapter

    return load_adapter({"provider": "ollama", "llm": llm_block})


def _copy_example_session(dest_root: Path, name: str) -> Path:
    """Copy a committed example session into a writable tmp location.

    The merge pipeline writes into the session tree, so the git-tracked originals
    must never be used in place.
    """
    src = _example_session_dir(name)
    if not (src / "intermediate" / "schema.json").is_file():
        pytest.skip(f"example session data missing: {src}")

    dest = dest_root / name
    shutil.copytree(src, dest)
    for sub in ("input", "output", "intermediate"):
        (dest / sub).mkdir(parents=True, exist_ok=True)
    (dest / "mykg_config.yaml").write_text(_MERGE_CFG, encoding="utf-8")
    return dest


@pytest.mark.live
def test_merge_graphs_over_real_sessions_with_ollama(tmp_path):
    """Full merge pipeline over both real example sessions against live Ollama.

    Assertions are invariants rather than exact values — the harmonize and
    quality-review stages call a real model, whose output is not byte-stable.
    """
    adapter = _ollama_adapter()

    sessions_root = tmp_path / "sessions"
    sessions_root.mkdir(parents=True, exist_ok=True)
    _copy_example_session(sessions_root, _SESSION_A)
    _copy_example_session(sessions_root, _SESSION_B)

    merged_root = tmp_path / "merged"
    output_dir = merged_root / "output"
    intermediate_dir = merged_root / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    (merged_root / "input").mkdir(exist_ok=True)

    ctx = MergeContext(
        session_a_name=_SESSION_A,
        session_b_name=_SESSION_B,
        sessions_root=sessions_root,
        input_dir=sessions_root,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        review=False,
    )

    run_merge(ctx)

    schema_path = intermediate_dir / "schema.json"
    assert schema_path.is_file()
    merged_schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert merged_schema["concepts"]
    assert merged_schema["properties"]

    assert (intermediate_dir / "schema.ttl").is_file()
    assert (intermediate_dir / "source_map.json").is_file()

    # Vocabulary shared by both sources must survive the LLM stages.
    a = _load_example_schema(_SESSION_A)
    b = _load_example_schema(_SESSION_B)
    shared = {c["type"] for c in a["concepts"]} & {c["type"] for c in b["concepts"]}
    merged_types = {c["type"] for c in merged_schema["concepts"]}
    assert shared <= merged_types

    manifest_path = intermediate_dir / "merge_manifest.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["session_a"] == _SESSION_A
    assert manifest["session_b"] == _SESSION_B
    assert "schema_synonym_log" in manifest

    assert (output_dir / "nodes.jsonl").is_file()
    assert (output_dir / "knowledge_graph.ttl").is_file()
