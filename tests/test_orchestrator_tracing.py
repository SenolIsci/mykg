from mykg.orchestrator import PipelineContext, Step, run


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


def test_step_span_created_for_successful_step(tmp_path, span_exporter):
    calls = []

    def ok_step(ctx):
        calls.append(1)

    steps = [
        Step(name="ok_step", fn=ok_step, outputs=[], is_llm_step=False, blocking=True)
    ]
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)

    run(steps, ctx)

    assert calls == [1]

    spans = span_exporter.get_finished_spans()
    step_spans = [s for s in spans if s.name == "mykg.step.ok_step"]
    assert len(step_spans) == 1
    assert step_spans[0].attributes["mykg.step.name"] == "ok_step"
    assert step_spans[0].attributes["mykg.step.is_llm_step"] is False
    assert step_spans[0].attributes["mykg.step.blocking"] is True

    # Non-LLM steps skip the attempt-N span entirely — nothing content-bearing
    # would ever live under it (see _attempt_span() in orchestrator.py).
    attempt_spans = [s for s in spans if s.name == "attempt-1"]
    assert len(attempt_spans) == 0


def test_attempt_spans_created_on_retry(tmp_path, span_exporter):
    attempt_count = {"n": 0}

    def flaky_step(ctx):
        attempt_count["n"] += 1
        if attempt_count["n"] < 2:
            raise RuntimeError("transient failure")

    steps = [
        Step(
            name="flaky_step", fn=flaky_step, outputs=[], is_llm_step=False, blocking=True
        )
    ]
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)

    run(steps, ctx)

    assert attempt_count["n"] == 2  # bare retry succeeded on attempt 2

    # Non-LLM step: retry control flow still runs (attempt_count reached 2),
    # but neither attempt gets its own span — same reasoning as the
    # successful-step case above.
    spans = span_exporter.get_finished_spans()
    assert len([s for s in spans if s.name == "attempt-1"]) == 0
    assert len([s for s in spans if s.name == "attempt-2"]) == 0
    # non-LLM step: no feedback-correction attempt
    assert len([s for s in spans if s.name == "attempt-3-with-feedback"]) == 0

    step_spans = [s for s in spans if s.name == "mykg.step.flaky_step"]
    assert len(step_spans) == 1


def test_llm_step_gets_feedback_attempt_span_on_persistent_failure(
    tmp_path, span_exporter, monkeypatch
):
    import mykg.feedback as feedback

    monkeypatch.setattr(feedback, "apply", lambda *a, **kw: False)

    fail_count = {"n": 0}

    def bad_step(ctx):
        fail_count["n"] += 1
        raise ValueError(f"bad attempt {fail_count['n']}")

    steps = [
        Step(name="llm_step", fn=bad_step, outputs=["x.json"], is_llm_step=True, blocking=False),
    ]
    ctx = _make_ctx(tmp_path)
    ctx.intermediate_dir.mkdir(parents=True)
    ctx.output_dir.mkdir(parents=True)

    run(steps, ctx)

    assert fail_count["n"] == 3  # 1st attempt + bare retry + post-feedback attempt

    spans = span_exporter.get_finished_spans()
    assert len([s for s in spans if s.name == "attempt-1"]) == 1
    assert len([s for s in spans if s.name == "attempt-2"]) == 1
    assert len([s for s in spans if s.name == "attempt-3-with-feedback"]) == 1

    step_spans = [s for s in spans if s.name == "mykg.step.llm_step"]
    assert len(step_spans) == 1
    assert step_spans[0].attributes["mykg.step.error"] == "bad attempt 3"
