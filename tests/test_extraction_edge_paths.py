from __future__ import annotations

import json
from unittest.mock import MagicMock

from mykg.chunker import Chunk
from mykg.llm.adapter import LLMAdapter
from mykg.pass1 import run_pass1
from mykg.pass2 import _partial_recover, run_pass2

SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
    ],
}

FLAT_SCHEMA = {"Person": ["name"], "Organization": ["name"]}

VALID_SCHEMA_RESPONSE = json.dumps(
    {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [{"name": "knows", "domain": "Person", "range": "Person", "attributes": []}],
    }
)


def _make_adapter(responses: list[str]) -> LLMAdapter:
    adapter = MagicMock(spec=LLMAdapter)
    adapter.complete.side_effect = responses
    return adapter


def _make_chunk(text: str = "Alice works at Acme.", source_file: str = "doc.md") -> Chunk:
    return Chunk(source_file=source_file, chunk_index=0, text=text, token_start=0, token_end=10)


def test_pass1_json_retry_on_bad_json():
    adapter = _make_adapter(["not json at all", VALID_SCHEMA_RESPONSE])
    result = run_pass1([_make_chunk()], adapter, locked_schema_block="")
    assert len(result) == 1
    assert "concepts" in result[0]
    assert "properties" in result[0]


def test_pass1_batch_skipped_on_persistent_bad_json():
    adapter = _make_adapter(["not json", "still not json"])
    result = run_pass1([_make_chunk()], adapter, locked_schema_block="")
    assert result == []


def test_pass1_missing_properties_key_skipped():
    adapter = _make_adapter(['{"concepts": []}'])
    result = run_pass1([_make_chunk()], adapter, locked_schema_block="")
    assert result == []


def test_partial_recover_drops_dangling_edge():
    extraction = {
        "nodes": [
            {"id": "person-alice", "type": "Person", "confidence": 0.9, "attributes": {}},
        ],
        "edges": [
            {
                "type": "works_at",
                "from": "person-alice",
                "to": "org-ghost",
                "confidence": 0.8,
                "attributes": {},
            }
        ],
    }
    result = _partial_recover(extraction, SCHEMA, prior_nodes=None)
    assert result["edges"] == []


def test_partial_recover_drops_hallucinated_anchor():
    extraction = {
        "nodes": [
            {"id": "person-ghost", "type": "Person", "confidence": 0.9, "attributes": {}},
        ],
        "edges": [
            {
                "type": "works_at",
                "from": "person-ghost",
                "to": "org-unknown",
                "confidence": 0.8,
                "attributes": {},
            }
        ],
    }
    result = _partial_recover(extraction, SCHEMA, prior_nodes=None)
    node_ids = [n["id"] for n in result["nodes"]]
    assert "person-ghost" not in node_ids
    assert result["edges"] == []


def test_partial_recover_prior_node_not_in_output_nodes():
    prior_node = {"id": "person-alice", "type": "Person", "confidence": 0.9, "attributes": {}}
    result = _partial_recover({"nodes": [], "edges": []}, SCHEMA, prior_nodes=[prior_node])
    node_ids = [n["id"] for n in result["nodes"]]
    assert "person-alice" not in node_ids


def test_pass2_failed_chunk_recorded(tmp_path):
    class BlankAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return ""

        def endpoint_label(self) -> str:
            return "mock-blank"

    manifest = {"doc.md": "Alice works at Acme Corp.\n" * 40}
    _result, _chunk_index, failed = run_pass2(
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
    assert any(e["filename"] == "doc.md" for e in entries)


# ---------------------------------------------------------------------------
# Extended Unit 5 — pass2 edge paths
# ---------------------------------------------------------------------------


def test_normalize_scalars_non_dict_node_attrs_replaced():
    from mykg.pass2 import _normalize_scalars

    extraction = {
        "nodes": [
            {"id": "p-1", "type": "Person", "attributes": "not-a-dict"},
            {"id": "p-2", "type": "Person", "attributes": {"name": "Alice"}},
            None,  # null item handled gracefully
        ],
        "edges": [
            {"id": "e-1", "type": "x", "attributes": "string-not-dict"},
            None,
        ],
    }
    out = _normalize_scalars(extraction)
    assert out["nodes"][0]["attributes"] == {}
    # bare scalar coerced into wrapper
    assert out["nodes"][1]["attributes"]["name"]["value"] == "Alice"
    assert out["nodes"][1]["attributes"]["name"]["confidence"] > 0
    assert out["edges"][0]["attributes"] == {}


def test_backfill_extraction_handles_missing_attrs():
    """_backfill_extraction adds null+0.0 for missing required attributes."""
    from mykg.pass2 import _backfill_extraction

    schema = {
        "concepts": [{"type": "Person", "attributes": ["name", "email"]}],
        "properties": [
            {"name": "knows", "domain": "Person", "range": "Person", "attributes": ["since"]},
        ],
    }
    flat = {"Person": ["name", "email"]}
    extraction = {
        "nodes": [
            {"id": "p-1", "type": "Person", "attributes": {}},
            None,
        ],
        "edges": [
            {"type": "knows", "from": "p-1", "to": "p-1", "attributes": {}},
            None,
        ],
    }
    out = _backfill_extraction(extraction, schema, flat)
    p1_attrs = out["nodes"][0]["attributes"]
    assert p1_attrs["name"]["value"] is None
    assert p1_attrs["email"]["confidence"] == 0.0
    assert out["edges"][0]["attributes"]["since"]["value"] is None


def test_build_schema_hint_block_with_matching_chunk():
    """_build_schema_hint_block produces a non-empty hint when chunk_key matches."""
    from mykg.pass2 import _build_schema_hint_block

    hints = [
        {
            "orphan_id": "person-x",
            "orphan_name": "Mr. X",
            "orphan_type": "Person",
            "new_properties": ["works_at"],
            "shared_chunks": ["doc.md::1", "doc.md::3"],
        }
    ]
    block = _build_schema_hint_block("doc.md::1", hints)
    assert "SCHEMA ADDITION HINT" in block
    assert "person-x" in block
    assert "works_at" in block


def test_build_schema_hint_block_no_match():
    from mykg.pass2 import _build_schema_hint_block

    hints = [
        {
            "orphan_id": "x",
            "orphan_name": "X",
            "orphan_type": "Person",
            "new_properties": [],
            "shared_chunks": ["doc.md::5"],
        }
    ]
    assert _build_schema_hint_block("doc.md::99", hints) == ""


def test_fmt_elapsed():
    from mykg.pass2 import _fmt_elapsed

    assert "h" in _fmt_elapsed(3661)
    assert "m" in _fmt_elapsed(120)


def test_validate_extraction_returns_early_on_structural_errors():
    """Missing top-level keys / empty extraction should produce errors."""
    from mykg.pass2 import validate_extraction

    schema = {
        "concepts": [{"type": "Person", "attributes": ["name"]}],
        "properties": [],
    }
    flat = {"Person": ["name"]}
    errors = validate_extraction({}, schema, flat)
    assert any("Missing required top-level key" in e for e in errors)


def test_dedup_within_file_keeps_higher_confidence():
    from mykg.pass2 import _dedup_within_file

    a = {
        "id": "person-1",
        "type": "Person",
        "attributes": {
            "name": {"value": "Alice", "confidence": 0.7},
            "email": {"value": "a@x", "confidence": 0.9},
        },
    }
    b = {
        "id": "person-2",
        "type": "Person",
        "attributes": {
            "name": {"value": "Alice", "confidence": 0.9},
        },
    }
    out = _dedup_within_file([a, b])
    assert len(out) == 1
    # Higher-confidence name wins
    assert out[0]["attributes"]["name"]["confidence"] == 0.9
    # email comes from a
    assert out[0]["attributes"]["email"]["value"] == "a@x"


def test_run_pass2_stateful_chunks_carries_prior_nodes(monkeypatch):
    """When stateful_chunks=True, prior nodes are passed to subsequent chunks."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_STATEFUL_CHUNKS", True)

    calls = []

    class Adapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            calls.append(user)
            return json.dumps(
                {
                    "nodes": [
                        {
                            "id": "person-alice",
                            "type": "Person",
                            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                        }
                    ],
                    "edges": [],
                }
            )

        def endpoint_label(self) -> str:
            return "mock"

    files = {"doc.md": "Alice. " * 1500}  # multiple chunks
    result, _idx, _failed = run_pass2(files, SCHEMA, FLAT_SCHEMA, Adapter(), max_workers=1)
    assert "doc.md" in result
    # Second call should include "NODES ALREADY EXTRACTED" block
    if len(calls) > 1:
        assert any("NODES ALREADY EXTRACTED" in c for c in calls[1:])


def test_run_pass2_skip_files():
    """skip_files removes those entries from processing."""

    class Adapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps({"nodes": [], "edges": []})

        def endpoint_label(self) -> str:
            return "mock"

    files = {"doc1.md": "content", "doc2.md": "content"}
    result, _idx, _failed = run_pass2(
        files, SCHEMA, FLAT_SCHEMA, Adapter(), skip_files={"doc2.md"}, max_workers=1
    )
    assert "doc1.md" in result
    assert "doc2.md" not in result


def test_run_pass2_on_file_done_callback():
    """on_file_done callback receives per-file results."""

    class Adapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps({"nodes": [], "edges": []})

        def endpoint_label(self) -> str:
            return "mock"

    seen = []

    def on_done(fname, result, idx):
        seen.append((fname, result, idx))

    run_pass2(
        {"doc.md": "content"},
        SCHEMA,
        FLAT_SCHEMA,
        Adapter(),
        on_file_done=on_done,
        max_workers=1,
    )
    assert seen
    assert seen[0][0] == "doc.md"


def test_run_pass2_surgical_reextract_chunks(monkeypatch):
    """reextract_chunks confines processing to specific 1-based chunk indices."""

    class Adapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return json.dumps(
                {
                    "nodes": [
                        {
                            "id": "p-new",
                            "type": "Person",
                            "attributes": {"name": {"value": "NewPerson", "confidence": 1.0}},
                        }
                    ],
                    "edges": [],
                }
            )

        def endpoint_label(self) -> str:
            return "mock-surgical"

    files = {"doc.md": "Alice. " * 1500}  # multiple chunks
    prior_data = {
        "doc.md": {
            "nodes": [
                {
                    "id": "p-prior",
                    "type": "Person",
                    "attributes": {"name": {"value": "Prior", "confidence": 0.9}},
                }
            ],
            "edges": [],
        }
    }
    prior_idx = {"doc.md": {"1": ["person-prior"]}}

    result, _idx, _failed = run_pass2(
        files,
        SCHEMA,
        FLAT_SCHEMA,
        Adapter(),
        reextract_chunks={"doc.md": {2}},
        prior_extractions=prior_data,
        prior_chunk_index=prior_idx,
        max_workers=1,
    )
    # The surgical pass should preserve prior node + add new one
    node_ids = {n["id"] for n in result["doc.md"]["nodes"]}
    assert "p-prior" in node_ids


def test_partial_recover_with_unknown_node_type():
    """Nodes with type not in schema concepts are dropped."""
    from mykg.pass2 import _partial_recover

    extraction = {
        "nodes": [
            {"id": "alien-1", "type": "Alien", "attributes": {}},
            {"id": "p-1", "type": "Person", "attributes": {}},
        ],
        "edges": [],
    }
    result = _partial_recover(extraction, SCHEMA, prior_nodes=None)
    node_ids = {n["id"] for n in result["nodes"]}
    assert "alien-1" not in node_ids


def test_extract_chunk_returns_none_on_blank_retry():
    """_extract_chunk returns None when both initial and retry responses are blank."""
    from mykg.pass2 import _extract_chunk

    class BlankAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            return ""

        def endpoint_label(self) -> str:
            return "mock-blank"

    result = _extract_chunk("text", SCHEMA, FLAT_SCHEMA, BlankAdapter(), chunk_idx=1)
    assert result is None
