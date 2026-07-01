"""
Serializes the assembled knowledge graph to all output formats.

Primary outputs (export_nodes_jsonl / export_edges_jsonl / export_ttl):
  output/nodes.jsonl           — one JSON record per deduplicated node (D12)
  output/edges.jsonl           — one flat JSON record per edge, from sidecar (D13)
  output/knowledge_graph.ttl   — RDFS TBox + RDF ABox, no edge metadata (D14)

NetworkX outputs (export_networkx, toggled via mykg_config.yaml
export.networkx_enabled; written to output/networkx_output/):
  knowledge_graph.gml          — GML, human-readable
  knowledge_graph.graphml      — GraphML, full attributes (yEd, Gephi, Cytoscape)
  knowledge_graph.gexf         — GEXF, Gephi native
  knowledge_graph.net          — Pajek (numeric attributes dropped — format limitation)
  knowledge_graph.json         — JSON node-link (D3.js, Sigma.js)
  knowledge_graph.html         — interactive vis.js visualization (click to inspect)
  edges_nx.txt                 — plain edge list with attributes
  adjacency.txt                — adjacency list, topology only

Obsidian vault output (export_obsidian, toggled via mykg_config.yaml
export.obsidian_enabled; written to output/obsidian_vault/):
  <Type>/<node_id>.md          — one note per entity with YAML frontmatter and wikilinks
  index.md                     — vault root overview with per-type entity tables

Node/edge attributes are flattened to GML-safe scalars:
  attr_<name>_value / attr_<name>_confidence
source_files lists are pipe-joined ("a.md|b.md") for format compatibility.
"""

from __future__ import annotations

import html as _html
import json
import re
import warnings
from collections import defaultdict
from pathlib import Path

import networkx as nx
import yaml
from networkx.readwrite import json_graph

from mykg import config as _cfg


def _build_prefixes(include_skos: bool = False) -> str:
    ex = _cfg.TTL_SCHEMA_PREFIX_LABEL
    data = _cfg.TTL_DATA_PREFIX_LABEL
    prefixes = (
        f"@prefix rdf:  <{_cfg.TTL_NAMESPACE_RDF}> .\n"
        f"@prefix rdfs: <{_cfg.TTL_NAMESPACE_RDFS}> .\n"
        f"@prefix {ex}:   <{_cfg.TTL_NAMESPACE_SCHEMA}> .\n"
        f"@prefix {data}: <{_cfg.TTL_NAMESPACE_DATA}> .\n"
    )
    if include_skos:
        prefixes += f"@prefix skos: <{_cfg.TTL_NAMESPACE_SKOS}> .\n"
    return prefixes


def _ttl_local(name: str) -> str:
    """Sanitize a name for use as a Turtle local name (PN_LOCAL)."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)


def _escape_ttl(s: str) -> str:
    """Escape special characters in Turtle string literals."""
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def export_nodes_jsonl(nodes: list[dict]) -> str:
    lines = [json.dumps(node, ensure_ascii=False) for node in nodes]
    return "\n".join(lines) + "\n"


def export_edges_jsonl(edge_metadata: dict) -> str:
    lines = []
    for edge_id, edge in edge_metadata.items():
        record = {"id": edge_id, **edge} if "id" not in edge else edge
        lines.append(json.dumps(record, ensure_ascii=False))
    return "\n".join(lines) + "\n"


def export_ttl(schema: dict, nodes: list[dict], edge_metadata: dict) -> str:
    ex = _cfg.TTL_SCHEMA_PREFIX_LABEL
    data = _cfg.TTL_DATA_PREFIX_LABEL
    sep = "=" * _cfg.TTL_COMMENT_WIDTH

    has_aliases = any(node.get("aliases") for node in nodes)
    parts = [_build_prefixes(include_skos=has_aliases)]
    parts.append(f"# {sep}")
    parts.append("# 1. THE RDFS SCHEMA (TBox)")
    parts.append(f"# {sep}")
    parts.append("")

    # Classes
    for concept in schema["concepts"]:
        ctype = _ttl_local(concept["type"])
        parts.append(f"{ex}:{ctype} rdf:type rdfs:Class .")

    parts.append("")

    # Subclass hierarchy
    for concept in schema["concepts"]:
        if concept["parent"]:
            ctype = _ttl_local(concept["type"])
            parent = _ttl_local(concept["parent"])
            parts.append(f"{ex}:{ctype} rdfs:subClassOf {ex}:{parent} .")

    parts.append("")

    # Datatype properties (concept attributes)
    for concept in schema["concepts"]:
        ctype = _ttl_local(concept["type"])
        for attr in concept.get("attributes", []):
            attr_local = _ttl_local(attr)
            parts.append(
                f"{ex}:{attr_local} rdf:type rdf:Property ;\n"
                f"    rdfs:domain {ex}:{ctype} ;\n"
                f"    rdfs:range  rdfs:Literal ."
            )
    parts.append("")

    # Object properties
    for prop in schema["properties"]:
        pname = _ttl_local(prop["name"])
        domain = _ttl_local(prop["domain"])
        range_ = _ttl_local(prop["range"])
        parts.append(
            f"{ex}:{pname} rdf:type rdf:Property ;\n"
            f"    rdfs:domain {ex}:{domain} ;\n"
            f"    rdfs:range  {ex}:{range_} ."
        )
    parts.append("")

    # ABox section only emitted when there is instance data (D14/D17: schema.ttl is TBox-only)
    if nodes or edge_metadata:
        parts.append(f"# {sep}")
        parts.append("# 2. THE RDF INSTANCE DATA (ABox)")
        parts.append(f"# {sep}")
        parts.append("")

    # Node type declarations
    for node in nodes:
        ntype = _ttl_local(node["type"])
        parts.append(f"{data}:{node['id']} rdf:type {ex}:{ntype} .")

    parts.append("")

    # Datatype attribute triples (skip null values)
    for node in nodes:
        for attr, raw_val in node["attributes"].items():
            attr_val = (
                raw_val if isinstance(raw_val, dict) and "value" in raw_val else {"value": raw_val}
            )
            if attr_val["value"] is not None:
                val = attr_val["value"]
                if isinstance(val, list):
                    val = ", ".join(str(v) for v in val)
                escaped = _escape_ttl(str(val))
                attr_local = _ttl_local(attr)
                parts.append(f'{data}:{node["id"]} {ex}:{attr_local} "{escaped}" .')

    # skos:altLabel triples for aliases (D29) — one per alias per node
    if has_aliases:
        for node in nodes:
            for alias in node.get("aliases", []):
                escaped = _escape_ttl(str(alias))
                parts.append(f'{data}:{node["id"]} skos:altLabel "{escaped}" .')
        parts.append("")

    # Object property triples
    for edge in edge_metadata.values():
        etype = _ttl_local(edge["type"])
        parts.append(f"{data}:{edge['from']} {ex}:{etype} {data}:{edge['to']} .")

    parts.append("")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Interactive HTML export (vis.js)
# ---------------------------------------------------------------------------

_NODE_TYPE_COLORS = [
    "#4E79A7",
    "#F28E2B",
    "#E15759",
    "#76B7B2",
    "#59A14F",
    "#EDC948",
    "#B07AA1",
    "#FF9DA7",
    "#9C755F",
    "#BAB0AC",
]


def _html_styles() -> str:
    return """<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f0f1a; color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    display: flex; height: 100vh; overflow: hidden;
  }
  #graph { flex: 1; min-width: 0; }
  #resizer {
    width: 5px; background: #2a2a4e; cursor: col-resize; flex-shrink: 0;
    transition: background 0.15s;
  }
  #resizer:hover, #resizer.dragging { background: #4E79A7; }
  #sidebar {
    width: 280px; min-width: 180px; max-width: 600px;
    background: #1a1a2e; border-left: 1px solid #2a2a4e;
    display: flex; flex-direction: column; overflow: hidden; flex-shrink: 0;
  }
  #search-wrap { padding: 12px; border-bottom: 1px solid #2a2a4e; }
  #search {
    width: 100%; background: #0f0f1a; border: 1px solid #3a3a5e; color: #e0e0e0;
    padding: 7px 10px; border-radius: 6px; font-size: 14px; outline: none;
  }
  #search:focus { border-color: #4E79A7; }
  #search-results {
    max-height: 140px; overflow-y: auto; padding: 4px 12px;
    border-bottom: 1px solid #2a2a4e; display: none;
  }
  .search-item {
    padding: 4px 6px; cursor: pointer; border-radius: 4px; font-size: 14px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .search-item:hover { background: #2a2a4e; }
  #info-panel { padding: 14px; border-bottom: 1px solid #2a2a4e; min-height: 80px; flex: 1 1 0; overflow-y: auto; }
  #info-panel h3 {
    font-size: 14px; color: #aaa; margin-bottom: 8px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  #info-content { font-size: 14px; color: #ccc; line-height: 1.6; }
  #info-content .field { margin-bottom: 5px; }
  #info-content .field b { color: #e0e0e0; }
  #info-content .empty { color: #555; font-style: italic; }
  .neighbor-link {
    display: block; padding: 2px 6px; margin: 2px 0; border-radius: 3px;
    cursor: pointer; font-size: 14px; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; border-left: 3px solid #333;
  }
  .neighbor-link:hover { background: #2a2a4e; }
  #neighbors-list { max-height: 160px; overflow-y: auto; margin-top: 4px; }
  #legend-wrap { flex: 1; overflow-y: auto; padding: 12px; }
  #legend-wrap h3 {
    font-size: 14px; color: #aaa; margin-bottom: 10px;
    text-transform: uppercase; letter-spacing: 0.05em;
  }
  .legend-item {
    display: flex; align-items: center; gap: 8px; padding: 4px 0;
    cursor: pointer; border-radius: 4px; font-size: 14px;
  }
  .legend-item:hover { background: #2a2a4e; padding-left: 4px; }
  .legend-item.dimmed { opacity: 0.35; }
  .legend-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
  .legend-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .legend-count { color: #666; font-size: 14px; }
  #stats { padding: 10px 14px; border-top: 1px solid #2a2a4e; font-size: 14px; color: #555; }
  #legend-controls {
    display: flex; align-items: center; gap: 8px; margin-bottom: 8px; padding: 4px 0;
  }
  #legend-controls label {
    display: flex; align-items: center; gap: 6px;
    cursor: pointer; font-size: 14px; color: #aaa; user-select: none;
  }
  #legend-controls label:hover { color: #e0e0e0; }
  .legend-cb, #select-all-cb {
    appearance: none; -webkit-appearance: none; width: 14px; height: 14px;
    border: 1.5px solid #3a3a5e; border-radius: 3px; background: #0f0f1a;
    cursor: pointer; position: relative; flex-shrink: 0;
  }
  .legend-cb:checked, #select-all-cb:checked { background: #4E79A7; border-color: #4E79A7; }
  .legend-cb:checked::after, #select-all-cb:checked::after {
    content: ''; position: absolute; left: 3.5px; top: 1px; width: 4px; height: 7px;
    border: solid #fff; border-width: 0 2px 2px 0; transform: rotate(45deg);
  }
  #select-all-cb:indeterminate { background: #4E79A7; border-color: #4E79A7; }
  #select-all-cb:indeterminate::after {
    content: ''; position: absolute; left: 2px; top: 5px;
    width: 8px; height: 2px; background: #fff; border: none; transform: none;
  }
  #info-content .attr-block { margin-top: 10px; border-top: 1px solid #2a2a4e; padding-top: 8px; }
  #info-content .attr-row { display: flex; gap: 6px; font-size: 14px; margin-bottom: 3px; }
  #info-content .attr-key { color: #888; flex-shrink: 0; }
  #info-content .attr-val { color: #ddd; word-break: break-word; }
  #info-content .attr-conf { color: #555; font-size: 14px; margin-left: auto; flex-shrink: 0; }
  #conf-filters { margin-top: 10px; padding-top: 8px; border-top: 1px solid #2a2a4e; }
  .slider-row {
    display: flex; align-items: center; gap: 8px; margin: 6px 0;
    font-size: 13px; color: #aaa;
  }
  .slider-row label { flex-shrink: 0; min-width: 80px; }
  .slider-row input[type=range] {
    flex: 1; accent-color: #4E79A7; cursor: pointer;
  }
  .slider-row .readout {
    flex-shrink: 0; min-width: 50px; color: #ccc;
    font-variant-numeric: tabular-nums; text-align: right;
  }
</style>"""


def _html_script(nodes_json: str, edges_json: str) -> str:
    # All user-derived values embedded in innerHTML are escaped via esc() in JS
    # before insertion. This file is written locally, not served over a network.
    return f"""<script>
const RAW_NODES = {nodes_json};
const RAW_EDGES = {edges_json};

function esc(s) {{
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

const nodesDS = new vis.DataSet(RAW_NODES.map(n => ({{
  id: n.id, label: n.label, color: n.color, size: n.size,
  font: n.font, title: n.title,
}})));

const edgesDS = new vis.DataSet(RAW_EDGES.map((e, i) => ({{
  id: i, from: e.from, to: e.to,
  label: e.label,
  title: e.title,
  width: e.width,
  color: {{ color: '#3a3a6e', highlight: '#7777cc', opacity: 0.7 }},
  arrows: {{ to: {{ enabled: true, scaleFactor: 0.5 }} }},
  font: {{ size: 12, color: '#666', align: 'middle' }},
}})));

const container = document.getElementById('graph');
const network = new vis.Network(container, {{ nodes: nodesDS, edges: edgesDS }}, {{
  physics: {{
    enabled: true,
    solver: 'forceAtlas2Based',
    forceAtlas2Based: {{
      gravitationalConstant: -60,
      centralGravity: 0.005,
      springLength: 120,
      springConstant: 0.08,
      damping: 0.4,
      avoidOverlap: 0.8,
    }},
    stabilization: {{ iterations: 200, fit: true }},
  }},
  interaction: {{
    hover: true,
    tooltipDelay: 100,
    hideEdgesOnDrag: true,
    navigationButtons: false,
    keyboard: false,
  }},
  nodes: {{ shape: 'dot', borderWidth: 1.5 }},
  edges: {{ smooth: {{ type: 'continuous', roundness: 0.2 }}, selectionWidth: 3 }},
}});

network.once('stabilizationIterationsDone', () => {{
  network.setOptions({{ physics: {{ enabled: false }} }});
}});

function renderAttrs(rawNode) {{
  const rows = Object.entries(rawNode._raw_attrs || {{}}).map(([k, v]) => {{
    const val = (v && typeof v === 'object') ? (v.value ?? '') : v;
    const conf = (v && typeof v === 'object' && v.confidence != null)
      ? ' (' + Number(v.confidence).toFixed(2) + ')' : '';
    return '<div class="attr-row">'
      + '<span class="attr-key">' + esc(k) + '</span>'
      + '<span class="attr-val">' + esc(String(val ?? '')) + '</span>'
      + '<span class="attr-conf">' + esc(conf) + '</span>'
      + '</div>';
  }});
  return rows.length
    ? '<div class="attr-block">'
        + '<div style="font-size:14px;color:#888;margin-bottom:4px">Attributes</div>'
        + rows.join('') + '</div>'
    : '';
}}

function showInfo(nodeId) {{
  const rawNode = RAW_NODES.find(n => n.id === nodeId);
  if (!rawNode) return;
  const neighborIds = network.getConnectedNodes(nodeId);
  const neighborItems = neighborIds.map(nid => {{
    const nb = RAW_NODES.find(n => n.id === nid);
    const color = nb ? nb.color.background : '#555';
    return '<span class="neighbor-link" style="border-left-color:' + esc(color) + '"'
      + ' onclick="focusNode(' + JSON.stringify(nid) + ')">'
      + esc(nb ? nb.label : nid) + '</span>';
  }}).join('');
  const parts = [
    '<div class="field"><b>' + esc(rawNode.label) + '</b></div>',
    '<div class="field">Type: ' + esc(rawNode._node_type || 'unknown') + '</div>',
    '<div class="field">Confidence: ' + esc(String(rawNode._confidence ?? '')) + '</div>',
    '<div class="field">Sources: ' + esc(rawNode._source_files || '-') + '</div>',
    renderAttrs(rawNode),
    neighborIds.length
      ? '<div class="field attr-block" style="color:#aaa;font-size:14px">Neighbors ('
          + neighborIds.length + ')</div><div id="neighbors-list">' + neighborItems + '</div>'
      : '',
  ];
  document.getElementById('info-content').textContent = '';
  const div = document.getElementById('info-content');
  div.innerHTML = parts.join('');
}}

function focusNode(nodeId) {{
  network.focus(nodeId, {{ scale: 1.4, animation: true }});
  network.selectNodes([nodeId]);
  showInfo(nodeId);
}}

let hoveredNodeId = null;
network.on('hoverNode', params => {{
  hoveredNodeId = params.node;
  container.style.cursor = 'pointer';
}});
network.on('blurNode', () => {{
  hoveredNodeId = null;
  container.style.cursor = 'default';
}});
network.on('click', params => {{
  if (params.nodes.length > 0) {{
    showInfo(params.nodes[0]);
  }} else if (hoveredNodeId === null) {{
    const div = document.getElementById('info-content');
    div.innerHTML = '<span class="empty">Click a node to inspect it</span>';
  }}
}});

const searchInput = document.getElementById('search');
const searchResults = document.getElementById('search-results');
searchInput.addEventListener('input', () => {{
  const q = searchInput.value.toLowerCase().trim();
  searchResults.innerHTML = '';
  if (!q) {{ searchResults.style.display = 'none'; return; }}
  const matches = RAW_NODES.filter(n => {{
    if (!n.label.toLowerCase().includes(q)) return false;
    const cur = nodesDS.get(n.id);
    return !cur || cur.hidden !== true;
  }}).slice(0, 20);
  if (!matches.length) {{ searchResults.style.display = 'none'; return; }}
  searchResults.style.display = 'block';
  matches.forEach(n => {{
    const el = document.createElement('div');
    el.className = 'search-item';
    el.textContent = n.label;
    el.style.borderLeft = '3px solid ' + n.color.background;
    el.style.paddingLeft = '8px';
    el.onclick = () => {{
      focusNode(n.id);
      searchResults.style.display = 'none';
      searchInput.value = '';
    }};
    searchResults.appendChild(el);
  }});
}});
document.addEventListener('click', e => {{
  if (!searchResults.contains(e.target) && e.target !== searchInput)
    searchResults.style.display = 'none';
}});

const nodeSlider = document.getElementById('node-conf-slider');
const edgeSlider = document.getElementById('edge-conf-slider');
const nodeReadout = document.getElementById('node-conf-readout');
const edgeReadout = document.getElementById('edge-conf-readout');
const statsEl = document.getElementById('stats');
const TOTAL_NODES = RAW_NODES.length;
const TOTAL_EDGES = RAW_EDGES.length;

function applyConfidenceFilter() {{
  const nodeThr = parseFloat(nodeSlider.value);
  const edgeThr = parseFloat(edgeSlider.value);
  nodeReadout.textContent = '≥ ' + nodeThr.toFixed(2);
  edgeReadout.textContent = '≥ ' + edgeThr.toFixed(2);

  const hiddenNodeIds = new Set();
  const nodeUpdates = RAW_NODES.map(n => {{
    const hidden = (n._confidence ?? 0) < nodeThr;
    if (hidden) hiddenNodeIds.add(n.id);
    return {{ id: n.id, hidden: hidden }};
  }});
  nodesDS.update(nodeUpdates);

  let visibleEdges = 0;
  const edgeUpdates = RAW_EDGES.map((e, i) => {{
    const hidden = (e._confidence ?? 0) < edgeThr
      || hiddenNodeIds.has(e.from) || hiddenNodeIds.has(e.to);
    if (!hidden) visibleEdges += 1;
    return {{ id: i, hidden: hidden }};
  }});
  edgesDS.update(edgeUpdates);

  const visibleNodes = TOTAL_NODES - hiddenNodeIds.size;
  statsEl.textContent = TOTAL_NODES + ' nodes (' + visibleNodes + ' visible) · '
    + TOTAL_EDGES + ' edges (' + visibleEdges + ' visible)';
}}

nodeSlider.addEventListener('input', applyConfidenceFilter);
edgeSlider.addEventListener('input', applyConfidenceFilter);

const resizer = document.getElementById('resizer');
const sidebar = document.getElementById('sidebar');
let isResizing = false;
let startX = 0;
let startWidth = 0;
resizer.addEventListener('mousedown', e => {{
  isResizing = true;
  startX = e.clientX;
  startWidth = sidebar.offsetWidth;
  resizer.classList.add('dragging');
  document.body.style.userSelect = 'none';
  document.body.style.cursor = 'col-resize';
}});
document.addEventListener('mousemove', e => {{
  if (!isResizing) return;
  const delta = startX - e.clientX;
  const newWidth = Math.min(600, Math.max(180, startWidth + delta));
  sidebar.style.width = newWidth + 'px';
}});
document.addEventListener('mouseup', () => {{
  if (!isResizing) return;
  isResizing = false;
  resizer.classList.remove('dragging');
  document.body.style.userSelect = '';
  document.body.style.cursor = '';
  network.redraw();
  network.fit();
}});
</script>"""


def export_html(G: nx.DiGraph, out_dir: Path) -> str:
    """Write an interactive vis.js HTML file; return the output path as a string."""
    type_list = sorted({data.get("node_type", "") for _, data in G.nodes(data=True)})
    type_color = {t: _NODE_TYPE_COLORS[i % len(_NODE_TYPE_COLORS)] for i, t in enumerate(type_list)}

    degree = dict(G.degree())
    max_deg = max(degree.values(), default=1) or 1

    vis_nodes = []
    for node_id, data in G.nodes(data=True):
        node_type = data.get("node_type", "")
        color = type_color.get(node_type, _NODE_TYPE_COLORS[0])
        label = str(data.get("label", node_id))
        deg = degree.get(node_id, 1)
        size = round(10 + 30 * (deg / max_deg), 1)
        font_size = 15 if deg >= max_deg * 0.15 else 0

        raw_attrs = {
            k[len("attr_") : k.rfind("_")]: {
                "value": data.get(k),
                "confidence": data.get(k.replace("_value", "_confidence"), 0.0),
            }
            for k in data
            if k.startswith("attr_") and k.endswith("_value")
        }

        vis_nodes.append(
            {
                "id": node_id,
                "label": label,
                "color": {
                    "background": color,
                    "border": color,
                    "highlight": {"background": "#ffffff", "border": color},
                },
                "size": size,
                "font": {"size": font_size, "color": "#ffffff"},
                "title": _html.escape(label),
                "_node_type": node_type,
                "_confidence": data.get("confidence", 0.0),
                "_source_files": data.get("source_files", ""),
                "_raw_attrs": raw_attrs,
            }
        )

    vis_edges = []
    for u, v, data in G.edges(data=True):
        edge_type = data.get("edge_type", "")
        conf = float(data.get("confidence", 1.0))
        vis_edges.append(
            {
                "from": u,
                "to": v,
                "label": edge_type,
                "title": _html.escape(f"{edge_type} (conf={conf:.2f})"),
                "width": 2 if conf >= 0.8 else 1,
                "_confidence": conf,
            }
        )

    def _js_safe(obj: object) -> str:
        return json.dumps(obj).replace("</", r"<\/")

    nodes_json = _js_safe(vis_nodes)
    edges_json = _js_safe(vis_edges)
    stats = f"{G.number_of_nodes()} nodes &middot; {G.number_of_edges()} edges"

    type_legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;'
        f'gap:5px;margin:3px 8px 3px 0;font-size:14px">'
        f'<span style="width:10px;height:10px;border-radius:50%;'
        f'background:{type_color[t]};display:inline-block"></span>'
        f"{_html.escape(t or 'unknown')}</span>"
        for t in type_list
    )

    content = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="UTF-8">\n'
        "<title>mykg knowledge graph</title>\n"
        '<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>\n'
        + _html_styles()
        + "\n</head>\n<body>\n"
        '<div id="graph"></div>\n'
        '<div id="resizer"></div>\n'
        '<div id="sidebar">\n'
        '  <div id="search-wrap">\n'
        '    <input id="search" type="text" placeholder="Search nodes..." autocomplete="off">\n'
        '    <div id="search-results"></div>\n'
        "  </div>\n"
        '  <div id="info-panel">\n'
        "    <h3>Node Info</h3>\n"
        '    <div id="info-content"><span class="empty">Click a node to inspect it</span></div>\n'
        "  </div>\n"
        '  <div style="padding:10px 14px;border-top:1px solid #2a2a4e;'
        'font-size:14px;color:#666;flex-shrink:0;max-height:220px;overflow-y:auto">\n'
        '    <div style="margin-bottom:6px;color:#aaa">Node types</div>\n'
        f"    {type_legend_items}\n"
        '    <div id="conf-filters">\n'
        '      <div class="slider-row">\n'
        '        <label for="node-conf-slider">Node conf.</label>\n'
        '        <input id="node-conf-slider" type="range" min="0" max="1" step="0.01" value="0">\n'
        '        <span class="readout" id="node-conf-readout">&ge; 0.00</span>\n'
        "      </div>\n"
        '      <div class="slider-row">\n'
        '        <label for="edge-conf-slider">Link conf.</label>\n'
        '        <input id="edge-conf-slider" type="range" min="0" max="1" step="0.01" value="0">\n'
        '        <span class="readout" id="edge-conf-readout">&ge; 0.00</span>\n'
        "      </div>\n"
        "    </div>\n"
        "  </div>\n"
        f'  <div id="stats">{stats}</div>\n'
        "</div>\n" + _html_script(nodes_json, edges_json) + "\n</body>\n</html>"
    )

    p = out_dir / "knowledge_graph.html"
    p.write_text(content, encoding="utf-8")
    return str(p)


# ---------------------------------------------------------------------------
# NetworkX multi-format export
# ---------------------------------------------------------------------------


def _nx_flatten_attributes(attrs: dict) -> dict:
    """Flatten {name: {value, confidence}} pairs to GML-safe scalar fields."""
    flat = {}
    for name, payload in attrs.items():
        val = payload.get("value") or ""
        if isinstance(val, list):
            val = "|".join(str(v) for v in val)
        # GML requires ^[A-Za-z][0-9A-Za-z_]*$ — sanitize any invalid characters.
        safe_name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        flat[f"attr_{safe_name}_value"] = val
        flat[f"attr_{safe_name}_confidence"] = float(payload.get("confidence", 0.0))
    return flat


def _nx_source_files_str(source_files: list) -> str:
    return "|".join(source_files) if source_files else ""


def _build_nx_graph(nodes: list[dict], edge_metadata: dict) -> nx.DiGraph:
    G = nx.DiGraph()
    G.graph["name"] = "mykg knowledge graph"

    for node in nodes:
        aliases = node.get("aliases") or []
        attrs = {
            "label": node["id"],
            "node_type": node.get("type", ""),
            "confidence": float(node.get("confidence", 0.0)),
            "source_files": _nx_source_files_str(node.get("source_files", [])),
            "aliases": "|".join(aliases),
        }
        attrs.update(_nx_flatten_attributes(node.get("attributes", {})))
        G.add_node(node["id"], **attrs)

    for edge_id, edge in edge_metadata.items():
        attrs = {
            "label": edge_id,
            "edge_type": edge.get("type", ""),
            "confidence": float(edge.get("confidence", 0.0)),
            "source_files": _nx_source_files_str(edge.get("source_files", [])),
        }
        attrs.update(_nx_flatten_attributes(edge.get("attributes", {})))
        G.add_edge(edge["from"], edge["to"], **attrs)

    return G


def export_networkx(nodes: list[dict], edge_metadata: dict, output_dir: Path) -> list[str]:
    """Write all NetworkX formats to output_dir/networkx_output/. Returns list of written paths."""
    nx_dir = output_dir / "networkx_output"
    nx_dir.mkdir(exist_ok=True)

    G = _build_nx_graph(nodes, edge_metadata)
    written = []

    try:
        nx.write_gml(G, str(nx_dir / "knowledge_graph.gml"))
        written.append("knowledge_graph.gml")
    except Exception as e:
        warnings.warn(f"NetworkX GML export failed: {e}", stacklevel=2)

    try:
        nx.write_graphml(G, str(nx_dir / "knowledge_graph.graphml"))
        written.append("knowledge_graph.graphml")
    except Exception as e:
        warnings.warn(f"NetworkX GraphML export failed: {e}", stacklevel=2)

    try:
        nx.write_gexf(G, str(nx_dir / "knowledge_graph.gexf"))
        written.append("knowledge_graph.gexf")
    except Exception as e:
        warnings.warn(f"NetworkX GEXF export failed: {e}", stacklevel=2)

    # Pajek format drops non-string and empty attributes by design — silence the
    # per-attribute UserWarnings that networkx.readwrite.pajek emits for each one.
    try:
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"(Node|Edge) attribute .* is not processed\..*",
                category=UserWarning,
                module=r"networkx\.readwrite\.pajek",
            )
            nx.write_pajek(G, str(nx_dir / "knowledge_graph.net"))
        written.append("knowledge_graph.net")
    except Exception as e:
        warnings.warn(f"NetworkX Pajek export failed: {e}", stacklevel=2)

    try:
        with open(nx_dir / "knowledge_graph.json", "w", encoding="utf-8") as f:
            json.dump(json_graph.node_link_data(G), f, indent=_cfg.JSON_INDENT)
        written.append("knowledge_graph.json")
    except Exception as e:
        warnings.warn(f"NetworkX JSON export failed: {e}", stacklevel=2)

    try:
        export_html(G, nx_dir)
        written.append("knowledge_graph.html")
    except Exception as e:
        warnings.warn(f"NetworkX HTML export failed: {e}", stacklevel=2)

    try:
        nx.write_edgelist(G, str(nx_dir / "edges_nx.txt"), data=True)
        written.append("edges_nx.txt")
    except Exception as e:
        warnings.warn(f"NetworkX edge list export failed: {e}", stacklevel=2)

    try:
        nx.write_adjlist(G, str(nx_dir / "adjacency.txt"))
        written.append("adjacency.txt")
    except Exception as e:
        warnings.warn(f"NetworkX adjacency list export failed: {e}", stacklevel=2)

    return written


# ---------------------------------------------------------------------------
# Obsidian vault export
# ---------------------------------------------------------------------------


def _node_display_name(node: dict) -> str:
    """Return the human-readable display name for a node (name attribute value or node ID)."""
    name_attr = node.get("attributes", {}).get("name")
    if isinstance(name_attr, dict):
        val = name_attr.get("value")
        if val:
            return str(val)
    return node["id"]


def _obsidian_entity_note(
    node: dict,
    outgoing: list[tuple[str, str, float]],
    incoming: list[tuple[str, str, float]],
) -> str:
    """Render a single entity note as a Markdown string with YAML frontmatter."""
    node_id = node["id"]
    node_type = node.get("type", "")
    confidence = node.get("confidence", 0.0)
    source_files = node.get("source_files", [])
    attributes = node.get("attributes", {})
    display_name = _node_display_name(node)

    frontmatter_data: dict = {
        "id": node_id,
        "type": node_type,
        "confidence": round(float(confidence), 4),
    }
    if source_files:
        frontmatter_data["sources"] = list(source_files)

    frontmatter = yaml.dump(frontmatter_data, default_flow_style=False, allow_unicode=True).rstrip()
    lines: list[str] = ["---", frontmatter, "---", "", f"# {display_name}", ""]

    # Attributes section (skip "name" — it is the heading)
    attr_lines = []
    for attr_name, payload in attributes.items():
        if attr_name == "name":
            continue
        if isinstance(payload, dict):
            val = payload.get("value")
            conf = payload.get("confidence", 0.0)
        else:
            val = payload
            conf = 0.0
        if val is None:
            continue
        attr_lines.append(f"- **{attr_name}**: {val} ({round(float(conf), 2)})")

    if attr_lines:
        lines.append("## Attributes")
        lines.extend(attr_lines)
        lines.append("")

    # Relationships section
    if outgoing or incoming:
        lines.append("## Relationships")
        lines.append("")
        if outgoing:
            lines.append("### Outgoing")
            for target_name, edge_type, edge_conf in outgoing:
                lines.append(f"- [[{target_name}]] — {edge_type} ({round(float(edge_conf), 2)})")
            lines.append("")
        if incoming:
            lines.append("### Incoming")
            for source_name, edge_type, edge_conf in incoming:
                lines.append(f"- [[{source_name}]] — {edge_type} ({round(float(edge_conf), 2)})")
            lines.append("")

    # Source Files section
    if source_files:
        lines.append("## Source Files")
        for sf in source_files:
            lines.append(f"- {sf}")
        lines.append("")

    return "\n".join(lines)


def _obsidian_index(nodes: list[dict], edge_count: int) -> str:
    """Render the vault index.md listing all entities grouped by type."""
    lines: list[str] = [
        "# Knowledge Graph Index",
        "",
        f"**{len(nodes)} entities** — **{edge_count} relationships**",
        "",
    ]

    # Group nodes by type, sorted for deterministic output
    by_type: dict[str, list[dict]] = defaultdict(list)
    for node in nodes:
        by_type[node.get("type", "Unknown")].append(node)

    for node_type in sorted(by_type):
        # Compute display name once per node to avoid double attribute lookups
        group = sorted(
            ((n, _node_display_name(n)) for n in by_type[node_type]),
            key=lambda pair: pair[1],
        )
        lines.append(f"## {node_type}")
        lines.append("")
        lines.append("| Entity |")
        lines.append("| --- |")
        for _node, name in group:
            lines.append(f"| [[{name}]] |")
        lines.append("")

    return "\n".join(lines)


def export_obsidian(
    nodes: list[dict],
    edge_metadata: dict,
    schema: dict,  # kept for API symmetry with other export_ functions
    output_dir: Path,
) -> list[str]:
    """Write an Obsidian vault to output_dir/obsidian_vault/.

    One Markdown note per entity (Type/node_id.md), with YAML frontmatter,
    attributes, wikilinked relationships, and an index.md overview.

    Returns a list of written file paths as relative strings (same contract as
    export_networkx).  Returns an empty list when OBSIDIAN_ENABLED is False.
    """
    if not getattr(_cfg, "OBSIDIAN_ENABLED", False):
        return []

    vault_dir = output_dir / "obsidian_vault"
    vault_dir.mkdir(exist_ok=True)

    # Build id → display_name lookup for wikilinks
    id_to_name: dict[str, str] = {node["id"]: _node_display_name(node) for node in nodes}

    # Build adjacency: outgoing/incoming per node_id
    # Values: list of (peer_display_name, edge_type, confidence)
    outgoing: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    incoming: dict[str, list[tuple[str, str, float]]] = defaultdict(list)
    for edge in edge_metadata.values():
        from_id = edge.get("from", "")
        to_id = edge.get("to", "")
        edge_type = edge.get("type", "")
        conf = float(edge.get("confidence", 0.0))
        outgoing[from_id].append((id_to_name.get(to_id, to_id), edge_type, conf))
        incoming[to_id].append((id_to_name.get(from_id, from_id), edge_type, conf))

    # Pre-create one subdir per concept type to avoid repeated mkdir calls in the node loop
    type_dirs: dict[str, Path] = {}
    for node in nodes:
        node_type = node.get("type", "Unknown")
        if node_type not in type_dirs:
            d = vault_dir / node_type
            d.mkdir(exist_ok=True)
            type_dirs[node_type] = d

    written: list[str] = []

    for node in nodes:
        node_id = node["id"]
        node_type = node.get("type", "Unknown")
        type_dir = type_dirs[node_type]

        note_content = _obsidian_entity_note(
            node,
            outgoing=outgoing.get(node_id, []),
            incoming=incoming.get(node_id, []),
        )
        note_path = type_dir / f"{node_id}.md"
        note_path.write_text(note_content, encoding="utf-8")
        # Derive the relative path from the actual filesystem path to stay in sync
        written.append(str(note_path.relative_to(output_dir)))

    # Index
    index_content = _obsidian_index(nodes, edge_count=len(edge_metadata))
    (vault_dir / "index.md").write_text(index_content, encoding="utf-8")
    written.append("obsidian_vault/index.md")

    return written
