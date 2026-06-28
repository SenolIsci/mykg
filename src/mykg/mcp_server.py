"""MCP server exposing a mykg knowledge graph session for LLM-powered Q&A.

Loads nodes.jsonl, edges.jsonl, and schema.json from a session, builds an
in-memory NetworkX DiGraph, and exposes 11 query tools + 2 resources via the
Model Context Protocol.
"""
from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import networkx as nx

from mykg.exporters.neo4j._common import load_session
from mykg.exporter import _build_nx_graph

# ---------------------------------------------------------------------------
# KnowledgeGraph — in-memory session data + indexes
# ---------------------------------------------------------------------------


@dataclass
class KnowledgeGraph:
    """In-memory knowledge graph loaded from a mykg session."""

    session_root: Path
    nodes: list[dict] = field(default_factory=list)
    edges: list[dict] = field(default_factory=list)
    schema: dict = field(default_factory=dict)
    graph: nx.DiGraph = field(default_factory=nx.DiGraph)

    nodes_by_id: dict[str, dict] = field(default_factory=dict)
    nodes_by_type: dict[str, list[dict]] = field(default_factory=dict)
    edges_by_node: dict[str, list[dict]] = field(default_factory=dict)
    name_index: list[tuple[str, str, str]] = field(default_factory=list)
    alias_index: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.nodes, self.edges, self.schema = load_session(self.session_root)
        edge_metadata = {e["id"]: e for e in self.edges}
        self.graph = _build_nx_graph(self.nodes, edge_metadata)
        self._build_indexes()

    def _build_indexes(self) -> None:
        for node in self.nodes:
            nid = node["id"]
            self.nodes_by_id[nid] = node

            ntype = node.get("type", "Unknown")
            self.nodes_by_type.setdefault(ntype, []).append(node)

            name_val = _node_name(node)
            if name_val:
                self.name_index.append((name_val.lower(), nid, name_val))

            for alias in node.get("aliases") or []:
                self.alias_index[alias.lower()] = nid
                self.name_index.append((alias.lower(), nid, alias))

        for edge in self.edges:
            self.edges_by_node.setdefault(edge["from"], []).append(edge)
            self.edges_by_node.setdefault(edge["to"], []).append(edge)

    def reload(self, session_root: Path | None = None) -> None:
        """Re-read session files and rebuild the in-memory graph + indexes."""
        if session_root is not None:
            self.session_root = session_root
        self.nodes, self.edges, self.schema = load_session(self.session_root)
        edge_metadata = {e["id"]: e for e in self.edges}
        self.graph = _build_nx_graph(self.nodes, edge_metadata)
        self.nodes_by_id = {}
        self.nodes_by_type = {}
        self.edges_by_node = {}
        self.name_index = []
        self.alias_index = {}
        self._build_indexes()

    @property
    def session_name(self) -> str:
        return self.session_root.name

    @property
    def vault_dir(self) -> Path | None:
        d = self.session_root / "output" / "obsidian_vault"
        return d if d.is_dir() else None


def _node_name(node: dict) -> str:
    attrs = node.get("attributes") or {}
    name_attr = attrs.get("name")
    if isinstance(name_attr, dict):
        return name_attr.get("value") or ""
    return str(name_attr) if name_attr else ""


def _node_summary(node: dict) -> dict:
    return {
        "id": node["id"],
        "type": node.get("type", ""),
        "name": _node_name(node),
        "confidence": node.get("confidence", 0.0),
    }


# ---------------------------------------------------------------------------
# FastMCP server setup
# ---------------------------------------------------------------------------

try:
    from mcp.server.fastmcp import FastMCP, Context
except ImportError:
    print(
        "error: mcp package not installed. Run: pip install 'mcp>=1.0'",
        file=sys.stderr,
    )
    raise


@dataclass
class AppContext:
    kg: KnowledgeGraph
    sessions_root: Path


@asynccontextmanager
async def _lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    session_root: Path = server._mykg_session_root  # type: ignore[attr-defined]
    sessions_root: Path = session_root.parent
    kg = KnowledgeGraph(session_root=session_root)
    print(
        f"mykg MCP: loaded {len(kg.nodes)} nodes, {len(kg.edges)} edges "
        f"from session {kg.session_name}",
        file=sys.stderr,
    )
    yield AppContext(kg=kg, sessions_root=sessions_root)


mcp = FastMCP("mykg_mcp", lifespan=_lifespan)


def _get_kg(ctx: Context) -> KnowledgeGraph:
    return ctx.request_context.lifespan_context.kg


# ---------------------------------------------------------------------------
# MCP Tools — direct parameters (FastMCP auto-generates input schema)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="mykg_search_nodes",
    annotations={
        "title": "Search Knowledge Graph Nodes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_search_nodes(
    query: str,
    ctx: Context,
    type: str | None = None,
    limit: int = 20,
) -> str:
    """Search for entities in the knowledge graph by name, alias, or attribute value.

    Matches are ranked: exact > prefix > substring > alias > attribute value.
    Use this to discover node IDs before calling mykg_get_node or mykg_get_neighbors.
    """
    kg = _get_kg(ctx)
    query_lower = query.lower()
    scored: list[tuple[int, dict, str]] = []

    for name_lower, nid, original in kg.name_index:
        node = kg.nodes_by_id[nid]
        if type and node.get("type") != type:
            continue
        if name_lower == query_lower:
            scored.append((100, node, f"exact: {original}"))
        elif name_lower.startswith(query_lower):
            scored.append((80, node, f"prefix: {original}"))
        elif query_lower in name_lower:
            scored.append((60, node, f"substring: {original}"))

    type_nodes = kg.nodes_by_type.get(type, []) if type else kg.nodes
    for node in type_nodes:
        nid = node["id"]
        if any(nid == s[1]["id"] for s in scored):
            continue
        for attr_name, attr_val in (node.get("attributes") or {}).items():
            val = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
            if val and isinstance(val, str) and query_lower in val.lower():
                scored.append((40, node, f"attr:{attr_name}={val}"))
                break

    scored.sort(key=lambda x: -x[0])
    results = []
    seen: set[str] = set()
    for _score, node, match_field in scored[:limit]:
        if node["id"] in seen:
            continue
        seen.add(node["id"])
        results.append({**_node_summary(node), "match_field": match_field})

    if not results:
        return f"No nodes found matching '{query}'. Use mykg_list_node_types to see available types."
    return json.dumps(results, indent=2)


@mcp.tool(
    name="mykg_get_node",
    annotations={
        "title": "Get Node Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_get_node(node_id: str, ctx: Context) -> str:
    """Get full details for a node by its stable ID.

    Returns all attributes with confidence scores, source files, and aliases.
    Use mykg_search_nodes first to find valid node IDs.
    """
    kg = _get_kg(ctx)
    node = kg.nodes_by_id.get(node_id)
    if node is None:
        return f"Error: Node '{node_id}' not found. Use mykg_search_nodes to find valid IDs."
    return json.dumps(node, indent=2)


@mcp.tool(
    name="mykg_get_neighbors",
    annotations={
        "title": "Get Node Neighbors",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_get_neighbors(
    node_id: str,
    ctx: Context,
    direction: str = "both",
    edge_type: str | None = None,
    limit: int = 50,
) -> str:
    """Get direct neighbors of a node with edge details.

    Returns edges connecting to/from this node and summaries of neighbor nodes.
    Direction can be 'outgoing', 'incoming', or 'both'.
    """
    kg = _get_kg(ctx)
    if node_id not in kg.nodes_by_id:
        return f"Error: Node '{node_id}' not found. Use mykg_search_nodes to find valid IDs."

    all_edges = kg.edges_by_node.get(node_id, [])
    filtered: list[dict] = []
    for edge in all_edges:
        if direction == "outgoing" and edge["from"] != node_id:
            continue
        if direction == "incoming" and edge["to"] != node_id:
            continue
        if edge_type and edge.get("type") != edge_type:
            continue
        filtered.append(edge)

    filtered = filtered[:limit]
    neighbor_ids = set()
    for e in filtered:
        neighbor_ids.add(e["from"] if e["to"] == node_id else e["to"])

    neighbors = [_node_summary(kg.nodes_by_id[nid]) for nid in neighbor_ids if nid in kg.nodes_by_id]

    return json.dumps({
        "node_id": node_id,
        "direction": direction,
        "edge_count": len(filtered),
        "edges": filtered,
        "neighbors": neighbors,
    }, indent=2)


@mcp.tool(
    name="mykg_find_path",
    annotations={
        "title": "Find Shortest Path",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_find_path(
    from_id: str,
    to_id: str,
    ctx: Context,
    max_hops: int = 5,
) -> str:
    """Find the shortest path between two nodes.

    Tries directed path first, falls back to undirected. Returns the sequence
    of nodes and edges along the path.
    """
    kg = _get_kg(ctx)
    for nid in (from_id, to_id):
        if nid not in kg.nodes_by_id:
            return f"Error: Node '{nid}' not found. Use mykg_search_nodes to find valid IDs."

    if not nx.has_path(kg.graph, from_id, to_id):
        undirected = kg.graph.to_undirected()
        if not nx.has_path(undirected, from_id, to_id):
            return f"No path found between '{from_id}' and '{to_id}'."
        try:
            path = nx.shortest_path(undirected, from_id, to_id)
        except nx.NetworkXNoPath:
            return f"No path found between '{from_id}' and '{to_id}'."
    else:
        path = nx.shortest_path(kg.graph, from_id, to_id)

    if len(path) - 1 > max_hops:
        return f"No path found between '{from_id}' and '{to_id}' within {max_hops} hops (shortest is {len(path) - 1})."

    hops = []
    for i in range(len(path) - 1):
        src, dst = path[i], path[i + 1]
        edge_info = None
        for e in kg.edges_by_node.get(src, []):
            if (e["from"] == src and e["to"] == dst) or (e["from"] == dst and e["to"] == src):
                edge_info = {"type": e.get("type"), "confidence": e.get("confidence")}
                break
        hops.append({"from": src, "to": dst, "edge": edge_info})

    return json.dumps({
        "path": [_node_summary(kg.nodes_by_id[nid]) for nid in path],
        "hops": hops,
        "length": len(path) - 1,
    }, indent=2)


@mcp.tool(
    name="mykg_get_schema",
    annotations={
        "title": "Get Knowledge Graph Schema",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_get_schema(ctx: Context) -> str:
    """Get the full schema: concept types with hierarchy and relationship properties."""
    kg = _get_kg(ctx)
    return json.dumps(kg.schema, indent=2)


@mcp.tool(
    name="mykg_list_node_types",
    annotations={
        "title": "List Node Types",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_list_node_types(ctx: Context) -> str:
    """List all concept types with instance counts, sorted descending."""
    kg = _get_kg(ctx)
    type_list = []
    for ntype, nodes in sorted(kg.nodes_by_type.items(), key=lambda x: -len(x[1])):
        type_list.append({
            "type": ntype,
            "count": len(nodes),
            "sample_ids": [n["id"] for n in nodes[:3]],
        })
    return json.dumps(type_list, indent=2)


@mcp.tool(
    name="mykg_query_subgraph",
    annotations={
        "title": "Query Subgraph",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_query_subgraph(
    ctx: Context,
    node_ids: list[str] | None = None,
    types: list[str] | None = None,
    min_confidence: float = 0.0,
) -> str:
    """Extract a filtered subgraph by node IDs, types, and/or minimum confidence."""
    kg = _get_kg(ctx)
    filtered_nodes: list[dict] = []

    for node in kg.nodes:
        if node_ids and node["id"] not in node_ids:
            continue
        if types and node.get("type") not in types:
            continue
        if node.get("confidence", 0.0) < min_confidence:
            continue
        filtered_nodes.append(node)

    filtered_ids = {n["id"] for n in filtered_nodes}
    filtered_edges = [
        e for e in kg.edges
        if e["from"] in filtered_ids and e["to"] in filtered_ids
    ]

    return json.dumps({
        "nodes": [_node_summary(n) for n in filtered_nodes],
        "edges": filtered_edges,
        "stats": {"node_count": len(filtered_nodes), "edge_count": len(filtered_edges)},
    }, indent=2)


@mcp.tool(
    name="mykg_get_stats",
    annotations={
        "title": "Get Graph Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_get_stats(ctx: Context) -> str:
    """Get summary statistics: node/edge counts, type distribution, density, components, avg degree."""
    kg = _get_kg(ctx)
    G = kg.graph
    type_dist = {t: len(ns) for t, ns in sorted(kg.nodes_by_type.items(), key=lambda x: -len(x[1]))}

    source_files: set[str] = set()
    for node in kg.nodes:
        source_files.update(node.get("source_files") or [])

    session_root = kg.session_root.resolve()
    intermediate = session_root / "intermediate"

    original_input_dir = None
    raw_input_path = intermediate / "raw_input_folder.json"
    try:
        if raw_input_path.exists():
            original_input_dir = json.loads(raw_input_path.read_text(encoding="utf-8")).get("original_input_dir")
    except (json.JSONDecodeError, OSError):
        pass
    if original_input_dir is None:
        log_path = session_root / "run.log"
        try:
            if log_path.exists():
                for line in log_path.read_text(encoding="utf-8").splitlines()[:5]:
                    if "extract-graph " in line:
                        original_input_dir = line.split("extract-graph ", 1)[1].split(" --")[0].strip()
                        break
        except OSError:
            pass

    working_directory = None
    working_dir_path = intermediate / "working_directory.json"
    try:
        if working_dir_path.exists():
            working_directory = json.loads(working_dir_path.read_text(encoding="utf-8")).get("working_directory")
    except (json.JSONDecodeError, OSError):
        pass

    return json.dumps({
        "session_name": kg.session_name,
        "session_root": str(session_root),
        "working_directory": working_directory,
        "original_input_dir": original_input_dir,
        "input_dir": str(session_root / "input"),
        "output_dir": str(session_root / "output"),
        "intermediate_dir": str(session_root / "intermediate"),
        "has_vault": kg.vault_dir is not None,
        "node_count": G.number_of_nodes(),
        "edge_count": G.number_of_edges(),
        "type_distribution": type_dist,
        "density": round(nx.density(G), 6),
        "weakly_connected_components": nx.number_weakly_connected_components(G),
        "avg_degree": round(sum(d for _, d in G.degree()) / max(G.number_of_nodes(), 1), 2),
        "source_file_count": len(source_files),
    }, indent=2)


@mcp.tool(
    name="mykg_query_graph",
    annotations={
        "title": "Query Graph with Traversal",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_query_graph(
    question: str,
    ctx: Context,
    mode: str = "bfs",
    depth: int = 2,
    token_budget: int = 2000,
) -> str:
    """Search the knowledge graph using BFS or DFS traversal from seed nodes.

    Finds seed nodes matching the question, traverses outward, and returns a
    text context window of relevant nodes and edges for the LLM to reason over.
    """
    kg = _get_kg(ctx)
    query_lower = question.lower()

    scored: list[tuple[int, str]] = []
    for name_lower, nid, _original in kg.name_index:
        if name_lower == query_lower:
            scored.append((100, nid))
        elif query_lower in name_lower or name_lower in query_lower:
            scored.append((60, nid))

    for node in kg.nodes:
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

    undirected = kg.graph.to_undirected()
    visited: set[str] = set()
    traversal_edges: list[tuple[str, str, dict]] = []

    traverse = nx.dfs_edges if mode == "dfs" else nx.bfs_edges
    for seed in seeds:
        if seed not in undirected:
            continue
        for u, v in traverse(undirected, source=seed, depth_limit=depth):
            visited.add(u)
            visited.add(v)
            for e in kg.edges_by_node.get(u, []):
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
        node = kg.nodes_by_id.get(nid)
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


@mcp.tool(
    name="mykg_hub_nodes",
    annotations={
        "title": "Find Hub Nodes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_hub_nodes(ctx: Context, top_n: int = 10) -> str:
    """Return the most connected nodes by degree — the core entities of the graph."""
    kg = _get_kg(ctx)
    G = kg.graph
    degree_list = sorted(G.degree(), key=lambda x: -x[1])[:top_n]

    hubs = []
    for nid, degree in degree_list:
        node = kg.nodes_by_id.get(nid)
        if not node:
            continue
        hubs.append({
            **_node_summary(node),
            "degree": degree,
            "in_degree": G.in_degree(nid),
            "out_degree": G.out_degree(nid),
        })
    return json.dumps(hubs, indent=2)


@mcp.tool(
    name="mykg_orphan_nodes",
    annotations={
        "title": "Find Orphan Nodes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_orphan_nodes(ctx: Context) -> str:
    """Find all orphan nodes — entities with zero connections (no edges).

    These are isolated nodes that are not connected to any other entity in the
    graph. Useful for identifying extraction gaps or singleton entities.
    """
    kg = _get_kg(ctx)
    orphans = []
    for node in kg.nodes:
        if not kg.edges_by_node.get(node["id"], []):
            orphans.append(_node_summary(node))

    if not orphans:
        return "No orphan nodes found — all nodes have at least one connection."
    return json.dumps({
        "orphan_count": len(orphans),
        "total_nodes": len(kg.nodes),
        "orphans": orphans,
    }, indent=2)


@mcp.tool(
    name="mykg_read_note",
    annotations={
        "title": "Read Obsidian Vault LLM Wiki Note",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_read_note(node_id: str, ctx: Context) -> str:
    """Read the LLM wiki note for an entity from the Obsidian vault.

    The vault is a wikilinked knowledge base generated from the knowledge graph —
    each entity has a markdown note with attributes, relationships, and [[wikilinks]]
    to related entities. Use this for human-readable context about an entity.
    Falls back to a formatted summary from the graph if no vault exists.
    """
    kg = _get_kg(ctx)
    node = kg.nodes_by_id.get(node_id)
    if node is None:
        return f"Error: Node '{node_id}' not found. Use mykg_search_nodes to find valid IDs."

    vault = kg.vault_dir
    if vault:
        ntype = node.get("type", "Unknown")
        note_path = vault / ntype / f"{node_id}.md"
        if note_path.exists():
            return note_path.read_text(encoding="utf-8")

    lines = [f"# {_node_name(node)}", f"**Type:** {node.get('type', 'Unknown')}",
             f"**Confidence:** {node.get('confidence', 0.0):.2f}", ""]
    lines.append("## Attributes")
    for attr_name, attr_val in (node.get("attributes") or {}).items():
        val = attr_val.get("value") if isinstance(attr_val, dict) else attr_val
        conf = attr_val.get("confidence", 0.0) if isinstance(attr_val, dict) else 0.0
        lines.append(f"- **{attr_name}:** {val} (confidence: {conf:.2f})")

    aliases = node.get("aliases") or []
    if aliases:
        lines.append("")
        lines.append(f"**Aliases:** {', '.join(aliases)}")

    edges = kg.edges_by_node.get(node_id, [])
    if edges:
        lines.append("")
        lines.append("## Relationships")
        for edge in edges:
            peer_id = edge["to"] if edge["from"] == node_id else edge["from"]
            peer = kg.nodes_by_id.get(peer_id)
            peer_name = _node_name(peer) if peer else peer_id
            direction = "→" if edge["from"] == node_id else "←"
            lines.append(f"- {direction} **{edge.get('type', '')}** {peer_name} ({peer_id})")

    lines.append("")
    lines.append(f"**Source files:** {', '.join(node.get('source_files') or [])}")
    if not vault:
        lines.append("")
        lines.append("_Note: No obsidian_vault/ found. Re-run extract with --obsidian-vault to enable rich notes._")

    return "\n".join(lines)


@mcp.tool(
    name="mykg_list_sessions",
    annotations={
        "title": "List Available Sessions",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_list_sessions(ctx: Context) -> str:
    """List all available mykg sessions with their status and size.

    Shows which session is currently loaded, and for each session whether it
    has completed output files (nodes.jsonl, edges.jsonl, obsidian_vault).
    Use this to discover sessions before restarting the server with a
    different --session flag.

    Returns:
        JSON array of sessions with name, status, node/edge counts, and
        whether an obsidian vault exists.
    """
    app_ctx = ctx.request_context.lifespan_context
    sessions_root = app_ctx.sessions_root
    current_name = app_ctx.kg.session_name

    sessions = []
    for d in sorted(sessions_root.iterdir(), key=lambda p: p.name, reverse=True):
        if not d.is_dir():
            continue
        nodes_path = d / "output" / "nodes.jsonl"
        edges_path = d / "output" / "edges.jsonl"
        vault_path = d / "output" / "obsidian_vault"

        node_count = 0
        edge_count = 0
        if nodes_path.exists():
            with open(nodes_path, encoding="utf-8") as f:
                node_count = sum(1 for line in f if line.strip())
        if edges_path.exists():
            with open(edges_path, encoding="utf-8") as f:
                edge_count = sum(1 for line in f if line.strip())

        sessions.append({
            "name": d.name,
            "is_current": d.name == current_name,
            "status": "complete" if nodes_path.exists() else "incomplete",
            "node_count": node_count,
            "edge_count": edge_count,
            "has_vault": vault_path.is_dir(),
        })

    if not sessions:
        return "No sessions found."
    return json.dumps(sessions, indent=2)


@mcp.tool(
    name="mykg_reload",
    annotations={
        "title": "Reload Knowledge Graph",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def mykg_reload(ctx: Context, session: str | None = None) -> str:
    """Reload the in-memory knowledge graph from disk.

    Call this after running extract-graph, append, or any pipeline operation
    that changes the session's output files. Optionally switch to a different
    session by passing its name.
    """
    app_ctx = ctx.request_context.lifespan_context
    kg = app_ctx.kg
    prev_name = kg.session_name
    prev_nodes = len(kg.nodes)
    prev_edges = len(kg.edges)

    new_root = None
    if session:
        if '/' in session or '\\' in session or session in ('.', '..') or Path(session).is_absolute():
            return f"Error: invalid session name '{session}'."
        candidate = (app_ctx.sessions_root / session).resolve()
        try:
            candidate.relative_to(app_ctx.sessions_root.resolve())
        except ValueError:
            return f"Error: session '{session}' is outside sessions_root."
        if not (candidate / "output" / "nodes.jsonl").exists():
            return f"Error: Session '{session}' not found or has no output/nodes.jsonl."
        new_root = candidate

    kg.reload(session_root=new_root)

    return json.dumps({
        "status": "reloaded",
        "previous_session": prev_name,
        "current_session": kg.session_name,
        "previous": {"nodes": prev_nodes, "edges": prev_edges},
        "current": {"nodes": len(kg.nodes), "edges": len(kg.edges)},
    }, indent=2)


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------


@mcp.resource("graph://schema")
async def graph_schema(ctx: Context) -> str:
    """The knowledge graph schema: concept types and relationship properties."""
    kg = _get_kg(ctx)
    return json.dumps(kg.schema, indent=2)


@mcp.resource("graph://stats")
async def graph_stats(ctx: Context) -> str:
    """Summary statistics for the knowledge graph."""
    return await mykg_get_stats(ctx)


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------


def run_server(
    session_root: Path,
    transport: str = "stdio",
    host: str = "localhost",
    port: int = 3100,
) -> None:
    """Start the MCP server for a mykg session."""
    mcp._mykg_session_root = session_root  # type: ignore[attr-defined]
    mcp.settings.host = host
    mcp.settings.port = port
    if transport == "streamable_http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
