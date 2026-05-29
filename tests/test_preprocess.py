"""Unit tests for the optional preprocess layer (D39–D48)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mykg.preprocess import (
    ConvertResult,
    MineruRunner,
    PreprocessError,
    PreprocessManifest,
    _html_to_markdown,
    _is_supported,
    convert_directory,
    convert_file,
)

# ---------------------------------------------------------------------------
# Pydantic models — round-trip
# ---------------------------------------------------------------------------


def test_convert_result_roundtrip():
    r = ConvertResult(
        source_file="a.pdf",
        output_file="a.md",
        converter="mineru",
        converter_version="3.1.13",
        backend="pipeline",
        language="en",
        duration_seconds=12.3,
        success=True,
        image_count=5,
        sha256="deadbeef",
    )
    raw = r.model_dump_json()
    parsed = ConvertResult.model_validate_json(raw)
    assert parsed == r
    assert parsed.converter == "mineru"
    assert parsed.image_count == 5


def test_preprocess_manifest_roundtrip():
    m = PreprocessManifest(
        converted={
            "a.pdf": ConvertResult(source_file="a.pdf", converter="mineru"),
            "b.html": ConvertResult(source_file="b.html", converter="markdownify"),
        },
        skipped=["c.unknown"],
        failed={"d.pdf": "subprocess crashed"},
    )
    raw = m.model_dump_json()
    parsed = PreprocessManifest.model_validate_json(raw)
    assert set(parsed.converted.keys()) == {"a.pdf", "b.html"}
    assert parsed.skipped == ["c.unknown"]
    assert parsed.failed == {"d.pdf": "subprocess crashed"}


# ---------------------------------------------------------------------------
# HTML converter
# ---------------------------------------------------------------------------


def test_html_to_markdown_produces_markdown(tmp_path):
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><h1>Hello</h1><p>World</p>"
        "<table><tr><th>k</th><th>v</th></tr><tr><td>a</td><td>1</td></tr></table>"
        "</body></html>"
    )
    out_dir = tmp_path / "out"
    res = _html_to_markdown(src, out_dir)
    assert res.success is True
    assert res.converter == "markdownify"
    md_path = Path(res.output_file)
    assert md_path.exists()
    text = md_path.read_text()
    assert "Hello" in text
    assert "World" in text
    # ATX heading
    assert text.lstrip().startswith("# Hello") or "# Hello" in text


def test_html_to_markdown_sets_sha256(tmp_path):
    src = tmp_path / "page.html"
    src.write_text("<h1>Hi</h1>")
    res = _html_to_markdown(src, tmp_path / "out")
    assert res.sha256 and len(res.sha256) == 64


# ---------------------------------------------------------------------------
# Dispatcher routing
# ---------------------------------------------------------------------------


def test_is_supported_routes_html():
    assert _is_supported(Path("a.html"), ["pdf"], ["html"]) == "markdownify"
    assert _is_supported(Path("a.HTM"), ["pdf"], ["html", "htm"]) == "markdownify"


def test_is_supported_routes_mineru():
    assert _is_supported(Path("a.pdf"), ["pdf"], ["html"]) == "mineru"
    assert _is_supported(Path("a.DOCX"), ["pdf", "docx"], ["html"]) == "mineru"


def test_is_supported_returns_none_for_unknown():
    assert _is_supported(Path("a.xyz"), ["pdf"], ["html"]) is None


def test_convert_file_writes_sidecar_for_html(tmp_path):
    src = tmp_path / "doc.html"
    src.write_text("<h1>Test</h1>")
    out_dir = tmp_path / "out"
    res = convert_file(
        src,
        out_dir,
        extensions=[],
        html_extensions=["html"],
    )
    assert res.success is True
    sidecar = out_dir / "doc.mineru.json"
    assert sidecar.exists()
    data = json.loads(sidecar.read_text())
    assert data["converter"] == "markdownify"
    assert data["source_file"].endswith("doc.html")


def test_convert_file_raises_on_unsupported_extension(tmp_path):
    src = tmp_path / "doc.weird"
    src.write_text("not real")
    with pytest.raises(PreprocessError):
        convert_file(src, tmp_path / "out", extensions=["pdf"], html_extensions=["html"])


# ---------------------------------------------------------------------------
# MinerU runner — mocked subprocess
# ---------------------------------------------------------------------------


def test_mineru_runner_resolve_binary_missing(monkeypatch):
    runner = MineruRunner(mineru_path="totally-bogus-binary-not-on-path")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    assert runner.resolve_binary() is None


def test_mineru_runner_missing_raises_preprocess_error(tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    runner = MineruRunner(mineru_path="totally-bogus-binary-not-on-path")
    monkeypatch.setattr("shutil.which", lambda _name: None)
    with pytest.raises(PreprocessError, match="MinerU not found"):
        runner.convert(src, tmp_path / "out")


def _fake_mineru_run(input_path: Path, work_dir: Path, return_code: int = 0):
    """Helper that emulates MinerU writing <stem>.md and images/ under work_dir."""

    def _run(cmd, capture_output=True, text=True, timeout=None):
        if "--version" in cmd:
            proc = MagicMock()
            proc.returncode = 0
            proc.stdout = "mineru 3.1.13\n"
            proc.stderr = ""
            return proc
        # Inspect cmd to find -o argument
        out_idx = cmd.index("-o") + 1
        out_dir = Path(cmd[out_idx])
        nested = out_dir / "gradio" / "ts_hash_stem" / "result" / input_path.stem / "pipeline"
        nested.mkdir(parents=True, exist_ok=True)
        (nested / f"{input_path.stem}.md").write_text(
            f"# Converted {input_path.stem}\nBody text.\n"
        )
        images = nested / "images"
        images.mkdir(exist_ok=True)
        (images / "fig1.jpg").write_bytes(b"fakejpgdata")
        proc = MagicMock()
        proc.returncode = return_code
        proc.stdout = "ok"
        proc.stderr = ""
        return proc

    return _run


def test_mineru_runner_convert_success(tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    out_dir = tmp_path / "out"
    runner = MineruRunner(mineru_path="/fake/mineru")

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/mineru")
    monkeypatch.setattr("mykg.preprocess.subprocess.run", _fake_mineru_run(src, tmp_path))

    res = runner.convert(src, out_dir)
    assert res.success is True
    assert res.converter == "mineru"
    assert res.image_count == 1
    md_path = Path(res.output_file)
    assert md_path.exists() and md_path.read_text().startswith("# Converted doc")
    assert (out_dir / "images" / "fig1.jpg").exists()


def test_mineru_runner_convert_nonzero_exit(tmp_path, monkeypatch):
    src = tmp_path / "doc.pdf"
    src.write_bytes(b"%PDF-1.4 stub")
    runner = MineruRunner(mineru_path="/fake/mineru")

    monkeypatch.setattr("shutil.which", lambda _name: "/fake/mineru")

    def _bad(*_a, **_k):
        proc = MagicMock()
        proc.returncode = 2
        proc.stdout = ""
        proc.stderr = "boom"
        return proc

    monkeypatch.setattr("mykg.preprocess.subprocess.run", _bad)
    with pytest.raises(PreprocessError, match="exited with code 2"):
        runner.convert(src, tmp_path / "out")


# ---------------------------------------------------------------------------
# convert_directory — parallel + fail_fast
# ---------------------------------------------------------------------------


def test_convert_directory_dispatches_html_and_skips_unknown(tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    (src / "a.html").write_text("<h1>A</h1>")
    (src / "nested").mkdir()
    (src / "nested" / "b.html").write_text("<h1>B</h1>")
    (src / "ignored.weird").write_text("nothing")

    out = tmp_path / "out"
    manifest = convert_directory(
        src,
        out,
        extensions=[],
        html_extensions=["html"],
        max_workers=2,
    )
    assert set(manifest.converted.keys()) == {"a.html", "nested/b.html"}
    assert not manifest.failed
    assert (out / "a.md").exists()
    assert (out / "nested" / "b.md").exists()
    assert (out / "nested" / "b.mineru.json").exists()


def test_convert_directory_records_failures(tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    (src / "bad.html").write_text("<h1>ok</h1>")

    def _explode(*_a, **_k):
        raise PreprocessError("simulated")

    monkeypatch.setattr("mykg.preprocess._html_to_markdown", _explode)
    manifest = convert_directory(
        src,
        tmp_path / "out",
        extensions=[],
        html_extensions=["html"],
        max_workers=1,
        fail_fast=False,
    )
    assert "bad.html" in manifest.failed
    assert "simulated" in manifest.failed["bad.html"]


def test_convert_directory_fail_fast_raises(tmp_path, monkeypatch):
    src = tmp_path / "in"
    src.mkdir()
    (src / "bad.html").write_text("<h1>ok</h1>")

    def _explode(*_a, **_k):
        raise PreprocessError("simulated")

    monkeypatch.setattr("mykg.preprocess._html_to_markdown", _explode)
    with pytest.raises(PreprocessError):
        convert_directory(
            src,
            tmp_path / "out",
            extensions=[],
            html_extensions=["html"],
            max_workers=1,
            fail_fast=True,
        )


# ---------------------------------------------------------------------------
# step_preprocess — manifest + sentinel + skip when disabled
# ---------------------------------------------------------------------------


def test_step_preprocess_writes_sentinel_when_no_candidates(tmp_path):
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_preprocess import run_preprocess

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "a.md").write_text("# already markdown")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output,
        intermediate_dir=intermediate,
        adapter=None,
    )
    run_preprocess(ctx)
    assert (intermediate / "preprocess.done").exists()
    assert (intermediate / "preprocess_manifest.json").exists()
    data = json.loads((intermediate / "preprocess_manifest.json").read_text())
    assert data["converted"] == {}


def test_step_preprocess_processes_html(tmp_path):
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_preprocess import run_preprocess

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "page.html").write_text("<h1>Hi</h1><p>Body</p>")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output,
        intermediate_dir=intermediate,
        adapter=None,
    )
    run_preprocess(ctx)
    assert (input_dir / "page.md").exists()
    assert (input_dir / "page.mineru.json").exists()
    data = json.loads((intermediate / "preprocess_manifest.json").read_text())
    assert "page.html" in data["converted"]


def test_step_preprocess_disabled_short_circuits(tmp_path, monkeypatch):
    import mykg.config as cfg_mod
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_preprocess import run_preprocess

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "page.html").write_text("<h1>Hi</h1>")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    monkeypatch.setattr(cfg_mod, "PREPROCESS_ENABLED", False)
    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output,
        intermediate_dir=intermediate,
        adapter=None,
    )
    run_preprocess(ctx)
    # disabled => no conversion happens, but sentinel exists for idempotency
    assert (intermediate / "preprocess.done").exists()
    assert not (input_dir / "page.md").exists()


def test_step_preprocess_missing_mineru_with_non_html_records_failure(tmp_path, monkeypatch):
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_preprocess import run_preprocess

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "doc.pdf").write_bytes(b"%PDF-1.4 stub")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    output = tmp_path / "output"
    output.mkdir()

    monkeypatch.setattr("shutil.which", lambda _n: None)
    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output,
        intermediate_dir=intermediate,
        adapter=None,
    )
    run_preprocess(ctx)
    data = json.loads((intermediate / "preprocess_manifest.json").read_text())
    assert "doc.pdf" in data["failed"]
    assert data["failed"]["doc.pdf"] == "mineru-not-installed"


# ---------------------------------------------------------------------------
# Integration: STEPS[0].name
# ---------------------------------------------------------------------------


def test_preprocess_is_first_step():
    from mykg.pipeline import STEPS

    assert STEPS[0].name == "preprocess"
    assert "preprocess.done" in STEPS[0].outputs
    assert STEPS[0].blocking is False
    assert STEPS[0].is_llm_step is False


# ---------------------------------------------------------------------------
# Cleanup helper
# ---------------------------------------------------------------------------


def test_cleanup_converted_outputs_removes_only_converted(tmp_path):
    from mykg.steps.step_preprocess import cleanup_converted_outputs

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "page.html").write_text("<h1>Hi</h1>")
    (input_dir / "page.md").write_text("# converted")
    (input_dir / "page.mineru.json").write_text("{}")
    (input_dir / "hand.md").write_text("# hand-written")

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    manifest = {
        "converted": {
            "page.html": {
                "source_file": str(input_dir / "page.html"),
                "output_file": str(input_dir / "page.md"),
                "converter": "markdownify",
            }
        },
        "skipped": [],
        "failed": {},
    }
    (intermediate / "preprocess_manifest.json").write_text(json.dumps(manifest))

    removed = cleanup_converted_outputs(intermediate, input_dir)
    assert removed >= 2  # .md + .mineru.json
    assert not (input_dir / "page.md").exists()
    assert not (input_dir / "page.mineru.json").exists()
    # source file preserved
    assert (input_dir / "page.html").exists()
    # hand-written .md untouched
    assert (input_dir / "hand.md").exists()
