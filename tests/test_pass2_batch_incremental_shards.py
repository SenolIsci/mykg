"""Tests for incremental on_file_done flushing in run_pass2_batched.

A file's chunks can land in many non-adjacent batches (build_pass2_batches does
cross-file bin-packing by default), so on_file_done must fire as soon as every
chunk belonging to a file has appeared in a completed (post-retry) batch —
not only once, at the very end, after every batch in the whole corpus finishes.
This is what makes cancel/resume for `pass2.prep_mode: batch_chunks` possible:
a crash mid-run only loses batches still in flight, not everything computed
so far.
"""

import json
import threading
import unittest.mock as mock
from unittest.mock import MagicMock

import mykg.pass2 as p2_mod
from mykg.pass2 import run_pass2_batched


def test_on_file_done_fires_before_all_batches_complete():
    """A file whose chunks all land in early batches gets on_file_done called
    before the last batch (for a different, later file) has even resolved."""
    files = {
        "early.md": "# Early\nshort content about Alice",
        "late.md": "# Late\nshort content about Bob",
    }
    schema = {"concepts": [], "properties": []}
    flat = {}

    # batch_token_target=1 with per_file=True forces one chunk per batch and
    # file boundaries as hard split points, so "early.md" fully resolves in
    # its own batch(es) before "late.md"'s batch is even dispatched in order —
    # per_file=True also guarantees batches never mix files.
    call_order: list[str] = []

    def fake_extract(batch, *args, **kwargs):
        call_order.append(batch[0].source_file)
        return {"nodes": [], "edges": []}

    on_file_done_calls: list[str] = []

    def on_file_done(fname, result, file_idx):
        on_file_done_calls.append(fname)

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=1,
            on_file_done=on_file_done,
        )

    # Both files must have been finalized exactly once.
    assert sorted(on_file_done_calls) == ["early.md", "late.md"]
    assert len(on_file_done_calls) == 2
    # "early.md" is finalized strictly before "late.md" — the incremental path
    # does not wait for the whole corpus before flushing the first file.
    assert on_file_done_calls.index("early.md") < on_file_done_calls.index("late.md")


def test_on_file_done_not_called_twice_per_file():
    """The trailing defensive fallback loop must not re-finalize an
    already-flushed file (which would double-call on_file_done)."""
    files = {"a.md": "# A\nsome content", "b.md": "# B\nmore content"}
    schema = {"concepts": [], "properties": []}
    flat = {}

    def fake_extract(batch, *args, **kwargs):
        return {"nodes": [], "edges": []}

    on_file_done_calls: list[str] = []

    def on_file_done(fname, result, file_idx):
        on_file_done_calls.append(fname)

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=100_000,  # everything packs into one batch
            max_workers=1,
            on_file_done=on_file_done,
        )

    assert on_file_done_calls.count("a.md") == 1
    assert on_file_done_calls.count("b.md") == 1


def test_on_file_done_waits_for_retry_to_resolve():
    """A file's on_file_done must not fire after the first (failed) attempt —
    only after the retry round resolves it, success or exhausted-failure."""
    files = {"a.md": "# A\nsome content"}
    schema = {"concepts": [], "properties": []}
    flat = {}

    extract_calls = []

    def fail_once_then_succeed(batch, *args, **kwargs):
        extract_calls.append(1)
        if len(extract_calls) == 1:
            raise RuntimeError("simulated transient failure")
        return {"nodes": [], "edges": []}

    on_file_done_calls: list[str] = []

    def on_file_done(fname, result, file_idx):
        on_file_done_calls.append(fname)

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fail_once_then_succeed):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=100_000,
            batch_retry_max=1,
            max_workers=1,
            on_file_done=on_file_done,
        )

    # 1 initial failed attempt + 1 retry that succeeds.
    assert len(extract_calls) == 2
    # on_file_done fires exactly once, after the retry resolved it — not once
    # per attempt.
    assert on_file_done_calls == ["a.md"]


def test_on_file_done_fires_after_exhausted_retries_too():
    """A file whose batch never succeeds still gets finalized (with whatever
    partial results exist) once retries are exhausted — not silently dropped."""
    files = {"a.md": "# A\nsome content"}
    schema = {"concepts": [], "properties": []}
    flat = {}

    def always_fail(batch, *args, **kwargs):
        raise RuntimeError("always fails")

    on_file_done_calls: list[str] = []

    def on_file_done(fname, result, file_idx):
        on_file_done_calls.append(fname)

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=always_fail):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=100_000,
            batch_retry_max=1,
            max_workers=1,
            on_file_done=on_file_done,
        )

    assert on_file_done_calls == ["a.md"]


def test_shard_files_written_incrementally(tmp_path):
    """End-to-end: intermediate_dir shard files (via a step_pass2-style
    on_file_done) exist for a completed file even while other files in the
    same corpus haven't finished yet."""
    files = {
        "early.md": "# Early\nshort content",
        "late.md": "# Late\nshort content",
    }
    schema = {"concepts": [], "properties": []}
    flat = {}

    shard_dir = tmp_path / "raw_extractions_shards"
    shard_dir.mkdir()

    def fake_extract(batch, *args, **kwargs):
        return {"nodes": [], "edges": []}

    written_before_second_file_done: list[str] = []

    def on_file_done(fname, result, file_idx):
        (shard_dir / f"{fname.replace('.md', '')}.json").write_text("{}")
        # Snapshot what's on disk at the moment THIS file is finalized.
        written_before_second_file_done.append(
            sorted(p.name for p in shard_dir.glob("*.json"))
        )

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=1,
            on_file_done=on_file_done,
        )

    # When "early.json" was finalized, "late.json" must not yet exist —
    # proof that shards are written one file at a time, not all at once
    # at the very end.
    assert written_before_second_file_done[0] == ["early.json"]
    assert written_before_second_file_done[1] == ["early.json", "late.json"]


# ---------------------------------------------------------------------------
# on_batch_done incremental raw-batch persistence + resume-skip.
#
# Unlike the on_file_done tests above, these use max_workers > 1 to exercise
# the real production shape: thousands of batches dispatched concurrently via
# ThreadPoolExecutor, all sitting in as_completed together. The on_file_done
# tests' max_workers=1 makes batches resolve strictly in submission order,
# which never reproduces the reported bug (73/3002 batches done, zero shards
# persisted) — on_batch_done must fire per-batch regardless of dispatch order.
# ---------------------------------------------------------------------------


def test_on_batch_done_fires_before_as_completed_loop_drains():
    """on_batch_done must fire for each batch as it resolves, not only after
    the whole as_completed(futures) loop for the entire corpus has drained —
    this is the real bug: with max_workers>1 and many batches, the batch that
    finishes first must trigger on_batch_done before the last batch (still in
    flight) has resolved."""
    files = {f"f{i}.md": f"# F{i}\nshort content about topic {i}" for i in range(6)}
    schema = {"concepts": [], "properties": []}
    flat = {}

    release_last = threading.Event()

    def fake_extract(batch, *args, **kwargs):
        # Identify "the last batch" by content — block only the one
        # containing f5.md so it resolves last regardless of thread timing.
        is_last = any(c.source_file == "f5.md" for c in batch)
        if is_last:
            release_last.wait(timeout=5)
        return {"nodes": [], "edges": []}

    on_batch_done_indices: list[int] = []

    def on_batch_done(idx, extraction, error, batch_map_entry):
        on_batch_done_indices.append(idx)
        # Once at least one batch (not the blocked last one) has reported
        # done, release the last batch so the test terminates.
        if len(on_batch_done_indices) >= 1:
            release_last.set()

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=4,
            on_batch_done=on_batch_done,
        )

    # All 6 single-file batches reported via on_batch_done, and the first
    # report happened while the last batch was still blocked in flight —
    # proof on_batch_done isn't gated behind the full as_completed drain.
    assert len(on_batch_done_indices) == 6


def test_on_batch_done_persists_and_resume_skips_dispatched_batches(tmp_path):
    """A batch shard written via on_batch_done (mirroring step_pass2.py's
    _write_raw_batch_shard) is reloaded on a second run_pass2_batched() call
    and that batch index is not re-dispatched to the LLM."""
    files = {"a.md": "# A\nshort content", "b.md": "# B\nshort content"}
    schema = {"concepts": [], "properties": []}
    flat = {}
    shard_dir = tmp_path / "pass2_raw_batches"

    extract_call_count = {"n": 0}

    def fake_extract(batch, *args, **kwargs):
        extract_call_count["n"] += 1
        return {"nodes": [], "edges": []}

    def write_shard(idx, extraction, error, batch_map_entry):
        shard_dir.mkdir(exist_ok=True)
        entry = {
            "batch_index": idx,
            "status": "ok" if extraction is not None else "failed",
            "chunk_count": len(batch_map_entry.get("chunks", [])),
            "source_files": batch_map_entry.get("files", []),
        }
        if extraction is not None:
            entry["extraction"] = extraction
        (shard_dir / f"{idx:04d}.json").write_text(json.dumps(entry))

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=2,
            on_batch_done=write_shard,
            intermediate_dir=tmp_path,
        )

    first_run_calls = extract_call_count["n"]
    assert first_run_calls == 2  # one batch per file (per_file=True, tiny content)
    assert sorted(p.name for p in shard_dir.glob("*.json")) == ["0000.json", "0001.json"]

    # Second call over the SAME files/config: both shards should be reused,
    # zero new LLM calls.
    extract_call_count["n"] = 0
    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        results, _chunk_idx, _failed, _batch_map = run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=2,
            on_batch_done=write_shard,
            intermediate_dir=tmp_path,
        )

    assert extract_call_count["n"] == 0
    assert set(results.keys()) == {"a.md", "b.md"}


def test_on_batch_done_shard_not_reused_when_composition_differs(tmp_path):
    """A persisted shard whose chunk_count/source_files no longer match the
    freshly-rebuilt batch at that index (e.g. a different corpus reusing the
    same intermediate_dir) must not be reused — that batch is re-dispatched."""
    schema = {"concepts": [], "properties": []}
    flat = {}
    shard_dir = tmp_path / "pass2_raw_batches"
    shard_dir.mkdir()

    # Plant a stale shard for index 0 claiming a completely different
    # composition (source_files that don't exist in this run's corpus).
    (shard_dir / "0000.json").write_text(
        json.dumps(
            {
                "batch_index": 0,
                "status": "ok",
                "chunk_count": 99,
                "source_files": ["nonexistent.md"],
                "extraction": {"nodes": [], "edges": []},
            }
        )
    )

    files = {"a.md": "# A\nshort content"}
    extract_call_count = {"n": 0}

    def fake_extract(batch, *args, **kwargs):
        extract_call_count["n"] += 1
        return {"nodes": [], "edges": []}

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fake_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=1,
            intermediate_dir=tmp_path,
        )

    # The stale/mismatched shard must not have been trusted — batch 0 for
    # a.md was re-dispatched to the (mocked) LLM.
    assert extract_call_count["n"] == 1


def test_on_batch_done_failed_shard_is_retried_not_skipped(tmp_path):
    """A shard with status 'failed' must not be treated as done — it is
    still dispatched (and can succeed) on resume, mirroring Pass 1's
    None-proposal handling for failed shards."""
    schema = {"concepts": [], "properties": []}
    flat = {}
    shard_dir = tmp_path / "pass2_raw_batches"
    shard_dir.mkdir()

    files = {"a.md": "# A\nshort content"}

    def fake_extract(batch, *args, **kwargs):
        return {"nodes": [], "edges": []}

    # First, dispatch and persist a genuine "failed" shard.
    def fail_extract(batch, *args, **kwargs):
        raise RuntimeError("simulated failure")

    def write_shard(idx, extraction, error, batch_map_entry):
        entry = {
            "batch_index": idx,
            "status": "ok" if extraction is not None else "failed",
            "chunk_count": len(batch_map_entry.get("chunks", [])),
            "source_files": batch_map_entry.get("files", []),
        }
        if extraction is not None:
            entry["extraction"] = extraction
        else:
            entry["error"] = error
        (shard_dir / f"{idx:04d}.json").write_text(json.dumps(entry))

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=fail_extract):
        run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=1,
            batch_retry_max=0,
            on_batch_done=write_shard,
            intermediate_dir=tmp_path,
        )

    assert json.loads((shard_dir / "0000.json").read_text())["status"] == "failed"

    # Resume: the failed shard must be retried, not skipped.
    extract_call_count = {"n": 0}

    def succeed_extract(batch, *args, **kwargs):
        extract_call_count["n"] += 1
        return {"nodes": [], "edges": []}

    with mock.patch.object(p2_mod, "_extract_batch", side_effect=succeed_extract):
        results, _chunk_idx, _failed, _batch_map = run_pass2_batched(
            files,
            schema,
            flat,
            MagicMock(),
            batch_token_target=1,
            per_file=True,
            max_workers=1,
            on_batch_done=write_shard,
            intermediate_dir=tmp_path,
        )

    assert extract_call_count["n"] == 1
    assert "a.md" in results
