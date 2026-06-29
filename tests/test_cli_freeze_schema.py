"""CLI validation tests for --freeze-schema.

These exercise the early validation gates and the pass1 short-circuit.
"""

from pathlib import Path
from unittest.mock import MagicMock

import json
import pytest
from click.testing import CliRunner

from mykg.cli import cli


def test_freeze_schema_help_lists_flag():
    runner = CliRunner()
    result = runner.invoke(cli, ["extract-graph", "--help"])
    assert result.exit_code == 0
    assert "--freeze-schema" in result.output


def test_freeze_schema_requires_base_schema(tmp_path):
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    result = runner.invoke(
        cli,
        ["extract-graph", str(input_dir), "--freeze-schema"],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    assert "--base-schema" in result.output


def test_freeze_schema_excludes_append(tmp_path):
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    base_ttl = tmp_path / "base.ttl"
    base_ttl.write_text("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(input_dir),
            "--freeze-schema",
            "--base-schema",
            str(base_ttl),
            "--append",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_freeze_schema_excludes_grow_schema(tmp_path):
    runner = CliRunner()
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    base_ttl = tmp_path / "base.ttl"
    base_ttl.write_text("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
    result = runner.invoke(
        cli,
        [
            "extract-graph",
            str(input_dir),
            "--freeze-schema",
            "--base-schema",
            str(base_ttl),
            "--append-with-grow-schema",
        ],
        catch_exceptions=True,
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.output.lower()


def test_freeze_schema_pass1_skips_llm(tmp_path):
    """run_pass1_step with freeze_schema=True writes schema.json/schema.ttl
    from the base schema without making any LLM calls."""
    from mykg.orchestrator import PipelineContext

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    (intermediate / "schema_history").mkdir()

    adapter = MagicMock()

    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate,
        adapter=adapter,
        base_schema={
            "locked_classes": {
                "Person": {"type": "Person", "parent": None, "attributes": ["name", "email"]},
                "Organization": {
                    "type": "Organization",
                    "parent": None,
                    "attributes": ["name"],
                },
            },
            "locked_properties": {
                "works_at": {
                    "name": "works_at",
                    "domain": "Person",
                    "range": "Organization",
                    "attributes": ["role"],
                },
            },
        },
        freeze_schema=True,
    )

    from mykg.steps.step_pass1 import run_pass1_step

    run_pass1_step(ctx)

    schema = json.loads((intermediate / "schema.json").read_text())
    assert len(schema["concepts"]) == 2
    assert len(schema["properties"]) == 1

    concept_types = {c["type"] for c in schema["concepts"]}
    assert concept_types == {"Person", "Organization"}

    prop_names = {p["name"] for p in schema["properties"]}
    assert prop_names == {"works_at"}

    assert (intermediate / "schema.ttl").exists()
    ttl = (intermediate / "schema.ttl").read_text()
    assert "Person" in ttl
    assert "works_at" in ttl

    merge_log = json.loads((intermediate / "merge_log.json").read_text())
    assert merge_log == []

    adapter.assert_not_called()


def test_freeze_schema_pass1_empty_base_schema(tmp_path):
    """freeze_schema with a base_schema that has no locked_classes/locked_properties
    produces a valid but empty schema."""
    from mykg.orchestrator import PipelineContext

    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()
    (intermediate / "schema_history").mkdir()

    adapter = MagicMock()
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=intermediate,
        adapter=adapter,
        base_schema={"locked_classes": {}, "locked_properties": {}},
        freeze_schema=True,
    )

    from mykg.steps.step_pass1 import run_pass1_step

    run_pass1_step(ctx)

    schema = json.loads((intermediate / "schema.json").read_text())
    assert schema["concepts"] == []
    assert schema["properties"] == []
    assert (intermediate / "schema.ttl").exists()
    assert json.loads((intermediate / "merge_log.json").read_text()) == []
    adapter.assert_not_called()


def test_freeze_schema_pass1_errors_without_base_schema(tmp_path):
    """freeze_schema=True without base_schema raises RuntimeError."""
    from mykg.orchestrator import PipelineContext

    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=MagicMock(),
        freeze_schema=True,
    )

    from mykg.steps.step_pass1 import run_pass1_step

    with pytest.raises(RuntimeError, match="freeze_schema.*no base_schema"):
        run_pass1_step(ctx)


if __name__ == "__main__":
    pytest.main([str(Path(__file__))])
