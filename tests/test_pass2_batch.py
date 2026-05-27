from __future__ import annotations

import json

from mykg.chunker import Chunk
from mykg.pass2_batch import build_pass2_batches, make_batch_map


def _chunk(source_file: str, idx: int, tokens: int) -> Chunk:
    """Create a Chunk with a given token size for testing."""
    return Chunk(
        source_file=source_file,
        chunk_index=idx,
        text=f"chunk {idx} of {source_file}",
        token_start=idx * tokens,
        token_end=idx * tokens + tokens,
    )


# ---------------------------------------------------------------------------
# build_pass2_batches — mixed mode (per_file=False)
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty():
    assert build_pass2_batches([], batch_token_target=1000) == []


def test_single_chunk_forms_one_batch():
    chunks = [_chunk("a.md", 0, 100)]
    batches = build_pass2_batches(chunks, batch_token_target=1000)
    assert len(batches) == 1
    assert batches[0] == chunks


def test_all_chunks_fit_in_one_batch():
    chunks = [_chunk("a.md", i, 100) for i in range(5)]
    batches = build_pass2_batches(chunks, batch_token_target=10000)
    assert len(batches) == 1
    assert len(batches[0]) == 5


def test_packing_respects_token_target_mixed():
    """Greedy bin-packing splits into correct number of batches."""
    # 3 chunks × 50 tokens each; target=100 → [chunk0+chunk1], [chunk2]
    chunks = [_chunk("a.md", i, 50) for i in range(3)]
    batches = build_pass2_batches(chunks, batch_token_target=100)
    assert len(batches) == 2
    sizes = sorted(len(b) for b in batches)
    assert sizes == [1, 2]


def test_mixed_mode_can_combine_different_files():
    """In mixed mode, chunks from different files may land in the same batch."""
    c1 = _chunk("a.md", 0, 50)
    c2 = _chunk("b.md", 0, 50)
    # Both fit in one batch (50+50 ≤ 100+1)
    batches = build_pass2_batches([c1, c2], batch_token_target=200)
    assert len(batches) == 1
    assert set(b.source_file for b in batches[0]) == {"a.md", "b.md"}


def test_mixed_mode_preserves_order():
    """Chunks appear in batches in the same order they were passed in."""
    chunks = [_chunk("a.md", i, 10) for i in range(4)]
    batches = build_pass2_batches(chunks, batch_token_target=1000)
    all_chunks = [c for b in batches for c in b]
    assert all_chunks == chunks


# ---------------------------------------------------------------------------
# build_pass2_batches — per_file mode (per_file=True)
# ---------------------------------------------------------------------------


def test_per_file_never_mixes_files():
    """With per_file=True, chunks from different files are always in separate batches."""
    chunks = [_chunk("a.md", 0, 10), _chunk("b.md", 0, 10)]
    batches = build_pass2_batches(chunks, batch_token_target=1000, per_file=True)
    for batch in batches:
        files_in_batch = {c.source_file for c in batch}
        assert len(files_in_batch) == 1, f"Mixed files in batch: {files_in_batch}"


def test_per_file_large_file_splits_across_batches():
    """In per_file mode a large file still splits into multiple batches on overflow."""
    chunks = [_chunk("big.md", i, 60) for i in range(4)]
    # target=100 → [chunk0+chunk1 would be 120 > 100, so each chunk is its own batch]
    batches = build_pass2_batches(chunks, batch_token_target=100, per_file=True)
    # 60+60=120 > 100 so each chunk is alone (greedy: chunk0 alone, chunk1 overflows, etc.)
    assert all(c.source_file == "big.md" for b in batches for c in b)
    assert len(batches) == 4


def test_per_file_same_file_chunks_pack_together():
    """Chunks from the same file that fit within the target are packed together."""
    chunks = [_chunk("a.md", i, 30) for i in range(3)]
    # 30+30+30=90 ≤ 100
    batches = build_pass2_batches(chunks, batch_token_target=100, per_file=True)
    assert len(batches) == 1
    assert len(batches[0]) == 3


def test_per_file_file_boundary_is_hard_split():
    """Even if a+b would fit the target, per_file forces a split at file boundaries."""
    c_a = _chunk("a.md", 0, 30)
    c_b = _chunk("b.md", 0, 30)
    batches = build_pass2_batches([c_a, c_b], batch_token_target=100, per_file=True)
    # Must be 2 batches, not 1 (even though 30+30=60 ≤ 100)
    assert len(batches) == 2


# ---------------------------------------------------------------------------
# make_batch_map
# ---------------------------------------------------------------------------


def test_make_batch_map_empty():
    assert make_batch_map([]) == {}


def test_make_batch_map_names_are_sequential():
    batches = [[_chunk("a.md", 0, 10)], [_chunk("b.md", 0, 10)]]
    bmap = make_batch_map(batches)
    assert list(bmap.keys()) == ["batch_0000", "batch_0001"]


def test_make_batch_map_files_field():
    """files contains sorted unique source_file values for the batch."""
    c1 = _chunk("a.md", 0, 10)
    c2 = _chunk("b.md", 0, 10)
    c3 = _chunk("a.md", 1, 10)
    bmap = make_batch_map([[c1, c2, c3]])
    assert bmap["batch_0000"]["files"] == ["a.md", "b.md"]


def test_make_batch_map_chunks_field():
    """chunks contains one entry per Chunk with file and 1-based chunk_idx."""
    c = _chunk("notes.md", 2, 50)
    bmap = make_batch_map([[c]])
    assert bmap["batch_0000"]["chunks"] == [{"file": "notes.md", "chunk_idx": 3}]


def test_make_batch_map_total_tokens():
    """total_tokens equals the sum of (token_end - token_start) for all chunks."""
    c1 = _chunk("a.md", 0, 40)
    c2 = _chunk("a.md", 1, 60)
    bmap = make_batch_map([[c1, c2]])
    assert bmap["batch_0000"]["total_tokens"] == 100


def test_make_batch_map_multiple_batches():
    batches = [
        [_chunk("x.md", 0, 20), _chunk("x.md", 1, 30)],
        [_chunk("y.md", 0, 50)],
    ]
    bmap = make_batch_map(batches)
    assert bmap["batch_0000"]["total_tokens"] == 50
    assert bmap["batch_0001"]["total_tokens"] == 50
    assert bmap["batch_0000"]["files"] == ["x.md"]
    assert bmap["batch_0001"]["files"] == ["y.md"]


# ---------------------------------------------------------------------------
# run_pass2_batched — progress file tests
# ---------------------------------------------------------------------------

MINIMAL_SCHEMA = {
    "concepts": [{"type": "Person", "attributes": ["name"], "parent": None}],
    "properties": [],
}
MINIMAL_FLAT = {"Person": ["name"]}

VALID_EXTRACTION = json.dumps({
    "nodes": [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
        }
    ],
    "edges": [],
})


class _MockAdapter:
    """Minimal adapter that always returns VALID_EXTRACTION."""

    def complete(self, system: str, user: str, **kwargs) -> str:  # noqa: ARG002
        return VALID_EXTRACTION


class _FailAdapter:
    """Adapter that raises on every call."""

    def complete(self, system: str, user: str, **kwargs) -> str:  # noqa: ARG002
        raise RuntimeError("LLM error")


def _run_batched(files, adapter, tmp_path=None):
    """Helper that calls run_pass2_batched with standard args."""
    from mykg.pass2 import run_pass2_batched

    return run_pass2_batched(
        files,
        MINIMAL_SCHEMA,
        MINIMAL_FLAT,
        adapter,
        batch_token_target=100000,
        max_workers=1,
        intermediate_dir=tmp_path,
    )


def test_progress_file_created_when_intermediate_dir_provided(tmp_path):
    """pass2_progress.json is created before LLM calls start."""
    call_count = [0]
    progress_at_first_call = [None]

    class _TrackingAdapter:
        def complete(self, system, user, **kwargs):  # noqa: ARG002
            call_count[0] += 1
            if call_count[0] == 1:
                p = tmp_path / "pass2_progress.json"
                if p.exists():
                    progress_at_first_call[0] = json.loads(p.read_text())
            return VALID_EXTRACTION

    files = {"a.md": "Alice is a person."}
    _run_batched(files, _TrackingAdapter(), tmp_path)

    assert (tmp_path / "pass2_progress.json").exists(), "progress file must exist after run"
    # It should have been present before (or at) the first LLM call.
    assert progress_at_first_call[0] is not None, "progress file not found during first LLM call"


def test_progress_file_structure(tmp_path):
    """pass2_progress.json has required top-level keys."""
    files = {"a.md": "Alice is a person.", "b.md": "Bob is a person."}
    _run_batched(files, _MockAdapter(), tmp_path)

    data = json.loads((tmp_path / "pass2_progress.json").read_text())
    assert "total_batches" in data
    assert "completed" in data
    assert "failed" in data
    assert "batches" in data


def test_progress_file_all_done_after_success(tmp_path):
    """After all batches complete successfully, all entries show status='done'."""
    files = {"a.md": "Alice is a person.", "b.md": "Bob is a person."}
    _run_batched(files, _MockAdapter(), tmp_path)

    data = json.loads((tmp_path / "pass2_progress.json").read_text())
    statuses = [b["status"] for b in data["batches"].values()]
    assert all(s == "done" for s in statuses), f"Expected all done, got: {statuses}"
    assert data["completed"] == data["total_batches"]
    assert data["failed"] == 0


def test_progress_file_failed_batch_marked(tmp_path):
    """When a batch raises an exception, its entry shows status='failed' with error field."""
    files = {"a.md": "Alice is a person."}
    # _FailAdapter raises; run_pass2_batched catches it and marks failed.
    _run_batched(files, _FailAdapter(), tmp_path)

    data = json.loads((tmp_path / "pass2_progress.json").read_text())
    failed_batches = [b for b in data["batches"].values() if b["status"] == "failed"]
    assert len(failed_batches) > 0, "Expected at least one failed batch"
    # Each failed batch must have an error field.
    for fb in failed_batches:
        assert "error" in fb, "failed batch must carry 'error' field"
    assert data["failed"] > 0


def test_no_progress_file_when_no_intermediate_dir():
    """When intermediate_dir=None, no progress file is created and no crash occurs."""
    files = {"a.md": "Alice is a person."}
    # Should not raise, should not write any file.
    raw, chunk_idx, failed, batch_map = _run_batched(files, _MockAdapter(), tmp_path=None)
    assert isinstance(raw, dict)
    assert isinstance(batch_map, dict)


def test_progress_file_nodes_edges_counts(tmp_path):
    """done batches record node/edge counts from the extraction."""
    files = {"a.md": "Alice is a person."}
    _run_batched(files, _MockAdapter(), tmp_path)

    data = json.loads((tmp_path / "pass2_progress.json").read_text())
    done_batches = [b for b in data["batches"].values() if b["status"] == "done"]
    assert len(done_batches) > 0
    for b in done_batches:
        assert "nodes" in b
        assert "edges" in b
        assert isinstance(b["nodes"], int)
        assert isinstance(b["edges"], int)
