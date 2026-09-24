#!/usr/bin/env python3
"""Read back Phoenix span annotations for a mykg session and print a
pass-rate summary per evaluation name.

Reusable as-is across invocations of the mykg-phoenix-eval skill -- unlike
eval-py-skeleton.py, this doesn't need per-run adaptation since summarizing
"what annotations exist and what did they score" is the same operation
regardless of which evaluators produced them.

Usage:
    uv run python scripts/summarize_annotations.py <session_name>
    uv run python scripts/summarize_annotations.py  # defaults to latest session
"""

import sys
from pathlib import Path

from phoenix.client import Client

PHOENIX_URL = "http://localhost:6006"
PROJECT = "default"


def find_session_trace_id(client: Client, session_name: str) -> str:
    """See eval-py-skeleton.py for the full explanation of why this reads
    attributes.mykg as a nested dict rather than a dotted column."""
    df = client.spans.get_spans_dataframe(project_name=PROJECT, limit=2000)
    run_spans = df[df["name"] == "mykg.extract_graph.run"]
    mykg_attrs = run_spans["attributes.mykg"].apply(lambda d: d if isinstance(d, dict) else {})
    match = run_spans[mykg_attrs.apply(lambda d: d.get("session")) == session_name]
    if match.empty:
        raise ValueError(f"No mykg.extract_graph.run span found for session={session_name!r}")
    return match.iloc[0]["context.trace_id"]


def summarize(session_name: str):
    client = Client(base_url=PHOENIX_URL)
    trace_id = find_session_trace_id(client, session_name)

    spans_df = client.spans.get_spans_dataframe(project_name=PROJECT, limit=2000)
    trace_spans = spans_df[spans_df["context.trace_id"] == trace_id]
    span_ids = trace_spans["context.span_id"].tolist()

    if not span_ids:
        print(f"No spans found for session {session_name}.")
        return

    annotations = client.spans.get_span_annotations(
        span_ids=span_ids, project_identifier=PROJECT
    )
    if not annotations:
        print(
            f"No annotations found for session {session_name}. "
            "Has an eval.py been run against this session yet?"
        )
        return

    by_name: dict[str, list[dict]] = {}
    for ann in annotations:
        by_name.setdefault(ann["name"], []).append(ann)

    print(f"Session: {session_name}  (trace_id={trace_id})")
    print(f"{'Evaluation':<30} {'Count':>6} {'Pass rate':>10} {'Mean score':>11}")
    print("-" * 60)
    for name, anns in sorted(by_name.items()):
        scores = [a["result"].get("score") for a in anns if a["result"].get("score") is not None]
        if not scores:
            continue
        pass_rate = sum(1 for s in scores if s >= 1.0) / len(scores)
        mean_score = sum(scores) / len(scores)
        print(f"{name:<30} {len(scores):>6} {pass_rate:>9.0%} {mean_score:>11.2f}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        session = sys.argv[1]
    else:
        sessions_dir = Path("mykg_sessions")
        session = sorted(p.name for p in sessions_dir.iterdir())[-1]
        print(f"No session given, using latest: {session}")
    summarize(session)
