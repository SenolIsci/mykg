"""Corner cases created by the D58 --append/--sync split.

Each test here pins a failure mode that would otherwise be silent: a lost edit,
a wasted conversion, an undetectable deletion, or a full-corpus re-extraction.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from mykg.orchestrator import PipelineContext
from mykg.steps.step_ingest import _run_append_ingest


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _session(tmp_path: Path, files: dict[str, str], *, on_disk: dict[str, str] | None = None):
    """Build input/ + a manifest that claims `files` were already extracted."""
    inp = tmp_path / "input"
    inter = tmp_path / "intermediate"
    inp.mkdir(parents=True, exist_ok=True)
    inter.mkdir(parents=True, exist_ok=True)
    for name, content in (on_disk if on_disk is not None else files).items():
        (inp / name).write_text(content, encoding="utf-8")
    manifest = {
        name: {"content": c, "sha256": _sha(c), "token_count": 1} for name, c in files.items()
    }
    (inter / "file_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (inter / "raw_extractions.json").write_text(
        json.dumps({name: {"nodes": [], "edges": []} for name in files}), encoding="utf-8"
    )
    return inp, inter


def _ctx(inp: Path, inter: Path, *, sync: bool) -> PipelineContext:
    return PipelineContext(
        input_dir=inp,
        output_dir=inter,
        intermediate_dir=inter,
        adapter=None,
        append=True,
        sync=sync,
    )


# ---------------------------------------------------------------------------
# The manifest-freeze guard — the most dangerous corner case
# ---------------------------------------------------------------------------


def test_plain_append_does_not_advance_modified_sha(tmp_path):
    """Without --sync the WHOLE manifest entry stays frozen, not just the hash.

    Advancing sha256 alone would make the next run see no change and lose the
    edit permanently. Refreshing `content` while freezing sha256 is just as bad:
    grow-schema Pass 1, build_chunk_texts and the MCP server all read `content`
    without re-hashing, so chunk keys would resolve against text that never
    produced the stored nodes.
    """
    inp, inter = _session(tmp_path, {"notes.md": "original"})
    (inp / "notes.md").write_text("EDITED", encoding="utf-8")

    _run_append_ingest(_ctx(inp, inter, sync=False))

    entry = json.loads((inter / "file_manifest.json").read_text())["notes.md"]
    assert entry["sha256"] == _sha("original")
    assert entry["content"] == "original"


def test_modified_file_reports_again_until_synced(tmp_path):
    """A frozen entry means the edit keeps re-reporting rather than being lost."""
    inp, inter = _session(tmp_path, {"notes.md": "original"})
    (inp / "notes.md").write_text("EDITED", encoding="utf-8")

    for _ in range(2):
        ctx = _ctx(inp, inter, sync=False)
        _run_append_ingest(ctx)
        assert ctx.append_new_files == set()

    ctx = _ctx(inp, inter, sync=True)
    _run_append_ingest(ctx)
    assert ctx.append_new_files == {"notes.md"}
    assert json.loads((inter / "file_manifest.json").read_text())["notes.md"]["content"] == "EDITED"


# ---------------------------------------------------------------------------
# Deletion detection
# ---------------------------------------------------------------------------


def test_deletion_detected_but_not_acted_on_without_sync(tmp_path):
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"}, on_disk={"b.md": "B"})

    ctx = _ctx(inp, inter, sync=False)
    _run_append_ingest(ctx)

    assert not ctx.deleted_files
    assert "a.md" in json.loads((inter / "file_manifest.json").read_text())


def test_deletion_pops_manifest_entry_under_sync(tmp_path):
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"}, on_disk={"b.md": "B"})

    ctx = _ctx(inp, inter, sync=True)
    _run_append_ingest(ctx)

    assert ctx.deleted_files == {"a.md"}
    assert "a.md" not in json.loads((inter / "file_manifest.json").read_text())


def test_changed_and_deleted_sets_are_disjoint(tmp_path):
    """A file cannot be both: `deleted` comes only from manifest keys absent on disk."""
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"}, on_disk={"b.md": "B-EDITED"})

    ctx = _ctx(inp, inter, sync=True)
    _run_append_ingest(ctx)

    assert ctx.deleted_files == {"a.md"}
    assert ctx.append_new_files == {"b.md"}
    assert not (ctx.append_new_files & ctx.deleted_files)


def test_deleted_then_restored_file_is_treated_as_new(tmp_path):
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"}, on_disk={"b.md": "B"})
    _run_append_ingest(_ctx(inp, inter, sync=True))

    (inp / "a.md").write_text("A again", encoding="utf-8")
    ctx = _ctx(inp, inter, sync=True)
    _run_append_ingest(ctx)

    assert ctx.append_new_files == {"a.md"}
    assert not ctx.deleted_files


# ---------------------------------------------------------------------------
# The unextracted-recovery pass must not re-extract the corpus after a restart
# ---------------------------------------------------------------------------


def test_missing_raw_extractions_falls_back_to_shards(tmp_path):
    """A schema restart unlinks raw_extractions.json but PRESERVES the shards.

    Treating absence as "extract everything" would re-run the whole corpus at
    full LLM cost on the second pass of a restart.
    """
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"})
    (inter / "raw_extractions.json").unlink()
    shards = inter / "raw_extractions_shards"
    shards.mkdir()
    for name in ("a.md", "b.md"):
        (shards / f"{name}.json").write_text(
            json.dumps({"_fname": name, "data": {}}), encoding="utf-8"
        )

    ctx = _ctx(inp, inter, sync=False)
    _run_append_ingest(ctx)

    assert ctx.append_new_files == set()


def test_no_extraction_record_at_all_still_re_extracts(tmp_path):
    """With neither raw_extractions.json nor shards, nothing was extracted."""
    inp, inter = _session(tmp_path, {"a.md": "A", "b.md": "B"})
    (inter / "raw_extractions.json").unlink()

    ctx = _ctx(inp, inter, sync=False)
    _run_append_ingest(ctx)

    assert ctx.append_new_files == {"a.md", "b.md"}
