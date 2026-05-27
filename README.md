# mykg — Markdown Knowledge Graph Extractor

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-489%20passing-brightgreen.svg)](tests/)
[![Providers](https://img.shields.io/badge/LLM-Anthropic%20%7C%20OpenAI%20%7C%20Ollama%20%7C%20OpenRouter-orange.svg)](#configuration)

**mykg** turns a directory of Markdown files into a typed, confidence-scored property graph — with no manual schema authoring required.

It provides **two independent pipelines**:

- **`mykg extract-graph`** — two-pass LLM pipeline that reads `.md` files and produces a knowledge graph. Pass 1 induces a global RDFS schema from your corpus; Pass 2 extracts typed node and edge instances per file against that schema.
- **`mykg merge-graphs`** — merges two independently-produced graph sessions into a unified knowledge graph. Schemas are reconciled via the same three-stage merge chain as Pass 1; nodes are deduplicated across sessions by stable ID; new schema properties trigger targeted re-extraction.

Both pipelines write to three parallel formats: JSONL for property-graph consumers, Turtle RDF for OWL toolchains, and seven NetworkX formats for graph analysis and visualization.

```
mykg extract-graph my_notes/
mykg merge-graphs session-a session-b
```

```
# Extract output
sessions/2026-05-17T18-31-07/
  output/
    nodes.jsonl                    ← typed entities with confidence scores
    edges.jsonl                    ← typed relationships with provenance
    knowledge_graph.ttl            ← RDFS TBox + RDF ABox (Protégé, SPARQL)
    networkx_output/               ← GML, GraphML, GEXF, Pajek, JSON node-link,
                                      knowledge_graph.html (interactive vis)
  walkthrough.md                   ← per-run report: schema, stats, timing

# Merge output (same structure, additional merge artifacts)
sessions/2026-05-27T10-00-00/
  intermediate/
    source_map.json                ← file provenance for all namespaced files
    merge_manifest.json            ← schema deltas, re-extraction strategy used
  output/  ← same files as extract output above
  walkthrough.md                   ← includes Merge Provenance section
```

---

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [Extract Pipeline](#extract-pipeline)
  - [Running](#running)
  - [Sessions](#sessions)
  - [Pipeline Steps](#pipeline-steps)
  - [Outputs](#outputs)
  - [Re-running from a Specific Step](#re-running-from-a-specific-step)
  - [Orphan-Connection Pass](#orphan-connection-pass)
- [Merge Pipeline](#merge-pipeline)
- [Advanced Options](#advanced-options)
- [Development](#development)
- [Design](#design)

---

## Features

### Ontology-Guided Extraction

- **Schema-guided knowledge graph generation** — the extracted graph is always grounded in a formal RDFS schema: concept types, property names, domain/range constraints, and the is-a hierarchy are explicit and inspectable before any entity is extracted
- **Bring your own ontology** — supply a `--base-schema` TTL file to lock in classes and properties from an existing formal ontology; the LLM expands it with domain-specific concepts but cannot rename, remove, or contradict your authoritative vocabulary
- **SKOS thesaurus support** — pass `--thesaurus` to load a SKOS vocabulary; `skos:exactMatch` terms are collapsed silently, `skos:closeMatch` terms trigger a warning — giving the schema merger richer synonym awareness than string matching alone
- **Verifiable TTL ontology** — after Pass 1, the induced schema is exported as a valid RDFS Turtle file (`intermediate/schema.ttl`) that can be opened directly in ontology editors such as [Protégé](https://protege.stanford.edu/); the same TTL is validated by rdflib (syntax + semantic checks: domain/range refer to declared classes, no conflicting ranges) before any extraction begins
- **Human-in-the-loop ontology design** — run with `--review` to pause after schema induction; inspect and edit `schema.json` (or load `schema.ttl` in Protégé, modify, and save back) before a single entity is extracted; resume with `mykg approve-schema`
- **Incremental updates** — run with `--append` on an existing session to add new or modified Markdown files without re-running Pass 1; the schema is reused and only the new files go through Pass 2

### Input

- **Markdown files** — any directory of `.md` files; subdirectory structure is preserved; YAML/TOML frontmatter, headings, lists, and code blocks are all treated as structural signals
- **Other formats** — convert PDFs, Word docs, HTML, and other formats to Markdown first using a document parser such as [MinerU](https://github.com/opendatalab/mineru), then point mykg at the output directory

### Graph & Output

- **Provider-agnostic** — works with Anthropic (Claude), OpenAI (GPT-4o), Ollama (local), OpenRouter, or the `claude` CLI with no API key
- **Three output families** — JSONL for Neo4j/NetworkX/RAG, Turtle RDF for OWL toolchains, NetworkX multi-format for graph analysis
- **Interactive HTML graph** — node/edge filtering, search, hover popups; opens directly in a browser
- **Confidence scoring** — every extracted attribute, node, and edge carries a `0.0–1.0` confidence score
- **Name normalization** — surface-form variants ("Acme Corp", "ACME", "Acme Corporation") resolved to a single canonical node with aliases
- **Orphan-connection pass** — reconnects isolated nodes via co-occurrence heuristic + LLM confirmation
- **Cross-session merge** — combine two independently-produced graphs into one unified knowledge graph
- **Resumable pipeline** — every stage persists intermediate state; re-enter at any step after a crash or edit
- **Session isolation** — each run is fully self-contained; inputs, intermediate state, outputs, and logs co-located

---

## Quick Start

**Requirements:** Python 3.11+, and one of: an Anthropic/OpenAI/OpenRouter API key, Ollama running locally, or the `claude` CLI.

```bash
# 1. Install
git clone <repo-url> && cd mykg
uv sync          # or: pip install -e .

# 2. Configure (example: Anthropic Claude)
cat > pipeline_config.yaml << 'EOF'
profile: anthropic-claude

profiles:
  anthropic-claude:
    provider: anthropic
    llm:
      model: claude-opus-4-7
      context_window: 200000
      max_output_tokens: 64000
      timeout: 300
    pipeline:
      chunking:
        window_tokens: 30000
        overlap_tokens: 3000
        tiktoken_encoding: cl100k_base
      pass1:
        batch_token_target: 136000
        max_workers: 4
      pass2:
        max_workers: 4
        stateful_chunks: true
      normalize_names:
        enabled: true
        max_names_per_type: 2000
EOF

export ANTHROPIC_API_KEY=sk-ant-...

# 3. Run
uv run mykg extract-graph my_notes/
# → open sessions/<timestamp>/output/knowledge_graph.html in your browser
```

For Ollama (no API key needed):

```bash
ollama pull llama3.3
echo "profile: ollama-local" > pipeline_config.yaml
uv run mykg extract-graph my_notes/
```

---

## Configuration

All configuration lives in a single `pipeline_config.yaml` file discovered automatically from the working directory (or any parent). There are no hardcoded defaults in the code — the YAML is the sole source of truth.

### LLM Providers

| Provider | Profile name | API key env var | Notes |
|---|---|---|---|
| Anthropic (Claude) | custom (see Quick Start) | `ANTHROPIC_API_KEY` | Recommended for quality |
| OpenAI (GPT-4o) | `openai` | `OPENAI_API_KEY` | |
| Ollama | `ollama-local` | — | Local inference, no key needed |
| OpenRouter | `openrouter-free` | `OPENROUTER_API_KEY` | Access many models via one key |
| Claude CLI | `claude-cli` | — | Uses `claude -p` subprocess; billing via Claude Pro/Max; serial only |

Switch provider by setting `profile:` at the top of `pipeline_config.yaml`.

### Key Pipeline Parameters

| Key | Default | Description |
|---|---|---|
| `pipeline.chunking.window_tokens` | `2000` | Chunk size in tokens |
| `pipeline.chunking.overlap_tokens` | `200` | Overlap between adjacent chunks |
| `pipeline.pass1.batch_token_target` | `8000` | Max tokens per Pass 1 LLM batch |
| `pipeline.pass1.max_workers` | `4` | Parallel LLM workers for Pass 1 |
| `pipeline.pass2.max_workers` | `1` | Parallel workers for Pass 2 |
| `pipeline.pass2.stateful_chunks` | `false` | Pass prior-chunk node IDs to subsequent chunks for stable IDs |
| `pipeline.pass2.prep_mode` | `per_file` | `per_file` \| `concat` \| `batch_chunks` |
| `pipeline.normalize_names.enabled` | `true` | Run LLM name normalization step |
| `pipeline.orphan_pass.enabled` | `true` | Run the orphan-connection pass |
| `pipeline.orphan_pass.schema_max_restarts` | `1` | Max automated Pass 2 restarts from schema-gap recovery |
| `pipeline.export.networkx_enabled` | `true` | Write NetworkX formats to `output/networkx_output/` |
| `pipeline.error_gate.enabled` | `true` | Pause all workers on repeated API errors |

Run `python context_calculator.py --context <N> --max-output <M>` to compute correct `window_tokens` and `batch_token_target` for a different model's context window.

---

## Extract Pipeline

Reads a directory of `.md` files and produces a typed knowledge graph in three output formats. The pipeline runs 11 sequential steps; all intermediate state is persisted so any step can be re-entered without repeating upstream work.

### Running

```bash
uv run mykg extract-graph <input_dir> [OPTIONS]
```

`<input_dir>` is any directory of `.md` files. Subdirectories are included recursively.

### Options

| Option | Description |
|---|---|
| `--session NAME` | Resume an existing session by folder name |
| `--from-step NAME` | Delete a step's outputs and re-run from that point |
| `--review` | Pause after Pass 1 for manual schema review |
| `--append` | Skip Pass 1; re-run only on new/modified files |
| `--workers N` | Parallel workers for Pass 2 |
| `--confidence-agg mean\|max` | Confidence aggregation when deduplicating |
| `--base-schema PATH` | Locked TBox TTL file (locked classes/properties cannot be changed by the LLM) |
| `--thesaurus PATH` | SKOS TTL thesaurus for synonym resolution in schema merge |
| `--log-file PATH` | Write logs here (relative paths placed inside the session folder) |
| `--verbose / -v` | Enable DEBUG-level logging |

### Examples

```bash
# New run — auto-creates a timestamped session
uv run mykg extract-graph my_notes/

# Resume a session with 4 parallel Pass 2 workers
uv run mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --workers 4

# Pause for schema review after Pass 1
uv run mykg extract-graph my_notes/ --review
# → edit sessions/<name>/intermediate/schema.json
mykg approve-schema --session 2026-05-17T18-31-07
uv run mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --review

# Re-run from assembly onward (reuses existing extractions)
uv run mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --from-step assemble

# Lock a base ontology so the LLM won't rename its classes
uv run mykg extract-graph my_notes/ --base-schema ontology/core.ttl
```

---

### Sessions

Every run automatically creates an isolated session folder:

```
sessions/
  2026-05-17T18-31-07/
    input/           ← archived copy of all input Markdown files
    intermediate/    ← all intermediate pipeline state
    output/          ← final outputs (JSONL, TTL, HTML, NetworkX)
    run.log          ← log file
    walkthrough.md   ← post-run report
```

Sessions are the primary unit of resumability. Pass `--session <name>` to resume from the last completed step. Pass `--from-step <step>` to force-restart from a specific point.

The sessions root is configurable via `pipeline.paths.sessions_dir` (default: `sessions/` in the current directory).

---

### Pipeline Steps

The pipeline runs 11 steps in sequence. All intermediate state is written to disk so any step can be re-entered without repeating upstream work.

| # | Step | LLM | Key outputs |
|---|---|---|---|
| 1 | `ingest` | — | `file_manifest.json` |
| 2 | `pass1` | ✓ (3 calls) | `schema.json`, `schema.ttl`, `schema_history/` |
| 3 | `schema_validate` | — | `schema_validate.done` |
| 4 | `human_review` | — | `schema_approved.flag` *(only with `--review`)* |
| 5 | `schema_flatten` | — | `flattened_schema.json` |
| 6 | `pass2` | ✓ | `raw_extractions.json`, `chunk_node_index.json` |
| 7 | `normalize_names` | ✓ | `name_normalization.json` |
| 8 | `assemble` | — | `edge_metadata.json`, `nodes.json`, `merge_log.json` |
| 9 | `orphan_score` | — | `orphan_candidates.json` |
| 10 | `orphan_connect` | ✓ | `orphan_connections.json`, `orphan_log.json` |
| 11 | `validate_graph` | — | `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `knowledge_graph.html`, `networkx_output/` |

Pass 1 internally runs four sequential stages: parallel batch induction → algorithmic merge → harmonization LLM call → quality review LLM call.

---

### Outputs

### Property Graph (JSONL)

**`nodes.jsonl`** — one JSON line per entity:

```json
{
  "id": "person-alice",
  "type": "Person",
  "confidence": 0.94,
  "source_files": ["team.md"],
  "attributes": {
    "name":  {"value": "Alice",          "confidence": 1.0},
    "email": {"value": "alice@acme.com", "confidence": 0.88}
  },
  "aliases": ["Alice Smith", "A. Smith"]
}
```

**`edges.jsonl`** — one JSON line per relationship:

```json
{
  "id": "works_at-abc123",
  "type": "works_at",
  "from": "person-alice",
  "to": "org-acme-corp",
  "confidence": 0.96,
  "method": "llm_extraction",
  "attributes": {
    "role":       {"value": "Engineer", "confidence": 0.91},
    "start_date": {"value": null,       "confidence": 0.0}
  }
}
```

Missing attributes are never dropped — they are represented as `{"value": null, "confidence": 0.0}`.

The `method` field distinguishes edges extracted by Pass 2 (`llm_extraction`) from edges inferred by the orphan pass (`orphan_inferred`).

### RDF / OWL (Turtle)

**`knowledge_graph.ttl`** — pure RDFS triples, no edge metadata:

```turtle
@prefix ex: <http://mykg.local/schema/> .
@prefix :   <http://mykg.local/data/> .

ex:Person  a rdfs:Class .
ex:works_at  rdfs:domain ex:Person ;  rdfs:range ex:Organization .

:person-alice  a ex:Person ;  rdfs:label "Alice" .
:person-alice  ex:works_at  :org-acme-corp .
```

Load in Protégé, query with SPARQL (Fuseki, GraphDB), or reason with HermiT/Pellet.

### Interactive HTML

**`knowledge_graph.html`** — self-contained D3.js force-directed graph. Open in any browser, no server required. Supports:
- Filter nodes and edges by type
- Filter by confidence threshold
- Search by name
- Hover popups with full attribute values
- Resizable sidebar

### NetworkX Formats (`networkx_output/`)

| File | Format | Best for |
|---|---|---|
| `knowledge_graph.graphml` | GraphML | yEd, Gephi, Cytoscape |
| `knowledge_graph.gexf` | GEXF | Gephi native (rich metadata) |
| `knowledge_graph.json` | JSON node-link | D3.js, Sigma.js, web apps |
| `knowledge_graph.gml` | GML | Human-readable inspection |
| `knowledge_graph.net` | Pajek | Network analysis |
| `edges_nx.txt` | Edge list | Text pipelines |
| `adjacency.txt` | Adjacency list | Topology consumers |

Node/edge attributes are exported as `attr_<name>_value` / `attr_<name>_confidence` scalar pairs for GML compatibility.

---

### Re-running from a Specific Step

Use `--from-step` to delete a step's outputs and all downstream outputs, then re-run from that point.

```bash
SESSION=2026-05-17T18-31-07

# Re-run from Pass 2 (reuse the existing schema)
uv run mykg extract-graph my_notes/ --session $SESSION --from-step pass2

# Re-run only assembly + export (reuse raw extractions)
uv run mykg extract-graph my_notes/ --session $SESSION --from-step assemble

# Re-run both orphan stages
uv run mykg extract-graph my_notes/ --session $SESSION --from-step orphan_score

# Orphan LLM pass only — full clean sweep
uv run mykg extract-graph my_notes/ --session $SESSION --from-step orphan_connect_fullsweep

# Orphan LLM pass only — additive (preserves prior confirmed edges)
uv run mykg extract-graph my_notes/ --session $SESSION --from-step orphan_connect_incremental
```

**Four re-entry patterns:**

| Pattern | When to use | Command |
|---|---|---|
| **A — Schema changed** | Wrong concept types, missing properties | Edit `schema.json` → `approve-schema` → `--from-step pass1` |
| **B — Extraction errors** | LLM missed entities or invented edge types | Edit shard in `raw_extractions_shards/` → `--from-step pass2` |
| **C — Assembly errors** | Bad dedup decisions in `merge_log.json` | Edit `raw_extractions.json` → `--from-step assemble` |
| **D — Orphan pass** | Wrong candidates or confirmations | `--from-step orphan_score` or `orphan_connect_fullsweep` |

---

### Orphan-Connection Pass

After assembly, nodes with zero edges are "orphans" — present in the graph but unreachable by traversal. The orphan pass reconnects them in two stages:

**Stage 1 — `orphan_score` (no LLM):** Uses `chunk_node_index.json` to find nodes that co-occur in the same source chunk as each orphan. Candidates are scored by co-occurrence frequency and filtered by schema type compatibility. Written to `orphan_candidates.json`.

**Stage 2 — `orphan_connect` (LLM):** One LLM call per source chunk. The prompt includes the full chunk text, all orphan IDs from that chunk, co-occurring connected nodes, and all schema properties. Confirmed edges carry `"method": "orphan_inferred"` and are merged directly into `edge_metadata.json`.

Unconnectable orphans (no resolvable source chunk) are logged as `orphan_unconnectable` advisory events in `orphan_log.json`.

Configure via `pipeline.orphan_pass.*` in `pipeline_config.yaml`. Disable entirely with `pipeline.orphan_pass.enabled: false`.

---

## Merge Pipeline

`mykg merge-graphs` is a 12-step pipeline that combines two independently-produced extract sessions into a single unified knowledge graph. Both sessions are read-only; all output lands in a fresh timestamped session.

```bash
uv run mykg merge-graphs <session-A> <session-B> [OPTIONS]
```

```bash
# Example
uv run mykg merge-graphs 2026-05-01T10-00-00 2026-05-15T14-30-00

# Resume a merge (last incomplete step auto-detected)
uv run mykg merge-graphs A B --output-session <merged-name>
```

**Options:**

| Option | Description |
|---|---|
| `--output-session TEXT` | Name for the merged session (default: auto-timestamped) |
| `--no-review` | Skip the human review gate after schema merge |
| `--thesaurus PATH` | SKOS thesaurus for schema synonym matching |
| `--base-schema PATH` | Locked TBox TTL base schema |
| `--from-step NAME` | Force re-run from a specific merge step |

### Merge Pipeline Steps

| # | Step | LLM | What it does |
|---|---|---|---|
| 1 | `merge_setup` | — | Load both sessions, namespace shard files, write `source_map.json` |
| 2 | `merge_schema` | ✓ (3 calls) | Schema union → LLM harmonization → LLM quality review → `schema.json` |
| 3 | `schema_validate` | — | RDFS validation; LLM correction on failure |
| 4 | `human_review` | — | Optional gate (`--review`); edit `schema.json` before re-extraction |
| 5 | `schema_flatten` | — | Flatten inheritance for LLM prompts |
| 6 | `merge_reextract` | ✓ | Re-extract chunks for new properties (`none`/`surgical`/`full`) |
| 7 | `merge_raw` | — | Namespace + merge raw extractions from both sessions |
| 8 | `assemble` | — | Stable IDs, node/edge dedup, edge metadata sidecar |
| 9 | `orphan_score` | — | Co-occurrence heuristic for isolated nodes |
| 10 | `orphan_connect` | ✓ | LLM confirmation for orphan edges |
| 11 | `validate_graph` | — | Export `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `networkx_output/` |
| 12 | `merge_manifest` | — | Write `merge_manifest.json` audit record |

**What happens:**

1. Both schemas are merged via the same three-stage chain as Pass 1 (algorithmic union → LLM harmonization → LLM quality review)
2. All file-keyed structures are namespaced (`session_a/<filename>`, `session_b/<filename>`) before merging
3. Nodes are deduplicated across sessions: same type + canonical name → single node, regardless of source session
4. Re-extraction strategy (`none` / `surgical` / `full`) handles properties absent from one session's schema
5. `source_map.json` records full file provenance; `merge_manifest.json` records schema deltas and strategy used
6. `walkthrough.md` includes a Merge Provenance section with before/after counts and node/edge breakdowns

Configure the re-extraction strategy:

```yaml
merge_graphs:
  reextraction_strategy: surgical   # none | surgical | full
```

---

## Advanced Options

### Human Review Gate (`--review`)

Pause after Pass 1 to inspect and edit the induced schema before Pass 2 runs:

```bash
uv run mykg extract-graph my_notes/ --review
# → pipeline halts; edit sessions/<name>/intermediate/schema.json
mykg approve-schema --session <name>
uv run mykg extract-graph my_notes/ --session <name> --review   # resumes from Pass 2
```

### Locked Base Schema (`--base-schema`)

Lock certain classes and properties so the LLM cannot rename, remove, or restructure them:

```bash
uv run mykg extract-graph my_notes/ --base-schema ontology/base.ttl
```

Locked entries can still receive additional attributes proposed by the LLM. Near-duplicate LLM proposals are collapsed into the locked entry with a warning.

### SKOS Thesaurus (`--thesaurus`)

Resolve near-duplicate concept names during schema merge using a SKOS vocabulary:

```bash
uv run mykg extract-graph my_notes/ --thesaurus ontology/terms.skos.ttl
```

- `skos:exactMatch` → silent collapse
- `skos:closeMatch` → collapse with warning in `merge_log.json`
- `skos:broader` / `skos:narrower` → advisory hints only

### Walkthrough Report

A human-readable summary is written to `sessions/<name>/walkthrough.md` after every run:

```bash
# Regenerate the walkthrough for an existing session
uv run mykg walkthrough --session 2026-05-17T18-31-07
```

Disable with `pipeline.report.enabled: false`.

### Append Mode

Re-run the pipeline on new or modified files without re-running Pass 1:

```bash
uv run mykg extract-graph my_notes/ --session <name> --append
```

---

## Development

### Installation

```bash
git clone <repo-url> && cd mykg
uv sync
```

### Testing

```bash
# All non-live tests (fast, no API key needed)
uv run pytest -m "not live" -v

# All tests including live API integration tests
# Requires OPENROUTER_API_KEY in environment or .env
uv run pytest -m live -v

# Single file
uv run pytest tests/test_assembler.py -v

# With coverage (HTML report at htmlcov/index.html)
uv run pytest -m "not live"
open htmlcov/index.html
```

### Linting and Formatting

```bash
uv run ruff check src/ tests/          # lint
uv run ruff check --fix src/ tests/    # auto-fix
uv run ruff format src/ tests/         # format
```

### Token Budget Calculator

When switching to a model with a different context window:

```bash
python context_calculator.py --context 128000 --max-output 16384
```

Outputs a ready-to-paste YAML snippet for the `pipeline:` block.

### Profiling

```bash
python -m cProfile -o profile.out -m mykg.cli extract input_files/
uv run snakeviz profile.out
```

---

## Design

For a thorough description of the architecture, algorithm, data models, and design decisions, see [docs/design.md](docs/design.md).

---

## License

MIT — see [LICENSE](LICENSE).
