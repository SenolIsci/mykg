"""End-to-end regression test for --append re-extracting MODIFIED files.

Drives the real pipeline (``orchestrator.run(STEPS, ctx)``) twice with a
step-routing scripted adapter:

  1. Fresh run over two files — each contributes a unique node.
  2. One file is blanked on disk, then re-run with ``append=True`` and an
     adapter that now returns an empty extraction for that file.

Before the fix, the blanked file's stale shard survived and its unique node
persisted as a ghost in ``output/nodes.jsonl``. This test asserts the ghost is
gone after the append run.

Both prep modes are exercised: ``per_file`` and ``batch_chunks`` (the shipped
default, which also exercises the pass2_raw_batches composition-cache eviction).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS


# ``a.md`` contributes person-alice; ``b.md`` contributes person-bob. After
# blanking a.md, person-alice must disappear from the final graph.
_A_NODE = {
    "id": "person-alice",
    "type": "Person",
    "attributes": {"name": {"value": "Alice", "confidence": 1.0}},
}
_B_NODE = {
    "id": "person-bob",
    "type": "Person",
    "attributes": {"name": {"value": "Bob", "confidence": 1.0}},
}

_SCHEMA_JSON = json.dumps(
    {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
)


class ScriptedAdapter(LLMAdapter):
    """Routes each pipeline LLM call by context_label to a canned response.

    - pass1 / harmonize / quality review → the fixed one-concept schema
    - normalize_names → empty mappings
    - pass2 → whichever nodes the current phase should extract, keyed by which
      source file's text the user prompt contains
    """

    def __init__(self) -> None:
        # Mutated between the fresh run and the append run.
        self.a_nodes: list[dict] = [_A_NODE]

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        label = context_label or ""
        if label.startswith("pass1 batch") or label in (
            "schema_harmonize",
            "schema_quality_review",
        ):
            return _SCHEMA_JSON
        if label.startswith("pass2 chunk"):
            # Route by which file markers are in the prompt. A batch_chunks
            # prompt may contain BOTH markers (both files packed into one
            # batch) — return every matching file's nodes so the fresh run is
            # complete regardless of prep mode.
            nodes: list[dict] = []
            if "ALICE_MARKER" in user:
                nodes.extend(self.a_nodes)
            if "BOB_MARKER" in user:
                nodes.append(_B_NODE)
            return json.dumps({"nodes": nodes, "edges": []})
        # normalize_names and anything else: no-op mappings.
        return "{}"

    def endpoint_label(self) -> str:
        return "scripted"


def _make_full_ctx(tmp_path: Path, adapter: LLMAdapter, *, append: bool) -> PipelineContext:
    out = tmp_path / "output"
    inter = tmp_path / "intermediate"
    inp = tmp_path / "input"
    for p in (out, inter, inp):
        p.mkdir(parents=True, exist_ok=True)
    return PipelineContext(
        input_dir=inp,
        output_dir=out,
        intermediate_dir=inter,
        adapter=adapter,
        base_schema=None,
        thesaurus=None,
        review=False,
        append=append,
    )


def _node_ids(output_dir: Path) -> set[str]:
    path = output_dir / "nodes.jsonl"
    ids: set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                ids.add(json.loads(line)["id"])
    return ids


def test_append_blanked_file_removes_ghost_nodes_per_file(tmp_path, monkeypatch):
    """per_file mode: blanking a file and re-appending removes its nodes from the
    final graph. Each file gets its own LLM call and its own shard, so no
    over-attribution smears its nodes into a sibling's shard."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")
    monkeypatch.setattr(cfg, "ORPHAN_PASS_ENABLED", False)

    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "a.md").write_text("Alice is a person. ALICE_MARKER", encoding="utf-8")
    (inp / "b.md").write_text("Bob is a person. BOB_MARKER", encoding="utf-8")

    adapter = ScriptedAdapter()

    ctx = _make_full_ctx(tmp_path, adapter, append=False)
    run(STEPS, ctx)
    ids = _node_ids(ctx.output_dir)
    assert "person-alice" in ids, "fresh run should extract Alice from a.md"
    assert "person-bob" in ids

    (inp / "a.md").write_text("", encoding="utf-8")
    adapter.a_nodes = []  # blanked file now yields no nodes

    ctx2 = _make_full_ctx(tmp_path, adapter, append=True)
    run(STEPS, ctx2)

    ids_after = _node_ids(ctx2.output_dir)
    assert "person-alice" not in ids_after, (
        "ghost: Alice's node survived after a.md was blanked and re-appended"
    )
    assert "person-bob" in ids_after, "Bob (unchanged file) must remain"


def test_append_reextracts_modified_file_shard_batch_chunks(tmp_path, monkeypatch):
    """batch_chunks mode: the minimal shard-eviction fix guarantees the MODIFIED
    file's OWN shard is re-extracted (here, to empty after blanking).

    Known limitation (D53 over-attribution): when files share a batch, the single
    LLM result is fanned out to every member's shard, so a blanked file's nodes
    also live in its batch siblings' shards. Those siblings are unchanged and are
    not re-extracted on append, so the node can still reach the final graph via a
    sibling shard. Fully removing that requires re-extracting the whole batch — a
    larger change deliberately out of scope for this fix. This test therefore
    asserts the guarantee the fix actually makes: the changed file's own shard is
    refreshed, not that every trace is gone from the merged graph."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "batch_chunks")
    monkeypatch.setattr(cfg, "ORPHAN_PASS_ENABLED", False)

    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "a.md").write_text("Alice is a person. ALICE_MARKER", encoding="utf-8")
    (inp / "b.md").write_text("Bob is a person. BOB_MARKER", encoding="utf-8")

    adapter = ScriptedAdapter()
    ctx = _make_full_ctx(tmp_path, adapter, append=False)
    run(STEPS, ctx)

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    a_before = json.loads((shard_dir / "a.md.json").read_text())
    assert "person-alice" in {n["id"] for n in a_before["data"]["nodes"]}

    (inp / "a.md").write_text("", encoding="utf-8")
    adapter.a_nodes = []

    ctx2 = _make_full_ctx(tmp_path, adapter, append=True)
    run(STEPS, ctx2)

    # The blanked file's OWN shard was re-extracted and no longer carries Alice.
    a_after = json.loads((shard_dir / "a.md.json").read_text())
    assert "person-alice" not in {n["id"] for n in a_after["data"]["nodes"]}, (
        "modified file's own shard was not re-extracted"
    )


def test_append_blanked_file_removes_ghost_batch_chunks_per_file(tmp_path, monkeypatch):
    """batch_chunks + batch_per_file=true: a batch never mixes files, so there is
    no over-attribution to smear a file's nodes into a sibling's shard. The
    shard-eviction fix therefore removes a blanked file's nodes from the FINAL
    graph, exactly like per_file mode — closing the batch_chunks limitation for
    users who set batch_per_file: true."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "batch_chunks")
    monkeypatch.setattr(cfg, "PASS2_BATCH_PER_FILE", True)
    monkeypatch.setattr(cfg, "ORPHAN_PASS_ENABLED", False)

    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "a.md").write_text("Alice is a person. ALICE_MARKER", encoding="utf-8")
    (inp / "b.md").write_text("Bob is a person. BOB_MARKER", encoding="utf-8")

    adapter = ScriptedAdapter()
    ctx = _make_full_ctx(tmp_path, adapter, append=False)
    run(STEPS, ctx)
    ids = _node_ids(ctx.output_dir)
    assert "person-alice" in ids
    assert "person-bob" in ids

    (inp / "a.md").write_text("", encoding="utf-8")
    adapter.a_nodes = []

    ctx2 = _make_full_ctx(tmp_path, adapter, append=True)
    run(STEPS, ctx2)

    ids_after = _node_ids(ctx2.output_dir)
    assert "person-alice" not in ids_after, (
        "ghost: with batch_per_file=true there is no sibling smear, so Alice's "
        "node must be fully removed after a.md is blanked"
    )
    assert "person-bob" in ids_after, "Bob (unchanged file) must remain"
