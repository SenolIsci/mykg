
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
[![Downloads](https://img.shields.io/pepy/dt/mykg?color=blue&label=downloads)](https://pepy.tech/project/mykg)
[![GitHub Stars](https://img.shields.io/github/stars/SenolIsci/mykg?style=flat-square&logo=github)](https://github.com/SenolIsci/mykg/stargazers)
[![GitHub Issues](https://img.shields.io/github/issues/SenolIsci/mykg.svg)](https://github.com/SenolIsci/mykg/issues)
[![Visitors](https://visitor-badge.laobi.icu/badge?page_id=SenolIsci.mykg)](https://github.com/SenolIsci/mykg)
[![Medium](https://img.shields.io/badge/Medium-000000?logo=medium&logoColor=white)](https://medium.com/@senol.isci)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-senolisci-0077B5?logo=linkedin)](https://www.linkedin.com/in/senolisci/)

**myKG** automatically generates a confidence-scored knowledge graph from a set of mixed documents — Markdown, plain text, PDF, Word, PowerPoint, Excel, HTML, and images — grounded in an induced RDFS/OWL ontology.

<p align="center">
  <img src="https://gcore.jsdelivr.net/gh/SenolIsci/mykg@main/docs/mykg_logo_panel.png" width="95%" style="vertical-align:middle;">
</p>

## Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Command line](#command-line)
- [Articles & Tutorials](#articles--tutorials)
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
  - [Website / Repo Fetching](#website--repo-fetching-mykg-fetch-web)
  - [Standalone Document Conversion](#standalone-document-conversion-mykg-parse-docs)
  - [Append Mode](#append-mode)
    - [Incremental Schema Growth](#incremental-schema-growth---append-with-grow-schema)
  - [Merging Sessions](#merging-sessions)
  - [Walkthrough Report](#walkthrough-report)
  - [Obsidian Vault Export](#obsidian-vault-export)
  - [Neo4j LOAD CSV Export](#neo4j-load-csv-export)
- [MCP (Model Context Protocol) Server](#mcp-model-context-protocol-server)
- [Using mykg with Claude Code](#using-mykg-with-claude-code)
  - [Agent mode (Claude Code skill)](#agent-mode-claude-code-skill)
  - [claude-cli profile](#claude-cli-profile)
- [Roadmap](#roadmap)
- [Development](#development)
- [Design](#design)
- [License](#license)

## Features
MyKG builds trustworthy knowledge graphs through a self-evolving ontology that continuously adapts, maintains consistency, and assigns confidence scores to knowledge, keeping information grounded and reliable as it grows.

### Ontology-Guided Extraction
- **Schema-guided knowledge graph generation** — the extracted graph is always grounded in a formal RDFS/OWL schema: concept types, property names, domain/range constraints, and the is-a hierarchy are explicit and inspectable before any entity is extracted

- **AI coding assistant friendly** — designed for smooth use alongside AI coding assistants such as [Claude Code](https://claude.ai/code); run extractions, inspect outputs, and iterate on your knowledge graph without leaving your coding environment; see [Using mykg with Claude Code](#using-mykg-with-claude-code)
- **Second brain for AI coding assistants** — the Obsidian vault output turns your extracted knowledge graph into a directory of wikilinked Markdown notes that any AI coding assistant can read as project context; point Claude Code, Cursor, or Copilot at `output/obsidian_vault/` and ask questions, trace relationships, and get answers grounded in your own documents
- **MCP server for desktop AI apps** — run `mykg mcp-serve` to expose your knowledge graph via the [Model Context Protocol](https://modelcontextprotocol.io/); integrates with [Claude Desktop](https://claude.ai/download), [Cherry Studio](https://cherry-ai.com), and any MCP-compatible client — 13 query tools let LLMs search entities, explore relationships, find paths, traverse the graph, and read wiki notes directly from your extracted knowledge; see [MCP Server](#mcp-model-context-protocol-server)
- **Incremental updates** — append new files to an existing session, extracting only what changed. Optionally grow the schema from new documents while preserving existing concepts and properties
- **Bring your own ontology** — supply a `--base-schema` TTL file (RDFS or OWL) to lock in classes and properties from an existing formal ontology; the LLM expands it with domain-specific concepts but will not rename, remove, or contradict your authoritative vocabulary.Please note that this mechanism is contolled by the LLM, and may not be strictly enforced. Add `--freeze-schema` to skip LLM schema induction entirely and extract from the documents strictly against your ontology verbatim — no surprise types, no invented properties
- **SKOS thesaurus support** — pass `--thesaurus` to load a SKOS vocabulary; `skos:exactMatch` terms are collapsed silently, `skos:closeMatch` terms trigger a warning — giving the schema merger richer synonym awareness than string matching alone
- **Verifiable TTL ontology** — after Pass 1, the induced schema is exported as a valid RDFS/OWL Turtle file (`intermediate/schema.ttl`) that can be opened directly in ontology editors such as [Protégé](https://protege.stanford.edu/). The TTL is validated by rdflib (syntax + semantic checks: domain/range refer to declared classes, no conflicting ranges) before any extraction begins
- **Human-in-the-loop ontology design** — pause after schema induction with `--review`, edit the schema, and resume extraction. Edit `schema.json` directly or refine `schema.ttl` in Protégé and feed it back with `--freeze-schema`

<p align="center">
  <img src="https://gcore.jsdelivr.net/gh/SenolIsci/mykg@main/docs/diagrams/architecture-sketch.png" width="95%" style="vertical-align:middle;">
</p>

### Input

- **Mixed-format corpora** — point `mykg extract-graph` at any directory; supported extensions are converted to Markdown automatically before ingest:

  | Format | Extensions | Backend |
  |---|---|---|
  | Markdown | `.md` | passthrough (consumed as-is) |
  | Plain text | `.txt` | renamed to `.md` in-process |
  | PDF, Word, PowerPoint, Excel, images | `.pdf .docx .doc .pptx .xlsx .png .jpg .jpeg` | [MinerU](https://github.com/opendatalab/mineru) in an ephemeral `uv`-managed Python 3.12 venv — nothing is installed into your active environment |
  | HTML | `.html .htm` | [`markdownify`](https://pypi.org/project/markdownify/) in-process; anchors and image tags stripped |
  | Websites, GitHub repos | any URL | [Crawlee](https://github.com/apify/crawlee) in an ephemeral `uv` venv — produces an `mykg_web_fetch/` folder

  Anything outside the allowlist (e.g. `.svg`, `.css`, `.php` assets next to an HTML bundle) is logged and skipped, never silently dropped. The allowlist is configurable via `preprocess.extensions` in `mykg_config.yaml`.

  **Incremental conversion** — unchanged source files are skipped on re-run. Adding one PDF to a corpus and re-running only re-converts that PDF. Force a full re-conversion with `mykg extract-graph --from-step preprocess`.

### Graph & Output

- **Provider-agnostic** — works with Anthropic (Claude), OpenAI (GPT), Ollama (local), OpenRouter, or the `claude` CLI
- **Five output families** — JSONL for Neo4j/NetworkX/RAG, Turtle RDF for OWL toolchains, NetworkX multi-format for graph analysis, Obsidian vault for linked personal knowledge management, and an optional Neo4j LOAD CSV bundle (plain-header CSVs + paste-and-run Cypher script for Neo4j Browser / `cypher-shell`)
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

Requires Python 3.11+ (developed on macOS; automated CI runs the test suite on Ubuntu and Windows), and one of: an Anthropic/OpenAI/OpenRouter API key, Ollama running locally, or the `claude` CLI.

### Install from PyPI

Install mykg, then run the interactive setup wizard — it asks for your provider, model, and API key and writes `mykg_config.yaml` and `.env.mykg` in one step.

```bash
pip install mykg
mykg init
```

Then extract a knowledge graph from your notes:

```bash
mykg extract-graph my_notes/
```

Open `mykg_sessions/<timestamp>/output/knowledge_graph.html` in your browser to explore the result.

### Install from source

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), clone the repo, sync dependencies, run the setup wizard, then extract.

```bash
git clone https://github.com/SenolIsci/mykg && cd mykg
uv sync && uv run mykg init --force
```

Then extract a knowledge graph from your notes:

```bash
uv run mykg extract-graph my_notes/
```

For Ollama (local inference, no API key needed), pull a model and select the `ollama-local` profile when `mykg init` prompts you.

```bash
ollama pull llama3.3
mykg init
mykg extract-graph my_notes/
```

## Command line

### All Commands

| Command | Purpose |
|---|---|
| [`mykg init`](#configuration) | Interactive setup wizard — writes `mykg_config.yaml` and `.env.mykg` |
| [`mykg extract-graph`](#extract-pipeline) | Run the two-pass extraction pipeline over a directory |
| `mykg approve-schema` | Write `schema_approved.flag` to unblock the `human_review` gate after editing `schema.json` (used with `--review`, see [Human Review Gate](#human-review-gate---review)) |
| [`mykg walkthrough`](#walkthrough-report) | Regenerate `walkthrough.md` for an existing session |
| [`mykg merge-graphs`](#merging-sessions) | Merge two independently-produced sessions into one unified graph |
| [`mykg parse-docs`](#standalone-document-conversion-mykg-parse-docs) | Standalone MinerU/markdownify document-to-Markdown conversion |
| [`mykg fetch-web`](#website--repo-fetching-mykg-fetch-web) | Crawl a website or clone a GitHub repo into an `extract-graph`-ready folder |
| [`mykg mcp-serve`](#mcp-model-context-protocol-server) | Start the MCP server exposing read-only graph query tools |

```
mykg extract-graph my_notes/        # any directory: .md, .txt, .pdf, .docx, .html, images
```
It uses a **two-pass LLM pipeline**: Pass 1 induces a global RDFS/OWL schema from your document corpus; Pass 2 extracts typed entity and relationship instances per file against that schema. Non-Markdown inputs (`.txt .pdf .docx .doc .pptx .xlsx .png .jpg .jpeg .html .htm`) are converted to Markdown automatically before extraction. The result is exported to multiple formats: JSONL for property-graph consumers such as Neo4j, Turtle RDF for OWL toolchains, seven NetworkX formats for graph analysis and visualization, an Obsidian vault — a second brain of wikilinked Markdown notes your AI coding assistant (Claude Code, Cursor, Copilot) can read and reason over directly — and optionally a Neo4j LOAD CSV bundle with a paste-and-run Cypher script for one-step import into Neo4j Browser or `cypher-shell`.


## Articles & Tutorials

Walkthroughs and case studies on [Medium](https://medium.com/@senol.isci):

- [How I Turned My Website Into a Knowledge Graph with myKG](https://medium.com/@senol.isci/how-i-turned-my-website-into-a-knowledge-graph-with-mykg-7dc85ac894c3)
- [How to Build a Second Brain You Can Actually Trust](https://medium.com/@senol.isci/how-to-build-a-second-brain-you-can-actually-trust-52ac621188b7)
- [Build an LLM Wiki for Your AI Agents](https://medium.com/@senol.isci/build-an-llm-wiki-for-your-ai-agents-b993af38d7c4)
- [From Documents to a Living Knowledge Graph: Introducing myKG](https://medium.com/@senol.isci/from-documents-to-a-living-knowledge-graph-introducing-mykg-fab7cea22de5)

## Configuration

All configuration lives in a single `mykg_config.yaml` file discovered automatically from the working directory (or any parent). There are no hardcoded defaults in the code — the YAML is the sole source of truth.

```bash
mykg init           # interactive: choose provider, model, paste API key
                    # writes mykg_config.yaml and .env.mykg in one step
mykg init --force   # overwrite an existing config
mykg init --profile openrouter-free --model google/llama-4-maverick --api-key sk-or-...  # non-interactive
```

The wizard walks you through three prompts:

1. **Profile** — choose your LLM provider (OpenRouter, Anthropic, OpenAI, Ollama, Claude CLI, or Agent / Claude Code skill)
2. **Model** — accept the default or type any model slug for that provider *(skipped in agent mode — the host Claude Code session is the LLM)*
3. **API key** — paste your key (skipped for Ollama, Claude CLI, and agent mode)

### LLM Providers

| Provider | Profile name | API key env var | Notes |
|---|---|---|---|
| Anthropic (Claude) | `anthropic-claude` | `ANTHROPIC_API_KEY` | Recommended for quality |
| OpenAI | `openai` | `OPENAI_API_KEY` | |
| Ollama | `ollama-local` | — | Local inference, no key needed |
| OpenRouter | `openrouter-free` | `OPENROUTER_API_KEY` | Access many models via one key |
| Claude CLI | `claude-cli` | — | Uses `claude -p` subprocess; serial only |
| Agent (Claude Code skill) | `agent-claude-code` | — | LLM answers come from a Claude Code skill via filesystem inbox/outbox — see [docs/agent-mode.md](docs/agent-mode.md) |

Switch provider by setting `profile:` at the top of [`mykg_config.yaml`](mykg_config.yaml).

### Token Budgets

Each profile's `llm:` and `pipeline:` blocks carry a chain of token-budget values sized for that model's context window:

- `llm.context_window` — the model's total context limit
- `llm.max_output_tokens` — the output cap reserved for each LLM response
- `pipeline.pass1.batch_token_target` and `pipeline.pass2.concat_batch_token_target` / `batch_token_target` — input budget per LLM call, sized to `(context_window − max_output_tokens) × 0.95`
- `pipeline.chunking.window_tokens` / `overlap_tokens` — chunk size and overlap for splitting large files, sized to roughly `batch_token_target / 4` and `window_tokens × 0.10`

The shipped values are tuned per profile (e.g. `claude-cli`/`anthropic-claude` assume a 200K context window, `openrouter-free`/`ollama-local` assume 64K). **If you switch to a different model — especially on `ollama-local` or `openrouter-free` — check that model's actual context window and rescale these values**, otherwise `window_tokens + max_output_tokens` may exceed what the model can actually handle, causing truncated or failed responses.

Use the bundled `context-calculator` tool to recompute the chain for a new model:

```bash
# Compute a full token-budget chain from context window + output cap:
context-calculator --context 64000 --max-output 32000

# Or measure your actual corpus and suggest values for the active profile:
context-calculator --from-config --input-dir my_notes/
```

`--from-config` reads the active profile from `mykg_config.yaml`, measures token counts across your input files, and writes suggested values to `mykg_config_candidate.yaml` for review before copying them into `mykg_config.yaml`.

### Diagnosing Truncated/Rejected LLM Calls

On JSON parse or validation errors in Pass 1/2, check `run.log` for a `mykg.llm.retry` warning just above the failure — always logged, regardless of `logging.llm_log`:

- **`output truncated (finish_reason=...)`** — hit `max_output_tokens`. Lower `pipeline.chunking.window_tokens` or raise `llm.max_output_tokens`, then recompute with `context-calculator` (see [Token Budgets](#token-budgets)).
- **`context length exceeded, request rejected: ...`** — input didn't fit the context window. Lower `batch_token_target` (`pipeline.pass1`/`pipeline.pass2`).

### Pass 2 Prep Mode (`pass2.prep_mode`)

Controls how source files are packed into Pass 2 LLM calls (set per profile in `mykg_config.yaml`):

- **`batch_chunks`** *(default)* — packs chunks across files into token-bounded batches, ignoring file boundaries; best throughput and extraction density.
- **`concat`** — merges whole small files into directory-grouped batches (one LLM call per window) for cross-file context.
- **`per_file`** — one file per extraction unit; cleanest provenance (every entity traces to one source file).

See [docs/architecture.md](docs/architecture.md#choosing-a-prep-mode) for the full comparison.

### Hitting API Rate Limits (HTTP 429)

If you see repeated `429` errors during `pass1`, `pass2`, or the orphan-connection pass, your account's requests-per-minute limit is lower than the number of concurrent calls mykg is making. Each profile sets these independently under `pipeline:`:

- `pass1.max_workers` — concurrent schema-induction batch calls
- `pass2.max_workers` — concurrent per-file extraction calls
- `orphan_pass.max_workers` — concurrent orphan-connection calls

Lower these (e.g. from `8` down to `2`–`4`) in the active profile to reduce concurrent requests. This is especially likely on `openrouter-free` (free-tier models have very low per-minute caps) and on lower-tier `anthropic-claude`/`openai` accounts. `llm.retry_429_max` / `llm.retry_429_base_delay` control automatic backoff on a 429, but a persistent 429 is a signal to reduce `max_workers`, not just retry harder. `claude-cli` is unaffected — it is serial by design (`max_workers: 1`); it doesn't hit API rate limits since there's no API call. `agent-claude-code` is not API rate-limited either (no API key involved), but it is not serial — its default profile sets `pass1`/`pass2`/`orphan_pass` `max_workers` > 1 (configurable, like any other profile), since the skill dispatches multiple subagents per wave.

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

`<input_dir>` is any directory containing your source files. Subdirectories are included recursively. Only files matching the configured extensions are copied into the session:

- `.md` — always included (the pipeline's native format)
- All extensions listed under `preprocess.extensions` in `mykg_config.yaml` (`.pdf`, `.docx`, `.doc`, `.pptx`, `.xlsx`, `.png`, `.jpg`, `.jpeg`, `.html`, `.htm`, `.txt` by default)

Everything else (`.py`, `.json`, `.yaml`, lock files, etc.) is ignored. Hidden directories (`.venv`, `.git`, etc.) and the sessions folder are also excluded automatically, so you can safely point `extract-graph` at the project root or any parent directory.

### Options

| Option | Description |
|---|---|
| `--session NAME` | Resume an existing session by folder name |
| `--from-step NAME` | Delete a step's outputs and re-run from that point |
| `--review` | Pause after Pass 1 for manual schema review |
| `--append` | Skip Pass 1; re-run only on new/modified files |
| `--append-with-grow-schema` | Like `--append`, but runs a locked Pass 1 over changed files to expand the schema |
| `--pass1-schema-induction-only` | Run every step before Pass 2 (through `schema_flatten`), then stop — inspect/edit the schema before extracting |
| `--pass2-kg-extraction-only` | Skip schema induction (requires an existing schema) and extract the full corpus through `validate_graph`. Unlike `--from-step pass2`, always re-derives `flattened_schema.json` first, so a hand-edited schema is picked up |
| `--profile NAME` | Use a different LLM profile from `mykg_config.yaml` for THIS run only (config file untouched; re-resolves provider/model/workers/timeouts from that profile) |
| `--model NAME` | Override the model for this run. Requires `--profile` |
| `--workers N` | Parallel workers for Pass 2 (default: `pass2.max_workers` from the active/selected profile) |
| `--confidence-agg mean\|max` | Confidence aggregation when deduplicating |
| `--base-schema PATH` | Locked TBox TTL file (locked classes/properties cannot be changed by the LLM) |
| `--freeze-schema` | Use `--base-schema` verbatim: skip Pass 1 LLM induction entirely |
| `--thesaurus PATH` | SKOS TTL thesaurus for synonym resolution in schema merge |
| `--obsidian-vault` | Force Obsidian vault export for this run (overrides config) |
| `--neo4j-csv` | Force Neo4j LOAD CSV bundle export for this run (overrides config) |
| `--log-file PATH` | Write logs here (relative paths placed inside the session folder) |
| `--verbose / -v` | Enable DEBUG-level logging |

### Examples

```bash
# New run — auto-creates a timestamped session
mykg extract-graph my_notes/

# Resume a session with 4 parallel Pass 2 workers
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --workers 4

# Run once against a different profile/model without editing mykg_config.yaml
mykg extract-graph my_notes/ --profile openrouter-free --model google/llama-4-maverick

# Pause for schema review after Pass 1
mykg extract-graph my_notes/ --review
# → edit mykg_sessions/<name>/intermediate/schema.json
mykg approve-schema --session 2026-05-17T18-31-07
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --review

# Re-run from assembly onward (reuses existing extractions)
mykg extract-graph my_notes/ --session 2026-05-17T18-31-07 --from-step assemble

# Lock a base ontology so the LLM won't rename its classes
mykg extract-graph my_notes/ --base-schema ontology/core.ttl

# Induce and inspect the schema first, extract in a second invocation
mykg extract-graph my_notes/ --pass1-schema-induction-only
# → review/edit mykg_sessions/<name>/intermediate/schema.json
mykg extract-graph my_notes/ --session <name> --pass2-kg-extraction-only

# Mix models across phases: a strong model for schema induction,
# a smaller/cheaper one for the laborious Pass 2 extraction
mykg extract-graph my_notes/ --profile openrouter-free --model google/gemma-4-26b-a4b-it:free --pass1-schema-induction-only
```

**Per-run `--profile` / `--model` for phase-specific model selection.** Because
`--profile` and `--model` override the run without touching `mykg_config.yaml`, you
can pick a different model for each phase of a two-phase extraction. Schema induction
(Pass 1) benefits from a strong reasoning model, while the laborious per-file Pass 2
extraction can run on a smaller, cheaper model — just change `--profile`/`--model`
between the `--pass1-schema-induction-only` and `--pass2-kg-extraction-only` runs.

### Sessions

Every run automatically creates an isolated session folder:

```
mykg_sessions/
  2026-05-17T18-31-07/
    input/           ← archived copy of all input Markdown files
    intermediate/    ← all intermediate pipeline state
    output/          ← final outputs (JSONL, TTL, HTML, NetworkX)
    run.log          ← log file
    walkthrough.md   ← post-run report
```

Sessions are the primary unit of resumability. Pass `--session <name>` to resume from the last completed step. Pass `--from-step <step>` to force-restart from a specific point.

The sessions root is configurable via `pipeline.paths.sessions_dir` (default: `mykg_sessions/` in the current directory).

### Pipeline Steps

The pipeline runs 12 steps in sequence. All intermediate state is written to disk so any step can be re-entered without repeating upstream work.

| # | Step | LLM | Key outputs |
|---|---|---|---|
| 1 | `preprocess` | — | `preprocess.done`, `preprocess_manifest.json`, files under `input/_preprocessed/` *(routes non-md inputs to MinerU, markdownify, or rename; no-op for pure Markdown corpora)* |
| 2 | `ingest` | — | `file_manifest.json` |
| 3 | `pass1` | ✓ (3 calls) | `schema.json`, `schema.ttl`, `schema_history/`, `pass1_batch_selection.json`, `pass1_batch_proposals/` |
| 4 | `schema_validate` | — | `schema_validate.done` |
| 5 | `human_review` | — | `schema_approved.flag` *(only with `--review`)* |
| 6 | `schema_flatten` | — | `flattened_schema.json` |
| 7 | `pass2` | ✓ | `raw_extractions.json`, `chunk_node_index.json` |
| 8 | `normalize_names` | ✓ | `name_normalization.json` |
| 9 | `assemble` | — | `edge_metadata.json`, `nodes.json`, `merge_log.json` |
| 10 | `orphan_score` | — | `orphan_candidates.json` |
| 11 | `orphan_connect` | ✓ | `orphan_connections.json`, `orphan_log.json` |
| 12 | `validate_graph` | — | `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `knowledge_graph.html`, `networkx_output/`, `obsidian_vault/`, `neo4j_csv/` *(optional)* |

Pass 1 internally runs four sequential stages: parallel batch induction → algorithmic merge → harmonization LLM call → quality review LLM call. `pass1.max_schema_proposals` (default 50) caps the number of batches dispatched to the LLM; set to `-1` to dispatch all batches on large corpora.

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

### Neo4j LOAD CSV Bundle (`neo4j_csv/`)

Optional, off by default. Enable with `--neo4j-csv` on the command line, or set `pipeline.export.neo4j_csv_enabled: true` in `mykg_config.yaml`.

When enabled, `step_validate_graph` writes a self-contained Neo4j import bundle next to the other outputs:

```
output/neo4j_csv/
  nodes_<Label>.csv             ← one per concept type (Person, Organization, …)
  relationships_<TYPE>.csv      ← one per property (WORKS_AT, KNOWS, …)
  import_browser.cypher         ← paste-and-run for Neo4j Browser
  import_shell.cypher           ← for `cypher-shell -f`
  README.md                     ← bundle-local quick-reference
```

Plain CSV headers (`id,name,name_confidence,_node_confidence,_parents,_source_files,...`) — no `:ID` / `:LABEL` decorations, so the same files work for both Neo4j and any other CSV-aware tool.

**Two ways to import the bundle:**

```bash
# Flow A — Neo4j Browser
# 1. Copy *.csv into your DBMS's import/ directory
# 2. Paste the contents of import_browser.cypher and press play

# Flow B — cypher-shell (set dbms.security.allow_csv_import_from_file_urls=true first)
cypher-shell -u neo4j -p <pw> -f output/neo4j_csv/import_shell.cypher
```

Both scripts use idempotent `MERGE` against a `_MykgNode` uniqueness constraint, so re-running updates the graph in place. Requires Neo4j 5+. No Python driver, no plugin, no APOC — the scripts use only core Cypher.

See [Neo4j LOAD CSV Export](#neo4j-load-csv-export) below for configuration details and the standalone CLI fallback.

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

# Re-run only merge/harmonize/quality-review (reuse existing Pass 1 batch proposals)
mykg extract-graph my_notes/ --session $SESSION --from-step merge_proposals
```

**Five re-entry patterns:**

| Pattern | When to use | Command |
|---|---|---|
| **A — Schema changed** | Wrong concept types, missing properties | Edit `schema.json` → `approve-schema` → `--from-step pass1` |
| **A (merge-only)** | Want to re-run merge/harmonize with a different `--thesaurus`/`--base-schema`, without re-paying for Pass 1's schema-induction LLM calls | `--from-step merge_proposals` (requires `pass1_batch_proposals/` from a prior run; unlike plain `--from-step pass1`, does not delete it) |
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
# → pipeline halts; edit mykg_sessions/<name>/intermediate/schema.json
mykg approve-schema --session <name>
mykg extract-graph my_notes/ --session <name> --review   # resumes from Pass 2
```

### Locked Base Schema (`--base-schema`)

Lock certain classes and properties so the LLM cannot rename, remove, or restructure them:

```bash
mykg extract-graph my_notes/ --base-schema ontology/base.ttl
```

Both RDFS and OWL ontologies are accepted — `owl:Class`, `owl:ObjectProperty`, and `owl:DatatypeProperty` are recognized alongside their RDFS equivalents, so you can use an OWL ontology exported from Protégé directly without conversion. Locked entries can still receive additional attributes proposed by the LLM. Near-duplicate LLM proposals are collapsed into the locked entry with a warning.

### Frozen Schema (`--freeze-schema`)

Use the base schema verbatim — skip Pass 1 LLM induction entirely. The LLM extracts instances against exactly the classes and properties you provide, with no additions:

```bash
mykg extract-graph my_notes/ --base-schema ontology/base.ttl --freeze-schema
```

This is useful when you have a complete ontology and want strict extraction — no LLM-invented types, no surprise properties. Only the concepts and relationships in your TTL will appear in the output. Requires `--base-schema`. Mutually exclusive with `--append` and `--append-with-grow-schema`.

**Comparison with `--base-schema` alone:**

| Behavior | `--base-schema` | `--base-schema --freeze-schema` |
|---|---|---|
| Pass 1 LLM calls | 3 (batch + harmonize + quality review) | **0 (skipped)** |
| Schema | Locked entries + LLM-induced additions | **Exactly the TTL file** |
| New concept types | LLM can add them | **None** |
| New properties | LLM can add them | **None** |

### SKOS Thesaurus (`--thesaurus`)

Resolve near-duplicate concept names during schema merge using a SKOS vocabulary:

```bash
mykg extract-graph my_notes/ --thesaurus ontology/terms.skos.ttl
```

- `skos:exactMatch` → silent collapse
- `skos:closeMatch` → collapse with warning in `merge_log.json`
- `skos:broader` / `skos:narrower` → advisory hints only

### Website / Repo Fetching (`mykg fetch-web`)

Crawl a website, or shallow-clone a GitHub repo, into a folder that's a ready-made `extract-graph` input:

```bash
# Crawl a website (same-domain, robots.txt-respecting)
mykg fetch-web https://example.com
mykg extract-graph ./mykg_web_fetch/example.com/

# Shallow-clone a GitHub repo (git clone --depth 1, no Crawlee/venv)
mykg fetch-web https://github.com/SenolIsci/mykg
mykg extract-graph ./mykg_web_fetch/github.com_SenolIsci_mykg/input/

# Fetch multiple seeds (one URL per line; mix of sites and GitHub repos)
mykg fetch-web --url-list urls.txt --output ./mykg_web_fetch/batch/
```

- **GitHub URLs** (`https://github.com/<owner>/<repo>`) are detected automatically and routed to `git clone` — no Crawlee, no venv.
- **Everything else** is crawled with Crawlee inside an ephemeral `uv` venv (same pattern as the MinerU venv used by `preprocess`), respecting `robots.txt`, `--max-pages`, `--max-depth`, and a configurable request delay/concurrency.
- **Resumable** — `fetch_manifest.json` records a SHA-256 per page; re-running skips unchanged pages. `--force` re-fetches everything.
- **Output dir** defaults to `./<fetch.output_dir>/<seed-domain>/` (configurable via `fetch.output_dir` in `mykg_config.yaml`, default `mykg_web_fetch`); `--output` overrides it and is required with `--url-list`.
- **Downloaded assets** (PDFs, images, etc.) are filtered through the same `preprocess.extensions` allowlist used by `extract-graph`, so anything Crawlee saves is something `preprocess` already knows how to convert.

All knobs live under `fetch:` in `mykg_config.yaml` — see [docs/architecture.md](docs/architecture.md#website-and-repo-fetching-mykg-fetch-web) for the full crawl/clone sequence diagrams. Run `mykg fetch-web --help` for the complete flag list.

**From Claude Code**, the [`/mykg` skill](#agent-mode-claude-code-skill) handles fetch requests in plain English — no flags to remember:

```bash
/mykg fetch https://example.com and extract
/mykg download the repo: https://github.com/SenolIsci/mykg
/mykg fetch these urls: <url1> <url2> ... and extract
```

All work: the skill picks the right `fetch-web` invocation (single page, GitHub clone, or `--url-list` batch with an auto-generated temp file for inline URLs), runs it, and — for the "and extract" intents — chains straight into `extract-graph` on the fetched output (one fresh session per seed for multi-seed fetches), confirming with you before the LLM-bearing extraction step.

### Standalone Document Conversion (`mykg parse-docs`)

`extract-graph` already converts non-Markdown inputs (PDF, DOCX, images, …) to Markdown automatically via the `preprocess` step — on both the initial run and on `--append`. You only need `parse-docs` when you want to convert documents **on their own**, without running a pipeline or creating a session: inspecting MinerU output, building a Markdown corpus to commit, or feeding another tool.

```bash
# Convert a single file
mykg parse-docs --input report.pdf --output ./md/

# Convert every non-.md file under a directory (recursive; structure preserved)
mykg parse-docs --input raw_docs/ --output ./md/

# Convert only specific files (relative to --input; repeatable)
mykg parse-docs --input raw_docs/ --output ./md/ --file a.pdf --file sub/b.docx
```

- **MinerU in an ephemeral venv** — conversion runs MinerU inside a throwaway `uv`-managed venv that is built per invocation and deleted on exit; nothing is installed into mykg's own interpreter. The multi-GB install is paid once per call and reused across every file in that call.
- **Extension allowlist** — candidate files are filtered through `preprocess.extensions` from `mykg_config.yaml` (the same allowlist `extract-graph` uses). `.html`/`.htm` are always hard-skipped (MinerU cannot convert HTML — use `extract-graph`, which routes HTML through `markdownify`). Pass `--no-filter` to send every non-`.md` file to MinerU regardless of suffix.
- **Large corpora** — use `--file-list <path>` (one rel-path per line) instead of repeated `--file` flags to avoid the OS argv-size limit. `--file` and `--file-list` are mutually exclusive.
- **No session** — `parse-docs` is a pure file-to-file utility: it does not create a session or touch `mykg_sessions/`. Per-file failures are logged and the run continues, exiting non-zero at the end if any file failed.

Run `mykg parse-docs --help` for the complete flag list. **From Claude Code**, `/mykg convert pdfs in ./inbox to ./md` maps to the right invocation automatically.

### Append Mode

Re-run the pipeline on new or modified files without re-running Pass 1:

```bash
mykg extract-graph my_notes/ --session <name> --append
```

The input directory may contain PDF, DOCX, HTML, TXT, and image files alongside `.md` — newly-added non-Markdown files are converted automatically during the append run (the same incremental `preprocess` step the initial run uses, subject to `preprocess.enabled`). No separate `mykg parse-docs` step is needed. Only new or changed source files are converted; unchanged ones are skipped by content hash.

#### Incremental Schema Growth (`--append-with-grow-schema`)

Plain `--append` freezes the schema — Pass 1 is skipped, so new entity types and relationships are never induced. Use `--append-with-grow-schema` when you add documents that introduce concepts the current schema doesn't cover:

```bash
mykg extract-graph my_notes/ --session <name> --append-with-grow-schema
```

This runs a **locked Pass 1** over only the changed files: the LLM may add new concepts and properties but cannot rename, remove, or restructure existing ones. When the schema grows, a surgical back-fill re-extracts the old chunks most likely to contain instances of the new types (configurable via `append.grow_schema_backfill_top_k_chunks_per_type`, default 10; set 0 to disable). When the new documents don't introduce new types, the run collapses to a plain `--append` at no extra cost.

The flag implies `--append` (no need to pass both) and is mutually exclusive with `--from-step` and `--base-schema` (the session's existing `schema.ttl` is auto-loaded as the locked base).

> **Mixed-format inputs:** Both `--append` and `--append-with-grow-schema` automatically preprocess newly-added non-Markdown files (PDF, DOCX, HTML, TXT, images). Just drop the new files into the input directory and append — the `preprocess` step runs incrementally, converting only the new or changed sources (unchanged files are skipped by content hash) and feeding the converted Markdown straight into extraction. No separate `mykg parse-docs` step is required.

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

### Neo4j LOAD CSV Export

Optional bundle for one-step import into Neo4j 5+. Off by default. When enabled, every run writes the bundle to `output/neo4j_csv/` alongside the other outputs.

**Bundle contents** (see [`neo4j_csv/`](#neo4j-load-csv-bundle-neo4j_csv) above for the full layout):
- One `nodes_<Label>.csv` per concept type with plain headers (`id,name,name_confidence,...`)
- One `relationships_<TYPE>.csv` per property (rel-type names sanitized to upper snake_case)
- `import_browser.cypher` — paste-and-run for Neo4j Browser (relative `file:/<name>.csv` URIs)
- `import_shell.cypher` — for `cypher-shell -f` (absolute `file:///` URIs)
- `README.md` — bundle-local quick-reference with paste instructions

**The scripts use:**
1. A uniqueness constraint on `(_MykgNode {id})` — created on first run, `IF NOT EXISTS` thereafter
2. `MERGE` for every node and edge — idempotent, safe to re-run
3. `IN TRANSACTIONS OF 1000 ROWS` — handles large bundles without OOM
4. Per-label domain labels (`:Person`, `:Organization`) plus the shared `:_MykgNode` label that carries the constraint

**Config:**

```yaml
pipeline:
  export:
    neo4j_csv_enabled: false        # default — set true to enable
    neo4j_csv_dir: neo4j_csv        # subfolder name inside output/
```

Or use `--neo4j-csv` on the command line for a one-off run without editing config.

### Walkthrough Report

A human-readable summary is written to `mykg_sessions/<name>/walkthrough.md` after every run:

```bash
# Regenerate the walkthrough for an existing session
mykg walkthrough --session 2026-05-17T18-31-07
```

Disable with `pipeline.report.enabled: false`.

## MCP (Model Context Protocol) Server

Serve any completed session as an MCP server for LLM-powered Q&A:

```bash
# Serve the latest session (stdio transport — for Claude Desktop)
mykg mcp-serve

# Serve a specific session
mykg mcp-serve --session 2026-06-25T19-16-18

# Serve via streamable HTTP for web clients (Cherry Studio, etc.)
mykg mcp-serve --transport streamable_http --port 3100

# Serve a specific session via streamable HTTP
mykg mcp-serve --session 2026-06-25T19-16-18 --transport streamable_http --port 3100
```

**Claude Desktop (stdio)** — the client launches mykg as a subprocess, no manual server start needed. Add to `claude_desktop_config.json`. Replace `/path/to/your/project` with the absolute path to your project folder:

```json
{
  "mcpServers": {
    "mykg": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/project",
        "run",
        "mykg",
        "mcp-serve"
      ]
    }
  }
}
```

To serve a specific session:

```json
{
  "mcpServers": {
    "mykg": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/project",
        "run",
        "mykg",
        "mcp-serve",
        "--session",
        "2026-06-25T19-16-18"
      ]
    }
  }
}
```

**Claude Code (stdio)** — add a `.mcp.json` file to your project root so Claude Code launches the MCP server automatically at session start:

```json
{
  "mcpServers": {
    "mykg": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/project",
        "run",
        "mykg",
        "mcp-serve"
      ]
    }
  }
}
```

To serve a specific session:

```json
{
  "mcpServers": {
    "mykg": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/your/project",
        "run",
        "mykg",
        "mcp-serve",
        "--session",
        "2026-06-25T19-16-18"
      ]
    }
  }
}
```

> **Restart required.** Claude Code reads `.mcp.json` at session start. After creating or editing this file, restart your Claude Code session for the server to connect. You will be prompted to approve the `mykg` MCP server on first use.

After a pipeline run (`extract-graph`, `--append`, etc.), the in-memory graph becomes stale. Call the `mykg_reload` tool to refresh it without restarting — or restart the Claude Code session to reload from scratch.

If you also have the [`/mykg` skill](#agent-mode-claude-code-skill) installed, the skill will prefer MCP tools for read-only queries when the server is connected, and fall back to direct file reads when it is not.

**Streamable HTTP** (Cherry Studio, MCP Inspector, or any HTTP-based MCP client) — start the server first with `mykg mcp-serve --transport streamable_http --port 3100`, then connect your client:

```json
{
  "mcpServers": {
    "mykg": {
      "type": "streamableHttp",
      "url": "http://localhost:3100/mcp"
    }
  }
}
```

The MCP server exposes 14 tools: `mykg_search_nodes`, `mykg_get_node`, `mykg_get_neighbors`, `mykg_find_path`, `mykg_get_schema`, `mykg_list_node_types`, `mykg_query_subgraph`, `mykg_get_stats`, `mykg_query_graph` (BFS/DFS traversal), `mykg_hub_nodes`, `mykg_orphan_nodes`, `mykg_read_note` (Obsidian vault LLM wiki notes), `mykg_list_sessions`, and `mykg_reload` (refresh the in-memory graph after pipeline runs).

**Configuration** — default transport, host, and port are set per profile in `mykg_config.yaml`:

```yaml
    mcp:
      host: localhost              # bind address for streamable HTTP (ignored for stdio)
      port: 3100                   # port for streamable HTTP (ignored for stdio)
      transport: stdio             # default transport: stdio | streamable_http
```

To default to streamable HTTP, change `transport: streamable_http` in your active profile. CLI flags (`--transport`, `--host`, `--port`) override the config.

---

## Using mykg with Claude Code

myKG ships with two complementary integrations for running extractions from inside [Claude Code](https://claude.ai/code):

- **Agent mode (`agent-claude-code` profile + bundled skill)** — the pipeline writes LLM tasks to a session-local inbox folder and a Claude Code skill dispatches subagents to answer them. Parallel by default.
- **`claude-cli` profile** — the pipeline shells out to the `claude -p` binary for each LLM step. Serial only.

Pick the `claude-cli` for a drop-in `claude`-as-LLM experience; pick `agent-claude-code` when you want agent skill and parallel subagent dispatch.

### Agent mode (Claude Code skill)

Agent mode is a different way to run myKG inside Claude Code: instead of `claude -p` subprocesses, the pipeline writes LLM tasks to a session-local inbox folder and a Claude Code **skill** dispatches subagents to answer them. Pick agent mode over `claude-cli` when you want parallel subagent dispatch from inside an active Claude Code session.

#### Why pick agent mode

- **No API key needed.** Uses your existing Claude Pro/Max plan via the skill subagents — same as `claude-cli`, but without invoking the `claude -p` binary.
- **Inspectable LLM I/O.** Every prompt lands as `intermediate/agent_inbox/<id>.task.json` and every answer as `intermediate/agent_outbox/<id>.answer.json`. Replay or edit any step by hand.
- **Parallel by default.** The skill dispatches up to `pass2.max_workers` subagents per wave in a single message — not serial like `claude-cli`. Pass-2 chunks complete in parallel waves.

#### Install and configure

```bash
pip install mykg          # or: uv tool install mykg
mykg init --profile agent-claude-code
# ...then restart Claude Code so the skill loader picks up the new entry.
```

`mykg init --profile agent-claude-code` writes `mykg_config.yaml`, copies the bundled skill into `~/.claude/skills/mykg` (honoring `$CLAUDE_CONFIG_DIR` if set), *and* adds a managed `<!-- BEGIN mykg-section --> ... <!-- END mykg-section -->` block to the project's `CLAUDE.md`. A `.mykg_skill_version` stamp file is written next to the skill so future runs can detect drift; the CLAUDE.md block tells Claude Code where the wiki lives, how to find the most-recent session, and how to extend the graph with new documents (no separate setup required).

**Upgrade after `pip install -U mykg`:**

```bash
mykg init --reinstall-skill --reinstall-claude-md
```

This atomically refreshes the bundled skill (copy to `.tmp` → `os.replace`) without touching your `mykg_config.yaml`, and replaces the content between the CLAUDE.md markers with the version shipped in the current package — any user content outside the markers is preserved. Either flag can be used alone (`--reinstall-skill` only / `--reinstall-claude-md` only). The copy-based skill install is deliberately not a symlink — symlinks fail on Windows without Developer Mode, dangle if mykg is uninstalled, and don't sync through OneDrive. The cost (live edits don't auto-propagate) only matters for mykg developers, who pass `--reinstall-skill` between edits.

The `agent:` block in the generated `mykg_config.yaml` configures the inbox/outbox paths and poll interval:

```yaml
profile: agent-claude-code

profiles:
  agent-claude-code:
    provider: agent
    agent:
      inbox_dir: agent_inbox        # relative to <session>/intermediate/
      outbox_dir: agent_outbox
      poll_interval_seconds: 2
    pipeline:
      pass2:
        max_workers: 8              # how many subagents the skill dispatches per wave
```

#### Invoke from inside Claude Code

The skill exposes one slash command — `/mykg` — that accepts free-form intent. You describe what you want; the skill figures out which `mykg` CLI command to run, reads the live `--help` to validate flags, confirms expensive actions, and (for `extract-graph`) drains the LLM inbox in parallel waves.

Examples:

| You type | The skill runs |
| --- | --- |
| `/mykg extract ./docs` | `mykg extract-graph ./docs` |
| `/mykg ./docs` | `mykg extract-graph ./docs` (legacy positional alias) |
| `/mykg extract ./docs with human review` | `mykg extract-graph ./docs --review` |
| `/mykg extract ./docs with frozen schema from ontology.ttl` | `mykg extract-graph ./docs --base-schema ontology.ttl --freeze-schema` |
| `/mykg append the new notes in ./docs` | `mykg extract-graph ./docs --append --session <latest>` |
| `/mykg expand the schema with ./docs` | `mykg extract-graph ./docs --append-with-grow-schema --session <latest>` |
| `/mykg resume the last session` | `mykg extract-graph --session <latest>` |
| `/mykg approve the schema` | `mykg approve-schema --session <latest>` |
| `/mykg make a walkthrough` | `mykg walkthrough --session <latest>` |
| `/mykg convert pdfs in ./inbox to ./md` | `mykg parse-docs --input ./inbox --output ./md` |
| `/mykg fetch https://example.com and extract` | `mykg fetch-web https://example.com`, then `mykg extract-graph <printed output dir>` (fresh session) |

Any flag mykg accepts on the CLI works here too — the skill reads `--help` rather than maintaining its own list, so `--from-step orphan_connect`, `--workers 8`, `--obsidian-vault`, etc. all flow through.

`mykg init` and `mykg merge-graphs` are intentionally not wrapped: init is interactive (run from a shell once per machine), and merge-graphs has additional design questions and will be added in a follow-up.

Full design and contract: [docs/agent-mode.md](docs/agent-mode.md). Skill source: [src/mykg/data/skills/mykg/SKILL.md](src/mykg/data/skills/mykg/SKILL.md).


### claude-cli profile

myKG ships with a `claude-cli` profile that runs extractions through the locally-installed `claude` CLI.

#### Setup

Install the `claude` CLI, then install mykg and run the setup wizard — select **[5] Claude CLI** when prompted.

```bash
npm install -g @anthropic-ai/claude-code
pip install mykg && mykg init
mykg extract-graph my_notes/
```

#### How it works

The `claude-cli` provider calls `claude -p` as a subprocess for every LLM step (Pass 1 schema induction, Pass 2 extraction, orphan connection, name normalization). All pipeline features — session isolation, resumability, orphan recovery, cross-session merge — work identically to API-based providers.

**Key constraints of the `claude-cli` profile:**
- `max_workers` must be `1` — the `claude` CLI is serial by design; parallel workers will queue
- The `effort` and `model` fields in `mykg_config.yaml` map directly to `--effort` and `--model` flags passed to `claude -p`

#### Using myKG from inside Claude Code Session

You can run myKG extractions as a tool call from within a Claude Code session. This is useful for building knowledge graphs from notes or documentation while you work:

```bash
# From any Claude Code session terminal:
mykg extract-graph ./docs/ --session my-docs-kg

# Then reference the output in your session:
# mykg_sessions/my-docs-kg/output/nodes.jsonl
# mykg_sessions/my-docs-kg/output/knowledge_graph.ttl
```

Claude Code can then read `nodes.jsonl` or `edges.jsonl` as well as the Obsidian vault directly to answer questions about the extracted graph, or load `knowledge_graph.ttl` into a SPARQL tool for structured queries.


---

## Roadmap

- in preparation.

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

## Design

**Storage & runtime model** — myKG uses JSONL files (`nodes.jsonl`, `edges.jsonl`) as its persistent graph storage and builds an in-memory NetworkX `DiGraph` for all graph operations (traversal, search, path-finding, hub/orphan detection, MCP server queries). There is no external database dependency — the graph loads from flat files at startup and all computation happens in-process. This keeps the tool self-contained and portable: a session folder is everything you need.

For a thorough description of the architecture, algorithm, data models, and design decisions, see [docs/architecture.md](docs/architecture.md).

---

## License

MIT — see [LICENSE](LICENSE).
