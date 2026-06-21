"""Unit tests for the grow-schema back-fill chunk selector (Unit 4 / D52)."""

from mykg.steps.grow_schema_backfill import compute_backfill_chunks

# A small grown schema with a hierarchy:
#   MilitaryUnit (root)
#     Brigade is-a MilitaryUnit   (newly added concept)
#   Officer (root)
# Properties: commands (Officer -> MilitaryUnit) is newly added.
NEW_SCHEMA = {
    "concepts": [
        {"type": "MilitaryUnit", "parent": None, "attributes": ["name"]},
        {"type": "Brigade", "parent": "MilitaryUnit", "attributes": ["name"]},
        {"type": "Officer", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "commands", "domain": "Officer", "range": "MilitaryUnit", "attributes": []},
    ],
}

# chunk_node_index: stable-id prefix encodes the type (D19): officer-*, militaryunit-*.
CHUNK_INDEX = {
    "old1.md": {
        "1": ["officer-patton", "militaryunit-thirdarmy"],
        "2": ["officer-bradley"],
    },
    "old2.md": {
        "1": ["militaryunit-firstinfantry"],
        "2": ["person-someone"],  # unrelated type
    },
}


def test_new_property_targets_domain_or_range_chunks():
    """A new property D->R selects chunks containing a D or R node."""
    result = compute_backfill_chunks(
        added_concepts=[],
        added_properties=[NEW_SCHEMA["properties"][0]],
        new_schema=NEW_SCHEMA,
        chunk_node_index=CHUNK_INDEX,
        top_k=10,
    )
    # chunks with Officer or MilitaryUnit nodes: old1#1, old1#2, old2#1
    assert result["old1.md"] == {1, 2}
    assert result["old2.md"] == {1}
    # old2#2 (person only) is never selected
    assert 2 not in result.get("old2.md", set())


def test_new_concept_uses_hierarchy_signal_parent():
    """A new subclass concept targets chunks containing its PARENT-type nodes."""
    result = compute_backfill_chunks(
        added_concepts=["Brigade"],  # is-a MilitaryUnit
        added_properties=[],
        new_schema=NEW_SCHEMA,
        chunk_node_index=CHUNK_INDEX,
        top_k=10,
    )
    # parent = MilitaryUnit → chunks with militaryunit-* nodes: old1#1, old2#1
    assert result.get("old1.md") == {1}
    assert result.get("old2.md") == {1}


def test_root_concept_with_no_siblings_yields_no_targets():
    """A brand-new ROOT concept (no parent, no siblings) selects ZERO chunks."""
    schema = {
        "concepts": [
            {"type": "Country", "parent": None, "attributes": ["name"]},
            {"type": "MilitaryUnit", "parent": None, "attributes": ["name"]},
            {"type": "Officer", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
    result = compute_backfill_chunks(
        added_concepts=["Country"],
        added_properties=[],
        new_schema=schema,
        chunk_node_index=CHUNK_INDEX,
        top_k=10,
    )
    assert result == {}


def test_top_k_zero_disables_backfill():
    result = compute_backfill_chunks(
        added_concepts=["Brigade"],
        added_properties=[NEW_SCHEMA["properties"][0]],
        new_schema=NEW_SCHEMA,
        chunk_node_index=CHUNK_INDEX,
        top_k=0,
    )
    assert result == {}


def test_empty_delta_returns_empty():
    result = compute_backfill_chunks(
        added_concepts=[],
        added_properties=[],
        new_schema=NEW_SCHEMA,
        chunk_node_index=CHUNK_INDEX,
        top_k=10,
    )
    assert result == {}


def test_top_k_cap_keeps_only_highest_cooccurrence():
    """With top_k=1, only the single highest-co-occurrence chunk per signal survives."""
    schema = {
        "concepts": [{"type": "Officer", "parent": None, "attributes": ["name"]}],
        "properties": [
            {"name": "commands", "domain": "Officer", "range": "Officer", "attributes": []}
        ],
    }
    idx = {
        "a.md": {"1": ["officer-x", "officer-y", "officer-z"]},  # score 3
        "b.md": {"1": ["officer-q"]},  # score 1
    }
    result = compute_backfill_chunks(
        added_concepts=[],
        added_properties=schema["properties"],
        new_schema=schema,
        chunk_node_index=idx,
        top_k=1,
    )
    assert result == {"a.md": {1}}


def test_empty_chunk_index_returns_empty():
    result = compute_backfill_chunks(
        added_concepts=["Brigade"],
        added_properties=[NEW_SCHEMA["properties"][0]],
        new_schema=NEW_SCHEMA,
        chunk_node_index={},
        top_k=10,
    )
    assert result == {}


def test_unknown_added_concept_yields_no_targets():
    """A concept name not present in new_schema's concepts contributes no chunks."""
    result = compute_backfill_chunks(
        added_concepts=["Nonexistent"],  # not in NEW_SCHEMA["concepts"]
        added_properties=[],
        new_schema=NEW_SCHEMA,
        chunk_node_index=CHUNK_INDEX,
        top_k=10,
    )
    assert result == {}


def test_malformed_chunk_index_key_is_skipped():
    """Non-integer chunk-index keys are ignored rather than raising."""
    idx = {
        "old.md": {
            "1": ["officer-patton"],  # valid → selected
            "notanint": ["officer-bradley"],  # malformed key → skipped
        },
    }
    result = compute_backfill_chunks(
        added_concepts=[],
        added_properties=[NEW_SCHEMA["properties"][0]],  # Officer is domain
        new_schema=NEW_SCHEMA,
        chunk_node_index=idx,
        top_k=10,
    )
    assert result == {"old.md": {1}}


def test_new_concept_with_siblings_targets_sibling_type_chunks():
    """A new subclass also targets chunks containing SIBLING-type nodes."""
    schema = {
        "concepts": [
            {"type": "MilitaryUnit", "parent": None, "attributes": ["name"]},
            {"type": "Division", "parent": "MilitaryUnit", "attributes": ["name"]},
            {"type": "Brigade", "parent": "MilitaryUnit", "attributes": ["name"]},  # new
        ],
        "properties": [],
    }
    idx = {
        "a.md": {"1": ["division-first"]},  # sibling type
        "b.md": {"1": ["militaryunit-generic"]},  # parent type
        "c.md": {"1": ["officer-x"]},  # unrelated
    }
    result = compute_backfill_chunks(
        added_concepts=["Brigade"],
        added_properties=[],
        new_schema=schema,
        chunk_node_index=idx,
        top_k=10,
    )
    # parent (MilitaryUnit) and sibling (Division) chunks selected; officer chunk not
    assert result == {"a.md": {1}, "b.md": {1}}
