from __future__ import annotations

from pathlib import Path

from mykg.exporters.neo4j._common import load_session
from mykg.exporters.neo4j.load_csv import build_plain_csvs, export_neo4j_csv

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "neo4j_sample_session"
EXPECTED_DIR = FIXTURE_ROOT / "expected_load_csv"


def test_plain_csv_file_set():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    names = {p.name for p in csvs.keys()}
    assert names == {
        "nodes_SoftwareEngineer.csv",
        "nodes_Person.csv",
        "nodes_Organization.csv",
        "relationships_WORKS_AT.csv",
        "relationships_KNOWS.csv",
        "relationships_LOCATED_IN.csv",
    }


def test_plain_csv_contents_match_snapshots():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    for path, content in csvs.items():
        expected_path = EXPECTED_DIR / path.name
        assert expected_path.exists(), f"missing expected CSV: {expected_path}"
        assert content == expected_path.read_text(), f"mismatch in {path.name}"


def test_node_csv_header_is_plain():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    person_csv = next(c for p, c in csvs.items() if p.name == "nodes_Person.csv")
    header = person_csv.splitlines()[0]
    assert ":ID" not in header
    assert ":LABEL" not in header
    assert ":string" not in header
    assert header.startswith("id,")


def test_rel_csv_header_is_plain():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    works_csv = next(c for p, c in csvs.items() if p.name == "relationships_WORKS_AT.csv")
    header = works_csv.splitlines()[0]
    assert ":START_ID" not in header
    assert ":END_ID" not in header
    assert ":TYPE" not in header
    assert header.startswith("from,to,")


def test_list_columns_use_semicolon_separator():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    se_csv = next(c for p, c in csvs.items() if p.name == "nodes_SoftwareEngineer.csv")
    assert "A. Smith;Alice Smith" in se_csv


from mykg.exporters.neo4j.load_csv import build_browser_cypher


def test_browser_cypher_matches_snapshot():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_browser_cypher(csvs)
    expected = (EXPECTED_DIR / "import_browser.cypher").read_text()
    assert cypher == expected


def test_browser_cypher_uses_relative_paths():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_browser_cypher(csvs)
    for line in cypher.splitlines():
        if "LOAD CSV WITH HEADERS FROM" in line:
            assert "'file:/" in line and "file:///" not in line, line


def test_constraint_query_present_in_browser_cypher():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_browser_cypher(csvs)
    assert cypher.count("CREATE CONSTRAINT _mykgnode_id_unique") == 1


def test_one_node_block_per_label_in_browser_cypher():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_browser_cypher(csvs)
    node_blocks = [line for line in cypher.splitlines() if "FROM 'file:/nodes_" in line]
    assert len(node_blocks) == 3


def test_one_edge_block_per_rel_type_in_browser_cypher():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_browser_cypher(csvs)
    edge_blocks = [line for line in cypher.splitlines() if "FROM 'file:/relationships_" in line]
    assert len(edge_blocks) == 3


from mykg.exporters.neo4j.load_csv import build_shell_cypher


def test_shell_cypher_matches_snapshot():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_shell_cypher(csvs, Path("/FIXTURE_OUT_DIR"))
    expected = (EXPECTED_DIR / "import_shell.cypher").read_text()
    assert cypher == expected


def test_shell_cypher_uses_absolute_paths():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    cypher = build_shell_cypher(csvs, Path("/FIXTURE_OUT_DIR"))
    for line in cypher.splitlines():
        if "LOAD CSV WITH HEADERS FROM" in line:
            assert "'file:///" in line, line
            assert "'file:/nodes_" not in line and "'file:/relationships_" not in line, line


def test_shell_cypher_has_same_block_count_as_browser():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    browser = build_browser_cypher(csvs)
    shell = build_shell_cypher(csvs, Path("/FIXTURE_OUT_DIR"))
    assert browser.count("LOAD CSV WITH HEADERS FROM") == shell.count("LOAD CSV WITH HEADERS FROM")
    assert browser.count("CREATE CONSTRAINT") == shell.count("CREATE CONSTRAINT") == 1


import pytest


def test_shell_cypher_rejects_relative_out_dir():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    with pytest.raises(ValueError, match="absolute"):
        build_shell_cypher(csvs, Path("relative/path"))


from mykg.exporters.neo4j.load_csv import build_readme


def test_readme_matches_snapshot():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    readme = build_readme(Path("/FIXTURE_OUT_DIR"), list(csvs.keys()))
    expected = (EXPECTED_DIR / "README.md").read_text()
    assert readme == expected


def test_readme_mentions_both_flows():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    readme = build_readme(Path("/FIXTURE_OUT_DIR"), list(csvs.keys()))
    assert "Neo4j Browser" in readme
    assert "cypher-shell" in readme
    assert "import_browser.cypher" in readme
    assert "import_shell.cypher" in readme


import csv as csv_module


def test_round_trip_referential_integrity():
    """Every from/to in emitted relationship CSVs exists as id in some node CSV."""
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)

    all_node_ids: set[str] = set()
    for path, content in csvs.items():
        if not path.name.startswith("nodes_"):
            continue
        reader = csv_module.reader(content.splitlines())
        header = next(reader)
        id_col = header.index("id")
        for row in reader:
            all_node_ids.add(row[id_col])

    for path, content in csvs.items():
        if not path.name.startswith("relationships_"):
            continue
        reader = csv_module.reader(content.splitlines())
        header = next(reader)
        from_col = header.index("from")
        to_col = header.index("to")
        for row in reader:
            assert row[from_col] in all_node_ids, f"unknown from in {path.name}: {row[from_col]}"
            assert row[to_col] in all_node_ids, f"unknown to in {path.name}: {row[to_col]}"


# ---------------------------------------------------------------------------
# export_neo4j_csv (pipeline integration shim) tests
# ---------------------------------------------------------------------------


def _fixture_inputs():
    """Load the fixture in the dict-shape that step_validate_graph passes in."""
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    edge_metadata = {f"edge-{i:03d}": e for i, e in enumerate(edges, start=1)}
    return nodes, edge_metadata, schema


def test_export_neo4j_csv_returns_empty_when_disabled(tmp_path, monkeypatch):
    """export_neo4j_csv returns [] when NEO4J_CSV_ENABLED is False."""
    import mykg.config as _cfg

    monkeypatch.setattr(_cfg, "NEO4J_CSV_ENABLED", False, raising=False)
    nodes, edge_metadata, schema = _fixture_inputs()
    result = export_neo4j_csv(nodes, edge_metadata, schema, tmp_path)
    assert result == []
    assert not (tmp_path / "neo4j_csv").exists()


def test_export_neo4j_csv_writes_full_bundle(tmp_path, monkeypatch):
    """When enabled, the bundle dir holds every CSV + both scripts + README."""
    import mykg.config as _cfg

    monkeypatch.setattr(_cfg, "NEO4J_CSV_ENABLED", True, raising=False)
    monkeypatch.setattr(_cfg, "NEO4J_CSV_DIR", "neo4j_csv", raising=False)

    nodes, edge_metadata, schema = _fixture_inputs()
    written = export_neo4j_csv(nodes, edge_metadata, schema, tmp_path)

    vault = tmp_path / "neo4j_csv"
    assert vault.is_dir()
    expected_files = {
        "nodes_SoftwareEngineer.csv",
        "nodes_Person.csv",
        "nodes_Organization.csv",
        "relationships_WORKS_AT.csv",
        "relationships_KNOWS.csv",
        "relationships_LOCATED_IN.csv",
        "import_browser.cypher",
        "import_shell.cypher",
        "README.md",
    }
    actual_files = {p.name for p in vault.iterdir()}
    assert actual_files == expected_files

    # `written` reports the relative paths, prefixed with the vault dir name
    assert set(written) == {f"neo4j_csv/{name}" for name in expected_files}


def test_export_neo4j_csv_honors_custom_dir_name(tmp_path, monkeypatch):
    """NEO4J_CSV_DIR controls the output subdirectory name."""
    import mykg.config as _cfg

    monkeypatch.setattr(_cfg, "NEO4J_CSV_ENABLED", True, raising=False)
    monkeypatch.setattr(_cfg, "NEO4J_CSV_DIR", "my_neo4j_dump", raising=False)

    nodes, edge_metadata, schema = _fixture_inputs()
    written = export_neo4j_csv(nodes, edge_metadata, schema, tmp_path)

    assert (tmp_path / "my_neo4j_dump").is_dir()
    assert not (tmp_path / "neo4j_csv").exists()
    assert all(p.startswith("my_neo4j_dump/") for p in written)


def test_export_neo4j_csv_shell_script_uses_absolute_uris(tmp_path, monkeypatch):
    """import_shell.cypher must use absolute file:// URIs rooted at the vault."""
    import mykg.config as _cfg

    monkeypatch.setattr(_cfg, "NEO4J_CSV_ENABLED", True, raising=False)
    monkeypatch.setattr(_cfg, "NEO4J_CSV_DIR", "neo4j_csv", raising=False)

    nodes, edge_metadata, schema = _fixture_inputs()
    export_neo4j_csv(nodes, edge_metadata, schema, tmp_path)

    shell_cypher = (tmp_path / "neo4j_csv" / "import_shell.cypher").read_text()
    vault_uri_prefix = (tmp_path / "neo4j_csv").absolute().as_uri()
    assert vault_uri_prefix in shell_cypher
