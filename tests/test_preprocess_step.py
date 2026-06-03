from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from mykg.orchestrator import PipelineContext
from mykg.steps.step_preprocess import run_preprocess


def _make_ctx(tmp_path: Path) -> PipelineContext:
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
    (ctx.input_dir / "page.html").write_text(
        "<html><body><h1>Hello</h1><p>World</p></body></html>"
    )

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
