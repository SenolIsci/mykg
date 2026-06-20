import json
from unittest.mock import MagicMock

from mykg.schema_merge import (
    _HARMONIZE_SYSTEM_PROMPT,
    _QUALITY_SYSTEM_PROMPT,
    _normalize_schema,
    harmonize_schema,
    harmonize_schema_for_merge,
    merge_proposals,
    review_schema_quality,
    review_schema_quality_for_merge,
    synonym_match,
)
from mykg.thesaurus import SynonymIndex

NO_THESAURUS = None

BATCH_1 = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name", "industry"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]}
    ],
}

BATCH_2 = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "birth_date"]},
        {"type": "SoftwareEngineer", "parent": "Person", "attributes": ["seniority"]},
    ],
    "properties": [
        {
            "name": "works_at",
            "domain": "Person",
            "range": "Organization",
            "attributes": ["start_date"],
        }
    ],
}


# synonym_match tests
def test_synonym_match_exact():
    assert synonym_match("Person", "Person", NO_THESAURUS) is True


def test_synonym_match_normalised():
    assert synonym_match("ML Model", "ml_model", NO_THESAURUS) is True


def test_synonym_match_different():
    assert synonym_match("Person", "Organization", NO_THESAURUS) is False


def test_synonym_match_thesaurus_exact():
    idx = SynonymIndex(term_count=2)
    idx._add(idx.exact_matches, "MLModel", "MachineLearningModel")
    assert synonym_match("MLModel", "MachineLearningModel", idx) is True


def test_synonym_match_thesaurus_close():
    idx = SynonymIndex(term_count=2)
    idx._add(idx.close_matches, "Org", "Organisation")
    assert synonym_match("Org", "Organisation", idx) is True


# merge_proposals tests
def test_merge_deduplicates_concepts():
    schema, _ = merge_proposals(
        [BATCH_1, BATCH_2], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    types = [c["type"] for c in schema["concepts"]]
    assert types.count("Person") == 1


def test_merge_unions_attributes():
    schema, _ = merge_proposals(
        [BATCH_1, BATCH_2], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    person = next(c for c in schema["concepts"] if c["type"] == "Person")
    assert "email" in person["attributes"]
    assert "birth_date" in person["attributes"]


def test_merge_includes_subtype():
    schema, _ = merge_proposals(
        [BATCH_1, BATCH_2], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    types = [c["type"] for c in schema["concepts"]]
    assert "SoftwareEngineer" in types


def test_merge_deduplicates_properties_and_unions_attrs():
    schema, _ = merge_proposals(
        [BATCH_1, BATCH_2], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    props = schema["properties"]
    assert len([p for p in props if p["name"] == "works_at"]) == 1
    wa = next(p for p in props if p["name"] == "works_at")
    assert "role" in wa["attributes"]
    assert "start_date" in wa["attributes"]


def test_merge_respects_locked_classes():
    locked = {"Vehicle": {"type": "Vehicle", "parent": None, "attributes": ["year"]}}
    batch = {
        "concepts": [{"type": "Vehicle", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    schema, _ = merge_proposals(
        [batch], locked_classes=locked, locked_properties={}, thesaurus=NO_THESAURUS
    )
    vehicle = next(c for c in schema["concepts"] if c["type"] == "Vehicle")
    # locked parent wins; attributes unioned
    assert vehicle["parent"] is None
    assert "year" in vehicle["attributes"]
    assert "name" in vehicle["attributes"]


def test_relationship_concept_is_rejected():
    """merge_proposals must reject any concept named 'Relationship' (case-insensitive)."""
    proposals = [
        {
            "concepts": [
                {"type": "Relationship", "parent": None, "attributes": []},
                {"type": "relationship", "parent": None, "attributes": []},
                {"type": "RELATIONSHIP", "parent": None, "attributes": []},
                {"type": "Person", "parent": None, "attributes": ["name"]},
            ],
            "properties": [],
        }
    ]
    schema, _ = merge_proposals(proposals, {}, {}, None)
    types = [c["type"] for c in schema["concepts"]]
    assert "Relationship" not in types
    assert "relationship" not in types
    assert "RELATIONSHIP" not in types
    assert "Person" in types


def test_close_match_collapse_logged():
    """skos:closeMatch collapses are recorded in the returned synonym_log."""
    idx = SynonymIndex(term_count=2)
    idx._add(idx.close_matches, "Org", "Organisation")
    proposals = [
        {"concepts": [{"type": "Org", "parent": None, "attributes": ["name"]}], "properties": []},
        {
            "concepts": [{"type": "Organisation", "parent": None, "attributes": ["industry"]}],
            "properties": [],
        },
    ]
    schema, synonym_log = merge_proposals(proposals, {}, {}, idx)
    types = [c["type"] for c in schema["concepts"]]
    # Both names collapse into one entry
    assert len([t for t in types if t in ("Org", "Organisation")]) == 1
    # The collapse is logged
    close_events = [e for e in synonym_log if e.get("reason") == "skos:closeMatch"]
    assert len(close_events) == 1


def test_merge_proposals_returns_tuple():
    """merge_proposals returns (schema_dict, synonym_log list)."""
    result = merge_proposals([BATCH_1], {}, {}, None)
    assert isinstance(result, tuple)
    schema, log = result
    assert "concepts" in schema
    assert isinstance(log, list)


# harmonize_schema tests

_SMALL_SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name", "industry"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]}
    ],
}

_REDUCED_SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name"]},
    ],
    "properties": [],
}

_RAW_PROPOSALS = [
    {
        "concepts": [{"type": "Employee", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
]


def test_harmonize_returns_improved_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    result = harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert result["concepts"][0]["type"] == "Person"
    assert result["properties"] == []
    assert result is not _SMALL_SCHEMA


def test_harmonize_falls_back_on_invalid_json():
    adapter = MagicMock()
    adapter.complete.return_value = "not json {"
    result = harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert result is _SMALL_SCHEMA


def test_harmonize_falls_back_on_wrong_structure():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"concepts": []})
    result = harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert result is _SMALL_SCHEMA


# base-schema lock injection (D27) — the locked block must reach the cleanup-pass
# system prompt so this unlocked pass is told which names it must not rename/remove.

_LOCKED_BLOCK = (
    "EXISTING SCHEMA (DO NOT RENAME, REMOVE, OR DUPLICATE THESE):\n"
    "Classes: OrderHeader\nProperties: writes\n"
)


def test_harmonize_injects_locked_block():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter, locked_block=_LOCKED_BLOCK)
    system_prompt = adapter.complete.call_args[0][0]
    # Exact match pins the placement and spacing of the block, not just its presence,
    # so a prompt-format regression that weakens the lock signal is caught.
    assert system_prompt == _HARMONIZE_SYSTEM_PROMPT + "\n\n" + _LOCKED_BLOCK


def test_harmonize_no_locked_block_unchanged():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    system_prompt = adapter.complete.call_args[0][0]
    assert system_prompt == _HARMONIZE_SYSTEM_PROMPT


def test_review_quality_injects_locked_block():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_SMALL_SCHEMA)
    review_schema_quality(_SMALL_SCHEMA, adapter, locked_block=_LOCKED_BLOCK)
    system_prompt = adapter.complete.call_args[0][0]
    # Exact match (mirrors the harmonize test) guards placement + spacing of the block.
    assert system_prompt == _QUALITY_SYSTEM_PROMPT + "\n\n" + _LOCKED_BLOCK


def test_review_quality_no_locked_block_unchanged():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_SMALL_SCHEMA)
    review_schema_quality(_SMALL_SCHEMA, adapter)
    system_prompt = adapter.complete.call_args[0][0]
    assert system_prompt == _QUALITY_SYSTEM_PROMPT


def test_harmonize_calls_llm_once():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert adapter.complete.call_count == 1


def test_harmonize_prompt_contains_merged_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    user_prompt = adapter.complete.call_args[0][1]
    assert "Organization" in user_prompt


def test_harmonize_prompt_contains_raw_proposals():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_REDUCED_SCHEMA)
    harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    user_prompt = adapter.complete.call_args[0][1]
    assert "Employee" in user_prompt


def test_harmonize_normalizes_returned_schema():
    schema_missing_attrs = {
        "concepts": [{"type": "Person", "parent": None}],
        "properties": [{"name": "knows", "domain": "Person", "range": "Person"}],
    }
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(schema_missing_attrs)
    result = harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert result["concepts"][0]["attributes"] == []
    assert result["properties"][0]["attributes"] == []


def test_harmonize_falls_back_on_adapter_exception():
    adapter = MagicMock()
    adapter.complete.side_effect = RuntimeError("boom")
    result = harmonize_schema(_SMALL_SCHEMA, _RAW_PROPOSALS, adapter)
    assert result is _SMALL_SCHEMA


# _normalize_schema tests
def test_normalize_schema_adds_missing_attributes():
    schema = {
        "concepts": [{"type": "Person", "parent": None}],
        "properties": [{"name": "knows", "domain": "Person", "range": "Person"}],
    }
    _normalize_schema(schema)
    assert schema["concepts"][0]["attributes"] == []
    assert schema["properties"][0]["attributes"] == []


def test_normalize_schema_leaves_existing_attributes():
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    _normalize_schema(schema)
    assert schema["concepts"][0]["attributes"] == ["name"]


def test_normalize_schema_returns_schema():
    schema = {"concepts": [], "properties": []}
    result = _normalize_schema(schema)
    assert result is schema


def test_merge_proposals_skips_non_dict_concept():
    proposal = {
        "concepts": [
            "SomeString",
            {"type": "Person", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
    schema, _ = merge_proposals(
        [proposal], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    types = [c["type"] for c in schema["concepts"]]
    assert "Person" in types


# _normalize_schema null-guard tests
def test_normalize_schema_filters_null_concepts():
    schema = {
        "concepts": [None, {"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    _normalize_schema(schema)
    assert len(schema["concepts"]) == 1
    assert schema["concepts"][0]["type"] == "Person"


def test_normalize_schema_null_concepts_key():
    schema = {"concepts": None, "properties": []}
    _normalize_schema(schema)
    assert schema["concepts"] == []


def test_normalize_schema_null_properties_key():
    schema = {"concepts": [], "properties": None}
    _normalize_schema(schema)
    assert schema["properties"] == []


def test_normalize_schema_mixed_null_and_valid():
    schema = {
        "concepts": [None, {"type": "Org", "parent": None}, None],
        "properties": [None, {"name": "knows", "domain": "Org", "range": "Org"}, None],
    }
    _normalize_schema(schema)
    assert len(schema["concepts"]) == 1
    assert schema["concepts"][0]["attributes"] == []
    assert len(schema["properties"]) == 1
    assert schema["properties"][0]["attributes"] == []


def test_normalize_schema_normal_case_still_works():
    schema = {
        "concepts": [{"type": "Person", "parent": None}],
        "properties": [{"name": "knows", "domain": "Person", "range": "Person"}],
    }
    result = _normalize_schema(schema)
    assert result["concepts"][0]["attributes"] == []
    assert result["properties"][0]["attributes"] == []
    assert result is schema


def test_merge_proposals_skips_non_dict_property():
    proposal = {
        "concepts": [],
        "properties": [
            42,
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
        ],
    }
    schema, _ = merge_proposals(
        [proposal], locked_classes={}, locked_properties={}, thesaurus=NO_THESAURUS
    )
    prop_names = [p["name"] for p in schema["properties"]]
    assert "works_at" in prop_names


# ---------------------------------------------------------------------------
# harmonize_schema_for_merge tests
# ---------------------------------------------------------------------------

_SESSION_SCHEMAS = [
    {
        "concepts": [
            {"type": "Document", "parent": None, "attributes": ["name", "date", "subject"]}
        ],
        "properties": [],
    },
    {
        "concepts": [{"type": "Document", "parent": None, "attributes": ["name", "document_type"]}],
        "properties": [],
    },
]

_MERGED_SCHEMA_FOR_MERGE = {
    "concepts": [
        {
            "type": "Document",
            "parent": None,
            "attributes": ["name", "date", "subject", "document_type"],
        }
    ],
    "properties": [],
}


def test_harmonize_for_merge_returns_improved_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MERGED_SCHEMA_FOR_MERGE)
    result = harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    assert result["concepts"][0]["type"] == "Document"
    assert result is not _MERGED_SCHEMA_FOR_MERGE


def test_harmonize_for_merge_falls_back_on_invalid_json():
    adapter = MagicMock()
    adapter.complete.return_value = "not json {"
    result = harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    assert result is _MERGED_SCHEMA_FOR_MERGE


def test_harmonize_for_merge_falls_back_on_wrong_structure():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"concepts": []})
    result = harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    assert result is _MERGED_SCHEMA_FOR_MERGE


def test_harmonize_for_merge_calls_llm_once():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MERGED_SCHEMA_FOR_MERGE)
    harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    assert adapter.complete.call_count == 1


def test_harmonize_for_merge_prompt_contains_merged_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MERGED_SCHEMA_FOR_MERGE)
    harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    user_prompt = adapter.complete.call_args[0][1]
    assert "Document" in user_prompt
    assert "MERGED SCHEMA:" in user_prompt


def test_harmonize_for_merge_prompt_contains_session_schemas():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MERGED_SCHEMA_FOR_MERGE)
    harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    user_prompt = adapter.complete.call_args[0][1]
    assert "SESSION SCHEMAS:" in user_prompt


def test_harmonize_for_merge_falls_back_on_adapter_exception():
    adapter = MagicMock()
    adapter.complete.side_effect = RuntimeError("boom")
    result = harmonize_schema_for_merge(_MERGED_SCHEMA_FOR_MERGE, _SESSION_SCHEMAS, adapter)
    assert result is _MERGED_SCHEMA_FOR_MERGE


# ---------------------------------------------------------------------------
# review_schema_quality_for_merge tests
# ---------------------------------------------------------------------------


def test_review_quality_for_merge_returns_improved_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MERGED_SCHEMA_FOR_MERGE)
    result = review_schema_quality_for_merge(_MERGED_SCHEMA_FOR_MERGE, adapter)
    assert result["concepts"][0]["type"] == "Document"
    assert result is not _MERGED_SCHEMA_FOR_MERGE


def test_review_quality_for_merge_falls_back_on_invalid_json():
    adapter = MagicMock()
    adapter.complete.return_value = "not json {"
    result = review_schema_quality_for_merge(_MERGED_SCHEMA_FOR_MERGE, adapter)
    assert result is _MERGED_SCHEMA_FOR_MERGE


def test_review_quality_for_merge_falls_back_on_adapter_exception():
    adapter = MagicMock()
    adapter.complete.side_effect = RuntimeError("boom")
    result = review_schema_quality_for_merge(_MERGED_SCHEMA_FOR_MERGE, adapter)
    assert result is _MERGED_SCHEMA_FOR_MERGE


# ---------------------------------------------------------------------------
# _reject_empty_schema guard tests (bug #151)
# ---------------------------------------------------------------------------

_MULTI_CONCEPT_SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name", "industry"]},
        {"type": "Project", "parent": None, "attributes": ["name", "deadline"]},
        {"type": "SoftwareEngineer", "parent": "Person", "attributes": ["seniority"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]}
    ],
}


def test_review_schema_quality_rejects_empty_concepts():
    """review_schema_quality must fall back to original when LLM returns zero concepts."""
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"concepts": [], "properties": []})
    result = review_schema_quality(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is _MULTI_CONCEPT_SCHEMA


def test_review_schema_quality_rejects_drastic_reduction():
    """review_schema_quality must fall back when LLM drops >50% of concepts."""
    adapter = MagicMock()
    # 1 concept out of 4 original is 25% — below the 50% floor
    tiny = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    adapter.complete.return_value = json.dumps(tiny)
    result = review_schema_quality(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is _MULTI_CONCEPT_SCHEMA


def test_review_schema_quality_accepts_minor_reduction():
    """review_schema_quality must accept LLM result when concept count is >= 50% of original."""
    adapter = MagicMock()
    # 3 concepts out of 4 original is 75% — above the 50% floor
    trimmed = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
            {"type": "Project", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
    adapter.complete.return_value = json.dumps(trimmed)
    result = review_schema_quality(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is not _MULTI_CONCEPT_SCHEMA
    assert len(result["concepts"]) == 3


def test_review_schema_quality_accepts_same_count():
    """review_schema_quality must accept LLM result with identical concept count."""
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_MULTI_CONCEPT_SCHEMA)
    result = review_schema_quality(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is not _MULTI_CONCEPT_SCHEMA
    assert len(result["concepts"]) == 4


def test_review_quality_for_merge_rejects_empty_concepts():
    """review_schema_quality_for_merge must fall back to original when LLM returns zero concepts."""
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"concepts": [], "properties": []})
    result = review_schema_quality_for_merge(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is _MULTI_CONCEPT_SCHEMA


def test_review_quality_for_merge_rejects_drastic_reduction():
    """review_schema_quality_for_merge must fall back when LLM drops >50% of concepts."""
    adapter = MagicMock()
    tiny = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    adapter.complete.return_value = json.dumps(tiny)
    result = review_schema_quality_for_merge(_MULTI_CONCEPT_SCHEMA, adapter)
    assert result is _MULTI_CONCEPT_SCHEMA
