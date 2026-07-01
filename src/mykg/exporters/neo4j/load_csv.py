from __future__ import annotations

import csv
import io
from collections import defaultdict
from pathlib import Path

from ._common import (
    flatten_edge_properties,
    flatten_node_properties,
    sanitize_label,
    sanitize_rel_type,
)

ARRAY_SEP = ";"


def _serialize_cell(value) -> str:
    """Plain CSV cell. None -> empty. Lists -> ';'-joined. Everything else -> str."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ARRAY_SEP.join(str(v) for v in value)
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _collect_node_columns(rows: list[dict]) -> list[str]:
    """Union of all property keys across rows, excluding 'id'. Sorted deterministically."""
    seen: set[str] = set()
    for row in rows:
        for k in row["props"]:
            if k == "id":
                continue
            seen.add(k)
    return sorted(seen)


def _collect_edge_columns(rows: list[dict]) -> list[str]:
    """Union of all property keys across rows. Sorted deterministically."""
    seen: set[str] = set()
    for row in rows:
        for k in row["props"]:
            seen.add(k)
    return sorted(seen)


def _csv_text(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerows(rows)
    return buf.getvalue()


def build_plain_csvs(nodes: list[dict], edges: list[dict], schema: dict) -> dict[Path, str]:
    """Plain-header CSVs for LOAD CSV. No :ID, no :LABEL, no type decorations."""
    out: dict[Path, str] = {}

    nodes_by_label: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        label = sanitize_label(node["type"])
        nodes_by_label[label].append({"id": node["id"], "props": flatten_node_properties(node, schema)})

    for label, group in sorted(nodes_by_label.items()):
        group = sorted(group, key=lambda r: r["id"])
        columns = _collect_node_columns(group)
        header = ["id"] + columns
        body = []
        for row in group:
            cells = [row["id"]] + [_serialize_cell(row["props"].get(c)) for c in columns]
            body.append(cells)
        out[Path(f"nodes_{label}.csv")] = _csv_text([header] + body)

    edges_by_type: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        rel_type = sanitize_rel_type(edge["type"])
        edges_by_type[rel_type].append({
            "from": edge["from"],
            "to": edge["to"],
            "props": flatten_edge_properties(edge),
        })

    for rel_type, group in sorted(edges_by_type.items()):
        group = sorted(group, key=lambda r: (r["from"], r["to"]))
        columns = _collect_edge_columns(group)
        header = ["from", "to"] + columns
        body = []
        for row in group:
            cells = [row["from"], row["to"]] + [_serialize_cell(row["props"].get(c)) for c in columns]
            body.append(cells)
        out[Path(f"relationships_{rel_type}.csv")] = _csv_text([header] + body)

    return out


CONSTRAINT_STMT = (
    "CREATE CONSTRAINT _mykgnode_id_unique IF NOT EXISTS\n"
    "FOR (n:_MykgNode) REQUIRE n.id IS UNIQUE;"
)


def _cast_expr(column: str, column_type: str) -> str:
    """Return the inline CASE expression for one column.

    column_type: 'string', 'float', or 'list'.
    """
    if column_type == "float":
        return (
            f"CASE WHEN row.{column} = '' THEN null "
            f"ELSE toFloat(row.{column}) END"
        )
    if column_type == "list":
        return (
            f"CASE WHEN row.{column} = '' THEN [] "
            f"ELSE split(row.{column}, '{ARRAY_SEP}') END"
        )
    return f"CASE WHEN row.{column} = '' THEN null ELSE row.{column} END"


_NODE_LIST_COLUMNS = {"_parents", "_aliases", "_source_files"}
_NODE_FLOAT_COLUMNS = {"_node_confidence"}
_EDGE_LIST_COLUMNS = {"source_files"}
_EDGE_FLOAT_COLUMNS = {"confidence"}


def _node_column_type(column: str) -> str:
    if column in _NODE_LIST_COLUMNS:
        return "list"
    if column in _NODE_FLOAT_COLUMNS or column.endswith("_confidence"):
        return "float"
    return "string"


def _edge_column_type(column: str) -> str:
    if column in _EDGE_LIST_COLUMNS:
        return "list"
    if column in _EDGE_FLOAT_COLUMNS or column.endswith("_confidence"):
        return "float"
    return "string"


def _node_block(label: str, columns: list[str], csv_uri: str) -> str:
    set_lines = [
        f"      n.{c} = {_cast_expr(c, _node_column_type(c))}"
        for c in columns
    ]
    set_block = ",\n".join(set_lines)
    return (
        f":auto LOAD CSV WITH HEADERS FROM '{csv_uri}' AS row\n"
        f"CALL {{\n"
        f"  WITH row\n"
        f"  MERGE (n:_MykgNode {{id: row.id}})\n"
        f"  SET n:{label}\n"
        f"  SET\n"
        f"{set_block}\n"
        f"}} IN TRANSACTIONS OF 1000 ROWS;"
    )


def _edge_block(rel_type: str, columns: list[str], csv_uri: str) -> str:
    set_lines = [
        f"      r.{c} = {_cast_expr(c, _edge_column_type(c))}"
        for c in columns
    ]
    set_block = ",\n".join(set_lines)
    return (
        f":auto LOAD CSV WITH HEADERS FROM '{csv_uri}' AS row\n"
        f"CALL {{\n"
        f"  WITH row\n"
        f"  MATCH (a:_MykgNode {{id: row.from}})\n"
        f"  MATCH (b:_MykgNode {{id: row.to}})\n"
        f"  MERGE (a)-[r:{rel_type}]->(b)\n"
        f"  SET\n"
        f"{set_block}\n"
        f"}} IN TRANSACTIONS OF 1000 ROWS;"
    )


def _columns_from_csv(csv_text: str, leading: int) -> list[str]:
    """Header columns after the first `leading` fixed columns (id; or from,to)."""
    header_line = csv_text.splitlines()[0]
    cols = next(csv.reader([header_line]))
    return cols[leading:]


def _build_cypher_script(csvs: dict[Path, str], uri_for) -> str:
    """Render the Cypher script. uri_for(path) returns the LOAD CSV URI for one CSV.

    Single source of truth used by both build_browser_cypher and build_shell_cypher.
    """
    lines = [
        "// Generated by mykg emit_load_csv. Do not edit by hand.",
        "",
        "// 1. Constraint",
        CONSTRAINT_STMT,
        "",
        "// 2. Nodes — one block per label",
    ]
    node_paths = sorted(p for p in csvs if p.name.startswith("nodes_"))
    for path in node_paths:
        label = path.stem.removeprefix("nodes_")
        columns = _columns_from_csv(csvs[path], leading=1)
        lines.append("")
        lines.append(_node_block(label, columns, uri_for(path)))

    lines.append("")
    lines.append("// 3. Edges — one block per rel-type")
    edge_paths = sorted(p for p in csvs if p.name.startswith("relationships_"))
    for path in edge_paths:
        rel_type = path.stem.removeprefix("relationships_")
        columns = _columns_from_csv(csvs[path], leading=2)
        lines.append("")
        lines.append(_edge_block(rel_type, columns, uri_for(path)))

    return "\n".join(lines) + "\n"


def build_browser_cypher(csvs: dict[Path, str]) -> str:
    """Cypher script using relative file:/<name>.csv URIs.

    These resolve against the DBMS's import/ directory. User must copy CSVs there.
    """
    def uri_for(path: Path) -> str:
        return f"file:/{path.name}"
    return _build_cypher_script(csvs, uri_for)


def build_shell_cypher(csvs: dict[Path, str], out_dir_abs: Path) -> str:
    """Cypher script using absolute file:/// URIs.

    out_dir_abs must be an absolute path. Pass an unrelated placeholder (e.g.
    PurePosixPath('/FIXTURE_OUT_DIR')) when generating snapshots so the fixture
    is machine-independent on both Windows and Unix.

    Requires `dbms.security.allow_csv_import_from_file_urls=true` in neo4j.conf.
    """
    # Accept PurePosixPath from snapshot tests; only coerce plain strings.
    if not hasattr(out_dir_abs, "is_absolute"):
        out_dir_abs = Path(out_dir_abs)
    if not out_dir_abs.is_absolute():
        raise ValueError(f"out_dir_abs must be absolute, got: {out_dir_abs}")

    def uri_for(path: Path) -> str:
        return (out_dir_abs / path.name).as_uri()
    return _build_cypher_script(csvs, uri_for)


def build_readme(out_dir_abs: Path, csv_paths: list[Path]) -> str:
    """Per-run README explaining both import flows."""
    # Accept PurePosixPath from snapshot tests; only coerce plain strings.
    if not hasattr(out_dir_abs, "is_absolute"):
        out_dir_abs = Path(out_dir_abs)
    node_csvs = sorted(p for p in csv_paths if p.name.startswith("nodes_"))
    rel_csvs = sorted(p for p in csv_paths if p.name.startswith("relationships_"))
    shell_script_path = out_dir_abs / "import_shell.cypher"
    return (
        "# Neo4j LOAD CSV bundle\n"
        "\n"
        "Generated by `mykg emit_load_csv`. This directory contains:\n"
        "\n"
        f"- {len(node_csvs)} node CSV file(s): {', '.join(p.name for p in node_csvs)}\n"
        f"- {len(rel_csvs)} relationship CSV file(s): {', '.join(p.name for p in rel_csvs)}\n"
        "\n"
        "**Requires Neo4j 5.x or newer.** The Cypher uses `IN TRANSACTIONS OF`, modern `CREATE CONSTRAINT … REQUIRE … IS UNIQUE` syntax, and the `:auto` client directive — none of which work on Neo4j 4.x. The scripts are designed for **Neo4j Browser** and **`cypher-shell`**; they will not run unmodified over a Bolt session because of `:auto`.\n"
        "\n"
        "- `import_browser.cypher` — paste-and-run in Neo4j Browser (relative paths against the DBMS `import/` directory).\n"
        "- `import_shell.cypher` — for `cypher-shell -f`. Uses absolute `file:///` URIs rooted at this directory.\n"
        "\n"
        "## Flow A — Neo4j Browser\n"
        "\n"
        f"1. Copy every `*.csv` from `{out_dir_abs}` into your DBMS's `import/` directory.\n"
        "   In Neo4j Desktop: click your DBMS → \"...\" → \"Open folder\" → \"Import\".\n"
        "2. Open Neo4j Browser.\n"
        "3. Paste the contents of `import_browser.cypher` and press play.\n"
        "\n"
        "The script creates a uniqueness constraint, MERGEs every node by `id`, and MERGEs every edge.\n"
        "Re-running is safe and idempotent.\n"
        "\n"
        "## Flow B — cypher-shell\n"
        "\n"
        "One-time setup: in `neo4j.conf` set\n"
        "\n"
        "```\n"
        "dbms.security.allow_csv_import_from_file_urls=true\n"
        "```\n"
        "\n"
        "and restart the DBMS. Then run:\n"
        "\n"
        "```bash\n"
        f"cypher-shell -u neo4j -p <pw> -f '{shell_script_path}'\n"
        "```\n"
        "\n"
        "## Data model\n"
        "\n"
        "Each node carries:\n"
        "- Its leaf concept type as a single domain label (e.g. `:Person`).\n"
        "- A shared `:_MykgNode` label which owns the `id` uniqueness constraint.\n"
        "- Properties flattened from the source `nodes.jsonl` — every non-null attribute becomes `<name>` and `<name>_confidence`.\n"
        "- `_parents`, `_aliases` (when present in source), `_source_files` — list properties (`;`-separated in CSV, real Cypher lists after load).\n"
        "\n"
        "Each relationship carries:\n"
        "- `confidence`, `method`, `source_files`, plus `<attr>` and `<attr>_confidence` for every non-null attribute.\n"
    )


def export_neo4j_csv(
    nodes: list[dict],
    edge_metadata: dict,
    schema: dict,
    output_dir: Path,
) -> list[str]:
    """Write a Neo4j LOAD CSV bundle to ``output_dir/<NEO4J_CSV_DIR>/``.

    Returns a list of written file paths as relative strings (same contract as
    ``export_networkx`` and ``export_obsidian``). Returns an empty list when
    ``NEO4J_CSV_ENABLED`` is False.
    """
    from mykg import config as _cfg

    if not getattr(_cfg, "NEO4J_CSV_ENABLED", False):
        return []

    vault_dir = Path(output_dir) / _cfg.NEO4J_CSV_DIR
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_dir_abs = vault_dir.absolute()

    edges = list(edge_metadata.values())
    csvs = build_plain_csvs(nodes, edges, schema)

    written: list[str] = []
    for rel_path, content in csvs.items():
        (vault_dir / rel_path.name).write_text(content, encoding="utf-8")
        written.append(f"{_cfg.NEO4J_CSV_DIR}/{rel_path.name}")

    (vault_dir / "import_browser.cypher").write_text(build_browser_cypher(csvs), encoding="utf-8")
    written.append(f"{_cfg.NEO4J_CSV_DIR}/import_browser.cypher")

    (vault_dir / "import_shell.cypher").write_text(build_shell_cypher(csvs, vault_dir_abs), encoding="utf-8")
    written.append(f"{_cfg.NEO4J_CSV_DIR}/import_shell.cypher")

    (vault_dir / "README.md").write_text(build_readme(vault_dir_abs, list(csvs.keys())), encoding="utf-8")
    written.append(f"{_cfg.NEO4J_CSV_DIR}/README.md")

    return written
