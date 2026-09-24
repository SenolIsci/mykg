"""Worked skeleton for a mykg + Phoenix eval.py.

This is NOT meant to be run unmodified. It shows the three-phase shape
(load -> evaluate -> write back + report) wired against real mykg span
shapes, with one code evaluator and one LLM-judge evaluator for Pass 2
extraction as a concrete example. Adapt the evaluators to whatever the
run actually needs graded -- read references/span-map.md and the SKILL.md
"How to propose evaluators" section before copying checks from here
verbatim, since the point of this skill is to reason about what could
actually go wrong in THIS run's data, not to run a fixed checklist.

All API calls below were verified against the installed
arize-phoenix-client / arize-phoenix-evals in this project by direct
introspection -- see SKILL.md's "verified API surface" section.
"""

import json
from pathlib import Path

import pandas as pd
from phoenix.client import Client
from phoenix.evals import ClassificationEvaluator, LLM, create_evaluator, evaluate_dataframe

PHOENIX_URL = "http://localhost:6006"
PROJECT = "default"  # mykg does not set a custom Phoenix project name today


# ---------------------------------------------------------------------------
# Phase 1: Load — resolve the session, find its trace, pull relevant spans
# ---------------------------------------------------------------------------


def find_session_trace_id(client: Client, session_name: str) -> str:
    """Match a mykg session name to its Phoenix trace_id via the root span's
    mykg.session attribute. Raises if not found -- never silently evaluate
    the wrong run.

    IMPORTANT: get_spans_dataframe() flattens OpenInference-namespaced
    attributes (llm.*, input.*, output.*, gen_ai.*) into individual dotted
    columns, but a custom namespace like mykg's own "mykg.*" attributes
    stays as ONE dict-valued column: attributes.mykg == {"session": ...,
    "profile": ..., ...}. Verified by direct introspection against a real
    run -- do not assume attributes.mykg.session exists as its own column.
    """
    df = client.spans.get_spans_dataframe(project_name=PROJECT, limit=2000)
    run_spans = df[df["name"] == "mykg.extract_graph.run"]
    mykg_attrs = run_spans["attributes.mykg"].apply(lambda d: d if isinstance(d, dict) else {})
    match = run_spans[mykg_attrs.apply(lambda d: d.get("session")) == session_name]
    if match.empty:
        raise ValueError(
            f"No mykg.extract_graph.run span found for session={session_name!r}. "
            "Was --otel passed (or otel.enabled: true set) for this run?"
        )
    return match.iloc[0]["context.trace_id"]


def load_pass2_chatcompletion_spans(client: Client, trace_id: str) -> pd.DataFrame:
    """Pull the ChatCompletion spans for Pass 2 LLM calls in this trace --
    these carry the actual source-chunk text and the extracted nodes/edges
    JSON, needed for grounding/hallucination-style evaluators."""
    df = client.spans.get_spans_dataframe(project_name=PROJECT, limit=2000)
    trace_spans = df[df["context.trace_id"] == trace_id]

    # mykg.llm.call spans carry context_label under the single dict-valued
    # "attributes.mykg" column (see the note in find_session_trace_id --
    # mykg's custom namespace does NOT get dotted-flattened like llm.*/
    # input.*/output.* do), keyed as attributes.mykg["llm"]["context_label"].
    llm_call_spans = trace_spans[trace_spans["name"] == "mykg.llm.call"]
    mykg_attrs = llm_call_spans["attributes.mykg"].apply(
        lambda d: d if isinstance(d, dict) else {}
    )
    context_labels = mykg_attrs.apply(lambda d: d.get("llm", {}).get("context_label", ""))
    pass2_calls = llm_call_spans[context_labels.str.startswith("pass2")]

    chat_spans = trace_spans[
        (trace_spans["name"] == "ChatCompletion")
        & (trace_spans["parent_id"].isin(pass2_calls["context.span_id"]))
    ]
    return chat_spans


# ---------------------------------------------------------------------------
# Phase 2: Evaluate — code checks first (cheap, exact), then LLM judges
# ---------------------------------------------------------------------------


def build_eval_dataframe(chat_spans_df: pd.DataFrame) -> pd.DataFrame:
    """Reshape ChatCompletion spans into a flat frame with one row per
    extracted node/edge, joined with the source chunk text -- the shape
    both the code and LLM evaluators below expect."""
    rows = []
    for _, span in chat_spans_df.iterrows():
        span_id = span["context.span_id"]
        input_messages = span["attributes.llm.input_messages"]
        # Each message dict has FLAT dotted keys "message.role"/"message.content"
        # (not a nested {"message": {"role": ..., "content": ...}} dict) --
        # verified by direct introspection. Index 1 is the user message; it
        # contains the source chunk text (see references/span-map.md).
        source_text = next(
            (m["message.content"] for m in input_messages if m.get("message.role") == "user"),
            "",
        )
        try:
            output = json.loads(span["attributes.output.value"])
            content = output["choices"][0]["message"]["content"]
            extraction = json.loads(content)
        except (KeyError, IndexError, json.JSONDecodeError):
            continue  # a genuinely blank/unparseable response -- already
            # visible as a pass2.chunk.skipped event on the parent batch
            # span; nothing to grade here since there's no extraction

        node_ids = {n["id"] for n in extraction.get("nodes", [])}
        for edge in extraction.get("edges", []):
            # A malformed edge missing type/from/to is itself worth grading
            # as a failure (edge_endpoints_exist below will correctly score
            # it 0), so don't skip it here -- just don't let a None field
            # break identifier construction downstream in
            # write_back_and_report (f"{None}" -> the string "None", not a
            # crash, but skip() the row instead if you'd rather not annotate
            # a garbage edge with a garbage identifier at all).
            rows.append(
                {
                    "span_id": span_id,
                    "text": source_text,
                    "edge_type": edge.get("type"),
                    "edge_from": edge.get("from"),
                    "edge_to": edge.get("to"),
                    "node_ids": node_ids,  # used by the code evaluator, not the LLM template
                }
            )
    return pd.DataFrame(rows)


@create_evaluator(name="edge_endpoints_exist", kind="code")
def edge_endpoints_exist(edge_from: str, edge_to: str, node_ids: set) -> bool:
    """Deterministic check: does this edge's from/to resolve to a node ID
    that was actually extracted in the same call? mykg's own assembler
    already drops dangling edges silently -- this surfaces HOW OFTEN that
    happens as a metric, which the pipeline itself doesn't report."""
    return edge_from in node_ids and edge_to in node_ids


def build_edge_plausibility_judge() -> ClassificationEvaluator:
    """LLM-as-judge: is this edge type a plausible relationship given the
    source text, or does it look invented? Use gpt-5.4-mini or whatever
    model is cheap and fast -- the judge doesn't need to be the same model
    that did the extraction, and using a different one avoids the judge
    rubber-stamping its own mistakes."""
    llm = LLM(provider="openai", model="gpt-5.4-mini-2026-03-17")
    return ClassificationEvaluator(
        name="edge_type_plausible",
        llm=llm,
        prompt_template=(
            "Source text: {text}\n"
            "Extracted edge: {edge_type} from {edge_from} to {edge_to}\n"
            "Is this edge type a plausible relationship given the source text? "
            "Answer only: plausible or implausible."
        ),
        choices={"plausible": 1.0, "implausible": 0.0},
        include_explanation=True,
    )


# ---------------------------------------------------------------------------
# Phase 3: Write back + report
# ---------------------------------------------------------------------------


def write_back_and_report(client: Client, results_df: pd.DataFrame, score_columns: list[str]):
    """Attach each eval's score to the span it graded, and print a summary.

    CRITICAL: add_span_annotation / log_span_annotations_dataframe upsert by
    (span_id, annotation_name) -- writing a second annotation with the same
    name to a span already carrying one SILENTLY OVERWRITES it, it does not
    accumulate. Verified directly: writing two annotations with the same
    name to the same span_id but no identifier leaves only the second write
    behind. This matters a lot for mykg's own data shape, since a single
    ChatCompletion span (one Pass 2 batch call) commonly produces many edges
    -- if you're annotating per-edge but multiple edges share one span_id,
    you MUST set a distinct "identifier" per row (e.g. an edge's own
    from/to/type) or every edge but the last silently vanishes from Phoenix
    with no error. The "identifier" column is confirmed supported by
    log_span_annotations_dataframe specifically for this reason.

    Residual caveat, confirmed against a real run: even with this fix, a
    handful of annotations can still collide if two DIFFERENT edges within
    the same span happen to share the exact same (from, type, to) triple
    (e.g. a duplicate edge the LLM emitted twice, or two genuinely identical
    relationships extracted from different sentences in the same chunk) --
    124 graded edges landed as 116 annotations in one real test run, an ~6%
    gap consistent with this. If you need every graded row to be
    individually recoverable even in that case, append the DataFrame's own
    row index to the identifier (f"...-{i}") rather than relying on edge
    content alone to be unique.
    """
    for score_col in score_columns:
        eval_name = score_col.removesuffix("_score")
        ann_df = results_df[["span_id", "edge_type", "edge_from", "edge_to"]].copy()
        ann_df["identifier"] = ann_df.apply(
            lambda r: f"{r['edge_from']}->{r['edge_type']}->{r['edge_to']}", axis=1
        )
        scores = results_df[score_col].apply(pd.Series)  # unpack the score dict
        ann_df["score"] = scores["score"]
        ann_df["label"] = scores["label"]
        # "explanation" only exists on LLM-judge scores, not code evaluator
        # scores (create_evaluator never sets it) -- use a column of None
        # rather than DataFrame.get() on a possibly-missing column, which
        # returns a bare None scalar instead of a column and breaks the
        # assignment.
        ann_df["explanation"] = scores["explanation"] if "explanation" in scores else None

        client.spans.log_span_annotations_dataframe(
            dataframe=ann_df[
                ["span_id", "identifier", "score", "label", "explanation"]
            ].set_index("span_id"),
            annotation_name=eval_name,
            annotator_kind="CODE" if scores["kind"].iloc[0] == "code" else "LLM",
        )

        pass_rate = (ann_df["score"] >= 1.0).mean()
        print(f"{eval_name}: {pass_rate:.0%} pass rate over {len(ann_df)} edges")


def main(session_name: str):
    client = Client(base_url=PHOENIX_URL)

    trace_id = find_session_trace_id(client, session_name)
    chat_spans = load_pass2_chatcompletion_spans(client, trace_id)
    if chat_spans.empty:
        print(f"No Pass 2 LLM calls found for session {session_name} -- nothing to grade.")
        return

    eval_df = build_eval_dataframe(chat_spans)

    results_df = evaluate_dataframe(
        dataframe=eval_df,
        evaluators=[edge_endpoints_exist, build_edge_plausibility_judge()],
    )

    write_back_and_report(
        client, results_df, ["edge_endpoints_exist_score", "edge_type_plausible_score"]
    )


if __name__ == "__main__":
    import sys

    session = sys.argv[1] if len(sys.argv) > 1 else None
    if not session:
        latest = sorted(Path("mykg_sessions").iterdir())[-1].name
        print(f"No session given, using latest: {latest}")
        session = latest
    main(session)
