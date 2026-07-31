import json

from mykg.llm.adapter import LLMAdapter
from mykg.pass2 import PASS2_SYSTEM_PROMPT, run_pass2, validate_extraction

SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": ["role"]}
    ],
}

FLAT_SCHEMA = {
    "Person": ["name", "email"],
    "Organization": ["name"],
}

VALID_EXTRACTION = {
    "nodes": [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.97,
            "attributes": {
                "name": {"value": "Alice", "confidence": 0.99},
                "email": {"value": "alice@acme.com", "confidence": 0.97},
            },
        },
        {
            "id": "org-acme",
            "type": "Organization",
            "confidence": 0.99,
            "attributes": {"name": {"value": "Acme", "confidence": 0.99}},
        },
    ],
    "edges": [
        {
            "id": "edge-001",
            "type": "works_at",
            "from": "person-alice",
            "to": "org-acme",
            "confidence": 0.96,
            "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
        }
    ],
}


class MockAdapter(LLMAdapter):
    def __init__(self, response: str):
        self._response = response

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        return self._response

    def endpoint_label(self) -> str:
        return "mock"


def test_validate_valid_extraction_passes():
    errors = validate_extraction(VALID_EXTRACTION, SCHEMA, FLAT_SCHEMA)
    assert errors == []


def test_validate_unknown_node_type_fails():
    bad = dict(VALID_EXTRACTION)
    bad["nodes"] = [{"id": "x", "type": "Ghost", "confidence": 0.5, "attributes": {}}]
    bad["edges"] = []
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("Ghost" in e for e in errors)


def test_validate_invalid_edge_type_fails():
    bad = dict(VALID_EXTRACTION)
    bad["edges"] = [
        {
            "id": "e1",
            "type": "invented_type",
            "from": "person-alice",
            "to": "org-acme",
            "confidence": 0.5,
            "attributes": {},
        }
    ]
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("invented_type" in e for e in errors)


def test_validate_dangling_from_fails():
    bad = dict(VALID_EXTRACTION)
    bad["edges"] = [
        {
            "id": "e1",
            "type": "works_at",
            "from": "nonexistent-id",
            "to": "org-acme",
            "confidence": 0.5,
            "attributes": {},
        }
    ]
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("nonexistent-id" in e for e in errors)


def test_run_pass2_returns_keyed_by_file():
    adapter = MockAdapter(json.dumps(VALID_EXTRACTION))
    files = {"team.md": "Alice works at Acme."}
    result, chunk_index, _failed = run_pass2(files, SCHEMA, FLAT_SCHEMA, adapter)
    assert "team.md" in result
    assert "team.md" in chunk_index


class RecordingAdapter(LLMAdapter):
    """Adapter that records every `user` prompt (chunk text) it is asked to extract."""

    def __init__(self, response: str):
        self._response = response
        self.user_prompts: list[str] = []

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        self.user_prompts.append(user)
        return self._response

    def endpoint_label(self) -> str:
        return "recording"


def test_run_pass2_truncates_oversized_file(tmp_path):
    """A file over max_file_tokens is truncated to its prefix; the tail never reaches the LLM,
    and the truncation is recorded in oversized_files.json."""
    adapter = RecordingAdapter(json.dumps(VALID_EXTRACTION))
    tail_marker = "UNIQUETAILMARKER"
    # First part is comfortably over the 100-token cap; the tail marker sits past it.
    big = ("prefix content here. " * 400) + tail_marker
    small = "Alice works at Acme."
    files = {"big.md": big, "small.md": small}

    result, _chunk_index, _failed = run_pass2(
        files,
        SCHEMA,
        FLAT_SCHEMA,
        adapter,
        max_workers=1,
        intermediate_dir=tmp_path,
        max_file_tokens=100,
    )

    # The tail past the cap must never have been sent to the LLM.
    assert not any(tail_marker in p for p in adapter.user_prompts)
    # The big file collapsed to a single (truncated) chunk / LLM call — a 1607-token file
    # would otherwise span multiple windows. The repeated phrase appears far fewer times in
    # the sent prompt than in the original ~400 repetitions, proving the body was truncated.
    big_prompts = [p for p in adapter.user_prompts if "prefix content here" in p]
    assert len(big_prompts) == 1
    assert big_prompts[0].count("prefix content here") < big.count("prefix content here")
    # Both files still produced results.
    assert "big.md" in result and "small.md" in result

    manifest = json.loads((tmp_path / "oversized_files.json").read_text(encoding="utf-8"))
    assert [r["filename"] for r in manifest] == ["big.md"]
    assert manifest[0]["cap"] == 100
    assert manifest[0]["original_tokens"] > 100


def test_run_pass2_no_cap_leaves_content_untouched(tmp_path):
    """max_file_tokens=0 (the default, used by concat/surgical callers) must not truncate,
    and must not write an oversized_files.json manifest."""
    adapter = RecordingAdapter(json.dumps(VALID_EXTRACTION))
    tail_marker = "UNIQUETAILMARKER"
    big = ("prefix content here. " * 400) + tail_marker
    files = {"big.md": big}

    run_pass2(
        files,
        SCHEMA,
        FLAT_SCHEMA,
        adapter,
        max_workers=1,
        intermediate_dir=tmp_path,
        max_file_tokens=0,
    )

    # The whole file (including the tail) reached the LLM — nothing dropped.
    assert any(tail_marker in p for p in adapter.user_prompts)
    assert not (tmp_path / "oversized_files.json").exists()


def test_pass2_system_prompt_contains_key_rules():
    assert "nodes" in PASS2_SYSTEM_PROMPT
    assert "edges" in PASS2_SYSTEM_PROMPT
    assert "from" in PASS2_SYSTEM_PROMPT


def test_backfill_missing_node_attributes():
    """Nodes missing schema attributes must be backfilled with {value: null, confidence: 0.0}."""
    from mykg.pass2 import _backfill_extraction

    extraction = {
        "nodes": [
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 0.9,
                "attributes": {},  # missing "name"
            }
        ],
        "edges": [],
    }
    result = _backfill_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    assert result["nodes"][0]["attributes"]["name"] == {"value": None, "confidence": 0.0}


def test_backfill_missing_edge_attributes():
    """Edges missing schema property attributes must be backfilled."""
    from mykg.pass2 import _backfill_extraction

    extraction = {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.9,
                "attributes": {
                    "name": {"value": "Alice", "confidence": 0.9},
                    "email": {"value": "a@b.com", "confidence": 0.8},
                },
            },
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 0.9,
                "attributes": {"name": {"value": "Acme", "confidence": 0.9}},
            },
        ],
        "edges": [
            {
                "id": "edge-001",
                "type": "works_at",
                "from": "person-alice",
                "to": "org-acme",
                "confidence": 0.8,
                "attributes": {},  # missing "role"
            }
        ],
    }
    result = _backfill_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    assert result["edges"][0]["attributes"]["role"] == {"value": None, "confidence": 0.0}


def test_intrafile_dedup_collapses_same_entity():
    """Nodes with the same type+name appearing in two chunks of the same file are deduped."""
    from mykg.pass2 import _dedup_within_file

    nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {
                "name": {"value": "Alice", "confidence": 0.9},
                "email": {"value": "a@b.com", "confidence": 0.8},
            },
        },
        {
            "id": "person-alice-2",
            "type": "Person",
            "confidence": 0.7,
            "attributes": {
                "name": {"value": "Alice", "confidence": 0.7},
                "email": {"value": None, "confidence": 0.0},
            },
        },
    ]
    deduped = _dedup_within_file(nodes)
    assert len(deduped) == 1
    # Higher-confidence email wins
    assert deduped[0]["attributes"]["email"]["confidence"] == 0.8


def test_run_pass2_respects_max_workers():
    """run_pass2 accepts a max_workers parameter; default 1 is sequential."""
    calls = []

    class TrackingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            calls.append(1)
            return json.dumps(VALID_EXTRACTION)

        def endpoint_label(self) -> str:
            return "mock-tracking"

    files = {"a.md": "content a", "b.md": "content b"}
    results, _, _failed = run_pass2(files, SCHEMA, FLAT_SCHEMA, TrackingAdapter(), max_workers=1)
    assert set(results.keys()) == {"a.md", "b.md"}


def test_run_pass2_parallel_workers():
    """run_pass2 with max_workers=2 still produces results for all files."""

    class FastAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps(VALID_EXTRACTION)

        def endpoint_label(self) -> str:
            return "mock-fast"

    files = {"a.md": "content a", "b.md": "content b", "c.md": "content c"}
    results, _, _failed = run_pass2(files, SCHEMA, FLAT_SCHEMA, FastAdapter(), max_workers=2)
    assert set(results.keys()) == {"a.md", "b.md", "c.md"}


def test_chunk_retry_on_validation_failure():
    """On validation failure, run_pass2 retries the chunk once with an error prompt."""
    good = json.dumps(VALID_EXTRACTION)
    bad = json.dumps(
        {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {
                        "name": {"value": "Alice", "confidence": 0.9},
                        "email": {"value": "a@b.com", "confidence": 0.8},
                    },
                }
            ],
            "edges": [
                {
                    "id": "edge-001",
                    "type": "INVALID_TYPE",
                    "from": "person-alice",
                    "to": "org-acme",
                    "confidence": 0.8,
                    "attributes": {"role": {"value": "eng", "confidence": 0.8}},
                }
            ],
        }
    )
    calls = []

    class RetryAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            calls.append(user)
            if len(calls) == 1:
                return bad
            return good

        def endpoint_label(self) -> str:
            return "mock-retry"

    results, _, _failed = run_pass2(
        {"test.md": "content"},
        SCHEMA,
        FLAT_SCHEMA,
        RetryAdapter(),
    )
    assert len(calls) == 2  # original + 1 retry
    assert len(results["test.md"]["nodes"]) > 0


def test_validate_rejects_unexpected_top_level_keys():
    """Response with unexpected keys like 'relations' must be rejected."""
    bad = {
        "relations": [{"type": "works_at", "from": "person-alice", "to": "org-acme"}],
        "nodes": VALID_EXTRACTION["nodes"],
        "edges": VALID_EXTRACTION["edges"],
    }
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("Unexpected top-level keys" in e for e in errors)
    assert any("relations" in e for e in errors)


def test_validate_rejects_missing_nodes_key():
    """Response missing 'nodes' key must be rejected."""
    bad = {"edges": VALID_EXTRACTION["edges"]}
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("Missing required top-level key" in e for e in errors)
    assert any("nodes" in e for e in errors)


def test_validate_rejects_missing_edges_key():
    """Response missing 'edges' key must be rejected."""
    bad = {"nodes": VALID_EXTRACTION["nodes"]}
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert any("Missing required top-level key" in e for e in errors)
    assert any("edges" in e for e in errors)


def test_validate_rejects_multiple_unexpected_keys():
    """Response with multiple unexpected keys lists all of them."""
    bad = {
        "nodes": VALID_EXTRACTION["nodes"],
        "edges": VALID_EXTRACTION["edges"],
        "relations": [],
        "metadata": {},
    }
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    assert len(errors) == 1  # Single structural error with all unexpected keys
    assert "Unexpected top-level keys" in errors[0]
    # Both unexpected keys should appear in sorted order
    assert "metadata" in errors[0]
    assert "relations" in errors[0]


def test_validate_returns_early_on_structural_errors():
    """Structural errors are returned immediately; per-record validation skipped."""
    bad = {
        "relations": [],
        "nodes": [{"id": "x", "type": "Ghost", "confidence": 0.5, "attributes": {}}],
        "edges": [],
    }
    errors = validate_extraction(bad, SCHEMA, FLAT_SCHEMA)
    # Should only have structural error, not the "Unknown node type: Ghost" error
    assert len(errors) == 1
    assert "Unexpected top-level keys" in errors[0]


def test_skip_files_excludes_already_done_files():
    """Files in skip_files must not be submitted to the executor."""

    class TrackingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps(VALID_EXTRACTION)

        def endpoint_label(self) -> str:
            return "mock-tracking"

    files = {"a.md": "content a", "b.md": "content b", "c.md": "content c"}
    results, chunk_index, _failed = run_pass2(
        files,
        SCHEMA,
        FLAT_SCHEMA,
        TrackingAdapter(),
        skip_files={"a.md", "c.md"},
    )
    assert set(results.keys()) == {"b.md"}
    assert set(chunk_index.keys()) == {"b.md"}


def test_on_file_done_called_once_per_file():
    """on_file_done callback must be invoked exactly once per completed file."""
    done_calls: list[str] = []

    def _callback(fname, result, file_idx):
        done_calls.append(fname)

    class FastAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps(VALID_EXTRACTION)

        def endpoint_label(self) -> str:
            return "mock-fast"

    files = {"a.md": "content a", "b.md": "content b"}
    run_pass2(files, SCHEMA, FLAT_SCHEMA, FastAdapter(), on_file_done=_callback)
    assert sorted(done_calls) == ["a.md", "b.md"]


def test_partial_restart_skips_done_files():
    """Combining skip_files + on_file_done simulates a partial restart: done files
    are skipped and callback fires only for remaining files."""
    done_calls: list[str] = []

    def _callback(fname, result, file_idx):
        done_calls.append(fname)

    class FastAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps(VALID_EXTRACTION)

        def endpoint_label(self) -> str:
            return "mock-fast"

    files = {"a.md": "content a", "b.md": "content b", "c.md": "content c"}
    results, _, _failed = run_pass2(
        files,
        SCHEMA,
        FLAT_SCHEMA,
        FastAdapter(),
        skip_files={"a.md"},
        on_file_done=_callback,
    )
    # Only b.md and c.md were processed
    assert set(results.keys()) == {"b.md", "c.md"}
    assert sorted(done_calls) == ["b.md", "c.md"]


def test_blank_response_writes_failed_chunks(tmp_path):
    """A chunk that returns blank twice writes an entry to failed_chunks.json."""

    class BlankAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return ""  # always blank

        def endpoint_label(self) -> str:
            return "mock-blank"

    manifest = {"input.md": "Alice works at Acme Corp.\n" * 40}
    result, _, failed = run_pass2(
        manifest,
        SCHEMA,
        FLAT_SCHEMA,
        BlankAdapter(),
        intermediate_dir=tmp_path,
    )
    failed_path = tmp_path / "failed_chunks.json"
    assert failed_path.exists()
    entries = json.loads(failed_path.read_text())
    assert len(entries) > 0
    assert all(e["filename"] == "input.md" for e in entries)
    assert all(e["reason"] == "blank_response" for e in entries)
    assert all(isinstance(e["chunk_idx"], int) for e in entries)


def test_successful_chunk_not_in_failed_chunks(tmp_path):
    """A chunk that succeeds leaves failed_chunks.json empty or absent."""
    adapter = MockAdapter(json.dumps(VALID_EXTRACTION))
    manifest = {"input.md": "Alice works at Acme Corp."}
    run_pass2(manifest, SCHEMA, FLAT_SCHEMA, adapter, intermediate_dir=tmp_path)
    failed_path = tmp_path / "failed_chunks.json"
    if failed_path.exists():
        assert json.loads(failed_path.read_text()) == []


# ---------------------------------------------------------------------------
# Null-guard tests — D: LLM returns null items or null arrays
# ---------------------------------------------------------------------------


def test_normalize_scalars_tolerates_null_items_in_nodes():
    """_normalize_scalars must not crash when nodes contains null items."""
    from mykg.pass2 import _normalize_scalars

    extraction = {
        "nodes": [
            None,
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 1.0,
                "attributes": {"name": "Alice"},
            },
        ],
        "edges": [],
    }
    result = _normalize_scalars(extraction)
    # The non-null node should still be processed
    real_nodes = [n for n in result["nodes"] if n is not None]
    assert len(real_nodes) == 1
    assert result["nodes"][1]["attributes"]["name"] == {
        "value": "Alice",
        "confidence": 0.5,  # CONFIDENCE_SCALAR_OMITTED
    }


def test_normalize_scalars_tolerates_null_nodes_array():
    """_normalize_scalars must not crash when nodes key maps to None."""
    from mykg.pass2 import _normalize_scalars

    extraction = {"nodes": None, "edges": None}
    result = _normalize_scalars(extraction)
    # Should return without error; nodes/edges stay as-is (None) since we don't mutate them
    assert result is extraction


def test_backfill_tolerates_null_items_in_nodes():
    """_backfill_extraction must not crash when nodes contains null items."""
    from mykg.pass2 import _backfill_extraction

    extraction = {
        "nodes": [
            None,
            {"id": "org-acme", "type": "Organization", "confidence": 0.9, "attributes": {}},
        ],
        "edges": [],
    }
    result = _backfill_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    # The non-null node should be backfilled
    real_nodes = [n for n in result["nodes"] if n is not None]
    assert real_nodes[0]["attributes"]["name"] == {"value": None, "confidence": 0.0}


def test_backfill_tolerates_null_nodes_and_edges():
    """_backfill_extraction must not crash when nodes or edges key maps to None."""
    from mykg.pass2 import _backfill_extraction

    extraction = {"nodes": None, "edges": None}
    result = _backfill_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    assert result is extraction


def test_validate_tolerates_null_items_in_nodes():
    """validate_extraction must not crash when nodes contains null items."""
    extraction = {
        "nodes": [None, VALID_EXTRACTION["nodes"][0]],
        "edges": [],
    }
    # Should not raise; null items are skipped
    errors = validate_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    assert isinstance(errors, list)


def test_validate_tolerates_null_nodes_array():
    """validate_extraction must not crash when nodes key maps to None."""
    extraction = {"nodes": None, "edges": []}
    errors = validate_extraction(extraction, SCHEMA, FLAT_SCHEMA)
    assert isinstance(errors, list)


def test_extract_chunk_filters_nulls_via_run_pass2():
    """When LLM returns null items in nodes array, run_pass2 result has no null nodes."""
    extraction_with_nulls = {
        "nodes": [None, VALID_EXTRACTION["nodes"][0], None, VALID_EXTRACTION["nodes"][1]],
        "edges": VALID_EXTRACTION["edges"],
    }
    adapter = MockAdapter(json.dumps(extraction_with_nulls))
    results, _, _failed = run_pass2(
        {"test.md": "Alice works at Acme."}, SCHEMA, FLAT_SCHEMA, adapter
    )
    assert "test.md" in results
    for node in results["test.md"]["nodes"]:
        assert node is not None


def test_extract_chunk_handles_null_nodes_array_via_run_pass2():
    """When LLM returns nodes: null, run_pass2 handles it without crashing."""
    extraction_null_nodes = {"nodes": None, "edges": []}
    adapter = MockAdapter(json.dumps(extraction_null_nodes))
    results, _, _failed = run_pass2({"test.md": "Some content."}, SCHEMA, FLAT_SCHEMA, adapter)
    assert "test.md" in results
    assert isinstance(results["test.md"]["nodes"], list)
