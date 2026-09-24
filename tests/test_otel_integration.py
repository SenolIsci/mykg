"""End-to-end OTel span-tree verification against a real pipeline run.

Requires OPENROUTER_API_KEY (or equivalent) — skipped automatically when
absent, same as tests/test_live_pipeline.py. Reuses that file's exact
CLI-bypassing invocation pattern (run(STEPS, ctx) directly) rather than
inventing a new one.

Note: spans are created by mykg.orchestrator/pass1/pass2/retry regardless of
config.OTEL_ENABLED — that flag only gates whether setup_tracing() installs a
real OTLP-exporting TracerProvider (see mykg/tracing.py). The span_exporter
fixture installs its own in-memory provider directly, so this test does not
need --otel or config.OTEL_ENABLED=True to observe the span tree.
"""

import pytest

from mykg.llm.config import load_adapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS

from .test_live_pipeline import _raw_config


def _make_ctx(tmp_path, api_key, corpus_dir):
    import shutil

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for f in corpus_dir.iterdir():
        shutil.copy(f, input_dir / f.name)
    output_dir = tmp_path / "output"
    intermediate_dir = tmp_path / "intermediate"
    output_dir.mkdir(parents=True)
    intermediate_dir.mkdir(parents=True)
    adapter = load_adapter(_raw=_raw_config(api_key))
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        base_schema=None,
        thesaurus=None,
        review=False,
    )


@pytest.mark.live
def test_extract_graph_produces_expected_span_tree(
    tmp_path, openrouter_api_key, live_corpus, span_exporter
):
    ctx = _make_ctx(tmp_path, openrouter_api_key, live_corpus)
    run(STEPS, ctx)

    spans = span_exporter.get_finished_spans()

    step_spans = [s for s in spans if s.name.startswith("mykg.step.")]
    assert len(step_spans) >= 8, (
        f"expected at least 8 step spans (12-step pipeline, some may be "
        f"skipped e.g. orphan_pass disabled), got {len(step_spans)}: "
        f"{[s.name for s in step_spans]}"
    )

    llm_call_spans = [s for s in spans if s.name == "mykg.llm.call"]
    assert len(llm_call_spans) >= 1, "expected at least one mykg.llm.call span"
    assert all("gen_ai.system" in s.attributes for s in llm_call_spans)
    assert all("mykg.llm.context_label" in s.attributes for s in llm_call_spans)

    pass1_step = next(s for s in step_spans if s.name == "mykg.step.pass1")
    pass2_step = next(s for s in step_spans if s.name == "mykg.step.pass2")

    batch_spans = [s for s in spans if s.name in ("mykg.pass1.batch", "mykg.pass2.file")]
    assert len(batch_spans) >= 1, "expected at least one pass1/pass2 batch or file span"

    # attempt-N spans are only created for LLM steps (_attempt_span() skips
    # the span for non-LLM steps — see orchestrator.py — since there's never
    # any content-bearing child to attach to a non-LLM step's attempt). So
    # the right lower bound is "at least one attempt span per LLM step span
    # that actually ran", not one per step span overall.
    llm_step_spans = [s for s in step_spans if s.attributes.get("mykg.step.is_llm_step")]
    attempt_spans = [s for s in spans if s.name.startswith("attempt-")]
    assert len(attempt_spans) >= max(len(llm_step_spans) - 1, 0)  # allow one skipped/no-op LLM step

    assert pass1_step.status.is_ok
    assert pass2_step.status.is_ok
