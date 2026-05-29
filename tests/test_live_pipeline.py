"""Live integration tests — require OPENROUTER_API_KEY (or equivalent).

Run with:
    uv run pytest tests/test_live_pipeline.py -m live -v --no-cov

Skipped automatically when the API key is absent.
"""

import json
import os
import shutil

import pytest

from mykg.llm.config import load_adapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS
from mykg.steps.step_ingest import run_ingest
from mykg.steps.step_pass1 import run_pass1_step
from mykg.steps.step_pass2 import run_pass2_step, run_schema_flatten


def _raw_config(api_key: str) -> dict:
    return {
        "provider": "openrouter",
        "llm_retry": {"max_retries": 1},
        "llm": {
            "model": os.environ.get("OPENROUTER_MODEL", "google/gemma-4-31b-it"),
            "context_window": 32000,
            "max_output_tokens": 512,
            "timeout": 120,
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": api_key,
            "retry_429_max": 2,
            "retry_429_base_delay": 2.0,
        },
        "pipeline": {
            "ingest": {"max_workers": 1},
            "chunking": {
                "window_tokens": 1000,
                "overlap_tokens": 100,
                "tiktoken_encoding": "cl100k_base",
            },
            "pass1": {"batch_token_target": 2000, "max_workers": 1, "per_file_batching": False},
            "pass2": {"max_workers": 1, "stateful_chunks": False},
            "normalize_names": {"enabled": False},
            "orphan_pass": {"enabled": False},
            "error_gate": {"enabled": False},
            "logging": {"max_bytes": 10485760, "backup_count": 3, "capture_prompts": False},
            "assembly": {"confidence_agg": "mean"},
            "export": {"networkx_enabled": False},
            "paths": {"sessions_dir": "sessions"},
        },
    }


def _make_ctx(tmp_path, api_key, corpus_dir):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    for f in corpus_dir.iterdir():
        shutil.copy(f, input_dir / f.name)
    output_dir = tmp_path / "output"
    intermediate_dir = tmp_path / "intermediate"
    output_dir.mkdir(parents=True)
    intermediate_dir.mkdir(parents=True)
    adapter = load_adapter(_raw=_raw_config(api_key))
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        base_schema=None,
        thesaurus=None,
        review=False,
    )


@pytest.mark.live
def test_full_pipeline_smoke(tmp_path, openrouter_api_key, live_corpus):
    ctx = _make_ctx(tmp_path, openrouter_api_key, live_corpus)
    run(STEPS, ctx)

    nodes_path = ctx.output_dir / "nodes.jsonl"
    assert nodes_path.exists(), "nodes.jsonl not created"
    for line in nodes_path.read_text().splitlines():
        if not line.strip():
            continue
        node = json.loads(line)
        assert "id" in node, f"node missing 'id': {node}"
        assert "type" in node, f"node missing 'type': {node}"
        assert "confidence" in node, f"node missing 'confidence': {node}"

    edges_path = ctx.output_dir / "edges.jsonl"
    assert edges_path.exists(), "edges.jsonl not created"
    for line in edges_path.read_text().splitlines():
        if line.strip():
            json.loads(line)  # must be valid JSON

    ttl_path = ctx.output_dir / "knowledge_graph.ttl"
    assert ttl_path.exists(), "knowledge_graph.ttl not created"
    from rdflib import Graph

    g = Graph()
    g.parse(data=ttl_path.read_text(), format="turtle")

    schema_path = ctx.intermediate_dir / "schema.json"
    assert schema_path.exists(), "schema.json not created"
    schema = json.loads(schema_path.read_text())
    assert isinstance(schema.get("concepts"), list), "schema.concepts must be a list"
    assert isinstance(schema.get("properties"), list), "schema.properties must be a list"

    em_path = ctx.intermediate_dir / "edge_metadata.json"
    assert em_path.exists(), "edge_metadata.json not created"
    assert isinstance(json.loads(em_path.read_text()), dict)


@pytest.mark.live
def test_pass1_schema_rdfs_invariants(tmp_path, openrouter_api_key, live_corpus):
    ctx = _make_ctx(tmp_path, openrouter_api_key, live_corpus)
    run_ingest(ctx)
    run_pass1_step(ctx)

    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    concepts = schema.get("concepts", [])
    properties = schema.get("properties", [])

    declared_types = {c["type"] for c in concepts}

    for c in concepts:
        assert c.get("type") != "Relationship", (
            "schema must not contain an abstract Relationship class (D5)"
        )
        assert "name" in c.get("attributes", []), (
            f"concept {c['type']!r} missing required 'name' attribute"
        )

    for p in properties:
        assert p.get("domain") in declared_types, (
            f"property {p['name']!r} domain {p['domain']!r} not in declared concepts"
        )
        assert p.get("range") in declared_types, (
            f"property {p['name']!r} range {p['range']!r} not in declared concepts"
        )


@pytest.mark.live
def test_pass2_extraction_structural_validity(tmp_path, openrouter_api_key, live_corpus):
    ctx = _make_ctx(tmp_path, openrouter_api_key, live_corpus)
    run_ingest(ctx)
    run_pass1_step(ctx)
    run_schema_flatten(ctx)
    run_pass2_step(ctx)

    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    declared_types = {c["type"] for c in schema.get("concepts", [])}
    declared_props = {p["name"] for p in schema.get("properties", [])}

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    for fname, extraction in raw.items():
        for node in extraction.get("nodes", []):
            assert node.get("type") in declared_types, (
                f"[{fname}] node type {node.get('type')!r} not in schema"
            )
            assert node.get("id", "") != "", f"[{fname}] node has empty id"
            conf = node.get("confidence", -1)
            assert 0.0 <= conf <= 1.0, f"[{fname}] node confidence {conf} out of range"
        for edge in extraction.get("edges", []):
            assert edge.get("type") in declared_props, (
                f"[{fname}] edge type {edge.get('type')!r} not in schema properties"
            )
            conf = edge.get("confidence", -1)
            assert 0.0 <= conf <= 1.0, f"[{fname}] edge confidence {conf} out of range"


@pytest.mark.live
def test_live_pdf_to_kg(tmp_path, openrouter_api_key):
    """End-to-end PDF -> KG via the preprocess step + extract-graph.

    Requires MinerU installed AND an OpenRouter key. Skipped automatically
    when MinerU is absent. Tries a tiny PDF colocated in ``blog_demo_input/``
    first; falls back to the user's canonical artefact if present.
    """
    if shutil.which("mineru") is None:
        pytest.skip("mineru CLI not on PATH — install with: pip install mykg[mineru]")

    # Locate a suitable PDF (small first; user-side artefact second).
    repo_root = __import__("pathlib").Path(__file__).resolve().parent.parent
    candidates = [
        repo_root / "blog_demo_input" / "sample.pdf",
        __import__("pathlib").Path("/Users/senolisci/mineru/input.pdf"),
    ]
    pdf = next((p for p in candidates if p.exists()), None)
    if pdf is None:
        pytest.skip("no PDF artefact available for live test")

    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copy(pdf, input_dir / "sample.pdf")

    output_dir = tmp_path / "output"
    intermediate_dir = tmp_path / "intermediate"
    output_dir.mkdir()
    intermediate_dir.mkdir()

    adapter = load_adapter(_raw=_raw_config(openrouter_api_key))
    ctx = PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=adapter,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    run(STEPS, ctx)

    # Converted markdown should exist alongside the PDF source.
    assert (input_dir / "sample.md").exists()
    assert (intermediate_dir / "preprocess.done").exists()

    # Pipeline should produce real outputs even if the PDF is tiny.
    assert (output_dir / "nodes.jsonl").exists()
    assert (output_dir / "edges.jsonl").exists()


@pytest.mark.live
def test_claude_cli_adapter_smoke():
    if shutil.which("claude") is None:
        pytest.skip("claude CLI not on PATH")

    from mykg.llm.claude_cli_adapter import ClaudeCLIAdapter

    adapter = ClaudeCLIAdapter(max_tokens=64, timeout=30)
    response = adapter.complete(
        system="Reply with exactly one word: PONG",
        user="PING",
    )
    assert response.strip(), "expected non-empty response from claude CLI"
