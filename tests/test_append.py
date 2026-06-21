"""Tests for the append mode feature (Unit 5).

Covers: SHA256 helper, manifest migration, new/modified/unchanged file detection,
orchestrator skip logic, error on missing schema, nothing-to-append early exit,
and CLI mutual-exclusion of --append + --from-step.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from mykg.cli import cli
from mykg.orchestrator import PipelineContext, Step, run
from mykg.steps.step_ingest import _load_manifest, _sha256, run_ingest

# ---------------------------------------------------------------------------
# 1. SHA256 helper
# ---------------------------------------------------------------------------


def test_sha256_returns_known_hex():
    """_sha256('hello') must return the standard SHA-256 hex digest of b'hello'."""
    expected = hashlib.sha256(b"hello").hexdigest()
    assert _sha256("hello") == expected


def test_sha256_is_64_hex_chars():
    result = _sha256("some content")
    assert len(result) == 64
    assert all(c in "0123456789abcdef" for c in result)


# ---------------------------------------------------------------------------
# 2. Manifest format migration
# ---------------------------------------------------------------------------


def test_load_manifest_migrates_old_string_format(tmp_path):
    """Old manifest with string values must be migrated to {'content': ..., 'sha256': ...}."""
    content = "hello world"
    old_manifest = {"file.md": content}
    manifest_path = tmp_path / "file_manifest.json"
    manifest_path.write_text(json.dumps(old_manifest))

    result = _load_manifest(manifest_path)

    # Value must now be a dict
    assert isinstance(result["file.md"], dict)
    assert result["file.md"]["content"] == content
    assert result["file.md"]["sha256"] == _sha256(content)


def test_load_manifest_writes_migrated_manifest_to_disk(tmp_path):
    """After migration the updated manifest must be written back to disk."""
    content = "test content"
    old_manifest = {"note.md": content}
    manifest_path = tmp_path / "file_manifest.json"
    manifest_path.write_text(json.dumps(old_manifest))

    _load_manifest(manifest_path)

    on_disk = json.loads(manifest_path.read_text())
    assert isinstance(on_disk["note.md"], dict)
    assert on_disk["note.md"]["sha256"] == _sha256(content)


def test_load_manifest_does_not_re_migrate_new_format(tmp_path):
    """New-format manifest must be loaded without modification."""
    content = "existing content"
    sha = _sha256(content)
    new_manifest = {"doc.md": {"content": content, "sha256": sha}}
    manifest_path = tmp_path / "file_manifest.json"
    manifest_path.write_text(json.dumps(new_manifest))

    result = _load_manifest(manifest_path)

    assert result["doc.md"]["sha256"] == sha
    assert result["doc.md"]["content"] == content


def test_ingest_append_migrates_old_format_on_disk(tmp_path):
    """run_ingest in append mode must migrate an old-format manifest if present."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    intermediate_dir = tmp_path / "intermediate"
    intermediate_dir.mkdir()

    content = "original content"
    (input_dir / "file.md").write_text(content)

    # Write old-format manifest
    old_manifest = {"file.md": content}
    (intermediate_dir / "file_manifest.json").write_text(json.dumps(old_manifest))

    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate_dir,
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
        append=True,
    )

    run_ingest(ctx)

    written = json.loads((intermediate_dir / "file_manifest.json").read_text())
    assert isinstance(written["file.md"], dict), "Manifest must be migrated to dict format"
    assert written["file.md"]["sha256"] == _sha256(content)


# ---------------------------------------------------------------------------
# 3. Append ingest: new file detection
# ---------------------------------------------------------------------------


def _make_append_ctx(tmp_path, manifest_data: dict) -> PipelineContext:
    """Helper: create directories, write manifest and raw_extractions, return a PipelineContext."""
    input_dir = tmp_path / "input"
    input_dir.mkdir(exist_ok=True)
    intermediate_dir = tmp_path / "intermediate"
    intermediate_dir.mkdir(exist_ok=True)
    (intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest_data))
    # Simulate that all manifest files were already extracted in a prior run so
    # the unextracted-files check in _run_append_ingest doesn't mark them changed.
    raw = {fname: {"nodes": [], "edges": []} for fname in manifest_data}
    (intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    return PipelineContext(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate_dir,
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
        append=True,
    )


def test_append_ingest_detects_new_file(tmp_path):
    """A file present in input_dir but absent from the manifest must appear in append_new_files."""
    existing_content = "old file content"
    existing_sha = _sha256(existing_content)
    manifest = {"existing.md": {"content": existing_content, "sha256": existing_sha}}

    ctx = _make_append_ctx(tmp_path, manifest)
    (ctx.input_dir / "existing.md").write_text(existing_content)
    (ctx.input_dir / "new_file.md").write_text("brand new content")

    run_ingest(ctx)

    assert "new_file.md" in ctx.append_new_files
    assert "existing.md" not in ctx.append_new_files


# ---------------------------------------------------------------------------
# 4. Append ingest: modified file detection
# ---------------------------------------------------------------------------


def test_append_ingest_detects_modified_file(tmp_path):
    """A file whose content changed since last run must appear in append_new_files."""
    original_content = "original"
    original_sha = _sha256(original_content)
    manifest = {"notes.md": {"content": original_content, "sha256": original_sha}}

    ctx = _make_append_ctx(tmp_path, manifest)
    # Write a different version of the file
    (ctx.input_dir / "notes.md").write_text("completely different content")

    run_ingest(ctx)

    assert "notes.md" in ctx.append_new_files


# ---------------------------------------------------------------------------
# 5. Append ingest: nothing to append
# ---------------------------------------------------------------------------


def test_append_ingest_nothing_to_do(tmp_path):
    """When all files in input_dir match the manifest exactly, append_new_files must be empty."""
    content_a = "content of a"
    content_b = "content of b"
    manifest = {
        "a.md": {"content": content_a, "sha256": _sha256(content_a)},
        "b.md": {"content": content_b, "sha256": _sha256(content_b)},
    }

    ctx = _make_append_ctx(tmp_path, manifest)
    (ctx.input_dir / "a.md").write_text(content_a)
    (ctx.input_dir / "b.md").write_text(content_b)

    run_ingest(ctx)

    assert ctx.append_new_files == set()


# ---------------------------------------------------------------------------
# 6. Orchestrator skip logic for append mode
# ---------------------------------------------------------------------------


def _make_ctx(tmp_path: Path, append: bool = False) -> PipelineContext:
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
        append=append,
    )
    (tmp_path / "intermediate").mkdir(parents=True, exist_ok=True)
    (tmp_path / "output").mkdir(parents=True, exist_ok=True)
    return ctx


def test_orchestrator_skips_pass1_when_output_exists(tmp_path):
    """In append mode pass1/schema_validate/human_review are skipped because their
    outputs already exist (the _is_done check in the orchestrator handles this)."""
    ctx = _make_ctx(tmp_path, append=True)

    # Pre-populate pass1 and schema outputs so _is_done returns True for them
    (ctx.intermediate_dir / "schema.json").write_text('{"concepts":[],"properties":[]}')
    (ctx.intermediate_dir / "schema.ttl").write_text("")
    (ctx.intermediate_dir / "schema_validate.done").write_text("done")
    (ctx.intermediate_dir / "schema_approved.flag").write_text("auto-approved")
    (ctx.intermediate_dir / "flattened_schema.json").write_text("{}")

    executed = []

    def pass1_fn(c):
        executed.append("pass1")

    def schema_validate_fn(c):
        executed.append("schema_validate")

    def human_review_fn(c):
        executed.append("human_review")

    def pass2_fn(c):
        executed.append("pass2")
        (c.intermediate_dir / "raw_extractions.json").write_text("{}")
        (c.intermediate_dir / "chunk_node_index.json").write_text("{}")

    steps = [
        Step(name="pass1", fn=pass1_fn, outputs=["schema.json", "schema.ttl"], is_llm_step=True),
        Step(name="schema_validate", fn=schema_validate_fn, outputs=["schema_validate.done"]),
        Step(name="human_review", fn=human_review_fn, outputs=["schema_approved.flag"]),
        Step(name="schema_flatten", fn=lambda c: None, outputs=["flattened_schema.json"]),
        Step(name="pass2", fn=pass2_fn, outputs=["raw_extractions.json", "chunk_node_index.json"]),
    ]

    run(steps, ctx)

    # pass1, schema_validate, human_review must NOT have run (their outputs existed)
    assert "pass1" not in executed, "pass1 must be skipped in append mode when outputs exist"
    assert "schema_validate" not in executed
    assert "human_review" not in executed
    # pass2 must have run
    assert "pass2" in executed


def test_orchestrator_grow_schema_forces_pass1_and_schema_steps(tmp_path):
    """In --append --grow-schema mode pass1/schema_validate/schema_flatten must RUN
    again even though their outputs already exist (D52), while human_review stays
    skipped (no --review)."""
    ctx = _make_ctx(tmp_path, append=True)
    ctx.grow_schema = True

    # Pre-populate all schema outputs so plain append would skip them.
    (ctx.intermediate_dir / "schema.json").write_text('{"concepts":[],"properties":[]}')
    (ctx.intermediate_dir / "schema.ttl").write_text("")
    (ctx.intermediate_dir / "schema_validate.done").write_text("done")
    (ctx.intermediate_dir / "schema_approved.flag").write_text("auto-approved")
    (ctx.intermediate_dir / "flattened_schema.json").write_text("{}")

    executed = []

    def ingest_fn(c):
        executed.append("ingest")
        c.append_new_files = {"new.md"}  # simulate a detected new file

    def make(name):
        def _fn(c):
            executed.append(name)

        return _fn

    def pass2_fn(c):
        executed.append("pass2")
        (c.intermediate_dir / "raw_extractions.json").write_text("{}")
        (c.intermediate_dir / "chunk_node_index.json").write_text("{}")

    steps = [
        Step(name="ingest", fn=ingest_fn, outputs=["file_manifest.json"]),
        Step(
            name="pass1", fn=make("pass1"), outputs=["schema.json", "schema.ttl"], is_llm_step=True
        ),
        Step(name="schema_validate", fn=make("schema_validate"), outputs=["schema_validate.done"]),
        Step(name="human_review", fn=make("human_review"), outputs=["schema_approved.flag"]),
        Step(name="schema_flatten", fn=make("schema_flatten"), outputs=["flattened_schema.json"]),
        Step(name="pass2", fn=pass2_fn, outputs=["raw_extractions.json", "chunk_node_index.json"]),
    ]

    run(steps, ctx)

    assert "pass1" in executed, "pass1 must be force-run in grow_schema mode"
    assert "schema_validate" in executed, "schema_validate must be force-run in grow_schema mode"
    assert "schema_flatten" in executed, "schema_flatten must be force-run in grow_schema mode"
    assert "human_review" not in executed, "human_review stays skipped without --review"
    assert "pass2" in executed


# ---------------------------------------------------------------------------
# 7. Orchestrator: missing schema error
# ---------------------------------------------------------------------------


def test_append_ingest_raises_on_missing_manifest(tmp_path):
    """run_ingest with append=True and no file_manifest.json must raise RuntimeError."""
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    intermediate_dir = tmp_path / "intermediate"
    intermediate_dir.mkdir()
    # Intentionally do NOT write file_manifest.json

    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate_dir,
        adapter=None,
        base_schema=None,
        thesaurus=None,
        review=False,
        append=True,
    )

    with pytest.raises(RuntimeError, match="Run without --append first"):
        run_ingest(ctx)


# ---------------------------------------------------------------------------
# 8. Orchestrator: nothing-to-append early exit
# ---------------------------------------------------------------------------


def test_orchestrator_nothing_to_append_skips_downstream(tmp_path):
    """When append=True and append_new_files is empty, downstream steps must not run."""
    ctx = _make_ctx(tmp_path, append=True)

    # Pre-populate ingest output so _is_done returns True for it.
    (ctx.intermediate_dir / "file_manifest.json").write_text("{}")
    # Required by the append pre-check in run()
    (ctx.intermediate_dir / "schema.json").write_text("{}")

    # Simulate: ingest already ran and found no changes.
    ctx.append_new_files = set()

    executed = []

    def pass2_fn(c):
        executed.append("pass2")
        (c.intermediate_dir / "raw_extractions.json").write_text("{}")

    steps = [
        Step(name="ingest", fn=lambda c: None, outputs=["file_manifest.json"]),
        Step(name="pass2", fn=pass2_fn, outputs=["raw_extractions.json"]),
    ]

    run(steps, ctx)

    assert "pass2" not in executed, (
        "pass2 must not run when append=True and append_new_files is empty"
    )


# ---------------------------------------------------------------------------
# 9. CLI: --append + --from-step mutual exclusion
# ---------------------------------------------------------------------------


def test_cli_append_and_from_step_are_mutually_exclusive(tmp_path):
    """Invoking the CLI with both --append and --from-step must fail with exit code != 0."""
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(input_dir),
            "--append",
            "--from-step",
            "pass2",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code != 0, (
        f"Expected non-zero exit when --append and --from-step are combined, "
        f"got exit_code={result.exit_code}\nOutput: {result.output}"
    )
    # The error message should mention the mutual exclusion
    assert "mutually exclusive" in result.output.lower() or "append" in result.output.lower()
