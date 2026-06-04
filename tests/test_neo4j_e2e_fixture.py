from __future__ import annotations

import csv
import io
from pathlib import Path

from mykg.exporters.neo4j._common import load_session
from mykg.exporters.neo4j.load_csv import build_plain_csvs

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "neo4j_sample_session"


def _parse_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    reader = csv.reader(io.StringIO(text))
    header = next(reader)
    rows = [dict(zip(header, r)) for r in reader]
    return header, rows


def test_label_distribution():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    counts = {}
    for path, text in csvs.items():
        if path.name.startswith("nodes_"):
            label = path.stem[len("nodes_"):]
            _, rows = _parse_csv(text)
            counts[label] = len(rows)
    assert counts == {"SoftwareEngineer": 1, "Person": 2, "Organization": 3}


def test_rel_type_distribution():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    counts = {}
    for path, text in csvs.items():
        if path.name.startswith("relationships_"):
            rel_type = path.stem[len("relationships_"):]
            _, rows = _parse_csv(text)
            counts[rel_type] = len(rows)
    assert counts == {"WORKS_AT": 3, "KNOWS": 2, "LOCATED_IN": 1}


def test_referential_integrity():
    """Every from/to in a relationships CSV must resolve to an id in some nodes CSV."""
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)

    all_node_ids: set[str] = set()
    for path, text in csvs.items():
        if path.name.startswith("nodes_"):
            _, rows = _parse_csv(text)
            all_node_ids.update(r["id"] for r in rows)

    for path, text in csvs.items():
        if path.name.startswith("relationships_"):
            _, rows = _parse_csv(text)
            for r in rows:
                assert r["from"] in all_node_ids, f"unknown from: {r['from']} in {path.name}"
                assert r["to"] in all_node_ids, f"unknown to: {r['to']} in {path.name}"


def test_every_node_csv_has_mandatory_columns():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    for path, text in csvs.items():
        if path.name.startswith("nodes_"):
            header, _ = _parse_csv(text)
            for col in ("id", "_node_confidence", "_parents", "_source_files"):
                assert col in header, f"missing {col} in {path.name}"


def test_every_edge_csv_has_mandatory_columns():
    nodes, edges, schema = load_session(FIXTURE_ROOT)
    csvs = build_plain_csvs(nodes, edges, schema)
    for path, text in csvs.items():
        if path.name.startswith("relationships_"):
            header, _ = _parse_csv(text)
            for col in ("from", "to", "confidence", "method", "source_files"):
                assert col in header, f"missing {col} in {path.name}"
