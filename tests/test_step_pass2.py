"""Tests for mykg.steps.step_pass2 orchestration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext
from mykg.steps.step_pass2 import _load_manifest, run_pass2_step, run_schema_flatten


class MockAdapter(LLMAdapter):
    def __init__(self, response: str = '{"nodes": [], "edges": []}'):
        self._response = response

    def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
        return self._response

    def endpoint_label(self) -> str:
        return "mock"


def _make_ctx(tmp_path: Path) -> PipelineContext:
    out = tmp_path / "output"
    inter = tmp_path / "intermediate"
    inp = tmp_path / "input"
    for p in (out, inter, inp):
        p.mkdir(parents=True)
    return PipelineContext(
        input_dir=inp,
        output_dir=out,
        intermediate_dir=inter,
        adapter=MockAdapter(),
        base_schema=None,
        thesaurus=None,
        review=False,
    )


SCHEMA = {
    "concepts": [
        {"type": "Person", "parent": None, "attributes": ["name"]},
        {"type": "Organization", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
    ],
}


def _write_schema(ctx: PipelineContext) -> None:
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))


def test_run_schema_flatten_writes_flattened(tmp_path):
    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    run_schema_flatten(ctx)
    flat_path = ctx.intermediate_dir / "flattened_schema.json"
    assert flat_path.exists()
    flat = json.loads(flat_path.read_text())
    assert "Person" in flat
    assert "Organization" in flat


def test_load_manifest_from_ctx(tmp_path):
    ctx = _make_ctx(tmp_path)
    ctx.file_contents = {"doc.md": "content"}
    out = _load_manifest(ctx)
    assert out == {"doc.md": "content"}


def test_load_manifest_from_file(tmp_path):
    ctx = _make_ctx(tmp_path)
    manifest = {"doc.md": "content"}
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest))
    out = _load_manifest(ctx)
    assert out == manifest


def test_load_manifest_missing(tmp_path):
    ctx = _make_ctx(tmp_path)
    with pytest.raises(RuntimeError, match="file_manifest.json not found"):
        _load_manifest(ctx)


def test_run_pass2_step_fresh_extraction(tmp_path, monkeypatch):
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice works at Acme."})
    )

    run_pass2_step(ctx)

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "doc.md" in raw


def test_run_pass2_step_skips_shards_already_present(tmp_path, monkeypatch):
    """With existing shards, pass2 skips those files."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "x", "other.md": "y"})
    )

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()

    # Pre-existing shard for doc.md
    (shard_dir / "doc.md.json").write_text(
        json.dumps({"_fname": "doc.md", "data": {"nodes": [{"id": "p-1", "type": "Person"}], "edges": []}})
    )
    (chunk_shard_dir / "doc.md.json").write_text(
        json.dumps({"_fname": "doc.md", "data": {"1": ["p-1"]}})
    )

    run_pass2_step(ctx)
    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "doc.md" in raw
    assert "other.md" in raw  # newly extracted


def test_run_pass2_step_surgical_reextract(tmp_path):
    """When schema_hints + existing_raw both present, surgical re-extract runs."""
    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )

    # Required: file_manifest.json + existing shards
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice works at Acme."})
    )
    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()
    (shard_dir / "doc.md.json").write_text(
        json.dumps({"_fname": "doc.md", "data": {"nodes": [], "edges": []}})
    )
    (chunk_shard_dir / "doc.md.json").write_text(json.dumps({"_fname": "doc.md", "data": {}}))

    ctx.schema_hints = [
        {
            "orphan_id": "person-x",
            "orphan_name": "X",
            "orphan_type": "Person",
            "new_properties": ["works_at"],
            "shared_chunks": ["doc.md::1"],
        }
    ]

    run_pass2_step(ctx)
    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "doc.md" in raw


def test_run_pass2_step_no_files_to_extract(tmp_path):
    """When all files are skipped via shards, the step is a no-op write."""
    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps({"doc.md": "x"}))

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()
    (shard_dir / "doc.md.json").write_text(
        json.dumps({"_fname": "doc.md", "data": {"nodes": [], "edges": []}})
    )
    (chunk_shard_dir / "doc.md.json").write_text(json.dumps({"_fname": "doc.md", "data": {}}))

    run_pass2_step(ctx)
    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "doc.md" in raw


def test_run_pass2_step_batch_chunks_mode(tmp_path, monkeypatch):
    """When PASS2_PREP_MODE == 'batch_chunks', uses run_pass2_batched."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "batch_chunks")

    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice works at Acme."})
    )

    run_pass2_step(ctx)
    batch_map_path = ctx.intermediate_dir / "pass2_batch_map.json"
    assert batch_map_path.exists()


def test_load_manifest_with_dict_entry(tmp_path):
    """Manifest entries may be dicts (with content key) or bare strings."""
    ctx = _make_ctx(tmp_path)
    manifest = {"doc.md": {"content": "x", "sha256": "y"}}
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest))
    out = _load_manifest(ctx)
    assert out == manifest


def test_run_pass2_step_concat_mode_creates_batches(tmp_path, monkeypatch):
    """When PREP_MODE == 'concat', pass2_concat_map.json is written."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "concat")

    ctx = _make_ctx(tmp_path)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice. " * 50, "doc2.md": "Bob. " * 50})
    )

    run_pass2_step(ctx)
    assert (ctx.intermediate_dir / "pass2_concat_map.json").exists()
