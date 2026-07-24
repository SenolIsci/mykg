"""Terminal-callable knowledge-graph query, mirroring the MCP query tool.

This module replicates the algorithm of ``mykg_query_graph`` in
``src/mykg/mcp_server.py`` (the MCP tool named "query") so it can be driven
from the terminal via ``mykg query`` without importing or modifying the MCP
server. The MCP file is left untouched per an explicit user constraint; the
logic below is a byte-for-byte-compatible copy of the traversal, scoring, and
text formatting, using only MCP-free primitives.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from mykg.exporters.neo4j._common import load_session
from mykg.exporter import _build_nx_graph


def _node_name(node: dict) -> str:
    attrs = node.get("attributes") or {}
    name_attr = attrs.get("name")
    if isinstance(name_attr, dict):
        return name_attr.get("value") or ""
    return str(name_attr) if name_attr else ""


@dataclass
class QueryGraph:
    """In-memory index bundle for the terminal query path.

    Holds only the parts of the MCP ``KnowledgeGraph`` that the query
    traversal reads.
    """

    nodes: list[dict] = field(default_factory=list)
    nodes_by_id: dict[str, dict] = field(default_factory=dict)
    name_index: list[tuple[str, str, str]] = field(default_factory=list)
    edges_by_node: dict[str, list[dict]] = field(default_factory=dict)
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)


def build_query_graph(session_root: Path) -> QueryGraph:
    """Load a session and build the indexes the query traversal needs."""
    nodes, edges, _schema = load_session(session_root)
    edge_metadata = {e["id"]: e for e in edges}
    graph = _build_nx_graph(nodes, edge_metadata)

    qg = QueryGraph(nodes=nodes, graph=graph)

    for node in nodes:
        nid = node["id"]
        qg.nodes_by_id[nid] = node

        name_val = _node_name(node)
        if name_val:
            qg.name_index.append((name_val.lower(), nid, name_val))

        for alias in node.get("aliases") or []:
            qg.name_index.append((alias.lower(), nid, alias))

    for edge in edges:
        qg.edges_by_node.setdefault(edge["from"], []).append(edge)
        qg.edges_by_node.setdefault(edge["to"], []).append(edge)

    return qg


def query_graph(
    qg: QueryGraph,
    question: str,
    mode: str = "bfs",
    depth: int = 2,
    token_budget: int = 2000,
) -> str:
    """Search the knowledge graph using BFS or DFS traversal from seed nodes.

    Finds seed nodes matching the question, traverses outward, and returns a
    text context window of relevant nodes and edges. This is a line-for-line
    copy of ``mykg_query_graph``'s body (MCP tool), retargeted at ``qg``.
    """
    query_lower = question.lower()

    scored: list[tuple[int, str]] = []
    for name_lower, nid, _original in qg.name_index:
        if name_lower == query_lower:
            scored.append((100, nid))
        elif query_lower in name_lower or name_lower in query_lower:
            scored.append((60, nid))

    for node in qg.nodes:
        nid = node["id"]
        if any(nid == s[1] for s in scored):
            continue
        for _attr_name, attr_val in (node.get("attributes") or {}).items():
            val = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
            if val and isinstance(val, str) and query_lower in val.lower():
                scored.append((40, nid))
                break

    scored.sort(key=lambda x: -x[0])
    seeds = list(dict.fromkeys(s[1] for s in scored[:3]))

    if not seeds:
        return f"No nodes found matching '{question}'. Try mykg_search_nodes for more flexible search."

    undirected = qg.graph.to_undirected()
    visited: set[str] = set()
    traversal_edges: list[tuple[str, str, dict]] = []

    traverse = nx.dfs_edges if mode == "dfs" else nx.bfs_edges
    for seed in seeds:
        if seed not in undirected:
            continue
        for u, v in traverse(undirected, source=seed, depth_limit=depth):
            visited.add(u)
            visited.add(v)
            for e in qg.edges_by_node.get(u, []):
                if (e["from"] == u and e["to"] == v) or (e["from"] == v and e["to"] == u):
                    traversal_edges.append((e["from"], e["to"], e))
                    break
    visited.update(seeds)

    lines: list[str] = []
    lines.append(f"# Knowledge Graph Context: {question}")
    lines.append(f"Seeds: {', '.join(seeds)} | Mode: {mode} | Depth: {depth}")
    lines.append(f"Nodes visited: {len(visited)} | Edges found: {len(traversal_edges)}")
    lines.append("")

    lines.append("## Nodes")
    budget_chars = token_budget * 4
    for nid in visited:
        node = qg.nodes_by_id.get(nid)
        if not node:
            continue
        name = _node_name(node)
        ntype = node.get("type", "")
        conf = node.get("confidence", 0.0)
        attrs = []
        for attr_name, attr_val in (node.get("attributes") or {}).items():
            val = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
            if val and attr_name != "name":
                attrs.append(f"{attr_name}={val}")
        attr_str = f" ({', '.join(attrs)})" if attrs else ""
        lines.append(f"- [{ntype}] {name} ({nid}) conf={conf:.2f}{attr_str}")
        if sum(len(l) for l in lines) > budget_chars:
            lines.append("... (truncated to fit token budget)")
            break

    if sum(len(l) for l in lines) < budget_chars:
        lines.append("")
        lines.append("## Relationships")
        seen_edges: set[str] = set()
        for src, dst, edge in traversal_edges:
            eid = edge.get("id", f"{src}-{dst}")
            if eid in seen_edges:
                continue
            seen_edges.add(eid)
            etype = edge.get("type", "")
            conf = edge.get("confidence", 0.0)
            lines.append(f"- {src} --[{etype}]--> {dst} (conf={conf:.2f})")
            if sum(len(l) for l in lines) > budget_chars:
                lines.append("... (truncated to fit token budget)")
                break

    return "\n".join(lines)
