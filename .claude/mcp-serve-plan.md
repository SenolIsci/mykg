# Plan: `mykg mcp-serve` — Local MCP Server for Knowledge Graph Queries

## Context

A user validated this workflow: they created a simple Python MCP server pointed at their `networkx_output/knowledge_graph.graphml` file, used Cherry Studio as an MCP client, and got excellent Q&A results about their knowledge graph. We want to make this a first-class `mykg mcp-serve` command that launches an MCP server exposing the knowledge graph from any session — usable with Claude Desktop, Cherry Studio, Claude Code, or any MCP-compatible client.

## Implementation Approach

- **/mcp-builder** skill — FastMCP best practices (Pydantic inputs, tool annotations, lifespan, `{service}_mcp` naming)
- **/networkx** skill — reviewed all DiGraph operations for correctness and best practices (see NetworkX Review below)

Single work unit — all changes land in one branch (`feature/mcp-serve`).

## Data Sources

The MCP server loads from three session files via the existing `load_session()` function (`src/mykg/exporters/neo4j/_common.py`):
- **`output/nodes.jsonl`** — deduplicated entities with confidence-scored attributes, aliases, source files
- **`output/edges.jsonl`** — typed relationships with attributes, confidence, provenance
- **`intermediate/schema.json`** — concept hierarchy (types + parent chain) and property definitions (domain/range)

It then builds a NetworkX `DiGraph` in memory (via `exporter.py:_build_nx_graph()`) for graph algorithms (shortest path, subgraph extraction, density, etc.). This is richer than reading `.graphml` directly because the JSONL retains full confidence scores and nested attribute structures.

## Key Decisions

- **Command name**: `mykg mcp-serve` (not `serve` — more descriptive)
- **Core dependency**: `mcp>=1.0` in `pyproject.toml` (user chose core, not optional)
- **Transports**: stdio (default, for Claude Desktop) + streamable_http (for web clients)
- **Server name**: `mykg_mcp` (follows `{service}_mcp` convention from mcp-builder)
- **Tool prefix**: `mykg_` on all tools (avoids conflicts with other MCP servers)
- **Module**: Single file `src/mykg/mcp_server.py`

## Files to Create/Modify

| File | Action | What changes |
|------|--------|--------------|
| `src/mykg/mcp_server.py` | **create** | MCP server with KnowledgeGraph class, 11 tools, 2 resources |
| `src/mykg/cli.py` | modify | Add `mcp-serve` Click command before `main()` |
| `src/mykg/config.py` | modify | Add `MCP_HOST`, `MCP_PORT`, `MCP_TRANSPORT` constants |
| `mykg_config.yaml` | modify | Add `mcp:` top-level block |
| `src/mykg/data/mykg_config.yaml` | modify | Same `mcp:` block (Invariant 17) |
| `pyproject.toml` | modify | Add `mcp>=1.0` to dependencies |
| `tests/test_mcp_server.py` | **create** | Unit + integration tests (33 tests) |
| `README.md` | modify | Add "Querying with MCP" section |

## MCP Tools (11)

All read-only, all with Pydantic input validation and `mykg_` prefix.
Compared against [graphify](https://github.com/safishamsi/graphify) MCP server — we match or exceed its tool set for knowledge graph queries (graphify's PR-specific tools like `list_prs`/`triage_prs` are GitHub-specific and not applicable here).

1. **`mykg_search_nodes`** — substring search across names, aliases, attributes; filter by type; ranked by relevance (exact > prefix > substring > alias)
2. **`mykg_get_node`** — full node details by ID (like graphify's `get_node`)
3. **`mykg_get_neighbors`** — connected nodes (outgoing/incoming/both), filterable by edge type (like graphify's `get_neighbors` with `relation_filter`)
4. **`mykg_find_path`** — shortest path between two nodes via `nx.has_path()` + `nx.shortest_path()` (like graphify's `shortest_path`). Uses `edges_by_node` index for hop edge lookup.
5. **`mykg_get_schema`** — concept hierarchy + property definitions
6. **`mykg_list_node_types`** — types with counts
7. **`mykg_query_subgraph`** — filtered subgraph by node IDs, types, min confidence
8. **`mykg_get_stats`** — node/edge counts, `nx.density()`, `nx.number_weakly_connected_components()`, avg degree (like graphify's `graph_stats`)
9. **`mykg_query_graph`** — traversal from seed nodes using `nx.bfs_edges()` / `nx.dfs_edges()` with `depth_limit`, with configurable token budget. Inspired by graphify's `query_graph`.
10. **`mykg_hub_nodes`** — most connected nodes via `G.degree()` sorted descending, with `G.in_degree()` / `G.out_degree()` breakdown (like graphify's `god_nodes`)
11. **`mykg_read_note`** — read an Obsidian vault note for a node. Falls back to a formatted summary from `nodes.jsonl` if no vault exists. Inspired by the `/mykg query` skill's vault path.

## MCP Resources (2)

- `graph://schema` — schema JSON
- `graph://stats` — graph statistics

## NetworkX Review (/networkx skill)

Reviewed all NetworkX API usage against the skill's best practices. Three issues found and fixed:

| Issue | Before | After |
|-------|--------|-------|
| `mykg_find_path` edge lookup | Linear scan over all `kg.edges` for each hop — O(total edges) per hop | Indexed via `edges_by_node.get(src, [])` — O(degree) per hop |
| `mykg_find_path` path check | Exception-driven: try `shortest_path`, catch `NetworkXNoPath` | Pre-check with `nx.has_path()` first; only compute path if reachable |
| `mykg_query_graph` traversal | Hand-rolled BFS/DFS with manual stack/queue | `nx.bfs_edges(G, source, depth_limit=)` / `nx.dfs_edges(G, source, depth_limit=)` — built-in, handles edge cases correctly |

**Already correct** (no changes needed):
- `nx.DiGraph` is the right class for directed knowledge graphs with typed edges
- `G.degree()`, `G.in_degree()`, `G.out_degree()` used correctly for hub analysis
- `nx.density(G)` and `nx.number_weakly_connected_components(G)` for stats
- `G.to_undirected()` returns a view (no copy) — efficient for undirected path fallback
- `G.number_of_nodes()` / `G.number_of_edges()` for counts
- Division-by-zero guard on avg_degree: `max(G.number_of_nodes(), 1)`

## Existing Code to Reuse

- `src/mykg/exporters/neo4j/_common.py:load_session()` — loads nodes, edges, schema
- `src/mykg/exporter.py:_build_nx_graph()` — builds NetworkX DiGraph
- `src/mykg/config.py` — `_agent` block pattern for new top-level YAML keys

## Config Addition

```yaml
mcp:
  host: localhost
  port: 3100
  transport: stdio    # stdio | streamable_http
```

## E2E Verification

1. `uv pip install -e .`
2. `uv run pytest tests/test_mcp_server.py -v` — 33 tests, all passing
3. `mykg mcp-serve --transport streamable_http --port 3100` → connect with `npx @modelcontextprotocol/inspector`
4. Claude Desktop config: `{"mcpServers": {"mykg": {"command": "mykg", "args": ["mcp-serve"]}}}`

## Implementation Status

All files created/modified, all 33 tests passing, real session verified (44 nodes, 89 edges loaded from `2026-06-25T19-16-18`). Ready to commit on `feature/mcp-serve` branch.
