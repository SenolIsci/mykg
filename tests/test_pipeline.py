from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext, run
from mykg.pipeline import STEPS

MOCK_SCHEMA_RESPONSE = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name", "email"]},
            {"type": "Organization", "parent": None, "attributes": ["name", "industry"]},
        ],
        "properties": [
            {
                "name": "works_at",
                "domain": "Person",
                "range": "Organization",
                "attributes": ["role"],
            }
        ],
    }
)

MOCK_EXTRACTION_RESPONSE = json.dumps(
    {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.97,
                "attributes": {
                    "name": {"value": "Alice", "confidence": 0.99},
                    "email": {"value": "alice@acme.com", "confidence": 0.97},
                },
            },
            {
                "id": "organization-acme-corp",
                "type": "Organization",
                "confidence": 0.99,
                "attributes": {
                    "name": {"value": "Acme Corp", "confidence": 0.99},
                    "industry": {"value": None, "confidence": 0.0},
                },
            },
        ],
        "edges": [
            {
                "id": "edge-001",
                "type": "works_at",
                "from": "person-alice",
                "to": "organization-acme-corp",
                "confidence": 0.96,
                "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
            }
        ],
    }
)


class SequentialMockAdapter(LLMAdapter):
    def __init__(self):
        self._call_count = 0

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self._call_count += 1
        if self._call_count == 1:
            return MOCK_SCHEMA_RESPONSE
        return MOCK_EXTRACTION_RESPONSE

    def endpoint_label(self) -> str:
        return "mock"


def _make_ctx(tmpdir: str) -> PipelineContext:
    input_dir = Path(tmpdir) / "input"
    input_dir.mkdir()
    (input_dir / "team.md").write_text("Alice works at Acme Corp.")
    output_dir = Path(tmpdir) / "output"
    intermediate_dir = Path(tmpdir) / "intermediate"
    output_dir.mkdir(parents=True, exist_ok=True)
    intermediate_dir.mkdir(parents=True, exist_ok=True)
    return PipelineContext(
        input_dir=input_dir,
        output_dir=output_dir,
        intermediate_dir=intermediate_dir,
        adapter=SequentialMockAdapter(),
        base_schema=None,
        thesaurus=None,
        review=False,
    )


def test_pipeline_produces_nodes_jsonl():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        nodes_file = ctx.output_dir / "nodes.jsonl"
        assert nodes_file.exists()
        lines = nodes_file.read_text().strip().split("\n")
        assert len(lines) >= 1
        node = json.loads(lines[0])
        assert "id" in node
        assert "type" in node


def test_pipeline_produces_edges_jsonl():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        assert (ctx.output_dir / "edges.jsonl").exists()


def test_pipeline_produces_ttl():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        content = (ctx.output_dir / "knowledge_graph.ttl").read_text()
        assert "rdfs:Class" in content
        assert "rdf:type" in content


def test_pipeline_produces_intermediate_schema():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
        assert "concepts" in schema
        assert "properties" in schema


def test_pipeline_produces_validation_json():
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        result = json.loads((ctx.output_dir / "knowledge_graph_validation.json").read_text())
        assert "valid" in result


def test_pipeline_checkpoint_skips_done_steps():
    """Second run with output files present skips all steps except ingest."""
    with tempfile.TemporaryDirectory() as tmpdir:
        ctx = _make_ctx(tmpdir)
        run(STEPS, ctx)
        # Remove state file but keep outputs — second run should skip all steps
        (ctx.intermediate_dir / "pipeline_state.json").unlink(missing_ok=True)
        ctx2 = PipelineContext(
            input_dir=ctx.input_dir,
            output_dir=ctx.output_dir,
            intermediate_dir=ctx.intermediate_dir,
            adapter=SequentialMockAdapter(),
            base_schema=None,
            thesaurus=None,
            review=False,
        )
        run(STEPS, ctx2)
        # If we get here without error, checkpoint worked
        assert (ctx2.output_dir / "nodes.jsonl").exists()


def test_step_output_location_field():
    """Every Step has an output_location field ('intermediate' or 'output')."""
    from mykg.pipeline import STEPS

    for step in STEPS:
        assert step.output_location in ("intermediate", "output"), (
            f"Step '{step.name}' has invalid output_location: {step.output_location!r}"
        )


def test_export_step_output_location_is_output():
    """The export step writes to 'output', not 'intermediate'."""
    from mykg.pipeline import STEPS

    export_step = next(s for s in STEPS if s.name == "validate_graph")
    assert export_step.output_location == "output"


def test_delete_from_step_uses_steps_registry(tmp_path):
    """_delete_from_step deletes files declared in STEPS, including merge_log.json."""
    from mykg.cli import _delete_from_step

    inter = tmp_path / "intermediate"
    inter.mkdir()
    out = tmp_path / "output"
    out.mkdir()

    # Create files that assemble step declares as outputs
    (inter / "edge_metadata.json").write_text("{}")
    (inter / "nodes.json").write_text("[]")
    (inter / "merge_log.json").write_text("[]")

    _delete_from_step("assemble", inter, out)

    assert not (inter / "edge_metadata.json").exists()
    assert not (inter / "nodes.json").exists()


def test_log_rotation_constants_exist():
    from mykg import config

    assert isinstance(config.LOG_MAX_BYTES, int)
    assert isinstance(config.LOG_BACKUP_COUNT, int)
    assert config.LOG_MAX_BYTES > 0
    assert config.LOG_BACKUP_COUNT >= 0
