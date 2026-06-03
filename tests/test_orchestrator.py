import json

import pytest

from mykg.orchestrator import PipelineContext, PipelineHaltError, PipelineState, Step, run


def test_pipeline_context_fields(tmp_path):
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    assert ctx.input_dir == tmp_path / "input"
    assert ctx.review is False


def test_step_defaults():
    step = Step(name="foo", fn=lambda ctx: None, outputs=[])
    assert step.is_llm_step is False
    assert step.blocking is True
    assert step.requires_review_flag is False


def test_step_is_done_when_all_outputs_exist(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    (tmp_path / "b.json").write_text("{}")
    step = Step(name="foo", fn=lambda ctx: None, outputs=["a.json", "b.json"])
    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    from mykg.orchestrator import _is_done

    assert _is_done(step, ctx) is True


def test_step_not_done_when_output_missing(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    step = Step(name="foo", fn=lambda ctx: None, outputs=["a.json", "missing.json"])
    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    from mykg.orchestrator import _is_done

    assert _is_done(step, ctx) is False


def test_pipeline_halt_error():
    err = PipelineHaltError("pass1", "something broke")
    assert "pass1" in str(err)


def test_state_initialises_all_pending():
    state = PipelineState(step_names=["ingest", "pass1", "export"])
    assert state.steps["ingest"]["status"] == "pending"
    assert state.steps["pass1"]["status"] == "pending"


def test_state_mark_done():
    state = PipelineState(step_names=["ingest", "pass1"])
    state.mark_done("ingest")
    assert state.steps["ingest"]["status"] == "done"
    assert "completed_at" in state.steps["ingest"]


def test_state_mark_failed():
    state = PipelineState(step_names=["pass1"])
    state.mark_failed("pass1", "bad json", attempts=2, llm_correction=False)
    assert state.steps["pass1"]["status"] == "failed"
    assert state.errors["pass1"]["error"] == "bad json"
    assert state.errors["pass1"]["attempts"] == 2


def test_state_mark_waiting():
    state = PipelineState(step_names=["human_review"])
    state.mark_waiting("human_review")
    assert state.steps["human_review"]["status"] == "waiting"


def test_state_save_and_load(tmp_path):
    state = PipelineState(step_names=["ingest", "pass1"])
    state.mark_done("ingest")
    state.save(tmp_path)
    loaded = PipelineState.load(tmp_path, step_names=["ingest", "pass1"])
    assert loaded.steps["ingest"]["status"] == "done"
    assert loaded.steps["pass1"]["status"] == "pending"


def _make_ctx(tmp_path):
    return PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )


def test_run_executes_all_steps(tmp_path):
    executed = []

    def make_step(name, out):
        def fn(ctx):
            executed.append(name)
            (ctx.intermediate_dir / out).write_text("{}")

        return Step(name=name, fn=fn, outputs=[out])

    steps = [make_step("a", "a.json"), make_step("b", "b.json")]
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    run(steps, ctx)
    assert executed == ["a", "b"]


def test_run_skips_done_steps(tmp_path):
    executed = []
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    (ctx.intermediate_dir / "a.json").write_text("{}")

    def fn_a(c):
        executed.append("a")

    def fn_b(c):
        executed.append("b")
        (c.intermediate_dir / "b.json").write_text("{}")

    steps = [
        Step(name="a", fn=fn_a, outputs=["a.json"]),
        Step(name="b", fn=fn_b, outputs=["b.json"]),
    ]
    run(steps, ctx)
    assert "a" not in executed
    assert "b" in executed


def test_run_retries_on_failure(tmp_path):
    call_counts = {"n": 0}
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)

    def flaky(c):
        call_counts["n"] += 1
        if call_counts["n"] < 2:
            raise ValueError("transient error")
        (c.intermediate_dir / "out.json").write_text("{}")

    steps = [Step(name="flaky", fn=flaky, outputs=["out.json"])]
    run(steps, ctx)
    assert call_counts["n"] == 2


def test_run_halts_on_blocking_failure(tmp_path):
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)

    def always_fails(c):
        raise ValueError("permanent error")

    steps = [Step(name="bad", fn=always_fails, outputs=["x.json"], blocking=True)]
    with pytest.raises(PipelineHaltError) as exc_info:
        run(steps, ctx)
    assert "bad" in str(exc_info.value)


def test_run_continues_on_nonblocking_failure(tmp_path):
    executed = []
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)

    def always_fails(c):
        raise ValueError("non-blocking error")

    def fn_b(c):
        executed.append("b")
        (c.intermediate_dir / "b.json").write_text("{}")

    steps = [
        Step(name="bad", fn=always_fails, outputs=["x.json"], blocking=False),
        Step(name="b", fn=fn_b, outputs=["b.json"]),
    ]
    run(steps, ctx)
    assert "b" in executed


def test_pipeline_context_has_runtime_fields():
    """PipelineContext must declare all runtime fields with None defaults."""
    from pathlib import Path

    from mykg.orchestrator import PipelineContext

    ctx = PipelineContext(
        input_dir=Path("."),
        output_dir=Path("."),
        intermediate_dir=Path("."),
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    assert ctx.all_chunks is None
    assert ctx.file_contents is None
    assert ctx.nodes is None
    assert ctx.edge_metadata is None


def test_pipeline_context_thesaurus_type():
    """PipelineContext.thesaurus is typed — None by default."""
    from pathlib import Path

    from mykg.orchestrator import PipelineContext

    ctx = PipelineContext(
        input_dir=Path("."),
        output_dir=Path("."),
        intermediate_dir=Path("."),
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    assert ctx.thesaurus is None


def test_schema_restart_invalidates_schema_flatten_output(tmp_path, monkeypatch):
    """SchemaUpdatedError must delete flattened_schema.json so schema_flatten re-runs."""
    import mykg.config as _cfg
    from mykg.orchestrator import SchemaUpdatedError

    monkeypatch.setattr(_cfg, "ORPHAN_SCHEMA_MAX_RESTARTS", 1)

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate outputs that should survive restart
    (ctx.intermediate_dir / "schema.json").write_text('{"concepts":[],"properties":[]}')
    (ctx.intermediate_dir / "schema.ttl").write_text("")
    (ctx.intermediate_dir / "schema_validate.done").write_text("")
    (ctx.intermediate_dir / "schema_approved.flag").write_text("auto-approved")

    # flattened_schema.json must be deleted on schema restart
    stale_flat = ctx.intermediate_dir / "flattened_schema.json"
    stale_flat.write_text('{"OldType": ["old_attr"]}')

    restart_fired = {"n": 0}

    def schema_flatten_step(c):
        # Write fresh flattened_schema.json (representing updated schema)
        (c.intermediate_dir / "flattened_schema.json").write_text('{"NewType": ["new_attr"]}')

    def pass2_step(c):
        (c.intermediate_dir / "raw_extractions.json").write_text("{}")
        (c.intermediate_dir / "chunk_node_index.json").write_text("{}")

    def orphan_connect_step(c):
        restart_fired["n"] += 1
        if restart_fired["n"] == 1:
            # First run: trigger schema restart
            raise SchemaUpdatedError(["new_prop"])
        # Second run: write outputs normally
        (c.intermediate_dir / "orphan_connections.json").write_text("{}")
        (c.intermediate_dir / "orphan_log.json").write_text("[]")

    def export_step(c):
        (c.output_dir / "nodes.jsonl").write_text("")
        (c.output_dir / "edges.jsonl").write_text("")
        (c.output_dir / "knowledge_graph.ttl").write_text("")
        (c.output_dir / "knowledge_graph_validation.json").write_text("{}")

    steps = [
        Step(name="schema_flatten", fn=schema_flatten_step, outputs=["flattened_schema.json"]),
        Step(
            name="pass2",
            fn=pass2_step,
            outputs=["raw_extractions.json", "chunk_node_index.json"],
        ),
        Step(
            name="orphan_connect",
            fn=orphan_connect_step,
            outputs=["orphan_connections.json", "orphan_log.json"],
            is_llm_step=True,
        ),
        Step(
            name="export",
            fn=export_step,
            outputs=[
                "nodes.jsonl",
                "edges.jsonl",
                "knowledge_graph.ttl",
                "knowledge_graph_validation.json",
            ],
            output_location="output",
        ),
    ]

    run(steps, ctx)

    # schema_flatten must have re-run and written fresh content
    assert stale_flat.exists()
    assert '"NewType"' in stale_flat.read_text(), (
        "flattened_schema.json still contains stale content — "
        "schema_flatten was not invalidated by SchemaUpdatedError"
    )
    assert restart_fired["n"] == 2


def test_schema_restart_does_not_re_run_upstream_of_schema_flatten(tmp_path, monkeypatch):
    """Steps before schema_flatten (pass1, schema_validate) must not re-run on schema restart."""
    import mykg.config as _cfg
    from mykg.orchestrator import SchemaUpdatedError

    monkeypatch.setattr(_cfg, "ORPHAN_SCHEMA_MAX_RESTARTS", 1)

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    executed = []

    def pass1_step(c):
        executed.append("pass1")
        (c.intermediate_dir / "schema.json").write_text('{"concepts":[],"properties":[]}')
        (c.intermediate_dir / "schema.ttl").write_text("")

    def schema_flatten_step(c):
        executed.append("schema_flatten")
        (c.intermediate_dir / "flattened_schema.json").write_text("{}")

    fired = {"n": 0}

    def orphan_connect_step(c):
        fired["n"] += 1
        if fired["n"] == 1:
            raise SchemaUpdatedError(["prop_x"])
        (c.intermediate_dir / "orphan_connections.json").write_text("{}")
        (c.intermediate_dir / "orphan_log.json").write_text("[]")

    steps = [
        Step(name="pass1", fn=pass1_step, outputs=["schema.json", "schema.ttl"]),
        Step(name="schema_flatten", fn=schema_flatten_step, outputs=["flattened_schema.json"]),
        Step(
            name="orphan_connect",
            fn=orphan_connect_step,
            outputs=["orphan_connections.json", "orphan_log.json"],
            is_llm_step=True,
        ),
    ]

    run(steps, ctx)

    # pass1 must run exactly once (not re-run after restart)
    assert executed.count("pass1") == 1
    # schema_flatten must run twice (once before restart, once after)
    assert executed.count("schema_flatten") == 2


def test_schema_restart_is_iterative_not_recursive(tmp_path, monkeypatch):
    """SchemaUpdatedError restart must loop in the same stack frame, not call run() recursively.

    With a recursive implementation, run() calls itself and the inner call's stack frames
    are visible in the Python call stack. We detect this by patching mykg.orchestrator.run
    and counting how many times it is entered: iterative = 1 entry, recursive = 2+ entries.
    """
    import mykg.config as _cfg
    import mykg.orchestrator as orch
    from mykg.orchestrator import SchemaUpdatedError

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(_cfg, "ORPHAN_SCHEMA_MAX_RESTARTS", 1)

    run_entries = {"n": 0}
    _real_run = orch.run

    def counting_run(steps, ctx):
        run_entries["n"] += 1
        return _real_run(steps, ctx)

    monkeypatch.setattr(orch, "run", counting_run)

    fired = {"n": 0}

    def schema_flatten_step(c):
        (c.intermediate_dir / "flattened_schema.json").write_text("{}")

    def orphan_connect_step(c):
        fired["n"] += 1
        if fired["n"] == 1:
            raise SchemaUpdatedError(["prop_x"])
        (c.intermediate_dir / "orphan_connections.json").write_text("{}")
        (c.intermediate_dir / "orphan_log.json").write_text("[]")

    steps = [
        Step(name="schema_flatten", fn=schema_flatten_step, outputs=["flattened_schema.json"]),
        Step(
            name="orphan_connect",
            fn=orphan_connect_step,
            outputs=["orphan_connections.json", "orphan_log.json"],
            is_llm_step=True,
        ),
    ]

    counting_run(steps, ctx)

    assert fired["n"] == 2, "orphan_connect must run twice: trigger restart, then succeed"
    # With iteration: run_entries["n"] == 1 (our wrapper above).
    # With recursion: run_entries["n"] == 2 (our wrapper + inner self-call).
    assert run_entries["n"] == 1, (
        f"run() was entered {run_entries['n']} time(s) — restart must be iterative (1 entry), "
        "not recursive (2+ entries)"
    )


@pytest.mark.parametrize(
    "exc_factory,exc_type",
    [
        (lambda: KeyboardInterrupt(), KeyboardInterrupt),
        (lambda: SystemExit(1), SystemExit),
    ],
)
def test_interrupt_marks_step_failed(tmp_path, exc_factory, exc_type):
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)

    def raises(c):
        raise exc_factory()

    steps = [Step(name="interrupted", fn=raises, outputs=["x.json"])]
    with pytest.raises(exc_type):
        run(steps, ctx)

    state_path = ctx.intermediate_dir / "pipeline_state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text())
    assert state["steps"]["interrupted"]["status"] == "failed"


# ---------------------------------------------------------------------------
# Extended Unit 6 — retry / restart / re-entry coverage
# ---------------------------------------------------------------------------


def test_is_done_returns_false_when_no_outputs(tmp_path):
    """Step with empty outputs list is never 'done' (line 96)."""
    from mykg.orchestrator import _is_done

    step = Step(name="x", fn=lambda c: None, outputs=[])
    ctx = _make_ctx(tmp_path)
    assert _is_done(step, ctx) is False


def test_review_flag_check(tmp_path):
    """_review_flag_exists checks for the approval flag."""
    from mykg.orchestrator import _review_flag_exists

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    assert _review_flag_exists(ctx) is False
    (ctx.intermediate_dir / "schema_approved.flag").write_text("ok")
    assert _review_flag_exists(ctx) is True


def test_human_review_waits_for_approval(tmp_path):
    """Pipeline pauses at human_review when review=True and flag missing."""
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.review = True

    executed = []

    def fn(c):
        executed.append("ran")
        (c.intermediate_dir / "schema_approved.flag").write_text("approved")

    def fn_b(c):
        executed.append("b")
        (c.intermediate_dir / "b.json").write_text("{}")

    steps = [
        Step(name="human_review", fn=fn, outputs=["schema_approved.flag"], requires_review_flag=True),
        Step(name="b", fn=fn_b, outputs=["b.json"]),
    ]
    run(steps, ctx)
    # No flag pre-existing -> pipeline returns early, fn never called
    assert "b" not in executed


def test_schema_restart_limit_reached(tmp_path, monkeypatch):
    """schema_restart_count >= max -> step is marked failed, no further restart."""
    import mykg.config as _cfg
    from mykg.orchestrator import SchemaUpdatedError

    monkeypatch.setattr(_cfg, "ORPHAN_SCHEMA_MAX_RESTARTS", 0)

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)

    fired = {"n": 0}

    def orphan_connect_step(c):
        fired["n"] += 1
        raise SchemaUpdatedError(["new_prop"])

    steps = [
        Step(
            name="orphan_connect",
            fn=orphan_connect_step,
            outputs=["orphan_connections.json"],
            is_llm_step=True,
            blocking=False,
        ),
    ]
    run(steps, ctx)
    # With max=0, the first call should be marked failed without restart
    assert fired["n"] == 1


def test_feedback_handler_failure_logged(tmp_path, monkeypatch):
    """When feedback.apply raises, the orchestrator logs and continues."""
    import mykg.feedback as feedback

    monkeypatch.setattr(feedback, "apply", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("fb")))

    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)

    fail_count = {"n": 0}

    def bad_step(c):
        fail_count["n"] += 1
        raise ValueError(f"bad attempt {fail_count['n']}")

    steps = [
        Step(name="llm_step", fn=bad_step, outputs=["x.json"], is_llm_step=True, blocking=False),
    ]
    run(steps, ctx)
    # 1st attempt + retry + post-feedback attempt = 3 calls
    assert fail_count["n"] == 3


def test_append_mode_requires_existing_schema(tmp_path):
    """append=True without prior schema.json raises RuntimeError."""
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.append = True

    with pytest.raises(RuntimeError, match="without --append"):
        run([], ctx)


def test_append_mode_invalidates_downstream(tmp_path):
    """When append + new_files, pass2+downstream outputs are invalidated."""
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)
    ctx.append = True
    # Required for append mode to pass the initial guard
    (ctx.intermediate_dir / "schema.json").write_text("{}")

    # Pre-populate downstream outputs that should be deleted
    (ctx.intermediate_dir / "edge_metadata.json").write_text("{}")
    (ctx.intermediate_dir / "name_normalization.json").write_text("{}")

    def ingest_fn(c):
        c.append_new_files = {"doc.md"}
        (c.intermediate_dir / "file_manifest.json").write_text("{}")

    def pass2_fn(c):
        (c.intermediate_dir / "raw_extractions.json").write_text("{}")
        (c.intermediate_dir / "chunk_node_index.json").write_text("{}")

    def normalize_fn(c):
        (c.intermediate_dir / "name_normalization.json").write_text("{}")

    def assemble_fn(c):
        (c.intermediate_dir / "edge_metadata.json").write_text("{}")

    steps = [
        Step(name="ingest", fn=ingest_fn, outputs=["file_manifest.json"]),
        Step(
            name="pass2",
            fn=pass2_fn,
            outputs=["raw_extractions.json", "chunk_node_index.json"],
            is_llm_step=True,
        ),
        Step(name="normalize_names", fn=normalize_fn, outputs=["name_normalization.json"], is_llm_step=True),
        Step(name="assemble", fn=assemble_fn, outputs=["edge_metadata.json"]),
    ]
    run(steps, ctx)

    # All downstream outputs should be present at end of run (re-written by their steps)
    assert (ctx.intermediate_dir / "raw_extractions.json").exists()


def test_append_mode_no_new_files(tmp_path):
    """append + ingest finds no new files -> downstream steps skipped."""
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)
    ctx.append = True
    (ctx.intermediate_dir / "schema.json").write_text("{}")

    executed = []

    def ingest_fn(c):
        c.append_new_files = set()  # explicitly empty
        (c.intermediate_dir / "file_manifest.json").write_text("{}")
        executed.append("ingest")

    def downstream_fn(c):
        executed.append("downstream")
        (c.intermediate_dir / "out.json").write_text("{}")

    steps = [
        Step(name="ingest", fn=ingest_fn, outputs=["file_manifest.json"]),
        Step(name="pass2", fn=downstream_fn, outputs=["out.json"]),
    ]
    run(steps, ctx)

    assert "ingest" in executed
    # downstream skipped because append_new_files is empty
    assert "downstream" not in executed


def test_append_mode_skips_pass1(tmp_path):
    """append mode skips pass1, schema_validate, human_review."""
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)
    ctx.append = True
    (ctx.intermediate_dir / "schema.json").write_text("{}")

    executed = []

    def fn_pass1(c):
        executed.append("pass1")
        (c.intermediate_dir / "schema.json").write_text("{}")

    def fn_ingest(c):
        executed.append("ingest")
        c.append_new_files = set()
        (c.intermediate_dir / "file_manifest.json").write_text("{}")

    steps = [
        Step(name="ingest", fn=fn_ingest, outputs=["file_manifest.json"]),
        Step(name="pass1", fn=fn_pass1, outputs=["schema.json"], is_llm_step=True),
    ]
    run(steps, ctx)
    assert "pass1" not in executed
    assert "ingest" in executed
