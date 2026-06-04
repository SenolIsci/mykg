from __future__ import annotations

import json
import re
from pathlib import Path


def load_session(session_root: Path) -> tuple[list[dict], list[dict], dict]:
    """Read nodes.jsonl, edges.jsonl, and intermediate/schema.json from a session.

    Returns (nodes, edges, schema). Raises FileNotFoundError with a clear path
    if any required file is missing.
    """
    session_root = Path(session_root)
    nodes_path = session_root / "output" / "nodes.jsonl"
    edges_path = session_root / "output" / "edges.jsonl"
    schema_path = session_root / "intermediate" / "schema.json"

    if not nodes_path.exists():
        raise FileNotFoundError(f"nodes.jsonl not found at {nodes_path}")
    if not edges_path.exists():
        raise FileNotFoundError(f"edges.jsonl not found at {edges_path}")
    if not schema_path.exists():
        raise FileNotFoundError(f"schema.json not found at {schema_path}")

    nodes = [json.loads(line) for line in nodes_path.read_text().splitlines() if line.strip()]
    edges = [json.loads(line) for line in edges_path.read_text().splitlines() if line.strip()]
    schema = json.loads(schema_path.read_text())
    return nodes, edges, schema


_CAMEL_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")


def sanitize_label(raw: str) -> str:
    """Sanitize a concept type name to PascalCase Cypher label.

    Strips non-alphanumeric characters, splits on word boundaries, capitalizes each
    part. Leading digits are dropped because Cypher labels cannot start with a digit.
    """
    parts = re.findall(r"[A-Za-z]+|\d+", raw)
    cleaned: list[str] = []
    for part in parts:
        if part.isdigit() and not cleaned:
            continue
        cleaned.append(part)
    expanded: list[str] = []
    for part in cleaned:
        sub = _CAMEL_SPLIT_RE.findall(part)
        expanded.extend(sub if sub else [part])
    return "".join(p.capitalize() for p in expanded if p)


def sanitize_rel_type(raw: str) -> str:
    """Sanitize a relationship property name to SCREAMING_SNAKE_CASE."""
    parts = _CAMEL_SPLIT_RE.findall(raw)
    return "_".join(p.upper() for p in parts if p)


def parent_chain(schema: dict, type_name: str) -> list[str]:
    """Walk concepts[].parent from type_name up to a root.

    Returns ancestor types in order from immediate parent to root.
    Unknown types and root types both return []. Cycles are broken on
    re-visit of any previously-seen type.
    """
    by_type = {c["type"]: c.get("parent") for c in schema.get("concepts", [])}
    if type_name not in by_type:
        return []
    chain: list[str] = []
    seen = {type_name}
    current = by_type.get(type_name)
    while current is not None:
        if current in seen:
            break
        chain.append(current)
        seen.add(current)
        current = by_type.get(current)
    return chain


def flatten_node_properties(node: dict, schema: dict) -> dict:
    """Produce the Cypher property dict for a node.

    - Every attribute with a non-null value becomes `<name>` + `<name>_confidence`.
    - Null-valued attributes are omitted entirely.
    - `_node_confidence`, `_parents`, `_source_files` always present.
    - `_aliases` present iff the source record has an `aliases` key (may be empty list).
    """
    props: dict = {"id": node["id"]}
    for attr_name, attr_val in (node.get("attributes") or {}).items():
        value = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
        if value is None:
            continue
        props[attr_name] = value
        if isinstance(attr_val, dict) and attr_val.get("confidence") is not None:
            props[f"{attr_name}_confidence"] = attr_val["confidence"]
    props["_node_confidence"] = node.get("confidence")
    props["_parents"] = parent_chain(schema, node["type"])
    if "aliases" in node:
        props["_aliases"] = node["aliases"]
    props["_source_files"] = node.get("source_files", [])
    return props


def flatten_edge_properties(edge: dict) -> dict:
    """Produce the Cypher property dict for an edge.

    `confidence`, `method`, `source_files` always present. Each non-null attribute
    becomes `<name>` + `<name>_confidence`. Null-valued attributes are omitted.
    """
    props: dict = {"confidence": edge.get("confidence")}
    for attr_name, attr_val in (edge.get("attributes") or {}).items():
        value = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
        if value is None:
            continue
        props[attr_name] = value
        if isinstance(attr_val, dict) and attr_val.get("confidence") is not None:
            props[f"{attr_name}_confidence"] = attr_val["confidence"]
    props["method"] = edge.get("method")
    props["source_files"] = edge.get("source_files", [])
    return props
