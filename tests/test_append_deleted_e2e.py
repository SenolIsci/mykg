"""End-to-end regression tests for --append --sync removing DELETED files.

Drives the real pipeline (``orchestrator.run(STEPS, ctx)``) twice with a
step-routing scripted adapter, mirroring ``test_append_modified_e2e.py``:

  1. Fresh run over two files, each contributing a unique node plus a SHARED
     node so recomputation is observable.
  2. One file is deleted from disk, then re-run with ``append=True, sync=True``.

Before D58 the deleted file's manifest entry, shard and nodes all survived.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS

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
# Emitted by BOTH files, with a different confidence from each, so a merged
# node's confidence proves the assembler recomputed rather than filtered.
_SHARED_FROM_A = {
    "id": "organization-acme",
    "type": "Organization",
    "attributes": {"name": {"value": "Acme", "confidence": 0.6}},
}
_SHARED_FROM_B = {
    "id": "organization-acme",
    "type": "Organization",
    "attributes": {"name": {"value": "Acme", "confidence": 1.0}},
}

_SCHEMA_JSON = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
)


class ScriptedAdapter(LLMAdapter):
    """Routes each pipeline LLM call by context_label to a canned response."""

    def __init__(self) -> None:
        self.pass1_calls = 0

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        label = context_label or ""
        if label.startswith("pass1 batch"):
            self.pass1_calls += 1
            return _SCHEMA_JSON
        if label in ("schema_harmonize", "schema_quality_review"):
            return _SCHEMA_JSON
        if label.startswith("pass2"):
            nodes: list[dict] = []
            if "ALICE_MARKER" in user:
                nodes.extend([_A_NODE, _SHARED_FROM_A])
            if "BOB_MARKER" in user:
                nodes.extend([_B_NODE, _SHARED_FROM_B])
            return json.dumps({"nodes": nodes, "edges": []})
        return "{}"

    def endpoint_label(self) -> str:
        return "scripted"


def _make_full_ctx(tmp_path: Path, adapter: LLMAdapter, **kwargs) -> PipelineContext:
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
        **kwargs,
    )


def _nodes(output_dir: Path) -> dict[str, dict]:
    path = output_dir / "nodes.jsonl"
    out: dict[str, dict] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                node = json.loads(line)
                out[node["id"]] = node
    return out


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")
    monkeypatch.setattr(cfg, "ORPHAN_PASS_ENABLED", False)
    inp = tmp_path / "input"
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "a.md").write_text("Alice works at Acme. ALICE_MARKER", encoding="utf-8")
    (inp / "b.md").write_text("Bob works at Acme. BOB_MARKER", encoding="utf-8")
    return tmp_path, inp


def test_deleted_file_removes_its_nodes(corpus):
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    ctx = _make_full_ctx(tmp_path, adapter)
    run(STEPS, ctx)
    assert "person-alice" in _nodes(ctx.output_dir)

    (inp / "a.md").unlink()
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx2)

    after = _nodes(ctx2.output_dir)
    assert "person-alice" not in after, "deleted file's node survived as a ghost"
    assert "person-bob" in after, "surviving file's node must remain"


def test_shared_node_is_recomputed_not_filtered(corpus):
    """The assertion that proves recompute-don't-filter.

    A node contributed by both files must come back with only the survivor's
    source and the survivor's confidence. Stripping source_files in place would
    leave the deleted file's 0.6 still averaged into the value.
    """
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    ctx = _make_full_ctx(tmp_path, adapter)
    run(STEPS, ctx)
    assert set(_nodes(ctx.output_dir)["organization-acme"]["source_files"]) == {"a.md", "b.md"}

    (inp / "a.md").unlink()
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx2)

    acme = _nodes(ctx2.output_dir)["organization-acme"]
    assert set(acme["source_files"]) == {"b.md"}
    assert acme["attributes"]["name"]["confidence"] == 1.0


def test_deletion_evicts_shard_and_manifest_entry(corpus):
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    run(STEPS, _make_full_ctx(tmp_path, adapter))

    (inp / "a.md").unlink()
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx2)

    inter = ctx2.intermediate_dir
    assert not (inter / "raw_extractions_shards" / "a.md.json").exists()
    assert "a.md" not in json.loads((inter / "raw_extractions.json").read_text())
    assert "a.md" not in json.loads((inter / "file_manifest.json").read_text())


def test_deletion_survives_a_second_sync_run(corpus):
    """Without the shard unlink this passes run 1 and fails run 2.

    The shard glob rebuilds existing_raw with no manifest cross-check, so a
    surviving shard silently regrows the ghost on the next run.
    """
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    run(STEPS, _make_full_ctx(tmp_path, adapter))
    (inp / "a.md").unlink()
    run(STEPS, _make_full_ctx(tmp_path, adapter, append=True, sync=True))

    ctx3 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx3)

    assert "person-alice" not in _nodes(ctx3.output_dir)


def test_plain_append_leaves_the_graph_untouched(corpus):
    """--append is warn-only: it must not delete nodes OR pay a re-assemble."""
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    ctx = _make_full_ctx(tmp_path, adapter)
    run(STEPS, ctx)
    before = _nodes(ctx.output_dir)

    (inp / "a.md").unlink()
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True)
    run(STEPS, ctx2)

    assert _nodes(ctx2.output_dir).keys() == before.keys()


def test_all_files_deleted_yields_an_empty_graph(corpus):
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    run(STEPS, _make_full_ctx(tmp_path, adapter))

    for name in ("a.md", "b.md"):
        (inp / name).unlink()
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx2)

    assert _nodes(ctx2.output_dir) == {}
    assert json.loads((ctx2.intermediate_dir / "file_manifest.json").read_text()) == {}


def test_delete_and_modify_in_the_same_run(corpus):
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    run(STEPS, _make_full_ctx(tmp_path, adapter))

    (inp / "a.md").unlink()
    (inp / "b.md").write_text("Bob moved on. BOB_MARKER extra", encoding="utf-8")
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True)
    run(STEPS, ctx2)

    after = _nodes(ctx2.output_dir)
    assert "person-alice" not in after
    assert "person-bob" in after


def test_deletions_only_grow_schema_makes_no_pass1_calls(corpus):
    """A deletion cannot add a concept, so the locked Pass 1 must be skipped.

    Before D58 this fell through to a recovery branch that re-chunked the ENTIRE
    manifest and dispatched a full-corpus Pass 1.
    """
    tmp_path, inp = corpus
    adapter = ScriptedAdapter()
    run(STEPS, _make_full_ctx(tmp_path, adapter))

    (inp / "a.md").unlink()
    adapter.pass1_calls = 0
    ctx2 = _make_full_ctx(tmp_path, adapter, append=True, sync=True, grow_schema=True)
    run(STEPS, ctx2)

    assert adapter.pass1_calls == 0
    assert "person-alice" not in _nodes(ctx2.output_dir)
