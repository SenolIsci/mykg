"""End-to-end integration test for --append-with-grow-schema (Unit 7 / D52).

Uses a content-aware stub LLM adapter (no network). Verifies:
  (a) initial build over a small corpus;
  (b) re-run with a new doc + grow_schema where locked Pass 1 returns ONE new
      concept + ONE new property;
  (c) the grown schema keeps the locked-old entries AND gains the new ones;
  (d) old-file shards are surgically re-extracted for the affected chunks;
  (e) final nodes.jsonl/edges.jsonl include instances of the new type sourced
      from BOTH the old and the new docs;
  (f) a no-delta append collapses to a plain append (no back-fill, no full
      re-extract of old files).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import mykg.config as _cfg
from mykg.base_schema import parse_base_schema
from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS


@pytest.fixture(autouse=True)
def _per_file_prep(monkeypatch):
    """Pin per-file Pass 2 prep so shards are keyed by real filenames, isolating the
    grow-schema back-fill logic from concat/batch batching. per_file is a supported
    prep mode; the back-fill itself is concat-aware in production."""
    monkeypatch.setattr(_cfg, "PASS2_PREP_MODE", "per_file")


# --- canned schema proposals -------------------------------------------------

BASE_SCHEMA_PROPOSAL = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
        ],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []},
        ],
    }
)

# Locked Pass 1 over the NEW doc proposes one new concept (Project) + one new
# property (leads: Person -> Project). The locked merge will union these into the
# existing schema.
GROWN_SCHEMA_PROPOSAL = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
            {"type": "Project", "parent": None, "attributes": ["name"]},
        ],
        "properties": [
            {"name": "leads", "domain": "Person", "range": "Project", "attributes": []},
        ],
    }
)


def _node(nid: str, ntype: str, name: str) -> dict:
    return {
        "id": nid,
        "type": ntype,
        "confidence": 0.95,
        "attributes": {"name": {"value": name, "confidence": 0.99}},
    }


def _edge(eid: str, etype: str, frm: str, to: str) -> dict:
    return {"id": eid, "type": etype, "from": frm, "to": to, "confidence": 0.9, "attributes": {}}


class GrowSchemaMockAdapter(LLMAdapter):
    """Content-aware stub. Branches on system prompt + user text.

    grow: when True, Pass 1 (over the new doc) returns the grown proposal and
    Pass 2 over chunks mentioning Prometheus returns a Project node + leads edge.
    """

    def __init__(self, grow: bool):
        self.grow = grow
        self.pass1_calls = 0
        self.pass2_users: list[str] = []

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        # Harmonize / quality cleanup passes — return invalid JSON so the pipeline
        # keeps the merged schema unchanged (documented fallback behavior).
        if "harmonize" in system.lower() or "review a knowledge graph schema" in system.lower():
            return "not json {"

        # Pass 1 schema induction.
        if "rdfs ontology expert" in system.lower() and "extract a schema" in system.lower():
            self.pass1_calls += 1
            return GROWN_SCHEMA_PROPOSAL if self.grow else BASE_SCHEMA_PROPOSAL

        # Pass 2 instance extraction.
        if "knowledge graph extraction expert" in system.lower():
            self.pass2_users.append(user)
            nodes = []
            edges = []
            if "Alice" in user or "Acme" in user:
                nodes += [
                    _node("person-alice", "Person", "Alice"),
                    _node("organization-acme-corp", "Organization", "Acme Corp"),
                ]
                edges += [_edge("e-wa", "works_at", "person-alice", "organization-acme-corp")]
            # Prometheus appears in BOTH the old projects doc and the new doc — the
            # Project type only exists after the schema grew, so the grown-schema
            # extraction (back-fill on old + extraction on new) emits Project nodes.
            if self.grow and "Prometheus" in user:
                nodes += [
                    _node("person-alice", "Person", "Alice"),
                    _node("project-prometheus", "Project", "Prometheus"),
                ]
                edges += [_edge("e-leads", "leads", "person-alice", "project-prometheus")]
            return json.dumps({"nodes": nodes, "edges": edges})

        # Name normalization — empty map (no aliases).
        if "different surface forms" in system.lower():
            return "{}"

        # Orphan stage-2 / chunk recovery / schema-gap — no new edges, no schema gap.
        if "orphan" in system.lower():
            return "[]"

        # Default: empty extraction.
        return json.dumps({"nodes": [], "edges": []})

    def endpoint_label(self) -> str:
        return "grow-mock"


def _make_corpus(tmp_path: Path) -> Path:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "people.md").write_text("Alice works at Acme Corp.")
    # Old doc that mentions Prometheus but, at first build, only as plain text —
    # there is no Project type yet so nothing Project-shaped is extracted.
    (input_dir / "projects.md").write_text("Acme Corp is building Prometheus. Alice is involved.")
    return input_dir


def _ctx(input_dir: Path, tmp_path: Path, adapter, **kw) -> PipelineContext:
    output_dir = tmp_path / "output"
    intermediate_dir = tmp_path / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        base_schema=kw.pop("base_schema", None),
        thesaurus=None,
        review=False,
        **kw,
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().strip().splitlines() if line.strip()]


def test_grow_schema_end_to_end(tmp_path):
    input_dir = _make_corpus(tmp_path)

    # (a) initial build
    ctx = _ctx(input_dir, tmp_path, GrowSchemaMockAdapter(grow=False))
    run(STEPS, ctx)

    schema0 = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    types0 = {c["type"] for c in schema0["concepts"]}
    assert "Person" in types0 and "Organization" in types0
    assert "Project" not in types0

    # (b) add a new doc, re-run with --append-with-grow-schema (schema.ttl auto-loaded)
    (input_dir / "new_project.md").write_text("Alice leads the Prometheus project at Acme Corp.")
    base = parse_base_schema((ctx.intermediate_dir / "schema.ttl").read_text())

    grow_adapter = GrowSchemaMockAdapter(grow=True)
    ctx2 = _ctx(
        input_dir,
        tmp_path,
        grow_adapter,
        base_schema=base,
        append=True,
        grow_schema=True,
    )
    run(STEPS, ctx2)

    # (c) grown schema keeps locked-old + gains new
    schema1 = json.loads((ctx2.intermediate_dir / "schema.json").read_text())
    types1 = {c["type"] for c in schema1["concepts"]}
    props1 = {p["name"] for p in schema1["properties"]}
    assert {"Person", "Organization", "Project"} <= types1, types1
    assert {"works_at", "leads"} <= props1, props1

    # schema_history records the additions
    history = sorted((ctx2.intermediate_dir / "schema_history").glob("*.json"))
    added_concepts = set()
    added_props = set()
    for f in history:
        d = json.loads(f.read_text())
        added_concepts.update(d.get("concepts_added", []))
        added_props.update(d.get("properties_added", []))
    assert "Project" in added_concepts
    assert "leads" in added_props

    # (d) the OLD projects.md shard was surgically re-extracted (now carries a Project)
    old_shard = ctx2.intermediate_dir / "raw_extractions_shards" / "projects.md.json"
    assert old_shard.exists()
    old_data = json.loads(old_shard.read_text())["data"]
    old_types = {n["type"] for n in old_data["nodes"]}
    assert "Project" in old_types, f"back-fill did not add Project to old shard: {old_types}"

    # (e) final outputs include Project instances from BOTH old and new docs
    nodes = _read_jsonl(ctx2.output_dir / "nodes.jsonl")
    project_nodes = [n for n in nodes if n["type"] == "Project"]
    assert project_nodes, "no Project node in final nodes.jsonl"
    project_sources = set()
    for n in project_nodes:
        project_sources.update(n.get("source_files", []))
    assert "projects.md" in project_sources, project_sources  # old doc (back-filled)
    assert "new_project.md" in project_sources, project_sources  # new doc

    edges = _read_jsonl(ctx2.output_dir / "edges.jsonl")
    assert any(e["type"] == "leads" for e in edges), "no 'leads' edge in final edges.jsonl"


def test_grow_schema_no_delta_collapses_to_plain_append(tmp_path):
    """When the locked Pass 1 proposes nothing new, grow_schema must NOT re-extract old
    files (no back-fill) and the schema is unchanged."""
    input_dir = _make_corpus(tmp_path)

    ctx = _ctx(input_dir, tmp_path, GrowSchemaMockAdapter(grow=False))
    run(STEPS, ctx)
    schema0 = json.loads((ctx.intermediate_dir / "schema.json").read_text())

    # Capture old shard contents before the append re-run.
    old_shard = ctx.intermediate_dir / "raw_extractions_shards" / "projects.md.json"
    before = old_shard.read_text()

    # New doc, but the locked Pass 1 (grow=False) proposes only already-locked entries
    # → empty delta.
    (input_dir / "extra.md").write_text("Bob works at Acme Corp.")
    base = parse_base_schema((ctx.intermediate_dir / "schema.ttl").read_text())

    no_delta_adapter = GrowSchemaMockAdapter(grow=False)
    ctx2 = _ctx(
        input_dir,
        tmp_path,
        no_delta_adapter,
        base_schema=base,
        append=True,
        grow_schema=True,
    )
    run(STEPS, ctx2)

    schema1 = json.loads((ctx2.intermediate_dir / "schema.json").read_text())
    assert {c["type"] for c in schema1["concepts"]} == {c["type"] for c in schema0["concepts"]}, (
        "schema must be unchanged when no new concepts are proposed"
    )

    # Old shard for projects.md was NOT re-extracted (back-fill skipped on empty delta).
    after = old_shard.read_text()
    assert before == after, "old shard must be untouched when the schema did not grow"

    # The new file was still extracted.
    extra_shard = ctx2.intermediate_dir / "raw_extractions_shards" / "extra.md.json"
    assert extra_shard.exists()


if __name__ == "__main__":
    pytest.main([str(Path(__file__)), "-v"])
