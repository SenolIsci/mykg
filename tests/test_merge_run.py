"""Unit tests for mykg/merge_run.py.

Focuses on the SchemaUpdatedError restart loop (lines 135–212) and other
exception paths that are not exercised by the integration tests in
test_merge_pipeline.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import mykg.config as cfg_mod
from mykg.merge_context import MergeContext
from mykg.merge_pipeline import MERGE_STEPS
from mykg.merge_run import _MERGE_SCHEMA_RESTART_INVALIDATE, _log_merge_advisory, run_merge
from mykg.orchestrator import PipelineHaltError, SchemaUpdatedError, Step


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path: Path, review: bool = False) -> MergeContext:
    intermediate = tmp_path / "intermediate"
    output = tmp_path / "output"
    intermediate.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    return MergeContext(
        session_a_name="sess-a",
        session_b_name="sess-b",
        sessions_root=tmp_path / "sessions",
        input_dir=tmp_path / "input",
        output_dir=output,
        intermediate_dir=intermediate,
        adapter=None,
        review=review,
    )


def _make_gap_orphan(
    orphan_id: str = "node-orphan-1",
    orphan_type: str = "Person",
    orphan_name: str = "Alice",
    shared_chunks: list[str] | None = None,
) -> MagicMock:
    """Return a mock SchemaGapOrphan-like object."""
    orphan = MagicMock()
    orphan.orphan_id = orphan_id
    orphan.orphan_type = orphan_type
    orphan.orphan_name = orphan_name
    orphan.shared_chunks = shared_chunks or ["file.md::0"]
    return orphan


def _schema_updated_error(
    new_property_names: list[str] | None = None,
    gap_orphans: list | None = None,
) -> SchemaUpdatedError:
    return SchemaUpdatedError(
        new_property_names=new_property_names or ["new_prop"],
        gap_orphans=gap_orphans or [],
    )


# ---------------------------------------------------------------------------
# Test: SchemaUpdatedError restart loop — outputs invalidated
# ---------------------------------------------------------------------------

def test_run_merge_schema_restart_invalidates_outputs(tmp_path):
    """SchemaUpdatedError on orphan_connect causes outputs in
    _MERGE_SCHEMA_RESTART_INVALIDATE to be deleted."""
    ctx = _make_ctx(tmp_path)

    # Pre-create stale output files that should be deleted on restart
    stale_files = []
    for step in MERGE_STEPS:
        if step.name in _MERGE_SCHEMA_RESTART_INVALIDATE:
            for output in step.outputs:
                p = ctx.intermediate_dir / output
                p.write_text("stale")
                stale_files.append(p)

    # First call raises SchemaUpdatedError; subsequent calls succeed (no error)
    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        run_merge(ctx)

    for p in stale_files:
        assert not p.exists(), f"Stale file was not deleted: {p}"


def test_run_merge_schema_restart_regenerates_schema_ttl(tmp_path):
    """After SchemaUpdatedError, schema.ttl is regenerated from schema.json."""
    ctx = _make_ctx(tmp_path)

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [{"name": "new_prop", "domain": "Person", "range": "Person", "attributes": []}],
    }
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(schema))
    ttl_path = ctx.intermediate_dir / "schema.ttl"

    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error(["new_prop"])
        return None

    fake_ttl = "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
        patch("mykg.exporter.export_ttl", return_value=fake_ttl) as mock_export,
    ):
        run_merge(ctx)

    assert mock_export.called
    assert ttl_path.exists()
    assert ttl_path.read_text() == fake_ttl


def test_run_merge_schema_restart_removes_approval_flag(tmp_path):
    """schema_approved.flag is deleted when SchemaUpdatedError fires."""
    ctx = _make_ctx(tmp_path)
    flag = ctx.intermediate_dir / "schema_approved.flag"
    flag.write_text("approved")

    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        run_merge(ctx)

    assert not flag.exists(), "schema_approved.flag should have been deleted on restart"


def test_run_merge_schema_restart_clears_runtime_fields(tmp_path):
    """ctx.nodes, ctx.edge_metadata, ctx.chunk_node_index are reset to None on restart."""
    ctx = _make_ctx(tmp_path)
    ctx.nodes = [{"id": "n1"}]
    ctx.edge_metadata = {"e1": {}}
    ctx.chunk_node_index = {"file.md": {}}

    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        return None

    captured = {}

    def is_done_side_effect(step, ctx_arg):
        # After the first restart, capture runtime fields on the second pass
        if call_count[0] > 1 and "nodes" not in captured:
            captured["nodes"] = ctx_arg.nodes
            captured["edge_metadata"] = ctx_arg.edge_metadata
            captured["chunk_node_index"] = ctx_arg.chunk_node_index
        return False

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", side_effect=is_done_side_effect),
    ):
        run_merge(ctx)

    assert captured.get("nodes") is None
    assert captured.get("edge_metadata") is None
    assert captured.get("chunk_node_index") is None


def test_run_merge_schema_restart_resets_step_states_to_pending(tmp_path):
    """After SchemaUpdatedError, invalidated steps are reset to pending in pipeline_state.json."""
    ctx = _make_ctx(tmp_path)

    # Capture the pipeline_state.json snapshot written immediately after the restart
    # (before the second pass marks steps done) by reading it inside the side_effect.
    state_at_restart = {}

    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        # On the first step of the second pass, capture the state written by the restart
        if call_count[0] == 2:
            state_path = ctx_arg.intermediate_dir / "pipeline_state.json"
            if state_path.exists():
                state_at_restart.update(json.loads(state_path.read_text()).get("steps", {}))
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        run_merge(ctx)

    assert state_at_restart, "pipeline_state.json must have been written during restart"
    for step_name in _MERGE_SCHEMA_RESTART_INVALIDATE:
        if step_name in state_at_restart:
            assert state_at_restart[step_name]["status"] == "pending", (
                f"Step {step_name!r} should be pending after restart, "
                f"got {state_at_restart[step_name]['status']!r}"
            )


def test_run_merge_schema_restart_increments_restart_count(tmp_path):
    """ctx.schema_restart_count increments on each SchemaUpdatedError."""
    ctx = _make_ctx(tmp_path)
    assert ctx.schema_restart_count == 0

    call_count = [0]
    restart_counts_seen = []

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        restart_counts_seen.append(ctx_arg.schema_restart_count)
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        run_merge(ctx)

    assert ctx.schema_restart_count == 1
    assert any(c == 1 for c in restart_counts_seen)


# ---------------------------------------------------------------------------
# Test: schema_hints populated from gap_orphans
# ---------------------------------------------------------------------------

def test_run_merge_sets_schema_hints_on_restart(tmp_path):
    """ctx.schema_hints is populated with orphan data from gap_orphans on SchemaUpdatedError."""
    ctx = _make_ctx(tmp_path)

    gap_orphan = _make_gap_orphan(
        orphan_id="node-orphan-1",
        orphan_type="Technology",
        orphan_name="Python",
        shared_chunks=["notes.md::0", "notes.md::1"],
    )
    schema_exc = _schema_updated_error(
        new_property_names=["uses_technology"],
        gap_orphans=[gap_orphan],
    )

    # Capture schema_hints on the first step of the restarted pass (before they
    # could be overwritten by a second SchemaUpdatedError, which won't happen here).
    captured_hints = []
    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise schema_exc
        if not captured_hints and ctx_arg.schema_hints:
            captured_hints.extend(ctx_arg.schema_hints)
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        run_merge(ctx)

    assert len(captured_hints) == 1
    hint = captured_hints[0]
    assert hint["orphan_id"] == "node-orphan-1"
    assert hint["orphan_type"] == "Technology"
    assert hint["orphan_name"] == "Python"
    assert hint["shared_chunks"] == ["notes.md::0", "notes.md::1"]
    assert hint["new_properties"] == ["uses_technology"]


# ---------------------------------------------------------------------------
# Test: restart limit reached
# ---------------------------------------------------------------------------

def test_run_merge_schema_restart_limit_reached_continues(tmp_path):
    """When schema_restart_count >= MERGE_ORPHAN_SCHEMA_MAX_RESTARTS,
    a warning is logged and the pipeline continues (no exception raised)."""
    ctx = _make_ctx(tmp_path)
    # Simulate having already hit the restart limit
    ctx.schema_restart_count = cfg_mod.MERGE_ORPHAN_SCHEMA_MAX_RESTARTS

    call_count = [0]

    def side_effect(step, ctx_arg):
        call_count[0] += 1
        if call_count[0] == 1:
            raise _schema_updated_error()
        return None

    # Should not raise; the limit-exceeded branch logs a warning and continues
    with (
        patch("mykg.merge_run._try_run", side_effect=side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
        patch("mykg.merge_run.log") as mock_log,
    ):
        run_merge(ctx)  # must not raise

    warning_messages = [str(call) for call in mock_log.warning.call_args_list]
    assert any("restart limit" in msg and "reached" in msg for msg in warning_messages)


# ---------------------------------------------------------------------------
# Test: _log_merge_advisory — fallback hint for unknown step
# ---------------------------------------------------------------------------

def test_run_merge_hint_for_unknown_step_in_advisory(tmp_path):
    """_log_merge_advisory uses a fallback message for unknown step names."""
    ctx = _make_ctx(tmp_path)
    unknown_step = Step(
        name="totally_unknown_step",
        fn=lambda c: None,
        outputs=["some_file.json"],
    )

    with patch("mykg.merge_run.log") as mock_log:
        _log_merge_advisory(unknown_step, "something broke", ctx)

    error_messages = " ".join(str(c) for c in mock_log.error.call_args_list)
    assert "Re-run merge-graphs from the beginning" in error_messages


# ---------------------------------------------------------------------------
# Test: blocking step failure → PipelineHaltError
# ---------------------------------------------------------------------------

def test_run_merge_halt_error_raised_on_blocking_step_failure(tmp_path):
    """A blocking step that fails after all retries raises PipelineHaltError."""
    ctx = _make_ctx(tmp_path)

    # Always return an error string (simulates step failure on every attempt)
    with (
        patch("mykg.merge_run._try_run", return_value="simulated failure"),
        patch("mykg.merge_run._is_done", return_value=False),
        patch("mykg.merge_run.log"),
    ):
        with pytest.raises(PipelineHaltError) as exc_info:
            run_merge(ctx)

    assert exc_info.value.step_name is not None


# ---------------------------------------------------------------------------
# Test: _log_merge_advisory called on step failure
# ---------------------------------------------------------------------------

def test_run_merge_log_advisory_called_on_step_failure(tmp_path):
    """_log_merge_advisory is invoked when a blocking step fails after all retries."""
    ctx = _make_ctx(tmp_path)

    with (
        patch("mykg.merge_run._try_run", return_value="oops"),
        patch("mykg.merge_run._is_done", return_value=False),
        patch("mykg.merge_run._log_merge_advisory") as mock_advisory,
        patch("mykg.merge_run.log"),
    ):
        with pytest.raises(PipelineHaltError):
            run_merge(ctx)

    assert mock_advisory.called


# ---------------------------------------------------------------------------
# Test: non-blocking step continues after failure
# ---------------------------------------------------------------------------

def test_run_merge_non_blocking_step_continues_after_failure(tmp_path):
    """A non-blocking step failure logs a warning but does not halt the pipeline."""
    ctx = _make_ctx(tmp_path)

    non_blocking_names = {s.name for s in MERGE_STEPS if not s.blocking}
    if not non_blocking_names:
        pytest.skip("No non-blocking steps defined in MERGE_STEPS")

    # Pick the first non-blocking step
    target_step_name = next(iter(sorted(non_blocking_names)))

    def try_run_side_effect(step, ctx_arg):
        if step.name == target_step_name:
            return "non-blocking failure"
        return None

    with (
        patch("mykg.merge_run._try_run", side_effect=try_run_side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
        patch("mykg.merge_run.log") as mock_log,
    ):
        # Must not raise
        run_merge(ctx)

    warning_calls = " ".join(str(c) for c in mock_log.warning.call_args_list)
    assert "NON-BLOCKING" in warning_calls


# ---------------------------------------------------------------------------
# Test: KeyboardInterrupt — state saved as failed before re-raise
# ---------------------------------------------------------------------------

def test_run_merge_keyboard_interrupt_saved_to_state(tmp_path):
    """KeyboardInterrupt during a step saves the step as failed before re-raising."""
    ctx = _make_ctx(tmp_path)

    interrupted_step = [None]

    def try_run_side_effect(step, ctx_arg):
        interrupted_step[0] = step.name
        raise KeyboardInterrupt()

    with (
        patch("mykg.merge_run._try_run", side_effect=try_run_side_effect),
        patch("mykg.merge_run._is_done", return_value=False),
    ):
        with pytest.raises(KeyboardInterrupt):
            run_merge(ctx)

    state_path = ctx.intermediate_dir / "pipeline_state.json"
    assert state_path.exists(), "pipeline_state.json must be written even on interrupt"
    state = json.loads(state_path.read_text())
    assert interrupted_step[0] is not None
    assert state["steps"][interrupted_step[0]]["status"] == "failed"
