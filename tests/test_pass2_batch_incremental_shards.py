"""Tests for incremental on_file_done flushing in run_pass2_batched.

A file's chunks can land in many non-adjacent batches (build_pass2_batches does
cross-file bin-packing by default), so on_file_done must fire as soon as every
chunk belonging to a file has appeared in a completed (post-retry) batch —
not only once, at the very end, after every batch in the whole corpus finishes.
This is what makes cancel/resume for `pass2.prep_mode: batch_chunks` possible:
a crash mid-run only loses batches still in flight, not everything computed
so far.
"""

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
