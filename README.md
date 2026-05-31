
<p align="center">
  <img src="https://gcore.jsdelivr.net/gh/SenolIsci/mykg@main/docs/mykg-logo-text.svg" width="400px" style="vertical-align:middle;">
</p>

# myKG — Knowledge Graph Extractor

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![CI](https://github.com/SenolIsci/mykg/actions/workflows/ci.yml/badge.svg)](https://github.com/SenolIsci/mykg/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/SenolIsci/mykg/branch/main/graph/badge.svg)](https://codecov.io/gh/SenolIsci/mykg)
[![Providers](https://img.shields.io/badge/LLM-Anthropic%20%7C%20OpenAI%20%7C%20Ollama%20%7C%20OpenRouter-orange.svg)](#configuration)
[![PyPI version](https://img.shields.io/pypi/v/mykg.svg)](https://pypi.org/project/mykg/)
[![PyPI Downloads](https://img.shields.io/pypi/dm/mykg.svg)](https://pypi.org/project/mykg/)
[![GitHub Stars](https://img.shields.io/github/stars/SenolIsci/mykg?style=flat-square&logo=github)](https://github.com/SenolIsci/mykg/stargazers)
[![GitHub Issues](https://img.shields.io/github/issues/SenolIsci/mykg.svg)](https://github.com/SenolIsci/mykg/issues)
[![Visitors](https://visitor-badge.laobi.icu/badge?page_id=SenolIsci.mykg)](https://github.com/SenolIsci/mykg)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-senolisci-0077B5?logo=linkedin)](https://www.linkedin.com/in/senolisci/)

**myKG** automatically generates a confidence-scored knowledge graph from a directory of mixed documents — Markdown, PDF, Word, PowerPoint, HTML, and images — grounded in an inferred RDFS/OWL ontology.

## Command line

```
mykg extract-graph my_notes/        # any directory: .md, .pdf, .docx, .html, images
```
It uses a **two-pass LLM pipeline**: Pass 1 induces a global RDFS/OWL schema from your document corpus; Pass 2 extracts typed entity and relationship instances per file against that schema. Non-Markdown inputs (`.pdf .docx .doc .pptx .png .jpg .jpeg .html .htm`) are converted to Markdown automatically before extraction. The result is exported to multiple formats: JSONL for property-graph consumers such as Neo4j, Turtle RDF for OWL toolchains, seven NetworkX formats for graph analysis and visualization, and an Obsidian vault — a second brain of wikilinked Markdown notes your AI coding assistant (Claude Code, Cursor, Copilot) can read and reason over directly.
<p align="center">
  <img src="https://gcore.jsdelivr.net/gh/SenolIsci/mykg@main/docs/diagrams/architecture-sketch.png" width="80%" style="vertical-align:middle;">
</p>

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Using with Claude Code](#using-with-claude-code)
- [Configuration](#configuration)
- [Extract Pipeline](#extract-pipeline)
  - [Running](#running)
  - [Sessions](#sessions)
  - [Pipeline Steps](#pipeline-steps)
- [Outputs](#outputs)
  - [Re-running from a Specific Step](#re-running-from-a-specific-step)
  - [Orphan-Connection Pass](#orphan-connection-pass)
- [Advanced Options](#advanced-options)
  - [Human Review Gate](#human-review-gate---review)
  - [Locked Base Schema](#locked-base-schema---base-schema)
  - [SKOS Thesaurus](#skos-thesaurus---thesaurus)
  - [Append Mode](#append-mode)
  - [Merging Sessions](#merging-sessions)
  - [Walkthrough Report](#walkthrough-report)
  - [Obsidian Vault Export](#obsidian-vault-export)
- [Development](#development)
- [Roadmap](#roadmap)
- [Design](#design)
- [License](#license)

## Features

### Ontology-Guided Extraction

- **Schema-guided knowledge graph generation** — the extracted graph is always grounded in a formal RDFS/OWL schema: concept types, property names, domain/range constraints, and the is-a hierarchy are explicit and inspectable before any entity is extracted
- **Bring your own ontology** — supply a `--base-schema` TTL file to lock in classes and properties from an existing formal ontology; the LLM expands it with domain-specific concepts but cannot rename, remove, or contradict your authoritative vocabulary
- **SKOS thesaurus support** — pass `--thesaurus` to load a SKOS vocabulary; `skos:exactMatch` terms are collapsed silently, `skos:closeMatch` terms trigger a warning — giving the schema merger richer synonym awareness than string matching alone
- **Verifiable TTL ontology** — after Pass 1, the induced schema is exported as a valid RDFS/OWL Turtle file (`intermediate/schema.ttl`) that can be opened directly in ontology editors such as [Protégé](https://protege.stanford.edu/). The TTL is validated by rdflib (syntax + semantic checks: domain/range refer to declared classes, no conflicting ranges) before any extraction begins
- **Human-in-the-loop ontology design** — run with `--review` to pause after schema induction; inspect and edit `schema.json` (or load `schema.ttl` in Protégé, modify, and save back) before a single entity is extracted; resume with `mykg approve-schema`
- **Incremental updates** — run with `--append` on an existing session to add new or modified Markdown files without re-running Pass 1; the schema is reused and only the new files go through Pass 2
- **AI coding assistant friendly** — designed for smooth use alongside AI coding assistants such as [Claude Code](https://claude.ai/code); run extractions, inspect outputs, and iterate on your knowledge graph without leaving your coding environment; see [Using with Claude Code](#using-with-claude-code)
- **Second brain for AI coding assistants** — the Obsidian vault output turns your extracted knowledge graph into a directory of wikilinked Markdown notes that any AI coding assistant can read as project context; point Claude Code, Cursor, or Copilot at `output/obsidian_vault/` and ask questions, trace relationships, and get answers grounded in your own documents

### Input

- **Mixed-format corpora** — point `mykg extract-graph` at any directory; supported extensions are converted to Markdown automatically before ingest:

  | Format | Extensions | Backend |
  |---|---|---|
  | Markdown | `.md` | passthrough (consumed as-is) |
  | PDF, Word, PowerPoint, images | `.pdf .docx .doc .pptx .png .jpg .jpeg` | [MinerU](https://github.com/opendatalab/mineru) in an ephemeral `uv`-managed Python 3.12 venv — nothing is installed into your active environment |
  | HTML | `.html .htm` | [`markdownify`](https://pypi.org/project/markdownify/) in-process; anchors and image tags stripped |

  Anything outside the allowlist (e.g. `.svg`, `.css`, `.php` assets next to an HTML bundle) is logged and skipped, never silently dropped. The allowlist is configurable via `preprocess.extensions` in `mykg_config.yaml`.
- **Structural signals preserved** — YAML/TOML frontmatter, headings, lists, and code blocks all act as extraction hints regardless of the source format; subdirectory structure under the input dir is preserved through the pipeline.

### Graph & Output

- **Provider-agnostic** — works with Anthropic (Claude), OpenAI (GPT), Ollama (local), OpenRouter, or the `claude` CLI with no API key
- **Four output families** — JSONL for Neo4j/NetworkX/RAG, Turtle RDF for OWL toolchains, NetworkX multi-format for graph analysis, and Obsidian vault for linked personal knowledge management
- **Obsidian vault — second brain for AI coding assistants** — every extracted entity becomes a wikilinked Markdown note in `output/obsidian_vault/`; open it in [Obsidian](https://obsidian.md) to navigate the graph with backlinks and Graph View, or point your AI coding assistant (Claude Code, Cursor, Copilot) at the vault folder so it can answer questions, trace relationships, and reason over your knowledge base in natural language
- **Interactive HTML graph** — node/edge filtering, search, hover popups; opens directly in a browser
- **Confidence scoring** — every extracted attribute, node, and edge carries a `0.0–1.0` confidence score
- **Name normalization** — surface-form variants ("Acme Corp", "ACME", "Acme Corporation") resolved to a single canonical node with aliases
- **Orphan-connection pass** — reconnects isolated nodes via co-occurrence heuristic + LLM confirmation
- **Cross-session merge** — combine two independently-produced graphs into one unified knowledge graph
- **Resumable pipeline** — every stage persists intermediate state; re-enter at any step after a crash or edit
- **Session isolation** — each run is fully self-contained; inputs, intermediate state, outputs, and logs co-located
- **Query knowledge graph** — natural-language queries directly against the extracted graph via AI coding assistants such as [Claude Code](https://claude.ai/code).

## Quick Start

Requires Python 3.11+ and one of: an Anthropic/OpenAI/OpenRouter API key, Ollama running locally, or the `claude` CLI.

### Install from PyPI

Install mykg, then run the interactive setup wizard — it asks for your provider, model, and API key and writes `mykg_config.yaml` and `.env.mykg` in one step.

```bash
pip install mykg
mykg init
mykg extract-graph my_notes/
```

Open `sessions/<timestamp>/output/knowledge_graph.html` in your browser to explore the result.

### Install from source

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone the repo, sync dependencies, run the setup wizard, then extract.

```bash
git clone https://github.com/SenolIsci/mykg && cd mykg
uv sync && mykg init
uv run mykg extract-graph my_notes/
```

For Ollama (local inference, no API key needed), pull a model and select the `ollama-local` profile when `mykg init` prompts you.

```bash
ollama pull llama3.3
mykg init
mykg extract-graph my_notes/
```

## Using with Claude Code

myKG ships with a `claude-cli` profile that runs extractions through the locally-installed `claude` CLI — no API key or billing setup needed beyond your existing Claude Pro/Max plan.

### Setup

Install the `claude` CLI, then install mykg and run the setup wizard — select **[5] Claude CLI** when prompted (no API key needed).

```bash
npm install -g @anthropic-ai/claude-code
pip install mykg && mykg init
mykg extract-graph my_notes/
```

### How it works

The `claude-cli` provider calls `claude -p` as a subprocess for every LLM step (Pass 1 schema induction, Pass 2 extraction, orphan connection, name normalization). All pipeline features — session isolation, resumability, orphan recovery, cross-session merge — work identically to API-based providers.

**Key constraints of the `claude-cli` profile:**
- `max_workers` must be `1` — the `claude` CLI is serial by design; parallel workers will queue
- No API key required — billing goes through your Claude Pro/Max subscription
- The `effort` and `model` fields in `mykg_config.yaml` map directly to `--effort` and `--model` flags passed to `claude -p`

### Using myKG from inside Claude Code

You can run myKG extractions as a tool call from within a Claude Code session. This is useful for building knowledge graphs from notes or documentation while you work:

```bash
# From any Claude Code session terminal:
mykg extract-graph ./docs/ --session my-docs-kg

# Then reference the output in your session:
# sessions/my-docs-kg/output/nodes.jsonl
# sessions/my-docs-kg/output/knowledge_graph.ttl
```

Claude Code can then read `nodes.jsonl` or `edges.jsonl` directly to answer questions about the extracted graph, or load `knowledge_graph.ttl` into a SPARQL tool for structured queries.

### Recommended `mykg_config.yaml` settings for Claude Code

```yaml
profile: claude-cli

profiles:
  claude-cli:
    llm:
      model: sonnet       # or opus for higher quality
      effort: medium      # low | medium | high
    pipeline:
      pass1:
        max_workers: 1    # required — claude CLI is serial
      pass2:
        max_workers: 1
```

---

## Configuration

All configuration lives in a single `mykg_config.yaml` file discovered automatically from the working directory (or any parent). There are no hardcoded defaults in the code — the YAML is the sole source of truth.

```bash
mykg init           # interactive: choose provider, model, paste API key
                    # writes mykg_config.yaml and .env.mykg in one step
mykg init --force   # overwrite an existing config
mykg init --profile openrouter-free --model google/llama-4-maverick --api-key sk-or-...  # non-interactive
```

The wizard walks you through three prompts:

1. **Profile** — choose your LLM provider (OpenRouter, Anthropic, OpenAI, Ollama, Claude CLI)
2. **Model** — accept the default or type any model slug for that provider
3. **API key** — paste your key (skipped for Ollama and Claude CLI)

### LLM Providers

| Provider | Profile name | API key env var | Notes |
|---|---|---|---|
| Anthropic (Claude) | `anthropic-claude` | `ANTHROPIC_API_KEY` | Recommended for quality |
| OpenAI | `openai` | `OPENAI_API_KEY` | |
| Ollama | `ollama-local` | — | Local inference, no key needed |
| OpenRouter | `openrouter-free` | `OPENROUTER_API_KEY` | Access many models via one key |
| Claude CLI | `claude-cli` | — | Uses `claude -p` subprocess; billing via Claude Pro/Max; serial only |

Switch provider by setting `profile:` at the top of [`mykg_config.yaml`](mykg_config.yaml).


### API Keys

myKG reads API keys from environment variables. Set them by exporting directly or by creating a `.env.mykg` file in your project directory (loaded automatically on startup).

**Option A — export in your shell:**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Option B — create a `.env.mykg` file:**

```bash
# .env.mykg
ANTHROPIC_API_KEY=sk-ant-...
```
For source installs you can also copy [`sample.env.mykg`](sample.env.mykg) to `.env.mykg` as a starting template.



## Extract Pipeline

Reads a directory of mixed format files and produces a typed knowledge graph in three output formats. The pipeline runs 12 sequential steps; all intermediate state is persisted so any step can be re-entered without repeating upstream work.

### Running

```bash
mykg extract-graph <input_dir> [OPTIONS]
# source installs: uv run mykg extract-graph <input_dir> [OPTIONS]
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
| `--obsidian-vault` | Force Obsidian vault export for this run (overrides config) |
| `--log-file PATH` | Write logs here (relative paths placed inside the session folder) |
| `--verbose / -v` | Enable DEBUG-level logging |

### Examples

```bash
# New run — auto-creates a timestamped session
mykg extract-graph my_notes/

# Resume a session with 4 parallel Pass 2 workers
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --workers 4

# Pause for schema review after Pass 1
mykg extract-graph my_notes/ --review
# → edit sessions/<name>/intermediate/schema.json
mykg approve-schema --session 2026-05-17T18-31-07
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --review

# Re-run from assembly onward (reuses existing extractions)
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --from-step assemble

# Lock a base ontology so the LLM won't rename its classes
mykg extract-graph my_notes/ --base-schema ontology/core.ttl
```

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

### Pipeline Steps

The pipeline runs 12 steps in sequence. All intermediate state is written to disk so any step can be re-entered without repeating upstream work.

| # | Step | LLM | Key outputs |
|---|---|---|---|
| 1 | `preprocess` | — | `preprocess.done`, `preprocess_manifest.json`, files under `input/_preprocessed/` *(routes non-md inputs to MinerU or markdownify; no-op for pure Markdown corpora)* |
| 2 | `ingest` | — | `file_manifest.json` |
| 3 | `pass1` | ✓ (3 calls) | `schema.json`, `schema.ttl`, `schema_history/` |
| 4 | `schema_validate` | — | `schema_validate.done` |
| 5 | `human_review` | — | `schema_approved.flag` *(only with `--review`)* |
| 6 | `schema_flatten` | — | `flattened_schema.json` |
| 7 | `pass2` | ✓ | `raw_extractions.json`, `chunk_node_index.json` |
| 8 | `normalize_names` | ✓ | `name_normalization.json` |
| 9 | `assemble` | — | `edge_metadata.json`, `nodes.json`, `merge_log.json` |
| 10 | `orphan_score` | — | `orphan_candidates.json` |
| 11 | `orphan_connect` | ✓ | `orphan_connections.json`, `orphan_log.json` |
| 12 | `validate_graph` | — | `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `knowledge_graph.html`, `networkx_output/`, `obsidian_vault/` |

Pass 1 internally runs four sequential stages: parallel batch induction → algorithmic merge → harmonization LLM call → quality review LLM call.

## Outputs

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

**`knowledge_graph.ttl`** — pure RDFS/OWL triples, no edge metadata:

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

### Obsidian Vault (`obsidian_vault/`)

One `.md` note per extracted entity, grouped into subdirectories by concept type. Each note has YAML frontmatter (id, type, confidence, sources), an attributes section, outgoing and incoming wikilink relationship sections, and a source files list. An `index.md` at the vault root summarizes node counts per type with links to every entity.

Open `output/obsidian_vault/` as a vault in [Obsidian](https://obsidian.md) to get Graph View, backlink navigation, and full-text search across the extracted entities.

### Re-running from a Specific Step

Use `--from-step` to delete a step's outputs and all downstream outputs, then re-run from that point.

```bash
SESSION=2026-05-17T18-31-07

# Re-run from Pass 2 (reuse the existing schema)
mykg extract-graph my_notes/ --session $SESSION --from-step pass2

# Re-run only assembly + export (reuse raw extractions)
mykg extract-graph my_notes/ --session $SESSION --from-step assemble

# Re-run both orphan stages
mykg extract-graph my_notes/ --session $SESSION --from-step orphan_score

# Orphan LLM pass only — full clean sweep
mykg extract-graph my_notes/ --session $SESSION --from-step orphan_connect_fullsweep

# Orphan LLM pass only — additive (preserves prior confirmed edges)
mykg extract-graph my_notes/ --session $SESSION --from-step orphan_connect_incremental
```

**Four re-entry patterns:**

| Pattern | When to use | Command |
|---|---|---|
| **A — Schema changed** | Wrong concept types, missing properties | Edit `schema.json` → `approve-schema` → `--from-step pass1` |
| **B — Extraction errors** | LLM missed entities or invented edge types | Edit shard in `raw_extractions_shards/` → `--from-step pass2` |
| **C — Assembly errors** | Bad dedup decisions in `merge_log.json` | Edit `raw_extractions.json` → `--from-step assemble` |
| **D — Orphan pass** | Wrong candidates or confirmations | `--from-step orphan_score` or `orphan_connect_fullsweep` |

### Orphan-Connection Pass

After assembly, nodes with zero edges are "orphans" — present in the graph but unreachable by traversal. The orphan pass reconnects them in two stages:

**Stage 1 — `orphan_score` (no LLM):** Uses `chunk_node_index.json` to find nodes that co-occur in the same source chunk as each orphan. Candidates are scored by co-occurrence frequency and filtered by schema type compatibility. Written to `orphan_candidates.json`.

**Stage 2 — `orphan_connect` (LLM):** One LLM call per source chunk. The prompt includes the full chunk text, all orphan IDs from that chunk, co-occurring connected nodes, and all schema properties. Confirmed edges carry `"method": "orphan_inferred"` and are merged directly into `edge_metadata.json`.

Unconnectable orphans (no resolvable source chunk) are logged as `orphan_unconnectable` advisory events in `orphan_log.json`.

Configure via `pipeline.orphan_pass.*` in `mykg_config.yaml`. Disable entirely with `pipeline.orphan_pass.enabled: false`.

## Advanced Options

### Human Review Gate (`--review`)

Pause after Pass 1 to inspect and edit the induced schema before Pass 2 runs:

```bash
mykg extract-graph my_notes/ --review
# → pipeline halts; edit sessions/<name>/intermediate/schema.json
mykg approve-schema --session <name>
mykg extract-graph my_notes/ --session <name> --review   # resumes from Pass 2
```

### Locked Base Schema (`--base-schema`)

Lock certain classes and properties so the LLM cannot rename, remove, or restructure them:

```bash
mykg extract-graph my_notes/ --base-schema ontology/base.ttl
```

Locked entries can still receive additional attributes proposed by the LLM. Near-duplicate LLM proposals are collapsed into the locked entry with a warning.

### SKOS Thesaurus (`--thesaurus`)

Resolve near-duplicate concept names during schema merge using a SKOS vocabulary:

```bash
mykg extract-graph my_notes/ --thesaurus ontology/terms.skos.ttl
```

- `skos:exactMatch` → silent collapse
- `skos:closeMatch` → collapse with warning in `merge_log.json`
- `skos:broader` / `skos:narrower` → advisory hints only

### Append Mode

Re-run the pipeline on new or modified files without re-running Pass 1:

```bash
mykg extract-graph my_notes/ --session <name> --append
```

> **Note:** Append mode currently only supports adding or updating `.md` files. Mixed-format inputs (PDF, DOCX, HTML, etc. — i.e. anything requiring the `preprocess` step) are not yet supported. As a workaround, convert non-Markdown files to Markdown manually with `mykg parse-docs` first, pointing `--output` at the same folder you'll pass to `--append`:
>
> ```bash
> mykg parse-docs --input raw_docs/ --output my_notes/
> mykg extract-graph my_notes/ --session <name> --append
> ```

### Merging Sessions

Combine two independently-produced sessions into a unified knowledge graph:

```bash
mykg merge-graphs <session-A> <session-B> [OPTIONS]

# Example
mykg merge-graphs 2026-05-01T10-00-00 2026-05-15T14-30-00

# Resume a merge (last incomplete step auto-detected)
mykg merge-graphs A B --output-session <merged-name>
```

**Options:**

| Option | Description |
|---|---|
| `--output-session TEXT` | Name for the merged session (default: auto-timestamped) |
| `--no-review` | Skip the human review gate after schema merge |
| `--thesaurus PATH` | SKOS thesaurus for schema synonym matching |
| `--base-schema PATH` | Locked TBox TTL base schema |
| `--from-step NAME` | Force re-run from a specific merge step |

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

### Obsidian Vault Export

Every run writes a linked Markdown vault to `output/obsidian_vault/` by default. Open that folder in [Obsidian](https://obsidian.md) to explore the extracted knowledge graph with Graph View and backlinks.

**Vault structure:**

```
output/obsidian_vault/
  index.md                  ← overview: node count per type, links to every entity
  Person/
    person-alice-smith.md   ← one note per entity
    person-bob-jones.md
  Organization/
    organization-acme-corp.md
  ...
```

**Each entity note contains:**

```markdown
---
id: person-alice-smith
type: Person
confidence: 0.94
sources:
  - team.md
---

# Alice Smith

## Attributes
- **role**: Engineer (0.91)
- **email**: alice@acme.com (1.0)

## Relationships

### Outgoing
- [[Acme Corp]] — works_at (0.96)

### Incoming
- [[Bob Jones]] — manages (0.88)

## Source Files
- team.md
```

Wikilinks (`[[...]]`) are Obsidian-native — clicking them in the app navigates to the linked entity note, and the Graph View shows the full relationship network automatically.

**Config:**

```yaml
pipeline:
  export:
    obsidian_enabled: true          # default — set false to skip vault export
    obsidian_vault_dir: obsidian_vault   # subfolder name inside output/
```

Or use `--obsidian-vault` on the command line for a one-off run without editing config.

### Walkthrough Report

A human-readable summary is written to `sessions/<name>/walkthrough.md` after every run:

```bash
# Regenerate the walkthrough for an existing session
mykg walkthrough --session 2026-05-17T18-31-07
```

Disable with `pipeline.report.enabled: false`.

---

## Development

### Installation

```bash
git clone https://github.com/SenolIsci/mykg && cd mykg
uv sync
```

### Testing

```bash
# All non-live tests (fast, no API key needed)
uv run pytest -m "not live" -v

# All tests including live API integration tests
# Requires OPENROUTER_API_KEY in environment or .env.mykg (see sample.env.mykg)
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
context-calculator --context 128000 --max-output 16384
```

Outputs a ready-to-paste YAML snippet for the `pipeline:` block.

### Profiling

```bash
python -m cProfile -o profile.out -m mykg.cli extract input_files/
uv run snakeviz profile.out
```

---

## Roadmap

- **Query knowledge graph** — natural-language and structured queries directly against the extracted graph; planned support for SPARQL, graph traversal, and LLM-assisted Q&A over nodes and edges

---

## Design

For a thorough description of the architecture, algorithm, data models, and design decisions, see [docs/architecture.md](docs/architecture.md).

---

## License

MIT — see [LICENSE](LICENSE).
