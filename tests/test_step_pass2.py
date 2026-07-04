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


def test_run_pass2_step_batch_chunks_mode_persists_failed_batch_shard(tmp_path, monkeypatch):
    """A batch whose LLM response never parses as valid JSON writes a
    pass2_raw_batches/<index>.json shard with status "failed" and an error
    message — not silently dropped."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "batch_chunks")
    monkeypatch.setattr(cfg, "PASS2_BATCH_RETRY_MAX", 0)

    ctx = _make_ctx(tmp_path)
    ctx.adapter = MockAdapter(response="not valid json {{{")
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice works at Acme."})
    )

    run_pass2_step(ctx)

    shard_dir = ctx.intermediate_dir / "pass2_raw_batches"
    shards = list(shard_dir.glob("*.json"))
    assert len(shards) == 1
    entry = json.loads(shards[0].read_text())
    assert entry["status"] == "failed"
    assert "error" in entry
    assert entry["source_files"] == ["doc.md"]


def test_load_manifest_with_dict_entry(tmp_path):
    """Manifest entries may be dicts (with content key) or bare strings."""
    ctx = _make_ctx(tmp_path)
    manifest = {"doc.md": {"content": "x", "sha256": "y"}}
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest))
    out = _load_manifest(ctx)
    assert out == manifest


def _concat_ctx(tmp_path: Path, monkeypatch, response=None) -> PipelineContext:
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "concat")
    ctx = _make_ctx(tmp_path)
    if response is not None:
        ctx.adapter = MockAdapter(response)
    _write_schema(ctx)
    (ctx.intermediate_dir / "flattened_schema.json").write_text(
        json.dumps({"Person": ["name"], "Organization": ["name"]})
    )
    return ctx


def test_concat_shards_keyed_by_real_files(tmp_path, monkeypatch):
    """Concat persists shards keyed by REAL filenames, not virtual concat_batch_* names."""
    ctx = _concat_ctx(
        tmp_path,
        monkeypatch,
        response='{"nodes": [{"id": "person-x", "type": "Person", '
        '"attributes": {"name": {"value": "X", "confidence": 1.0}}}], "edges": []}',
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"a.md": "Alice.", "b.md": "Bob."})
    )

    run_pass2_step(ctx)

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert set(raw.keys()) == {"a.md", "b.md"}
    assert not any(k.startswith("concat_batch_") for k in raw)

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    shard_files = {p.name for p in shard_dir.glob("*.json")}
    assert shard_files == {"a.md.json", "b.md.json"}
    assert not any(n.startswith("concat_batch_") for n in shard_files)
    # Concat keeps the original whole-file-packing + window-sized-call path; it does
    # not persist a batch/concat map (resumability keys on real filenames now).
    assert not (ctx.intermediate_dir / "pass2_concat_map.json").exists()


def test_concat_fans_out_to_member_shards(tmp_path, monkeypatch):
    """A multi-file concat batch writes one real-keyed shard per member file, each
    carrying the batch result (assembler dedup collapses the duplication later)."""
    ctx = _concat_ctx(
        tmp_path,
        monkeypatch,
        response='{"nodes": [{"id": "person-x", "type": "Person", '
        '"attributes": {"name": {"value": "X", "confidence": 1.0}}}], "edges": []}',
    )
    # Two tiny same-dir files → one virtual batch → fan-out to two real shards.
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"dir/a.md": "Alice.", "dir/b.md": "Bob."})
    )

    run_pass2_step(ctx)

    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    names = {p.name for p in shard_dir.glob("*.json")}
    assert names == {"dir_a.md.json", "dir_b.md.json"}
    for n in names:
        data = json.loads((shard_dir / n).read_text())
        assert data["_fname"].startswith("dir/")
        assert len(data["data"]["nodes"]) == 1  # the batch result, fanned out to each


def test_concat_append_detects_only_changed_file(tmp_path, monkeypatch):
    """Real-file-keyed shards make append skip unchanged files and extract only the new one."""
    ctx = _concat_ctx(tmp_path, monkeypatch, response='{"nodes": [], "edges": []}')
    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()
    for n in ("a.md", "b.md"):
        (shard_dir / f"{n}.json").write_text(
            json.dumps({"_fname": n, "data": {"nodes": [], "edges": []}})
        )
        (chunk_shard_dir / f"{n}.json").write_text(json.dumps({"_fname": n, "data": {}}))
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"a.md": "A", "b.md": "B", "c.md": "C"})
    )
    ctx.append = True
    ctx.append_new_files = {"c.md"}

    run_pass2_step(ctx)

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert set(raw.keys()) == {"a.md", "b.md", "c.md"}
    assert not any(k.startswith("concat_batch_") for k in raw)


def test_concat_legacy_virtual_shards_migrated(tmp_path, monkeypatch):
    """A pre-existing concat_batch_* shard is cleared and the session rebuilds real-keyed."""
    ctx = _concat_ctx(tmp_path, monkeypatch, response='{"nodes": [], "edges": []}')
    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()
    # Legacy virtual-batch shard from a pre-refactor concat run.
    (shard_dir / "concat_batch_0000.md.json").write_text(
        json.dumps({"_fname": "concat_batch_0000.md", "data": {"nodes": [{"id": "stale"}], "edges": []}})
    )
    (ctx.intermediate_dir / "pass2_concat_map.json").write_text("{}")
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"a.md": "Alice."})
    )

    run_pass2_step(ctx)

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert set(raw.keys()) == {"a.md"}
    assert "stale" not in json.dumps(raw)
    assert not any(p.name.startswith("concat_batch_") for p in shard_dir.glob("*.json"))
