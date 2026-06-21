"""Tests for the append mode feature (Unit 5).

Covers: SHA256 helper, manifest migration, new/modified/unchanged file detection,
orchestrator skip logic, error on missing schema, nothing-to-append early exit,
and CLI mutual-exclusion of --append + --from-step.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from mykg.cli import cli
from mykg.orchestrator import PipelineContext, Step, run
from mykg.steps.step_ingest import _load_manifest, _run_append_ingest, _sha256, run_ingest
from mykg.steps.step_preprocess import run_preprocess

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
    """In --append-with-grow-schema mode pass1/schema_validate/schema_flatten must RUN
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
# 6b. Orchestrator: preprocess force-run in append mode (non-MD support)
# ---------------------------------------------------------------------------


def _preprocess_force_steps(executed: list) -> list[Step]:
    """Build a minimal step list whose preprocess step records execution.

    The preprocess output (preprocess.done) is pre-created by the caller so that
    _is_done would normally skip it — the test proves _append_force overrides that.
    """

    def preprocess_fn(c):
        executed.append("preprocess")

    def ingest_fn(c):
        executed.append("ingest")
        c.append_new_files = set()  # no downstream work needed for this assertion

    return [
        Step(name="preprocess", fn=preprocess_fn, outputs=["preprocess.done"]),
        Step(name="ingest", fn=ingest_fn, outputs=["file_manifest.json"]),
    ]


def test_orchestrator_append_forces_preprocess_despite_sentinel(tmp_path):
    """In plain --append mode preprocess must RUN again even though preprocess.done
    already exists (so its SHA-based change detection can convert new non-MD files)."""
    ctx = _make_ctx(tmp_path, append=True)

    # Required by the append pre-check in run(), plus the preprocess + ingest
    # outputs so _is_done returns True for them.
    (ctx.intermediate_dir / "schema.json").write_text("{}")
    (ctx.intermediate_dir / "preprocess.done").write_text("done")
    (ctx.intermediate_dir / "file_manifest.json").write_text("{}")

    executed: list = []
    run(_preprocess_force_steps(executed), ctx)

    assert "preprocess" in executed, (
        "preprocess must be force-run in append mode despite the surviving sentinel"
    )


def test_orchestrator_grow_schema_forces_preprocess_despite_sentinel(tmp_path):
    """--append-with-grow-schema must also force-run preprocess (it implies --append,
    and _append_force keys off ctx.append, so the same fix covers both flavors)."""
    ctx = _make_ctx(tmp_path, append=True)
    ctx.grow_schema = True

    (ctx.intermediate_dir / "schema.json").write_text("{}")
    (ctx.intermediate_dir / "preprocess.done").write_text("done")
    (ctx.intermediate_dir / "file_manifest.json").write_text("{}")

    executed: list = []
    run(_preprocess_force_steps(executed), ctx)

    assert "preprocess" in executed, (
        "preprocess must be force-run in --append-with-grow-schema mode too"
    )


# ---------------------------------------------------------------------------
# 6c. Real delta flow through run_preprocess (HTML/TXT — no MinerU, no LLM)
# ---------------------------------------------------------------------------


def _preprocess_ctx(tmp_path: Path) -> PipelineContext:
    input_dir = tmp_path / "input"
    intermediate_dir = tmp_path / "intermediate"
    output_dir = tmp_path / "output"
    input_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=None,
    )


def _preprocess_subdir(ctx: PipelineContext) -> Path:
    import mykg.config as _cfg

    return ctx.input_dir / _cfg.PREPROCESS_SUBDIR if _cfg.PREPROCESS_SUBDIR else ctx.input_dir


def test_append_delta_converts_new_non_md_file(tmp_path):
    """Two-stage delta: an initial non-MD file is converted, then a NEW one is added
    and only that new file is converted on re-run (the first is reused by SHA).

    Uses .txt input so the whole flow runs in-process (shutil.copy2) — no MinerU
    subprocess, no LLM. This is the real append delta the orchestrator fix enables.
    """
    ctx = _preprocess_ctx(tmp_path)
    (ctx.input_dir / "first.txt").write_text("first document content")

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        # Stage 1 — initial conversion.
        run_preprocess(ctx)

        sub = _preprocess_subdir(ctx)
        assert (sub / "first.md").exists()
        manifest = json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
        assert "first.txt" in manifest["source_files"]
        first_sha = manifest["source_files"]["first.txt"]["sha256"]

        # Stage 2 — drop a NEW file and re-run (sentinel + manifest now exist,
        # mirroring an --append re-entry where preprocess is force-run).
        (ctx.input_dir / "second.txt").write_text("second document content")
        run_preprocess(ctx)

    manifest2 = json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    # Both sources are now recorded.
    assert "first.txt" in manifest2["source_files"]
    assert "second.txt" in manifest2["source_files"]
    # The new file's markdown exists.
    assert (sub / "second.md").exists()
    # The first file was NOT re-converted — its SHA entry is unchanged and exactly
    # one file was skipped as unchanged.
    assert manifest2["source_files"]["first.txt"]["sha256"] == first_sha
    assert manifest2["unchanged_count"] == 1


def test_append_delta_ingest_picks_up_preprocessed_md(tmp_path):
    """The preprocess→ingest handoff: a freshly-converted .md under _preprocessed/
    is discovered by _run_append_ingest and lands in ctx.append_new_files."""
    ctx = _preprocess_ctx(tmp_path)
    ctx.append = True
    (ctx.input_dir / "note.txt").write_text("some note content")

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        run_preprocess(ctx)

    # An existing manifest with no entries simulates a prior session that had no
    # markdown from this source yet; the converted note.md must be detected as new.
    (ctx.intermediate_dir / "file_manifest.json").write_text("{}")
    _run_append_ingest(ctx)

    sub_name = _preprocess_subdir(ctx).name
    matches = [f for f in ctx.append_new_files if f.endswith("note.md")]
    assert matches, (
        f"ingest must discover the converted .md under {sub_name}/; "
        f"append_new_files={ctx.append_new_files}"
    )


@pytest.mark.live
def test_append_delta_real_mineru_pdf(tmp_path):
    """Real MinerU PDF→MD through the append delta (gated by -m live; not in default run).

    Exercises the actual ephemeral-venv MinerU path — no mocking. Stops at the
    preprocess/manifest layer, so no LLM/API key is needed (MinerU is LLM-free).
    """
    if shutil.which("uv") is None:
        pytest.skip("uv not available for the ephemeral MinerU venv")

    pdf_src = (
        Path(__file__).resolve().parents[1]
        / "_input_files3"
        / "ODNI-UAP-D001, USPER NARRATIVE, SENIOR USIC OFFICIAL.pdf"
    )
    if not pdf_src.exists():
        pytest.skip(f"PDF fixture not found at {pdf_src}")

    ctx = _preprocess_ctx(tmp_path)
    shutil.copy2(pdf_src, ctx.input_dir / "doc.pdf")

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        # Stage 1 — real MinerU conversion of the PDF.
        run_preprocess(ctx)
        sub = _preprocess_subdir(ctx)
        converted = sub / "doc.md"
        assert converted.exists(), "MinerU must produce doc.md under the preprocess subdir"
        assert converted.read_text().strip(), "converted markdown must be non-empty"

        manifest = json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
        pdf_sha = manifest["source_files"]["doc.pdf"]["sha256"]

        # Stage 2 — add a cheap .txt file and re-run; the PDF must be reused by SHA
        # (not re-converted), proving the incremental delta works across formats.
        (ctx.input_dir / "extra.txt").write_text("extra note")
        run_preprocess(ctx)

    manifest2 = json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest2["source_files"]["doc.pdf"]["sha256"] == pdf_sha
    assert "extra.txt" in manifest2["source_files"]
    assert manifest2["unchanged_count"] >= 1, "the already-converted PDF must be skipped on re-run"


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
