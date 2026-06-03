from __future__ import annotations

import json
from unittest.mock import MagicMock

from mykg.orphan_connector import (
    OrphanCandidate,
    OrphanChunkGroup,
    SchemaGapOrphan,
    _build_chunk_recovery_prompt,
    _build_confirmation_prompt,
    _extract_relevant_excerpt,
    _get_node_attr,
    build_chunk_texts,
    confirm_orphan_chunk_groups,
    confirm_orphan_edges,
    propose_schema_additions,
    score_orphan_candidates,
    score_orphan_candidates_v2,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _node(id_, type_, name):
    return {
        "id": id_,
        "type": type_,
        "confidence": 0.9,
        "attributes": {"name": {"value": name, "confidence": 0.9}},
        "source_files": ["input.md"],
    }


SCHEMA = {
    "concepts": [
        {"type": "Person", "attributes": ["name"], "parent": None},
        {"type": "Organization", "attributes": ["name"], "parent": None},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
        {"name": "knows", "domain": "Person", "range": "Person", "attributes": []},
    ],
}


# ---------------------------------------------------------------------------
# Test 1: no orphans when all nodes are connected
# ---------------------------------------------------------------------------


def test_no_orphans_when_all_connected():
    nodes = [_node("person-alice", "Person", "Alice"), _node("org-acme", "Organization", "Acme")]
    edge_metadata = {
        "edge-001": {
            "type": "works_at",
            "from": "person-alice",
            "to": "org-acme",
            "method": "llm_extraction",
        },
    }
    chunk_index = {"f.md": {"1": ["person-alice", "org-acme"]}}
    candidates, gap_orphans = score_orphan_candidates(nodes, edge_metadata, chunk_index, SCHEMA)
    assert candidates == []
    assert gap_orphans == []


# ---------------------------------------------------------------------------
# Test 2: orphan with no chunk appearances → skipped
# ---------------------------------------------------------------------------


def test_orphan_with_no_chunk_appearances_skipped():
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    edge_metadata = {
        "edge-001": {"type": "works_at", "from": "org-acme", "to": "org-acme"},
    }
    chunk_index = {"f.md": {"1": ["org-acme"]}}  # person-bob never appears
    candidates, gap_orphans = score_orphan_candidates(nodes, edge_metadata, chunk_index, SCHEMA)
    assert candidates == []
    assert gap_orphans == []  # no chunk appearances → skipped, not a schema gap


# ---------------------------------------------------------------------------
# Test 3: co-occurrence below min → filtered out
# ---------------------------------------------------------------------------


def test_cooccurrence_below_min_filtered():
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    edge_metadata = {}
    chunk_index = {"f.md": {"1": ["person-bob", "org-acme"]}}  # one co-occurrence
    candidates, _ = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, SCHEMA, min_cooccurrence=2
    )
    assert candidates == []


# ---------------------------------------------------------------------------
# Test 4: valid candidate produced above min
# ---------------------------------------------------------------------------


def test_valid_candidate_produced():
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    edge_metadata = {}
    chunk_index = {
        "f.md": {
            "1": ["person-bob", "org-acme"],
            "2": ["person-bob", "org-acme"],
        }
    }
    candidates, _ = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, SCHEMA, min_cooccurrence=2
    )
    # Both nodes are orphans, so both produce a candidate pointing at each other
    assert len(candidates) == 2
    orphan_ids = {c.orphan_id for c in candidates}
    assert "person-bob" in orphan_ids
    assert "org-acme" in orphan_ids
    for c in candidates:
        assert c.cooccurrence_count == 2


# ---------------------------------------------------------------------------
# Test 5: schema type filtering excludes incompatible pairs
# ---------------------------------------------------------------------------


def test_schema_type_filtering():
    # Organization→Organization: (Organization, Organization) not a valid pair in SCHEMA.
    # Both orgs co-occur but the schema filter eliminates all candidates → schema-gap orphans.
    nodes = [
        _node("org-acme", "Organization", "Acme"),
        _node("org-beta", "Organization", "Beta"),
    ]
    edge_metadata = {}
    chunk_index = {"f.md": {"1": ["org-acme", "org-beta"], "2": ["org-acme", "org-beta"]}}
    candidates, gap_orphans = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, SCHEMA, min_cooccurrence=2
    )
    assert candidates == []
    # Both orgs have co-occurring peers but no valid pair → both are schema-gap orphans
    assert len(gap_orphans) == 2


# ---------------------------------------------------------------------------
# Test 6: top_k limits candidates per orphan
# ---------------------------------------------------------------------------


def test_top_k_limits_candidates():
    nodes = [
        _node("person-bob", "Person", "Bob"),
        _node("org-a", "Organization", "A"),
        _node("org-b", "Organization", "B"),
        _node("org-c", "Organization", "C"),
    ]
    edge_metadata = {}
    chunk_index = {
        "f.md": {
            "1": ["person-bob", "org-a", "org-b", "org-c"],
            "2": ["person-bob", "org-a", "org-b"],
            "3": ["person-bob", "org-a"],
        }
    }
    candidates, _ = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, SCHEMA, min_cooccurrence=1, top_k=2
    )
    orphan_results = [c for c in candidates if c.orphan_id == "person-bob"]
    assert len(orphan_results) <= 2


# ---------------------------------------------------------------------------
# Test 7: heuristic_score is in [0, 1]
# ---------------------------------------------------------------------------


def test_heuristic_score_in_range():
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    edge_metadata = {}
    chunk_index = {"f.md": {"1": ["person-bob", "org-acme"], "2": ["person-bob", "org-acme"]}}
    candidates, _ = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, SCHEMA, min_cooccurrence=2
    )
    for c in candidates:
        assert 0.0 <= c.heuristic_score <= 1.0


# ---------------------------------------------------------------------------
# Test 8: _get_node_attr returns dict value
# ---------------------------------------------------------------------------


def test_get_node_attr_dict_value():
    node = {"id": "x", "attributes": {"name": {"value": "Alice", "confidence": 0.9}}}
    assert _get_node_attr(node, "name") == "Alice"


# ---------------------------------------------------------------------------
# Test 9: confirm_orphan_edges — LLM returns connected=true → edge produced
# ---------------------------------------------------------------------------


def test_confirm_returns_edge_on_connected():
    import json

    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=3,
        heuristic_score=0.6,
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "connected": True,
            "type": "works_at",
            "confidence": 0.85,
            "rationale": "Bob is described as an employee of Acme.",
        }
    )
    edges, _ = confirm_orphan_edges([candidate], SCHEMA, adapter, max_workers=1)
    assert len(edges) == 1
    assert edges[0]["type"] == "works_at"
    assert edges[0]["method"] == "orphan_inferred"
    assert edges[0]["from"] == "person-bob"
    assert edges[0]["to"] == "org-acme"
    assert 0.0 < edges[0]["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Test 9b: _extract_relevant_excerpt finds name mention, not start of text
# ---------------------------------------------------------------------------


def test_extract_relevant_excerpt_finds_name():
    junk = "X. " * 500  # 1500 chars of junk before the relevant text
    relevant = "Alice works at Acme Corp as an engineer."
    text = junk + relevant
    # With a small context (10 chars before match), the excerpt should contain the relevant text
    excerpt = _extract_relevant_excerpt(text, ["Alice", "Acme"], window=200, context=10)
    assert "Alice" in excerpt or "Acme" in excerpt
    # The excerpt must contain the relevant sentence, not just junk
    assert "works at Acme" in excerpt or "Alice works" in excerpt


def test_extract_relevant_excerpt_all_mentions():
    text = "Alice met Bob. Then Alice went home. Finally Alice called Bob."
    excerpt = _extract_relevant_excerpt(text, ["Alice"], window=30, context=5)
    # All three mentions of Alice should appear
    assert excerpt.count("Alice") == 3


def test_extract_relevant_excerpt_overlapping_windows_merged():
    # Two names close together should produce one merged window, not two
    text = "Alice and Bob work together at Acme."
    excerpt = _extract_relevant_excerpt(text, ["Alice", "Bob"], window=50, context=5)
    assert "---" not in excerpt  # merged into one window


def test_extract_relevant_excerpt_fallback_when_no_match():
    text = "Some text with no matching names."
    excerpt = _extract_relevant_excerpt(text, ["Gee", "Brentnall"], window=100, context=20)
    assert excerpt.startswith("Some text")


# ---------------------------------------------------------------------------
# Test 10a: chunk text appears in the confirmation prompt
# ---------------------------------------------------------------------------


def test_confirmation_prompt_includes_chunk_text():
    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=1,
        heuristic_score=0.5,
        shared_chunks=["f.md::1"],
    )
    chunk_texts = {"f.md::1": "Bob is the chief engineer at Acme Corp."}
    prompt = _build_confirmation_prompt(candidate, SCHEMA, chunk_texts)
    assert "Bob is the chief engineer at Acme Corp." in prompt
    assert "SOURCE TEXT" in prompt


# ---------------------------------------------------------------------------
# Test 10b: prompt still renders when no chunk text is available
# ---------------------------------------------------------------------------


def test_confirmation_prompt_no_chunk_text():
    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=1,
        heuristic_score=0.5,
        shared_chunks=["f.md::1"],
    )
    prompt = _build_confirmation_prompt(candidate, SCHEMA, {})
    assert "no source text available" in prompt


# ---------------------------------------------------------------------------
# Test 10c: _build_chunk_texts maps filename::1-based-idx correctly
# ---------------------------------------------------------------------------


def test_build_chunk_texts_key_format():
    manifest = {"doc.md": "Hello world " * 10}  # short enough to be one chunk
    texts = build_chunk_texts(manifest)
    assert any(k.startswith("doc.md::") for k in texts)
    # Key must be 1-based (chunk_index=0 → "1")
    assert "doc.md::1" in texts


# ---------------------------------------------------------------------------
# #86 — orphan-inferred edges must have schema attributes backfilled
# ---------------------------------------------------------------------------


def test_confirm_orphan_edges_backfills_schema_attributes():
    """confirmed edges must carry null-filled attributes for all schema edge attrs (Invariant 6)."""
    schema_with_attrs = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
        ],
        "properties": [
            {
                "name": "works_at",
                "domain": "Person",
                "range": "Organization",
                "attributes": ["role", "start_date"],
            },
        ],
    }
    candidate = OrphanCandidate(
        orphan_id="person-alice",
        orphan_type="Person",
        orphan_name="Alice",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=2,
        heuristic_score=0.8,
        shared_chunks=["doc.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "connected": True,
            "type": "works_at",
            "confidence": 0.9,
            "rationale": "text says so",
        }
    )

    confirmed, _ = confirm_orphan_edges([candidate], schema_with_attrs, adapter)

    assert len(confirmed) == 1
    attrs = confirmed[0]["attributes"]
    assert "role" in attrs, "role attribute must be backfilled"
    assert "start_date" in attrs, "start_date attribute must be backfilled"
    assert attrs["role"] == {"value": None, "confidence": 0.0}
    assert attrs["start_date"] == {"value": None, "confidence": 0.0}


# ---------------------------------------------------------------------------
# #92 — propose_schema_additions must reject invalid domain/range
# ---------------------------------------------------------------------------


def test_propose_schema_additions_rejects_unknown_domain():
    """Properties with domain not in concepts[] must be silently dropped."""
    schema_with_concepts = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
    gap_orphans = [
        SchemaGapOrphan(
            orphan_id="phenomenon-ufo",
            orphan_type="Phenomenon",
            orphan_name="UFO",
            cooccurring_types=["Person"],
            shared_chunks=[],
        )
    ]
    adapter = MagicMock()
    # LLM proposes a property with an unknown domain "Phenomenon"
    adapter.complete.return_value = json.dumps(
        {
            "new_properties": [
                {
                    "name": "witnessed_by",
                    "domain": "Phenomenon",
                    "range": "Person",
                    "attributes": [],
                },
                {"name": "bad_prop", "domain": "UnknownType", "range": "Person", "attributes": []},
            ]
        }
    )
    result = propose_schema_additions(gap_orphans, schema_with_concepts, adapter, {})
    # "witnessed_by" has domain "Phenomenon" which is NOT in concepts — must be dropped
    # "bad_prop" has domain "UnknownType" — must be dropped
    # Result should have new_properties filtered to only valid entries
    assert result is not None
    valid_names = [p["name"] for p in result.get("new_properties", [])]
    assert "bad_prop" not in valid_names
    assert "witnessed_by" not in valid_names  # Phenomenon not in concepts


def test_propose_schema_additions_keeps_valid_properties():
    """Properties with domain and range both in concepts[] must be kept."""
    schema_with_concepts = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
    gap_orphans = [
        SchemaGapOrphan(
            orphan_id="person-bob",
            orphan_type="Person",
            orphan_name="Bob",
            cooccurring_types=["Organization"],
            shared_chunks=[],
        )
    ]
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "new_properties": [
                {
                    "name": "affiliated_with",
                    "domain": "Person",
                    "range": "Organization",
                    "attributes": [],
                },
            ]
        }
    )
    result = propose_schema_additions(gap_orphans, schema_with_concepts, adapter, {})
    assert result is not None
    valid_names = [p["name"] for p in result.get("new_properties", [])]
    assert "affiliated_with" in valid_names


# ---------------------------------------------------------------------------
# #94 — orphan_log events: rejected candidates must be logged
# ---------------------------------------------------------------------------


def test_confirm_orphan_edges_returns_rejection_info():
    """confirm_orphan_edges must return rejection metadata alongside confirmed edges."""
    candidate_good = OrphanCandidate(
        orphan_id="person-alice",
        orphan_type="Person",
        orphan_name="Alice",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=3,
        heuristic_score=1.0,
        shared_chunks=["doc.md::1"],
    )
    candidate_bad = OrphanCandidate(
        orphan_id="person-alice",
        orphan_type="Person",
        orphan_name="Alice",
        candidate_id="org-other",
        candidate_type="Organization",
        candidate_name="Other Inc",
        cooccurrence_count=1,
        heuristic_score=0.3,
        shared_chunks=["doc.md::1"],
    )
    adapter = MagicMock()
    # First call: confirm; second call: reject
    adapter.complete.side_effect = [
        json.dumps({"connected": True, "type": "works_at", "confidence": 0.9, "rationale": "ok"}),
        json.dumps({"connected": False}),
    ]
    schema_local = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
        ],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
        ],
    }
    confirmed, rejections = confirm_orphan_edges(
        [candidate_good, candidate_bad], schema_local, adapter
    )
    assert len(confirmed) == 1
    assert len(rejections) == 1
    assert rejections[0]["orphan_id"] == "person-alice"
    assert rejections[0]["candidate_id"] == "org-other"
    assert rejections[0]["reason"] == "llm_rejected"


# ---------------------------------------------------------------------------
# #88 — feedback.apply("schema_extend") must use schema_extend handler
# ---------------------------------------------------------------------------


def test_feedback_schema_extend_handler_registered(tmp_path):
    """schema_extend must have its own handler in feedback._HANDLERS."""
    import json as _json
    from unittest.mock import MagicMock

    from mykg.feedback import apply
    from mykg.orchestrator import PipelineContext

    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=MagicMock(),
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    # Write a schema_gap_proposals.json so schema_extend handler has context
    proposal = {
        "new_properties": [
            {"name": "affiliated_with", "domain": "Person", "range": "Org", "attributes": []},
        ]
    }
    (ctx.intermediate_dir / "schema_gap_proposals.json").write_text(_json.dumps(proposal))
    (ctx.intermediate_dir / "schema.json").write_text(
        _json.dumps({"concepts": [], "properties": []})
    )

    corrected = {"concepts": [], "properties": []}
    ctx.adapter.complete.return_value = _json.dumps(corrected)

    result = apply("schema_extend", "domain Person not declared", ctx)
    assert result is True, "schema_extend must have a registered handler"


# ---------------------------------------------------------------------------
# Test 11: confirm_orphan_edges — connected=false → no edge
# ---------------------------------------------------------------------------


def test_confirm_returns_nothing_on_not_connected():
    import json

    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=3,
        heuristic_score=0.6,
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "connected": False,
            "type": None,
            "confidence": 0.1,
            "rationale": "No relationship found.",
        }
    )
    edges, rejections = confirm_orphan_edges([candidate], SCHEMA, adapter, max_workers=1)
    assert edges == []
    assert len(rejections) == 1
    assert rejections[0]["reason"] == "llm_rejected"


# ---------------------------------------------------------------------------
# Test 12: schema-gap orphan detection — type absent from all schema properties
# ---------------------------------------------------------------------------


def test_schema_gap_orphan_detected():
    # Vehicle co-occurs only with Person; (Vehicle, Person) not a valid pair → schema-gap.
    # Person co-occurs only with Vehicle; (Person, Vehicle) not a valid pair → also schema-gap.
    # Both are eliminated by the type-pair filter even though Person IS in schema_types.
    schema_with_vehicle = {
        "concepts": [
            {"type": "Person", "attributes": ["name"], "parent": None},
            {"type": "Vehicle", "attributes": ["name"], "parent": None},
        ],
        "properties": [
            {"name": "knows", "domain": "Person", "range": "Person", "attributes": []},
        ],
    }
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("vehicle-car", "Vehicle", "Car"),
    ]
    edge_metadata = {}
    chunk_index = {
        "f.md": {"1": ["person-alice", "vehicle-car"], "2": ["person-alice", "vehicle-car"]}
    }
    candidates, gap_orphans = score_orphan_candidates(
        nodes, edge_metadata, chunk_index, schema_with_vehicle, min_cooccurrence=1
    )
    gap_ids = {g.orphan_id for g in gap_orphans}
    assert "vehicle-car" in gap_ids
    assert "person-alice" in gap_ids  # only co-occurs with Vehicle, not another Person


# ---------------------------------------------------------------------------
# Test 13: propose_schema_additions — LLM returns new property → returned
# ---------------------------------------------------------------------------


def test_propose_schema_additions_returns_proposal():
    import json

    schema_with_vehicle = {
        "concepts": [
            {"type": "Person", "attributes": ["name"], "parent": None},
            {"type": "Vehicle", "attributes": ["name"], "parent": None},
        ],
        "properties": [
            {"name": "knows", "domain": "Person", "range": "Person", "attributes": []},
        ],
    }
    gap = SchemaGapOrphan(
        orphan_id="vehicle-car",
        orphan_type="Vehicle",
        orphan_name="Car",
        cooccurring_types=["Person"],
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "new_properties": [
                {"name": "owns", "domain": "Person", "range": "Vehicle", "attributes": []}
            ]
        }
    )
    result = propose_schema_additions([gap], schema_with_vehicle, adapter, chunk_texts={})
    assert result is not None
    assert len(result["new_properties"]) == 1
    assert result["new_properties"][0]["name"] == "owns"


# ---------------------------------------------------------------------------
# Test 14: propose_schema_additions — LLM proposes nothing → returns None
# ---------------------------------------------------------------------------


def test_propose_schema_additions_empty_returns_none():
    import json

    gap = SchemaGapOrphan(
        orphan_id="vehicle-car",
        orphan_type="Vehicle",
        orphan_name="Car",
        cooccurring_types=["Person"],
        shared_chunks=[],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"new_properties": []})
    result = propose_schema_additions([gap], SCHEMA, adapter, chunk_texts={})
    assert result is None


# ---------------------------------------------------------------------------
# Test 15: propose_schema_additions — no gap orphans → returns None immediately
# ---------------------------------------------------------------------------


def test_propose_schema_additions_no_gaps():
    adapter = MagicMock()
    result = propose_schema_additions([], SCHEMA, adapter, chunk_texts={})
    assert result is None
    adapter.complete.assert_not_called()


# ---------------------------------------------------------------------------
# Test 16: direction flip — LLM returns works_at (Person→Organization),
# orphan is Organization, candidate is Person → edge flipped to from=Person, to=Organization
# ---------------------------------------------------------------------------


def test_confirm_direction_flip():
    """When the schema property direction is candidate→orphan, the edge must be flipped."""
    import json

    # orphan is Organization, candidate is Person
    # works_at is defined as Person→Organization
    # so the direction must flip: from=candidate (Person), to=orphan (Organization)
    candidate = OrphanCandidate(
        orphan_id="org-acme",
        orphan_type="Organization",
        orphan_name="Acme",
        candidate_id="person-bob",
        candidate_type="Person",
        candidate_name="Bob",
        cooccurrence_count=2,
        heuristic_score=0.7,
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "connected": True,
            "type": "works_at",
            "confidence": 0.9,
            "rationale": "Bob is described as an employee of Acme.",
        }
    )
    edges, _ = confirm_orphan_edges([candidate], SCHEMA, adapter, max_workers=1)
    assert len(edges) == 1
    # works_at: Person→Organization; from = Person (candidate), to = Organization (orphan)
    assert edges[0]["from"] == "person-bob", "from must be Person (candidate), not orphan"
    assert edges[0]["to"] == "org-acme", "to must be Organization (orphan), not candidate"


# ---------------------------------------------------------------------------
# Test 17: incompatible type rejection — property exists globally but not for this pair
# ---------------------------------------------------------------------------


def test_confirm_incompatible_type_pair_rejected():
    """LLM returns a property that exists in schema but is incompatible with the type pair."""
    import json

    # knows is Person→Person; candidate pair here is Person↔Organization, so knows is incompatible
    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=2,
        heuristic_score=0.7,
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "connected": True,
            "type": "knows",  # 'knows' is Person→Person, not valid for Person↔Organization
            "confidence": 0.9,
            "rationale": "They know each other.",
        }
    )
    edges, rejections = confirm_orphan_edges([candidate], SCHEMA, adapter, max_workers=1)
    assert edges == [], "edge with incompatible type must be rejected"
    assert len(rejections) == 1, "rejection must be recorded"


# ---------------------------------------------------------------------------
# Tests for score_orphan_candidates_v2 and confirm_orphan_chunk_groups
# ---------------------------------------------------------------------------


def _failed(filename, chunk_idx):
    return {"filename": filename, "chunk_idx": chunk_idx, "reason": "blank_response"}


def test_chunk_group_groups_orphans_by_chunk():
    """Two orphans from the same chunk produce one OrphanChunkGroup."""
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("person-bob", "Person", "Bob"),
        _node("org-acme", "Organization", "Acme"),
    ]
    edge_metadata = {"e1": {"from": "org-acme", "to": "person-alice", "type": "works_at"}}
    chunk_index = {"input.md": {"1": ["person-alice", "person-bob", "org-acme"]}}

    groups, gap_orphans = score_orphan_candidates_v2(
        nodes, edge_metadata, chunk_index, SCHEMA, failed_chunks=[]
    )
    assert len(groups) == 1
    group = groups[0]
    assert group.chunk_key == "input.md::1"
    assert "person-bob" in group.orphan_ids
    assert group.is_blank_response is False


def test_blank_response_orphan_detected_via_failed_chunks():
    """Orphan with no index entry but matching failed_chunks gets flagged."""
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("org-acme", "Organization", "Acme"),
    ]
    edge_metadata = {"e1": {"from": "org-acme", "to": "org-acme", "type": "works_at"}}
    chunk_index = {}
    failed = [_failed("input.md", 1)]
    file_manifest = {"input.md": {"content": "Alice Smith attended the meeting.\n" * 5}}

    groups, gap_orphans = score_orphan_candidates_v2(
        nodes, edge_metadata, chunk_index, SCHEMA, failed_chunks=failed, file_manifest=file_manifest
    )
    assert len(groups) == 1
    g = groups[0]
    assert g.is_blank_response is True
    assert "person-alice" in g.orphan_ids
    alice = next(n for n in nodes if n["id"] == "person-alice")
    assert alice.get("extraction_quality") == "blank_response"
    assert alice.get("blank_chunk_file") == "input.md"
    assert alice.get("blank_chunk_idx") == 1


def test_schema_incompatible_connected_node_excluded():
    """Orphan co-occurring with a type-incompatible connected node: group created, empty ids."""
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("location-dc", "Location", "Washington DC"),
    ]
    edge_metadata = {"e1": {"from": "person-alice", "to": "person-alice", "type": "knows"}}
    schema_no_location = {
        "concepts": [
            {"type": "Person", "attributes": ["name"], "parent": None},
            {"type": "Location", "attributes": ["name"], "parent": None},
        ],
        "properties": [
            {"name": "knows", "domain": "Person", "range": "Person", "attributes": []},
        ],
    }
    chunk_index = {"input.md": {"1": ["person-alice", "location-dc"]}}
    groups, gap_orphans = score_orphan_candidates_v2(
        nodes, edge_metadata, chunk_index, schema_no_location, failed_chunks=[]
    )
    assert len(groups) == 1
    assert "location-dc" in groups[0].orphan_ids
    # person-alice is connected but Person→Location has no schema property → excluded
    assert groups[0].connected_ids == []
    assert len(gap_orphans) == 0


def test_connected_ids_sorted_by_cooccurrence_frequency():
    """Connected node co-occurring with more orphans in the group ranks higher."""
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("person-bob", "Person", "Bob"),
        _node("org-acme", "Organization", "Acme"),
    ]
    # alice and bob are orphans; acme is connected
    edge_metadata = {"e1": {"from": "org-acme", "to": "org-acme", "type": "works_at"}}
    # Both alice and bob co-occur with acme in the same chunk
    chunk_index = {"input.md": {"1": ["person-alice", "person-bob", "org-acme"]}}
    groups, _ = score_orphan_candidates_v2(
        nodes, edge_metadata, chunk_index, SCHEMA, failed_chunks=[]
    )
    assert len(groups) == 1
    # org-acme co-occurs with 2 orphans (alice=Person, bob=Person), both compatible via works_at
    assert groups[0].connected_ids == ["org-acme"]


def test_connected_ids_ranked_higher_frequency_first():
    """When two connected nodes compete, the one co-occurring with more orphans ranks first."""
    nodes = [
        _node("person-alice", "Person", "Alice"),
        _node("person-bob", "Person", "Bob"),
        _node("org-acme", "Organization", "Acme"),
        _node("org-beta", "Organization", "Beta"),
    ]
    # alice and bob are orphans; acme and beta are connected
    edge_metadata = {
        "e1": {"from": "org-acme", "to": "org-acme", "type": "works_at"},
        "e2": {"from": "org-beta", "to": "org-beta", "type": "works_at"},
    }
    # Both orphans share chunk 1 with acme; only alice shares chunk 1 with beta
    chunk_index = {
        "input.md": {
            "1": ["person-alice", "person-bob", "org-acme"],
            "2": ["person-alice", "org-beta"],
        }
    }
    groups, _ = score_orphan_candidates_v2(
        nodes, edge_metadata, chunk_index, SCHEMA, failed_chunks=[]
    )
    # Two chunk groups: chunk 1 and chunk 2
    by_key = {g.chunk_key: g for g in groups}
    # In chunk 1: acme co-occurs with 2 orphans (alice+bob) → score 2
    assert by_key["input.md::1"].connected_ids == ["org-acme"]
    # In chunk 2: beta co-occurs with 1 orphan (alice) → score 1; acme not in this chunk
    assert by_key["input.md::2"].connected_ids == ["org-beta"]


def test_chunk_recovery_prompt_contains_full_chunk_text():
    """Recovery prompt includes full chunk text, orphan node ids, and schema."""
    group = OrphanChunkGroup(
        chunk_key="input.md::1",
        filename="input.md",
        chunk_idx=1,
        is_blank_response=False,
        orphan_ids=["person-bob"],
        connected_ids=["org-acme"],
    )
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    chunk_texts = {"input.md::1": "Bob joined Acme Corp last year."}
    prompt = _build_chunk_recovery_prompt(group, nodes, SCHEMA, chunk_texts)
    assert "Bob joined Acme Corp last year." in prompt
    assert "person-bob" in prompt
    assert "org-acme" in prompt
    assert "works_at" in prompt


def test_confirm_chunk_groups_returns_edges_for_connected():
    """LLM returning a valid edge array produces confirmed edges."""
    group = OrphanChunkGroup(
        chunk_key="input.md::1",
        filename="input.md",
        chunk_idx=1,
        is_blank_response=False,
        orphan_ids=["person-bob"],
        connected_ids=["org-acme"],
    )
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    chunk_texts = {"input.md::1": "Bob works at Acme Corp."}
    response = json.dumps(
        [
            {
                "type": "works_at",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.9,
                "rationale": "Bob works at Acme Corp.",
            }
        ]
    )
    adapter = MagicMock()
    adapter.complete.return_value = response

    confirmed, rejections = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts=chunk_texts
    )
    assert len(confirmed) == 1
    edge = confirmed[0]
    assert edge["type"] == "works_at"
    assert edge["from"] == "person-bob"
    assert edge["to"] == "org-acme"
    assert edge["method"] == "orphan_inferred"


def test_blank_response_node_flagged_recovered_after_edge_found():
    """A blank_response node gets extraction_quality=blank_recovered when an edge is found."""
    group = OrphanChunkGroup(
        chunk_key="input.md::2",
        filename="input.md",
        chunk_idx=2,
        is_blank_response=True,
        orphan_ids=["person-alice"],
        connected_ids=["org-acme"],
    )
    nodes = [
        {**_node("person-alice", "Person", "Alice"), "extraction_quality": "blank_response"},
        _node("org-acme", "Organization", "Acme"),
    ]
    chunk_texts = {"input.md::2": "Alice worked at Acme Corp."}
    response = json.dumps(
        [
            {
                "type": "works_at",
                "from": "person-alice",
                "to": "org-acme",
                "confidence": 0.85,
                "rationale": "Alice worked at Acme Corp.",
            }
        ]
    )
    adapter = MagicMock()
    adapter.complete.return_value = response

    confirmed, _ = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts=chunk_texts
    )
    assert len(confirmed) == 1
    alice = next(n for n in nodes if n["id"] == "person-alice")
    assert alice["extraction_quality"] == "blank_recovered"


def test_blank_response_node_flagged_unresolved_when_no_edge():
    """A blank_response node gets extraction_quality=blank_unresolved when LLM returns []."""
    group = OrphanChunkGroup(
        chunk_key="input.md::2",
        filename="input.md",
        chunk_idx=2,
        is_blank_response=True,
        orphan_ids=["person-alice"],
        connected_ids=["org-acme"],
    )
    nodes = [
        {**_node("person-alice", "Person", "Alice"), "extraction_quality": "blank_response"},
        _node("org-acme", "Organization", "Acme"),
    ]
    chunk_texts = {"input.md::2": "Unrelated text."}
    adapter = MagicMock()
    adapter.complete.return_value = "[]"

    confirmed, _ = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts=chunk_texts
    )
    assert confirmed == []
    alice = next(n for n in nodes if n["id"] == "person-alice")
    assert alice["extraction_quality"] == "blank_unresolved"


def test_invalid_edge_type_dropped_partial_recovery():
    """An edge with unknown type is dropped; valid edges in same response kept."""
    group = OrphanChunkGroup(
        chunk_key="input.md::1",
        filename="input.md",
        chunk_idx=1,
        is_blank_response=False,
        orphan_ids=["person-bob"],
        connected_ids=["org-acme"],
    )
    nodes = [_node("person-bob", "Person", "Bob"), _node("org-acme", "Organization", "Acme")]
    chunk_texts = {"input.md::1": "Bob works at Acme."}
    response = json.dumps(
        [
            {
                "type": "invented_type",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.9,
                "rationale": "x",
            },
            {
                "type": "works_at",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.85,
                "rationale": "y",
            },
        ]
    )
    adapter = MagicMock()
    adapter.complete.return_value = response

    confirmed, _ = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts=chunk_texts
    )
    assert len(confirmed) == 1
    assert confirmed[0]["type"] == "works_at"


# ---------------------------------------------------------------------------
# Extended Unit 9 — orphan_connector helper coverage
# ---------------------------------------------------------------------------


def test_get_node_attr_bare_string_value():
    """_get_node_attr handles bare-string attribute values (line 100)."""
    node = {"id": "p-1", "attributes": {"nickname": "Alex"}}
    assert _get_node_attr(node, "nickname") == "Alex"


def test_get_node_attr_falls_back_to_id():
    """_get_node_attr returns id when attribute is missing or empty."""
    node = {"id": "p-1", "attributes": {"name": {"value": "", "confidence": 0.0}}}
    assert _get_node_attr(node, "name") == "p-1"


def test_best_display_name_subject_fallback():
    """_best_display_name uses subject when name is missing (line 114)."""
    from mykg.orphan_connector import _best_display_name

    node = {
        "id": "doc-1",
        "attributes": {"subject": {"value": "Report", "confidence": 1.0}},
    }
    assert _best_display_name(node) == "Report"


def test_best_display_name_bare_string():
    """_best_display_name handles bare string title attribute (line 114)."""
    from mykg.orphan_connector import _best_display_name

    node = {"id": "x", "attributes": {"title": "Memo"}}
    assert _best_display_name(node) == "Memo"


def test_best_display_name_falls_back_to_id():
    from mykg.orphan_connector import _best_display_name

    node = {"id": "thing-1", "attributes": {}}
    assert _best_display_name(node) == "thing-1"


def test_get_type_ancestors_walks_chain():
    """_get_type_ancestors walks parent chain (lines 128-129)."""
    from mykg.orphan_connector import _get_type_ancestors

    concept_map = {
        "Engineer": {"parent": "Person"},
        "Person": {"parent": "Agent"},
        "Agent": {"parent": None},
    }
    ancestors = _get_type_ancestors("Engineer", concept_map)
    assert "Engineer" in ancestors
    assert "Person" in ancestors
    assert "Agent" in ancestors


def test_get_type_ancestors_cycle_protection():
    """_get_type_ancestors stops on cycle (line 127)."""
    from mykg.orphan_connector import _get_type_ancestors

    concept_map = {
        "A": {"parent": "B"},
        "B": {"parent": "A"},  # cycle
    }
    ancestors = _get_type_ancestors("A", concept_map)
    assert "A" in ancestors
    assert "B" in ancestors


def test_is_schema_compatible_no_pairs_returns_true():
    """_is_schema_compatible: empty valid_pairs -> True (line 138)."""
    from mykg.orphan_connector import _is_schema_compatible

    assert _is_schema_compatible("X", "Y", {}, set()) is True


def test_confirm_one_json_parse_error():
    """_confirm_one returns None on bad JSON (lines 590-597)."""
    from mykg.orphan_connector import _confirm_one

    adapter = MagicMock()
    adapter.complete.return_value = "not valid json"

    candidate = OrphanCandidate(
        orphan_id="p-1",
        orphan_type="Person",
        orphan_name="Alice",
        candidate_id="o-1",
        candidate_type="Organization",
        candidate_name="Acme",
        shared_chunks=["doc.md::1"],
        heuristic_score=0.5,
        cooccurrence_count=1,
    )
    result = _confirm_one(candidate, SCHEMA, adapter, {"doc.md::1": "Alice at Acme"})
    assert result is None


def test_confirm_one_missing_type_returns_none():
    """_confirm_one returns None when connected=true but no type (lines 604-609)."""
    from mykg.orphan_connector import _confirm_one

    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"connected": True})

    candidate = OrphanCandidate(
        orphan_id="p-1",
        orphan_type="Person",
        orphan_name="Alice",
        candidate_id="o-1",
        candidate_type="Organization",
        candidate_name="Acme",
        shared_chunks=["doc.md::1"],
        heuristic_score=0.5,
        cooccurrence_count=1,
    )
    result = _confirm_one(candidate, SCHEMA, adapter, {})
    assert result is None


def test_confirm_orphan_chunk_groups_handles_parse_error():
    """confirm_orphan_chunk_groups handles JSON parse errors (lines 847-849)."""
    nodes = [_node("p-1", "Person", "Alice"), _node("o-1", "Organization", "Acme")]
    group = OrphanChunkGroup(
        filename="doc.md",
        chunk_idx=1,
        chunk_key="doc.md::1",
        orphan_ids=["p-1"],
        connected_ids=["o-1"],
        is_blank_response=False,
    )
    adapter = MagicMock()
    adapter.complete.return_value = "not valid json {{{"
    confirmed, rejections = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts={"doc.md::1": "text"}
    )
    assert confirmed == []
    assert any(r["reason"] == "parse_error" for r in rejections)


def test_confirm_orphan_chunk_groups_wrong_type():
    """confirm_orphan_chunk_groups handles dict response (not list) (lines 855-860)."""
    nodes = [_node("p-1", "Person", "Alice")]
    group = OrphanChunkGroup(
        filename="doc.md",
        chunk_idx=1,
        chunk_key="doc.md::1",
        orphan_ids=["p-1"],
        connected_ids=[],
        is_blank_response=False,
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"foo": "bar"})  # Not a list
    confirmed, rejections = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts={"doc.md::1": "x"}
    )
    assert confirmed == []
    assert any(r["reason"] == "wrong_type" for r in rejections)


def test_confirm_orphan_chunk_groups_drops_invalid_type():
    """Edges with unknown type are dropped (line 877)."""
    nodes = [_node("p-1", "Person", "Alice"), _node("o-1", "Organization", "Acme")]
    group = OrphanChunkGroup(
        filename="doc.md",
        chunk_idx=1,
        chunk_key="doc.md::1",
        orphan_ids=["p-1"],
        connected_ids=["o-1"],
        is_blank_response=False,
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        [
            {"type": "totally_invalid", "from": "p-1", "to": "o-1", "confidence": 0.9},
        ]
    )
    confirmed, _ = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts={"doc.md::1": "x"}
    )
    assert confirmed == []


def test_confirm_orphan_chunk_groups_drops_dangling():
    """Edges with from/to id not in node set are dropped (line 885)."""
    nodes = [_node("p-1", "Person", "Alice"), _node("o-1", "Organization", "Acme")]
    group = OrphanChunkGroup(
        filename="doc.md",
        chunk_idx=1,
        chunk_key="doc.md::1",
        orphan_ids=["p-1"],
        connected_ids=["o-1"],
        is_blank_response=False,
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        [
            {"type": "works_at", "from": "p-1", "to": "ghost", "confidence": 0.9},
        ]
    )
    confirmed, _ = confirm_orphan_chunk_groups(
        [group], nodes, SCHEMA, adapter, chunk_texts={"doc.md::1": "x"}
    )
    assert confirmed == []


def test_propose_schema_additions_unparseable(monkeypatch):
    """propose_schema_additions returns None on bad JSON (lines 1024-1026)."""
    adapter = MagicMock()
    adapter.complete.return_value = "not json"
    gap = SchemaGapOrphan(
        orphan_id="p-1",
        orphan_type="Person",
        orphan_name="Alice",
        cooccurring_types=["Organization"],
        shared_chunks=["doc.md::1"],
    )
    result = propose_schema_additions([gap], SCHEMA, adapter, {"doc.md::1": "x"})
    assert result is None


def test_propose_schema_additions_empty_after_filter():
    """All proposed properties have undeclared domain/range -> {new_properties: []}."""
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {
            "new_properties": [
                {
                    "name": "p1",
                    "domain": "UndeclaredType",
                    "range": "AnotherUndeclared",
                    "attributes": [],
                }
            ]
        }
    )
    gap = SchemaGapOrphan(
        orphan_id="p-1",
        orphan_type="Person",
        orphan_name="Alice",
        cooccurring_types=["Org"],
        shared_chunks=["doc.md::1"],
    )
    result = propose_schema_additions([gap], SCHEMA, adapter, {"doc.md::1": "x"})
    assert result == {"new_properties": []}
