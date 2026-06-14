import json
from unittest.mock import MagicMock

from mykg.chunker import Chunk
from mykg.orchestrator import PipelineContext
from mykg.steps.step_assemble import run_assemble
from mykg.steps.step_ingest import run_ingest
from mykg.steps.step_pass1 import run_pass1_step
from mykg.steps.step_pass2 import _fname_slug, run_pass2_step, run_schema_flatten
from mykg.steps.step_schema import run_human_review, run_schema_validate
from mykg.steps.step_validate_graph import run_validate_graph

SCHEMA = {
    "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
    "properties": [],
}

MOCK_SCHEMA_RESPONSE = json.dumps(SCHEMA)

MOCK_EXTRACTION = json.dumps(
    {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.9,
                "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
            }
        ],
        "edges": [],
    }
)


def _make_ctx(tmp_path, adapter=None):
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=adapter or MagicMock(),
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    ctx.input_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    return ctx


def test_run_ingest_populates_ctx(tmp_path):
    ctx = _make_ctx(tmp_path)
    (ctx.input_dir / "doc.md").write_text("Alice works at Acme.")
    run_ingest(ctx)
    assert hasattr(ctx, "all_chunks")
    assert hasattr(ctx, "file_contents")
    assert len(ctx.all_chunks) >= 1
    assert "doc.md" in ctx.file_contents


def test_run_pass1_step_writes_schema(tmp_path):
    adapter = MagicMock()
    adapter.complete.return_value = MOCK_SCHEMA_RESPONSE
    ctx = _make_ctx(tmp_path, adapter)
    ctx.all_chunks = [
        Chunk(
            source_file="doc.md",
            chunk_index=0,
            text="Alice works at Acme.",
            token_start=0,
            token_end=10,
        )
    ]
    ctx.file_contents = {}
    run_pass1_step(ctx)
    assert (ctx.intermediate_dir / "schema.json").exists()
    assert (ctx.intermediate_dir / "schema.ttl").exists()


def test_run_schema_validate_passes_on_valid_schema(tmp_path):
    ctx = _make_ctx(tmp_path)
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    from mykg.exporter import export_ttl

    (ctx.intermediate_dir / "schema.ttl").write_text(export_ttl(SCHEMA, [], {}))
    run_schema_validate(ctx)  # should not raise


def test_run_human_review_writes_flag_when_not_review_mode(tmp_path):
    ctx = _make_ctx(tmp_path)
    ctx.review = False
    run_human_review(ctx)
    assert (ctx.intermediate_dir / "schema_approved.flag").exists()


def test_run_schema_flatten_writes_flattened(tmp_path):
    ctx = _make_ctx(tmp_path)
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    run_schema_flatten(ctx)
    assert (ctx.intermediate_dir / "flattened_schema.json").exists()
    flat = json.loads((ctx.intermediate_dir / "flattened_schema.json").read_text())
    assert "Person" in flat


def test_run_pass2_step_writes_extractions(tmp_path):
    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION
    ctx = _make_ctx(tmp_path, adapter)
    ctx.file_contents = {"doc.md": "Alice works at Acme."}
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))
    run_pass2_step(ctx)
    assert (ctx.intermediate_dir / "raw_extractions.json").exists()


def test_run_pass2_step_append_merges_new_file(tmp_path, monkeypatch):
    """Append mode runs pass2 only on new files and merges into existing extractions."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION
    ctx = _make_ctx(tmp_path, adapter)
    ctx.append = True
    ctx.append_new_files = {"new.md"}
    ctx.file_contents = {"existing.md": "old content", "new.md": "Alice works at Acme."}

    existing = {
        "existing.md": {
            "nodes": [
                {
                    "id": "person-bob",
                    "type": "Person",
                    "confidence": 0.8,
                    "attributes": {"name": {"value": "Bob", "confidence": 0.8}},
                }
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(existing))
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps({"existing.md": {"1": ["person-bob"]}})
    )
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))

    run_pass2_step(ctx)

    merged = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "existing.md" in merged
    assert "new.md" in merged
    assert merged["existing.md"]["nodes"][0]["id"] == "person-bob"


def test_run_pass2_step_append_preserves_existing_chunk_index(tmp_path, monkeypatch):
    """Append mode extends chunk_node_index without overwriting existing entries."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION
    ctx = _make_ctx(tmp_path, adapter)
    ctx.append = True
    ctx.append_new_files = {"new.md"}
    ctx.file_contents = {"existing.md": "old", "new.md": "new content"}

    (ctx.intermediate_dir / "raw_extractions.json").write_text(
        json.dumps({"existing.md": {"nodes": [], "edges": []}})
    )
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps({"existing.md": {"1": ["person-bob"]}})
    )
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))

    run_pass2_step(ctx)

    index = json.loads((ctx.intermediate_dir / "chunk_node_index.json").read_text())
    assert "existing.md" in index
    assert "new.md" in index


def test_run_assemble_writes_edge_metadata(tmp_path):
    ctx = _make_ctx(tmp_path)
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
                }
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    run_assemble(ctx)
    assert (ctx.intermediate_dir / "edge_metadata.json").exists()
    assert hasattr(ctx, "nodes")
    assert hasattr(ctx, "edge_metadata")


def test_run_validate_graph_writes_all_outputs(tmp_path):
    ctx = _make_ctx(tmp_path)
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    ctx.nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "source_files": ["doc.md"],
            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
        }
    ]
    ctx.edge_metadata = {}
    run_validate_graph(ctx)
    assert (ctx.output_dir / "nodes.jsonl").exists()
    assert (ctx.output_dir / "edges.jsonl").exists()
    assert (ctx.output_dir / "knowledge_graph.ttl").exists()
    assert (ctx.output_dir / "knowledge_graph_validation.json").exists()


def test_run_ingest_writes_base_schema_parsed(tmp_path):
    """run_ingest writes intermediate/base_schema_parsed.json when base_schema is set."""
    from unittest.mock import MagicMock

    from mykg.steps.step_ingest import run_ingest

    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "test.md").write_text("# Hello")

    ctx = MagicMock()
    ctx.input_dir = tmp_path / "input"
    ctx.intermediate_dir = tmp_path
    ctx.append = False
    ctx.ingest_workers = 1
    ctx.base_schema = {
        "_source": "base.ttl",
        "locked_classes": {"Person": {"type": "Person", "parent": None, "attributes": ["name"]}},
        "locked_properties": {
            "works_at": {
                "name": "works_at",
                "domain": "Person",
                "range": "Organization",
                "attributes": [],
            },
        },
    }
    ctx.thesaurus = None

    run_ingest(ctx)

    out = tmp_path / "base_schema_parsed.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["source"] == "base.ttl"
    assert isinstance(data["locked_classes"], dict)
    assert isinstance(data["locked_properties"], dict)
    assert "Person" in data["locked_classes"]
    assert data["locked_classes"]["Person"]["type"] == "Person"
    assert data["locked_classes"]["Person"]["attributes"] == ["name"]
    assert "works_at" in data["locked_properties"]
    assert data["locked_properties"]["works_at"]["domain"] == "Person"


def test_run_ingest_writes_thesaurus_parsed(tmp_path):
    """run_ingest writes intermediate/thesaurus_parsed.json when thesaurus is set."""
    from unittest.mock import MagicMock

    from mykg.steps.step_ingest import run_ingest
    from mykg.thesaurus import SynonymIndex

    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "test.md").write_text("# Hello")

    idx = SynonymIndex(term_count=5)
    idx._add(idx.exact_matches, "Person", "Human")
    ctx = MagicMock()
    ctx.input_dir = tmp_path / "input"
    ctx.intermediate_dir = tmp_path
    ctx.append = False
    ctx.ingest_workers = 1
    ctx.base_schema = None
    ctx.thesaurus = idx

    run_ingest(ctx)

    out = tmp_path / "thesaurus_parsed.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert data["term_count"] == 5
    assert "skos:exactMatch" in data["relations_used"]


def test_run_ingest_no_files_written_when_options_absent(tmp_path):
    """run_ingest does not write parsed files when options are not provided."""
    from unittest.mock import MagicMock

    from mykg.steps.step_ingest import run_ingest

    (tmp_path / "input").mkdir()
    ctx = MagicMock()
    ctx.input_dir = tmp_path / "input"
    ctx.intermediate_dir = tmp_path
    ctx.append = False
    ctx.ingest_workers = 1
    ctx.base_schema = None
    ctx.thesaurus = None

    run_ingest(ctx)

    assert not (tmp_path / "base_schema_parsed.json").exists()
    assert not (tmp_path / "thesaurus_parsed.json").exists()


def test_run_validate_graph_does_not_raise_on_tbox_errors(tmp_path):
    """run_validate_graph must not raise on TBox validation errors — writes advisory output and returns."""
    import json
    from unittest.mock import MagicMock, patch

    from mykg.steps.step_validate_graph import run_validate_graph

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
        }
    ]
    edge_metadata = {}

    (tmp_path / "schema.json").write_text(json.dumps(schema))
    (tmp_path / "nodes.json").write_text(json.dumps(nodes))
    (tmp_path / "edge_metadata.json").write_text(json.dumps(edge_metadata))
    output_dir = tmp_path / "output"
    output_dir.mkdir()

    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path
    ctx.output_dir = output_dir
    ctx.nodes = None
    ctx.edge_metadata = None

    tbox_result = {
        "valid": False,
        "tbox_checks": {"errors": [{"message": "bad TBox"}]},
        "abox_checks": {"errors": []},
    }

    with patch(
        "mykg.steps.step_validate_graph.validate_knowledge_graph_ttl", return_value=tbox_result
    ):
        # Should not raise
        run_validate_graph(ctx)

    assert (output_dir / "knowledge_graph_validation.json").exists()


def test_run_validate_graph_calls_export_obsidian_when_enabled(tmp_path, monkeypatch):
    """run_validate_graph calls export_obsidian when OBSIDIAN_ENABLED is True."""
    from unittest.mock import patch

    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OBSIDIAN_ENABLED", True)
    monkeypatch.setattr(cfg_mod, "OBSIDIAN_VAULT_DIR", "obsidian_vault")

    ctx = _make_ctx(tmp_path)
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    ctx.nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "source_files": ["doc.md"],
            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
        }
    ]
    ctx.edge_metadata = {}

    with patch("mykg.exporter.export_obsidian", create=True, wraps=None) as mock_obs:
        mock_obs.return_value = ["obsidian_vault/person/alice.md"]
        with patch("mykg.steps.step_validate_graph._cfg", cfg_mod):
            run_validate_graph(ctx)

    mock_obs.assert_called_once()


def test_run_validate_graph_skips_export_obsidian_when_disabled(tmp_path, monkeypatch):
    """run_validate_graph does not call export_obsidian when OBSIDIAN_ENABLED is False."""
    from unittest.mock import patch

    import mykg.config as cfg_mod

    monkeypatch.setattr(cfg_mod, "OBSIDIAN_ENABLED", False)

    ctx = _make_ctx(tmp_path)
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    ctx.nodes = [
        {
            "id": "person-alice",
            "type": "Person",
            "confidence": 0.9,
            "source_files": ["doc.md"],
            "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
        }
    ]
    ctx.edge_metadata = {}

    with patch("mykg.exporter.export_obsidian", create=True) as mock_obs:
        with patch("mykg.steps.step_validate_graph._cfg", cfg_mod):
            run_validate_graph(ctx)

    mock_obs.assert_not_called()


def test_export_step_not_llm_step():
    """The validate_graph Step must have is_llm_step=False."""
    from mykg.pipeline import STEPS

    export_step = next(s for s in STEPS if s.name == "validate_graph")
    assert export_step.is_llm_step is False


def test_schema_validate_records_both_attempts(tmp_path):
    """run_schema_validate writes both attempt results to schema_validation_errors.json."""
    import json
    from unittest.mock import MagicMock, patch

    from mykg.steps.step_schema import run_schema_validate

    (tmp_path / "schema.ttl").write_text("@prefix ex: <http://example.org/> .")
    (tmp_path / "schema.json").write_text('{"concepts": [], "properties": []}')

    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path

    first_result = MagicMock()
    first_result.valid = False
    first_result.errors = [{"message": "bad domain"}]

    second_result = MagicMock()
    second_result.valid = True
    second_result.errors = []

    side_effects = [first_result, second_result]
    with patch("mykg.steps.step_schema.validate_schema_ttl", side_effect=side_effects):
        with patch("mykg.steps.step_schema._apply_llm_correction"):
            run_schema_validate(ctx)

    errors_file = tmp_path / "schema_validation_errors.json"
    assert errors_file.exists()
    data = json.loads(errors_file.read_text())
    assert "first_attempt" in data
    assert "second_attempt" in data
    assert data["first_attempt"]["passed"] is False
    assert data["second_attempt"]["passed"] is True
    assert data["llm_correction_attempted"] is True


def test_schema_validate_no_errors_no_file_written(tmp_path):
    """run_schema_validate does not write errors file when schema passes first try."""
    from unittest.mock import MagicMock, patch

    from mykg.steps.step_schema import run_schema_validate

    (tmp_path / "schema.ttl").write_text("@prefix ex: <http://example.org/> .")
    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path

    ok_result = MagicMock()
    ok_result.valid = True
    ok_result.errors = []

    with patch("mykg.steps.step_schema.validate_schema_ttl", return_value=ok_result):
        run_schema_validate(ctx)

    assert not (tmp_path / "schema_validation_errors.json").exists()


def test_schema_validate_step_not_llm_step():
    """schema_validate Step must have is_llm_step=False (handles its own retry)."""
    from mykg.pipeline import STEPS

    step = next(s for s in STEPS if s.name == "schema_validate")
    assert step.is_llm_step is False


def test_synonym_index_has_exact_relations():
    """SynonymIndex.has_exact_relations() returns True when _exact is non-empty."""
    from mykg.thesaurus import SynonymIndex

    idx = SynonymIndex(term_count=2)
    assert idx.has_exact_relations() is False

    idx._add(idx.exact_matches, "Person", "Human")
    assert idx.has_exact_relations() is True


def test_synonym_index_has_close_relations():
    """SynonymIndex.has_close_relations() returns True when _close is non-empty."""
    from mykg.thesaurus import SynonymIndex

    idx = SynonymIndex(term_count=2)
    assert idx.has_close_relations() is False

    idx._add(idx.close_matches, "Company", "Organization")
    assert idx.has_close_relations() is True


def test_run_schema_validate_regenerates_ttl_when_missing(tmp_path):
    """run_schema_validate should regenerate schema.ttl from schema.json if the TTL is missing."""
    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    (tmp_path / "schema.json").write_text(json.dumps(schema))
    # Intentionally do NOT write schema.ttl

    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path

    run_schema_validate(ctx)  # should not raise

    assert (tmp_path / "schema.ttl").exists()
    ttl_content = (tmp_path / "schema.ttl").read_text()
    assert "Person" in ttl_content


def test_run_schema_validate_raises_when_neither_file_exists(tmp_path):
    """run_schema_validate raises FileNotFoundError when schema.ttl and schema.json are absent."""
    import pytest

    ctx = MagicMock()
    ctx.intermediate_dir = tmp_path

    with pytest.raises(FileNotFoundError, match="schema.ttl"):
        run_schema_validate(ctx)


def test_on_file_done_writes_shard_not_full_rewrite(tmp_path, monkeypatch):
    """on_file_done writes shard files; the monolithic raw_extractions.json is not written."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION

    ctx = _make_ctx(tmp_path, adapter)
    ctx.file_contents = {"a.md": "Alice at Acme.", "b.md": "Bob at Beta."}
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))

    raw_path = ctx.intermediate_dir / "raw_extractions.json"
    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"

    # Monolithic file must not exist before the step writes it at the end
    assert not raw_path.exists()

    run_pass2_step(ctx)

    # Shard dirs and individual shards must be written
    assert shard_dir.exists()
    assert chunk_shard_dir.exists()
    shards = list(shard_dir.glob("*.json"))
    assert len(shards) == 2

    # Each shard must carry _fname and data keys
    for shard in shards:
        content = json.loads(shard.read_text())
        assert "_fname" in content
        assert "data" in content

    # Monolithic file is also written at end of _run (via _log_and_write)
    assert raw_path.exists()


def test_shards_loaded_on_restart(tmp_path):
    """Shard files written on a previous run are loaded instead of re-extracting."""
    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION

    ctx = _make_ctx(tmp_path, adapter)
    ctx.file_contents = {"a.md": "Alice at Acme.", "b.md": "Bob at Beta."}
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))

    # Pre-populate shard dirs as if a previous run had completed both files
    shard_dir = ctx.intermediate_dir / "raw_extractions_shards"
    chunk_shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    chunk_shard_dir.mkdir()

    existing_extraction = {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.9,
                "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
            }
        ],
        "edges": [],
    }
    for fname in ("a.md", "b.md"):
        slug = _fname_slug(fname)
        (shard_dir / f"{slug}.json").write_text(
            json.dumps({"_fname": fname, "data": existing_extraction})
        )
        (chunk_shard_dir / f"{slug}.json").write_text(json.dumps({"_fname": fname, "data": {}}))

    run_pass2_step(ctx)

    # LLM should NOT be called — both files were already done via shards
    adapter.complete.assert_not_called()

    # Results from shards must be reflected in the monolithic output
    merged = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    assert "a.md" in merged
    assert "b.md" in merged


def test_backward_compat_monolithic_fallback(tmp_path, monkeypatch):
    """When no shard dir exists, monolithic raw_extractions.json is loaded as fallback."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS2_PREP_MODE", "per_file")

    adapter = MagicMock()
    adapter.complete.return_value = MOCK_EXTRACTION

    ctx = _make_ctx(tmp_path, adapter)
    ctx.file_contents = {"existing.md": "old content", "new.md": "Alice at Acme."}
    (ctx.intermediate_dir / "schema.json").write_text(json.dumps(SCHEMA))
    (ctx.intermediate_dir / "flattened_schema.json").write_text(json.dumps({"Person": ["name"]}))

    existing_extraction = {
        "nodes": [
            {
                "id": "person-bob",
                "type": "Person",
                "confidence": 0.8,
                "attributes": {"name": {"value": "Bob", "confidence": 0.8}},
            }
        ],
        "edges": [],
    }
    # Write only the monolithic file — no shard dirs
    (ctx.intermediate_dir / "raw_extractions.json").write_text(
        json.dumps({"existing.md": existing_extraction})
    )
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(json.dumps({"existing.md": {}}))

    run_pass2_step(ctx)

    merged = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text())
    # existing.md loaded from monolithic — NOT re-extracted
    assert merged["existing.md"]["nodes"][0]["id"] == "person-bob"
    # new.md extracted via LLM
    assert "new.md" in merged


def test_run_ingest_base_schema_missing_attributes_key(tmp_path):
    """_write_base_schema_parsed uses .get('attributes', []) — no KeyError when key absent."""
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "test.md").write_text("# Hello")

    ctx = MagicMock()
    ctx.input_dir = tmp_path / "input"
    ctx.intermediate_dir = tmp_path
    ctx.append = False
    ctx.ingest_workers = 1
    ctx.base_schema = {
        "_source": "base.ttl",
        "locked_classes": {
            "Person": {"type": "Person", "parent": None},  # no "attributes" key
        },
        "locked_properties": {},
    }
    ctx.thesaurus = None

    run_ingest(ctx)  # should not raise KeyError

    out = tmp_path / "base_schema_parsed.json"
    assert out.exists()
    data = json.loads(out.read_text())
    assert "Person" in data["locked_classes"]


def test_run_ingest_parallel_all_files_ingested(tmp_path):
    """Parallel ingest: all 3 .md files appear in file_contents and all_chunks."""
    ctx = _make_ctx(tmp_path)
    ctx.ingest_workers = 3
    (ctx.input_dir / "a.md").write_text("Alice works at Acme.")
    (ctx.input_dir / "b.md").write_text("Bob leads the team.")
    (ctx.input_dir / "c.md").write_text("Carol manages projects.")
    run_ingest(ctx)
    assert set(ctx.file_contents.keys()) == {"a.md", "b.md", "c.md"}
    sources = {c.source_file for c in ctx.all_chunks}
    assert sources == {"a.md", "b.md", "c.md"}


def test_run_ingest_chunk_order_is_sorted(tmp_path):
    """ctx.all_chunks is sorted by (source_file, chunk_index) after parallel ingest."""
    ctx = _make_ctx(tmp_path)
    ctx.ingest_workers = 3
    (ctx.input_dir / "z.md").write_text("Last file content.")
    (ctx.input_dir / "a.md").write_text("First file content.")
    (ctx.input_dir / "m.md").write_text("Middle file content.")
    run_ingest(ctx)
    keys = [(c.source_file, c.chunk_index) for c in ctx.all_chunks]
    assert keys == sorted(keys)


def test_run_ingest_skips_unreadable_file(tmp_path):
    """Parallel ingest skips files that raise OSError and still ingests readable files."""
    from pathlib import Path
    from unittest.mock import patch

    ctx = _make_ctx(tmp_path)
    ctx.ingest_workers = 2
    (ctx.input_dir / "good.md").write_text("Good content here.")
    bad_file = ctx.input_dir / "bad.md"
    bad_file.write_text("Will be mocked to fail.")

    original_read_text = Path.read_text

    def _patched_read_text(self, *args, **kwargs):
        if self.name == "bad.md":
            raise OSError("Permission denied")
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", _patched_read_text):
        run_ingest(ctx)  # must not raise

    assert "good.md" in ctx.file_contents
    assert "bad.md" not in ctx.file_contents


# ---------------------------------------------------------------------------
# normalize_names: chunk_node_index ID remapping (#120)
# ---------------------------------------------------------------------------


def _norm_llm_response(norm_map: dict) -> str:
    """Build the JSON string returned by a mock normalization LLM call."""
    return json.dumps(norm_map)


def test_normalize_names_remaps_chunk_node_index(tmp_path):
    """After normalization, chunk_node_index IDs are updated to canonical stable IDs."""
    from mykg.ids import stable_id
    from mykg.steps.step_normalize import run_normalize_names

    # "Al" is an alias for "Alice" in the LLM response
    norm_response = {"Person": {"Al": "Alice"}}
    adapter = MagicMock()
    adapter.complete.return_value = _norm_llm_response(norm_response)

    ctx = _make_ctx(tmp_path, adapter)

    old_id = stable_id("Person", "Al")
    new_id = stable_id("Person", "Alice")

    # Both "Al" and "Alice" must be in the inventory so the validator accepts the mapping
    alice_id = stable_id("Person", "Alice")
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": old_id,
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Al", "confidence": 0.9}},
                },
                {
                    "id": alice_id,
                    "type": "Person",
                    "confidence": 0.95,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.95}},
                },
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    chunk_idx = {"doc.md": {"0": [old_id, "organization-acme"]}}
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(json.dumps(chunk_idx))

    run_normalize_names(ctx)

    updated = json.loads((ctx.intermediate_dir / "chunk_node_index.json").read_text())
    ids_in_chunk = updated["doc.md"]["0"]
    assert new_id in ids_in_chunk
    assert old_id not in ids_in_chunk
    assert "organization-acme" in ids_in_chunk  # unchanged IDs preserved


def test_normalize_names_skips_remap_when_no_chunk_index(tmp_path):
    """Normalization does not raise if chunk_node_index.json is absent."""
    from mykg.steps.step_normalize import run_normalize_names

    norm_response = {"Person": {"Al": "Alice"}}
    adapter = MagicMock()
    adapter.complete.return_value = _norm_llm_response(norm_response)

    ctx = _make_ctx(tmp_path, adapter)

    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-al",
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Al", "confidence": 0.9}},
                },
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.95,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.95}},
                },
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    # Intentionally do NOT write chunk_node_index.json

    run_normalize_names(ctx)  # must not raise

    assert not (ctx.intermediate_dir / "chunk_node_index.json").exists()


def test_normalize_names_updates_shard_files(tmp_path):
    """Shard files in chunk_index_shards/ are updated alongside the monolithic file."""
    from mykg.ids import stable_id
    from mykg.steps.step_normalize import run_normalize_names

    norm_response = {"Person": {"Bob": "Robert"}}
    adapter = MagicMock()
    adapter.complete.return_value = _norm_llm_response(norm_response)

    ctx = _make_ctx(tmp_path, adapter)

    old_id = stable_id("Person", "Bob")
    new_id = stable_id("Person", "Robert")

    robert_id = stable_id("Person", "Robert")
    raw = {
        "notes.md": {
            "nodes": [
                {
                    "id": old_id,
                    "type": "Person",
                    "confidence": 0.8,
                    "attributes": {"name": {"value": "Bob", "confidence": 0.8}},
                },
                {
                    "id": robert_id,
                    "type": "Person",
                    "confidence": 0.9,
                    "attributes": {"name": {"value": "Robert", "confidence": 0.9}},
                },
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps({"notes.md": {"0": [old_id]}})
    )

    shard_dir = ctx.intermediate_dir / "chunk_index_shards"
    shard_dir.mkdir()
    shard_file = shard_dir / "notes_md.json"
    shard_file.write_text(json.dumps({"_fname": "notes.md", "data": {"0": [old_id]}}))

    run_normalize_names(ctx)

    shard = json.loads(shard_file.read_text())
    assert new_id in shard["data"]["0"]
    assert old_id not in shard["data"]["0"]
