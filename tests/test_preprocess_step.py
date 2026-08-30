from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mykg.orchestrator import PipelineContext
from mykg.steps.step_preprocess import run_preprocess


def _make_ctx(tmp_path: Path, *, sync: bool = False) -> PipelineContext:
    """Build a PipelineContext over tmp_path.

    Pass ``sync=True`` for tests that exercise reconciliation of a CHANGED or
    DELETED source. Since D58 those actions are gated behind --sync; a new
    source is still converted unflagged, since that is an addition.
    """
    input_dir = tmp_path / "input"
    intermediate_dir = tmp_path / "intermediate"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    intermediate_dir.mkdir()
    output_dir.mkdir()
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=None,
        sync=sync,
    )


def test_preprocess_disabled_writes_sentinel(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    with (
        patch("mykg.config.PREPROCESS_ENABLED", False),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)
    assert (ctx.intermediate_dir / "preprocess.done").exists()
    fake_run.assert_not_called()


def test_preprocess_no_non_md_files_skips(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "a.md").write_text("# hi")
    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)
    assert (ctx.intermediate_dir / "preprocess.done").exists()
    fake_run.assert_not_called()


def test_preprocess_enabled_calls_parse_docs(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        run_preprocess(ctx)
    assert (ctx.intermediate_dir / "preprocess.done").exists()
    # Spawn shape: [sys.executable, "-m", "mykg", "parse-docs", ...]
    # — using the SAME interpreter avoids PATH shadowing by an older system mykg.
    assert captured["cmd"][:4] == [sys.executable, "-m", "mykg", "parse-docs"]
    assert "--input" in captured["cmd"]
    assert "--output" in captured["cmd"]


def test_preprocess_nonzero_raises(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        with pytest.raises(RuntimeError, match="exit code 1"):
            run_preprocess(ctx)


def test_preprocess_step_in_steps_registry() -> None:
    from mykg.pipeline import STEPS

    assert STEPS[0].name == "preprocess"
    assert STEPS[1].name == "ingest"


# ---------------------------------------------------------------------------
# Extended Unit 10 — HTML conversion + skipped-file paths
# ---------------------------------------------------------------------------


def test_preprocess_converts_html_file(tmp_path: Path) -> None:
    """HTML files routed through _convert_html_files (in-process markdownify)."""
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "page.html").write_text("<html><body><h1>Hello</h1><p>World</p></body></html>")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)

    # MinerU subprocess should NOT have been called for HTML-only input.
    fake_run.assert_not_called()
    subdir_name = __import__("mykg.config", fromlist=["PREPROCESS_SUBDIR"]).PREPROCESS_SUBDIR
    sub = ctx.input_dir / subdir_name if subdir_name else ctx.input_dir
    converted = sub / "page.md"
    assert converted.exists()
    assert "Hello" in converted.read_text()


def test_preprocess_skipped_files_in_manifest(tmp_path: Path) -> None:
    """Files whose suffix isn't in the allowlist are skipped + recorded."""
    import json as _json

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "ignored.svg").write_text("<svg/>")
    (ctx.input_dir / "ignored.css").write_text("body{}")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)

    fake_run.assert_not_called()
    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    skipped = manifest["skipped_files"]
    paths = {r["path"] for r in skipped}
    assert "ignored.svg" in paths
    assert "ignored.css" in paths


def test_preprocess_html_conversion_failure(tmp_path: Path, monkeypatch) -> None:
    """When markdownify raises, the failure is recorded but doesn't halt pipeline."""
    import json as _json

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "broken.html").write_text("<html>bad</html>")

    def fail_markdownify(html, **kwargs):
        raise ValueError("markdownify exploded")

    monkeypatch.setattr("markdownify.markdownify", fail_markdownify)

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        run_preprocess(ctx)

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    records = manifest.get("html_records", [])
    assert any(r["path"] == "broken.html" and not r["ok"] for r in records)


def test_preprocess_mineru_timeout(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF fake")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=10)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        with pytest.raises(RuntimeError, match="timed out"):
            run_preprocess(ctx)


def test_preprocess_default_subdir_layout(tmp_path: Path) -> None:
    """With default subdir, output lands under input/<subdir>/ ."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "page.html").write_text("<html><body>hi</body></html>")

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        run_preprocess(ctx)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    assert (sub / "page.md").exists()


def test_preprocess_html_and_pdf_combined(tmp_path: Path) -> None:
    """When both HTML and PDF files are present, both pathways run."""
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "page.html").write_text("<html><body>hi</body></html>")
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        run_preprocess(ctx)

    # Manifest should record both branches
    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest["html_files"] == 1
    assert manifest["mineru_files"] == 1


# ---------------------------------------------------------------------------
# Non-md change detection (D-new): SHA-256 of source bytes, persisted in
# preprocess_manifest.json["source_files"], used to skip unchanged files.
# ---------------------------------------------------------------------------


def _seed_prior_manifest(intermediate_dir: Path, source_files: dict) -> None:
    """Write a prior preprocess_manifest.json with the given source_files map."""
    import json as _json

    (intermediate_dir / "preprocess_manifest.json").write_text(
        _json.dumps({"enabled": True, "source_files": source_files})
    )


def _sha256_bytes(data: bytes) -> str:
    import hashlib as _h

    return _h.sha256(data).hexdigest()


def test_unchanged_source_skips_mineru(tmp_path: Path) -> None:
    """When sha matches and output_md exists, MinerU is not invoked."""
    ctx = _make_ctx(tmp_path)
    pdf_bytes = b"%PDF-1.4 unchanged"
    (ctx.input_dir / "doc.pdf").write_bytes(pdf_bytes)

    # Place a prior .md exactly where the manifest claims.
    import mykg.config as cfg

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    prior_md = sub / "doc" / "doc.md"
    prior_md.parent.mkdir(parents=True, exist_ok=True)
    prior_md.write_text("# prior content")

    _seed_prior_manifest(
        ctx.intermediate_dir,
        {
            "doc.pdf": {
                "sha256": _sha256_bytes(pdf_bytes),
                "output_md": str(prior_md.relative_to(ctx.input_dir)),
                "size_bytes": len(pdf_bytes),
            }
        },
    )

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)

    fake_run.assert_not_called()
    assert prior_md.read_text() == "# prior content"  # untouched

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest["unchanged_count"] == 1
    assert manifest["mineru_files"] == 0
    assert manifest["source_files"]["doc.pdf"]["sha256"] == _sha256_bytes(pdf_bytes)


@pytest.mark.parametrize(
    "scenario",
    ["new", "modified"],
)
def test_changed_source_is_reprocessed(tmp_path: Path, scenario: str) -> None:
    """Both 'new' (no prior) and 'modified' (sha differs) re-invoke MinerU.

    D58: a *new* source converts under plain --append (it is an addition); a
    *modified* one is reconciliation and needs --sync.
    """
    ctx = _make_ctx(tmp_path, sync=(scenario == "modified"))
    pdf_bytes = b"%PDF-1.4 new bytes"
    (ctx.input_dir / "doc.pdf").write_bytes(pdf_bytes)

    if scenario == "modified":
        # Prior manifest claims a *different* hash for the same file.
        _seed_prior_manifest(
            ctx.intermediate_dir,
            {"doc.pdf": {"sha256": "stalehash", "output_md": "_preprocessed/doc/doc.md"}},
        )

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        run_preprocess(ctx)

    cmd = captured["cmd"]
    assert "--file-list" in cmd
    list_path = Path(cmd[cmd.index("--file-list") + 1])
    assert list_path.exists()
    assert "doc.pdf" in list_path.read_text().splitlines()


def test_removed_source_cleans_up_output_md(tmp_path: Path) -> None:
    """Prior manifest entry whose source no longer exists → output unlinked under --sync."""
    ctx = _make_ctx(tmp_path, sync=True)
    # No source file present.

    import mykg.config as cfg

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    stale_md = sub / "gone" / "gone.md"
    stale_md.parent.mkdir(parents=True, exist_ok=True)
    stale_md.write_text("# orphaned content")

    _seed_prior_manifest(
        ctx.intermediate_dir,
        {
            "gone.pdf": {
                "sha256": "anything",
                "output_md": str(stale_md.relative_to(ctx.input_dir)),
            }
        },
    )

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)

    fake_run.assert_not_called()
    assert not stale_md.exists()

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert "gone.pdf" not in manifest.get("source_files", {})


def test_manifest_atomic_write_no_partial_clobber(tmp_path: Path) -> None:
    """If a previous run left a *.tmp behind, the real manifest is unaffected."""
    import json as _json

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "page.html").write_text("<html><body>x</body></html>")

    # Pretend a previous run crashed mid-write — only the .tmp exists.
    (ctx.intermediate_dir / "preprocess_manifest.json.tmp").write_text("corrupted partial")

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        run_preprocess(ctx)

    # The .tmp from this run was renamed onto the real file (os.replace),
    # so the real file is valid JSON and the stale .tmp is gone.
    manifest_path = ctx.intermediate_dir / "preprocess_manifest.json"
    assert manifest_path.exists()
    parsed = _json.loads(manifest_path.read_text())
    assert parsed["enabled"] is True


def test_html_source_change_detection(tmp_path: Path) -> None:
    """HTML files participate in the same SHA-based skip path as MinerU files."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    html_bytes = b"<html><body>cached</body></html>"
    (ctx.input_dir / "page.html").write_bytes(html_bytes)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    prior_md = sub / "page.md"
    prior_md.write_text("# cached html output")

    _seed_prior_manifest(
        ctx.intermediate_dir,
        {
            "page.html": {
                "sha256": _sha256_bytes(html_bytes),
                "output_md": str(prior_md.relative_to(ctx.input_dir)),
            }
        },
    )

    # markdownify must NOT be called (would overwrite prior_md).
    called = {"hit": False}

    def boom(*a, **kw):
        called["hit"] = True
        return ""

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("markdownify.markdownify", side_effect=boom),
    ):
        run_preprocess(ctx)

    assert called["hit"] is False
    assert prior_md.read_text() == "# cached html output"


# ---------------------------------------------------------------------------
# preprocess.keep_artifacts toggle
# ---------------------------------------------------------------------------


def _fake_mineru_writing_nested_tree(ctx, src_filename: str, output_subdir: str):
    """Build a fake subprocess.run that mimics MinerU's per-file output layout:
    <output>/<stem>/<backend>/<stem>.md + images/ + <stem>.mineru.json.
    """
    import mykg.config as cfg

    def fake_run(cmd, **kwargs):
        out = ctx.input_dir / cfg.PREPROCESS_SUBDIR / output_subdir
        backend_dir = out / "hybrid_auto"
        backend_dir.mkdir(parents=True, exist_ok=True)
        stem = Path(src_filename).stem
        (backend_dir / f"{stem}.md").write_text(f"# {stem}")
        (backend_dir / "images").mkdir(exist_ok=True)
        (backend_dir / "images" / "fig1.jpg").write_bytes(b"\xff\xd8")
        (out / f"{stem}.mineru.json").write_text('{"source_file": "x"}')
        return subprocess.CompletedProcess(cmd, 0)

    return fake_run


def test_keep_artifacts_false_flattens_to_md_only(tmp_path: Path) -> None:
    """When keep_artifacts=False, only <stem>.md survives at the output root."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.config.PREPROCESS_KEEP_ARTIFACTS", False),
        patch(
            "mykg.steps.step_preprocess.subprocess.run",
            side_effect=_fake_mineru_writing_nested_tree(ctx, "doc.pdf", "doc"),
        ),
    ):
        run_preprocess(ctx)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    assert (sub / "doc.md").exists(), "flattened .md should exist at the output root"
    assert (sub / "doc.md").read_text() == "# doc"
    assert not (sub / "doc").exists(), "MinerU subtree should be removed"

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest["source_files"]["doc.pdf"]["output_md"].endswith("doc.md")
    # Should NOT point into the nested subtree.
    assert "hybrid_auto" not in manifest["source_files"]["doc.pdf"]["output_md"]


def test_keep_artifacts_true_preserves_mineru_layout(tmp_path: Path) -> None:
    """When keep_artifacts=True, MinerU's nested tree + images + sidecar all survive."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 fake")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.config.PREPROCESS_KEEP_ARTIFACTS", True),
        patch(
            "mykg.steps.step_preprocess.subprocess.run",
            side_effect=_fake_mineru_writing_nested_tree(ctx, "doc.pdf", "doc"),
        ),
    ):
        run_preprocess(ctx)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    # Nested tree intact.
    assert (sub / "doc" / "hybrid_auto" / "doc.md").exists()
    assert (sub / "doc" / "hybrid_auto" / "images" / "fig1.jpg").exists()
    assert (sub / "doc" / "doc.mineru.json").exists()
    # No flattened copy at the root.
    assert not (sub / "doc.md").exists()

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    # output_md points into the nested tree.
    assert "hybrid_auto" in manifest["source_files"]["doc.pdf"]["output_md"]


def test_keep_artifacts_false_preserves_subfolder_structure(tmp_path: Path) -> None:
    """A PDF in a subdirectory should land at <subdir>/<rel>/<stem>.md."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "dir1").mkdir()
    (ctx.input_dir / "dir1" / "deep.pdf").write_bytes(b"%PDF-1.4 fake")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.config.PREPROCESS_KEEP_ARTIFACTS", False),
        patch(
            "mykg.steps.step_preprocess.subprocess.run",
            side_effect=_fake_mineru_writing_nested_tree(ctx, "deep.pdf", "dir1/deep"),
        ),
    ):
        run_preprocess(ctx)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    assert (sub / "dir1" / "deep.md").exists()
    assert not (sub / "dir1" / "deep").exists()


# ---------------------------------------------------------------------------
# .txt file support — shutil.copy2 as .md
# ---------------------------------------------------------------------------


def test_preprocess_copies_txt_file(tmp_path: Path) -> None:
    """TXT files routed through _convert_txt_files (shutil.copy2 as .md)."""
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "notes.txt").write_text("Some plain text content")

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run") as fake_run,
    ):
        run_preprocess(ctx)

    fake_run.assert_not_called()
    subdir_name = __import__("mykg.config", fromlist=["PREPROCESS_SUBDIR"]).PREPROCESS_SUBDIR
    sub = ctx.input_dir / subdir_name if subdir_name else ctx.input_dir
    converted = sub / "notes.md"
    assert converted.exists()
    assert converted.read_text() == "Some plain text content"


def test_preprocess_txt_and_pdf_combined(tmp_path: Path) -> None:
    """When both TXT and PDF files are present, both pathways run."""
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "notes.txt").write_text("plain text")
    (ctx.input_dir / "doc.pdf").write_bytes(b"%PDF fake")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0)

    with (
        patch("mykg.config.PREPROCESS_ENABLED", True),
        patch("mykg.steps.step_preprocess.subprocess.run", side_effect=fake_run),
    ):
        run_preprocess(ctx)

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest["txt_files"] == 1
    assert manifest["mineru_files"] == 1


def test_preprocess_txt_change_detection(tmp_path: Path) -> None:
    """TXT files participate in the same SHA-based skip path as other file types."""
    import mykg.config as cfg

    ctx = _make_ctx(tmp_path)
    txt_bytes = b"cached text content"
    (ctx.input_dir / "notes.txt").write_bytes(txt_bytes)

    sub = ctx.input_dir / cfg.PREPROCESS_SUBDIR
    sub.mkdir(parents=True, exist_ok=True)
    prior_md = sub / "notes.md"
    prior_md.write_text("# cached txt output")

    _seed_prior_manifest(
        ctx.intermediate_dir,
        {
            "notes.txt": {
                "sha256": _sha256_bytes(txt_bytes),
                "output_md": str(prior_md.relative_to(ctx.input_dir)),
            }
        },
    )

    with patch("mykg.config.PREPROCESS_ENABLED", True):
        run_preprocess(ctx)

    assert prior_md.read_text() == "# cached txt output"

    import json as _json

    manifest = _json.loads((ctx.intermediate_dir / "preprocess_manifest.json").read_text())
    assert manifest["unchanged_count"] == 1
    assert manifest["txt_files"] == 0
