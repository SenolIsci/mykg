# mykg — Architecture and Design

This document describes the architecture, algorithms, data models, and key design decisions behind mykg. It is the authoritative reference for contributors and anyone wanting to understand how the system works at depth.

For usage documentation, see [README.md](../README.md). For the full list of design decisions and the to-do history, see [CLAUDE.md](../CLAUDE.md) and [architecture.md](../architecture.md).

---

## Contents

- [System Overview](#system-overview)
- [Pipeline Architecture](#pipeline-architecture)
- [Component Map](#component-map)
- [Data Flow](#data-flow)
- [Algorithm Deep Dives](#algorithm-deep-dives)
  - [Pass 1: Schema Induction](#pass-1-schema-induction)
  - [Pass 2: Instance Extraction](#pass-2-instance-extraction)
  - [Assembly and Deduplication](#assembly-and-deduplication)
  - [Orphan-Connection Pass](#orphan-connection-pass)
  - [Name Normalization](#name-normalization)
  - [Cross-Session Merge](#cross-session-merge)
- [Data Models](#data-models)
- [Output Formats](#output-formats)
- [LLM Adapter Interface](#llm-adapter-interface)
- [Resumability and Re-entry](#resumability-and-re-entry)
- [Two-Tier Correction Model](#two-tier-correction-model)
- [Key Design Decisions](#key-design-decisions)
- [Key Invariants](#key-invariants)

---

## System Overview

mykg provides **two independent pipelines**, both invoked as CLI commands and both producing the same three output formats:

| Command | Steps | What it does |
|---|---|---|
| `mykg extract-graph <dir>` | 11 | Reads `.md` files; induces schema (Pass 1); extracts instances (Pass 2); assembles and exports the graph |
| `mykg merge-graphs <A> <B>` | 12 | Combines two extract sessions; reconciles schemas; deduplicates nodes/edges across sessions; re-extracts for new properties |

### Extract Pipeline Overview

The extract pipeline separates **schema induction** (what kinds of things and relationships exist in this corpus?) from **instance extraction** (which specific entities and relationships appear in each document?). This produces a globally consistent schema without requiring manual ontology authoring, while keeping extraction prompts focused and deterministic.

```
┌─────────────────────────────────────────────────────────┐
│                    Input: .md files                      │
└─────────────────────┬───────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  PASS 1 — Schema Induction                               │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐  ┌───────┐ │
│  │ Parallel │→ │Algorithmic│→ │Harmonize   │→ │Quality│ │
│  │ LLM calls│  │  merge   │  │(LLM call)  │  │review │ │
│  └──────────┘  └──────────┘  └────────────┘  └───────┘ │
│                                          ↓               │
│                               intermediate/schema.json   │
└─────────────────────────────────────────────────────────┘
                      │  [optional human review gate]
                      ▼
┌─────────────────────────────────────────────────────────┐
│  PASS 2 — Instance Extraction (per file, parallel)       │
│  ┌──────────────────────────────────────────────────┐   │
│  │  For each file chunk → LLM → nodes[] + edges[]   │   │
│  │  On-file-done: write per-file shard to disk      │   │
│  └──────────────────────────────────────────────────┘   │
│                          ↓                               │
│               intermediate/raw_extractions_shards/       │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  ASSEMBLY                                                │
│  normalize_names → stable IDs → dedup → edge sidecar    │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  ORPHAN-CONNECTION PASS                                  │
│  Stage 1: co-occurrence heuristic (no LLM)               │
│  Stage 2: LLM confirmation per chunk group               │
└─────────────────────────────────────────────────────────┘
                      │
                      ▼
┌─────────────────────────────────────────────────────────┐
│  EXPORT                                                  │
│  nodes.jsonl  edges.jsonl  knowledge_graph.ttl           │
│  networkx_output/ (GML, GraphML, GEXF, JSON,            │
│                    knowledge_graph.html, edge list …)    │
└─────────────────────────────────────────────────────────┘
```

### Merge Pipeline Overview

```
┌──────────────────────────────────────────────────────────┐
│  Input: session A + session B (both read-only)            │
└──────────────────────┬───────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  merge_setup                                              │
│  Namespace all file keys: session_a/<fname>               │
│  Write source_map.json (full provenance)                  │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  merge_schema  (3 LLM calls — same chain as Pass 1)       │
│  merge_proposals([schema_a, schema_b])                    │
│  → harmonize_schema() → review_schema_quality()           │
│  → schema.json  schema.ttl  schema_history/               │
└──────────────────────────────────────────────────────────┘
                       │  [optional human review gate]
                       ▼
┌──────────────────────────────────────────────────────────┐
│  merge_reextract  (strategy: none | surgical | full)      │
│  Re-extract only chunks needed for new schema properties  │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  merge_raw → assemble → orphan_score → orphan_connect     │
│  (reused extract-pipeline steps)                          │
└──────────────────────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────┐
│  validate_graph + merge_manifest                          │
│  nodes.jsonl  edges.jsonl  knowledge_graph.ttl            │
│  networkx_output/   merge_manifest.json                   │
└──────────────────────────────────────────────────────────┘
```

---

## Pipeline Architecture

### Orchestrator and Steps

The pipeline is defined as a flat list of `Step` objects in `src/mykg/pipeline.py`. Each step has:

- `name` — unique identifier
- `fn` — the function to execute (`run_<name>(ctx) → None`)
- `outputs` — list of intermediate files written by this step
- `is_llm_step` — whether this step makes LLM calls (affects retry/feedback behaviour)
- `blocking: bool` (default `True`) — if False, failures are logged but do not halt the pipeline
- `requires_review_flag: bool` (default `False`) — if True, the step waits for `schema_approved.flag` when `--review` is active (only `human_review` sets this)
- `output_location: Literal["intermediate", "output"]` (default `"intermediate"`) — controls which subdirectory the orchestrator checks for outputs on re-entry

The orchestrator (`src/mykg/orchestrator.py`) drives a `while True` loop over the step list. For each step it checks whether it is already complete (`_is_done` inspects sentinel files and output files), runs it if not, and handles retries and the two-tier correction model. The outer `while True` loop supports automated schema-gap restarts (see [Two-Tier Correction Model](#two-tier-correction-model)).

State transitions are persisted to `intermediate/pipeline_state.json` after every step via `PipelineState`.

### Extract Pipeline Steps

| # | Step | LLM | Sentinel / key outputs |
|---|---|---|---|
| 1 | `ingest` | — | `file_manifest.json` |
| 2 | `pass1` | ✓ (3 calls) | `schema.json`, `schema.ttl`, `schema_history/` |
| 3 | `schema_validate` | — | `schema_validate.done` |
| 4 | `human_review` | — | `schema_approved.flag` |
| 5 | `schema_flatten` | — | `flattened_schema.json` |
| 6 | `pass2` | ✓ | `raw_extractions.json`, `chunk_node_index.json`, `raw_extractions.done` (sentinel), `failed_chunks.json` (when chunks skipped) |
| 7 | `normalize_names` | ✓ | `name_normalization.json` |
| 8 | `assemble` | — | `edge_metadata.json`, `nodes.json` |
| 9 | `orphan_score` | — | `orphan_candidates.json` |
| 10 | `orphan_connect` | ✓ | `orphan_connections.json`, `orphan_log.json` |
| 11 | `validate_graph` | — | `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `networkx_output/` (incl. `knowledge_graph.html`) |

### Merge Pipeline Steps

`mykg merge-graphs` runs a 12-step `MERGE_STEPS` list via `src/mykg/merge_run.py`. It reuses all extract pipeline steps from `schema_validate` onward and adds merge-specific steps:

| Step | Description |
|---|---|
| `merge_setup` | Load both sessions, namespace shard files, write `source_map.json` |
| `merge_schema` | Three-stage schema merge (same chain as Pass 1) |
| `schema_validate` | Reused |
| `human_review` | Reused |
| `schema_flatten` | Reused |
| `merge_reextract` | Re-extract affected chunks per strategy (`none`/`surgical`/`full`) |
| `merge_raw` | Combine namespaced raw extractions |
| `assemble` | Reused |
| `orphan_score` | Reused |
| `orphan_connect` | Reused |
| `validate_graph` | Reused |
| `merge_manifest` | Write `merge_manifest.json` audit record |

---

## Component Map

```
src/mykg/
  cli.py                 ← Click CLI; session management; --from-step logic
  config.py              ← loads pipeline_config.yaml; exposes named constants
  pipeline.py            ← STEPS list; Step dataclass
  orchestrator.py        ← extract pipeline driver; while True + SchemaUpdatedError
  merge_run.py           ← merge pipeline driver; mirrors orchestrator
  merge_pipeline.py      ← MERGE_STEPS list
  merge_context.py       ← MergeContext(PipelineContext) Pydantic model
  merger.py              ← reextract_for_merge(); namespace helpers; session loading

  pass1.py               ← schema induction; ThreadPoolExecutor dispatch; JSON retry
  pass2.py               ← instance extraction; per-file shard writes; stateful chunks
  pass2_batch.py         ← batch_chunks prep mode
  pass2_concat.py        ← concat prep mode

  schema_merge.py        ← merge_proposals(); harmonize_schema(); review_schema_quality()
  schema_flattener.py    ← flatten_schema(); walks is-a hierarchy
  schema_validator.py    ← rdflib TBox validation; LLM correction retry
  schema_history.py      ← schema_history.write_schema(); numbered delta files
  assembler.py           ← stable_id(); deduplicate_nodes(); deduplicate_edges()
  ids.py                 ← stable_id() — shared between assembler and pass2
  name_normalizer.py     ← apply_normalization_map(); build_id_remap()
  orphan_connector.py    ← score_orphan_candidates_v2(); confirm_orphan_edges()
  feedback.py            ← _HANDLERS; apply(); per-step LLM correction functions
  exporter.py            ← export_jsonl(); export_ttl(); export_networkx()
  chunker.py             ← chunk_file(); count_tokens()
  base_schema.py         ← parse_base_schema_ttl()
  thesaurus.py           ← SynonymIndex; synonym_match()
  ttl_validator.py       ← validate_knowledge_graph_ttl(); sanitize_abox_ttl()
  walkthrough.py         ← generate_walkthrough_md()
  logging.py             ← get(); RotatingFileHandler setup
  prompts.py             ← load_prompt_template()

  llm/
    adapter.py           ← LLMAdapter ABC; complete(system, user) → str
    anthropic_adapter.py
    openai_adapter.py
    ollama_adapter.py
    openrouter_adapter.py
    claude_cli_adapter.py
    config.py            ← load_adapter(); reads provider from pipeline_config.yaml
    retry.py             ← llm_complete_with_retry(); retry_on_rate_limit()
    error_gate.py        ← ErrorGate; thread-safe pause-on-error circuit breaker

  steps/
    step_ingest.py
    step_pass1.py
    step_pass2.py
    step_schema.py       ← schema_validate + human_review + schema_flatten
    step_normalize.py
    step_assemble.py
    step_orphan_score.py
    step_orphan_connect.py
    step_validate_graph.py
    step_walkthrough.py
    step_merge_*.py      ← merge-specific steps
```

---

## Data Flow

### Intermediate File Chain

Each step reads from the previous step's outputs and writes its own. All files are in `sessions/<name>/intermediate/`.

```
file_manifest.json
  ↓ (pass1)
schema.json  →  schema.ttl  →  schema_history/
  ↓ (schema_flatten)
flattened_schema.json
  ↓ (pass2)
raw_extractions_shards/<slug>.json  (one per source file)
chunk_index_shards/<slug>.json
failed_chunks.json                  (blank/unparseable responses; absent if none)
  ↓ (merged after pass2 completes)
raw_extractions.json
chunk_node_index.json
  ↓ (normalize_names)
name_normalization.json
  ↓ (assemble)
nodes.json
edge_metadata.json
merge_log.json
  ↓ (orphan_score)
orphan_candidates.json
  ↓ (orphan_connect)
orphan_connections.json  →  (merged into edge_metadata.json in place)
orphan_log.json
  ↓ (validate_graph)
output/nodes.jsonl
output/edges.jsonl
output/knowledge_graph.ttl
output/networkx_output/              (GML, GraphML, GEXF, JSON, knowledge_graph.html, …)
```

### Context Object

`PipelineContext` (Pydantic `BaseModel`) is the shared in-memory state object passed to every step function. Representative fields (not exhaustive):

```python
class PipelineContext(BaseModel):
    # Paths
    input_dir:        Path
    output_dir:       Path
    intermediate_dir: Path

    # LLM backend
    adapter:          LLMAdapter

    # Runtime state (populated as steps complete)
    schema:           dict | None        # populated after pass1
    all_chunks:       list[Chunk] | None # populated after ingest
    nodes:            list[dict] | None  # populated after assemble
    edge_metadata:    dict | None        # populated after assemble
    chunk_node_index: dict | None        # populated after pass2
    file_contents:    dict | None        # populated after ingest
    raw_extractions:  dict | None        # populated after pass2

    # Optional config objects (None when feature not active)
    base_schema:      dict | None        # parsed --base-schema TTL
    thesaurus:        Any                # SynonymIndex | None
    error_gate:       Any                # ErrorGate | None

    # Mode flags
    review:           bool               # --review gate active
    append:           bool               # --append mode active
    append_new_files: set[str] | None    # new/modified files detected in append mode

    # Tuning parameters (loaded from pipeline_config.yaml)
    pass2_workers:    int
    ingest_workers:   int
    confidence_agg:   str               # "mean" or "max"
    orphan_incremental: bool

    # Schema-gap restart state
    schema_hints:     list[dict]         # populated by orphan_connect on restart; default []
    schema_restart_count: int            # incremented on SchemaUpdatedError
```

Steps read from context when available and fall back to loading from disk (enabling cold re-entry after a process restart).

---

## Algorithm Deep Dives

### Pass 1: Schema Induction

**Goal:** Produce `intermediate/schema.json` — a globally consistent RDFS schema with `concepts[]` (classes) and `properties[]` (object properties) derived from the full corpus.

Pass 1 runs four sequential stages:

#### Stage 1: Parallel Batch Induction

Files are chunked into overlapping windows (configurable: `window_tokens`, `overlap_tokens`). Chunks are packed into batches up to `pass1.batch_token_target` tokens. All batches are dispatched concurrently via `ThreadPoolExecutor(max_workers=pass1.max_workers)`.

Each batch LLM call returns a JSON object:
```json
{
  "concepts": [
    {"type": "Person", "parent": null, "attributes": ["name", "email"]},
    {"type": "SoftwareEngineer", "parent": "Person", "attributes": ["github_handle"]}
  ],
  "properties": [
    {"name": "works_at", "domain": "Person", "range": "Organization",
     "attributes": ["role", "start_date"]}
  ]
}
```

On `JSONDecodeError`, the batch is retried once with a correction prompt before being skipped.

#### Stage 2: Algorithmic Merge

All batch proposals are merged without an LLM call:

1. **Union** all concept types and property types across all batch results
2. **Exact deduplication** by name (case-sensitive first, then normalized)
3. **Near-duplicate resolution** via `synonym_match(a, b)`:
   - Exact string match → True
   - Normalized match (lowercase, whitespace/hyphens → underscores) → True
   - If SKOS thesaurus loaded: `skos:exactMatch` → collapse silently; `skos:closeMatch` → collapse with warning
4. **Attribute union**: for merged concepts, union the `attributes` lists from all proposals
5. **Parent resolution**: for merged concepts, keep the most specific declared parent
6. **Base schema locking**: if `--base-schema` was provided, locked classes and properties cannot be renamed, removed, or restructured

Result written to `intermediate/schema.json`.

#### Stage 3: Harmonization LLM Call

A single LLM call sees both the merged schema and all raw batch proposals. It collapses semantic near-duplicates the algorithmic merge missed (e.g., "MilitaryUnit" vs "ArmyUnit") and returns an updated schema. The original is kept if the response is unparseable.

#### Stage 4: Quality Review LLM Call

A second LLM call reviews the harmonized schema and:
- Removes over-narrow named-entity singletons (e.g., "FourthAirForce" → extract as `MilitaryUnit` instance)
- Fixes singleton types with no meaningful abstraction
- Collapses subclasses that add no own attributes
- Ensures every concept has at least a `name` attribute
- Flattens or deepens the hierarchy where appropriate

A lower-bound guard rejects the result if more than 50% of concepts are removed (prevents accidental schema deletion).

All four stages write delta records to `intermediate/schema_history/` via `schema_history.write_schema()`.

---

### Pass 2: Instance Extraction

**Goal:** For each document chunk, extract typed node and edge instances against the schema.

#### Preparation

Before Pass 2 runs, `schema_flatten` walks the inheritance chain for each concept type and unions all attributes from parent classes. The LLM receives the flat attribute list and never sees the word "inheritance". This ensures inherited attributes are always extracted.

Example: if `SoftwareEngineer` extends `Person`, the flattened spec for `SoftwareEngineer` includes `["name", "email", "birth_date", "github_handle"]`.

#### Extraction Loop

Pass 2 dispatches all source files concurrently via `ThreadPoolExecutor(max_workers=pass2.max_workers)`. For each file, chunks are processed sequentially.

Each chunk LLM call returns:
```json
{
  "nodes": [
    {"id": "alice-temp-id", "type": "Person", "confidence": 0.94,
     "attributes": {"name": {"value": "Alice", "confidence": 1.0}}}
  ],
  "edges": [
    {"type": "works_at", "from": "alice-temp-id", "to": "acme-temp-id",
     "confidence": 0.91, "attributes": {"role": {"value": "Engineer", "confidence": 0.88}}}
  ]
}
```

**Validation after each LLM call:**
- Reject edges whose `type` is not in the schema's `properties[]`
- Reject edges whose `from`/`to` values are not valid node IDs from the same extraction
- On failure: invoke `_partial_recover` (drop invalid edges; drop hallucinated anchor nodes — new nodes in this chunk that survive only to anchor a dropped edge)

**Attribute backfill:** For every node, any attribute declared in the flattened schema but absent from the LLM response is backfilled as `{"value": null, "confidence": 0.0}`. This enforces the invariant that missing attributes are never dropped.

#### Stateful Chunks

When `pass2.stateful_chunks: true`, prior-chunk node IDs are passed to the next chunk within the same file. This enables the LLM to use stable IDs across chunk boundaries, reducing cross-chunk deduplication cost.

The `prior_nodes_max_tokens` cap prevents the prior-nodes block from overflowing the context window on large files.

#### Per-File Shards

When a file completes, its results are written immediately as a per-file shard:
- `intermediate/raw_extractions_shards/<slug>.json` — raw nodes + edges for this file
- `intermediate/chunk_index_shards/<slug>.json` — chunk-to-node-ID index

On restart, completed files are detected by shard existence and skipped. Only files without a shard are re-extracted. This gives O(1) resumability at the file granularity.

#### Prep Modes

| Mode | Behaviour |
|---|---|
| `per_file` (default) | One LLM call per chunk |
| `concat` | Small files batched together into one call |
| `batch_chunks` | Chunks packed greedily up to `batch_token_target` across files |

---

### Assembly and Deduplication

**Goal:** Assign stable IDs, deduplicate nodes and edges across all files, write the edge metadata sidecar.

#### Stable ID Format

```
<type-prefix>-<name-slug>
```

Where:
- `type-prefix` = `re.sub(r"[^a-z0-9]", "", node.type.lower())` — non-alphanumeric characters stripped after lowercasing (e.g., `"SoftwareEngineer"` → `"softwareengineer"`)
- `name-slug` = canonical name with non-alphanumeric characters (except spaces) stripped, then spaces replaced by hyphens (e.g., `"Alice O'Brien"` → `"alice-obrien"`)

Example: `"person-alice-smith"`, `"organization-acme-corp"`

Canonical name = lowercased, whitespace-normalized `name` attribute value.

The key for deduplication is `hash(type + canonical_name)`. Nodes that produce the same stable ID across files are merged.

#### Node Deduplication

For each group of nodes sharing the same stable ID:

1. **Attribute merge**: keep the value with the highest confidence per attribute
2. **Confidence-1.0 string tie**: if both sources have confidence 1.0 and different string values, concatenate with `"; "` rather than silently discarding (lossless merge)
3. **Node confidence**: mean or max of all per-file confidences (configurable via `pipeline.assembly.confidence_agg`)
4. **Provenance**: `source_files` = union of all files where this node appeared
5. **Aliases**: union of all non-canonical name variants resolved by `normalize_names`

All merge decisions are logged to `intermediate/merge_log.json`.

#### Edge Deduplication

Key: `SHA256(type + sep + from_id + sep + to_id)` where `sep` is `ASSEMBLY_EDGE_DEDUP_SEPARATOR` from `pipeline_config.yaml` (default `"|"`). The separator prevents key collisions between e.g. `type="a_b", from="c"` and `type="a", from="b_c"`.

Same attribute merge rules as nodes. Edge confidence = mean of all per-occurrence confidences. `source_files` = union.

#### Edge Metadata Sidecar

All deduplicated edges are written to `intermediate/edge_metadata.json`, keyed by edge ID. This is the single source of truth for edges — `edges.jsonl` is always regenerated from the sidecar, never edited directly.

Every edge carries a `"method"` field: `"llm_extraction"` for Pass 2 edges, `"orphan_inferred"` for orphan-pass edges.

---

### Orphan-Connection Pass

**Goal:** Reconnect zero-edge nodes ("orphans") that were extracted but left isolated after assembly.

An orphan is any node whose stable ID appears as neither `from` nor `to` in any entry in `edge_metadata.json`.

#### Stage 1: `orphan_score` (no LLM)

Uses `chunk_node_index.json` to map each orphan to its source chunk(s). For each `(filename, chunk_idx)` pair containing at least one orphan:

1. Find all other node IDs that appear in the same chunk (co-occurring nodes)
2. Filter co-occurring peers by schema type compatibility: only pairs where a schema property exists with `domain = orphan_type` and `range = peer_type` (or compatible via inheritance)
3. Score each candidate by co-occurrence count
4. Produce an `OrphanChunkGroup` record for each `(filename, chunk_idx)`

Orphans with no resolvable source chunk are flagged as `orphan_unconnectable` advisory events in `orphan_log.json`.

Orphans from blank-response chunks (Pass 2 returned nothing) are cross-referenced against `failed_chunks.json` and the original file text to find their source chunk.

Results written to `intermediate/orphan_candidates.json` as `{"groups": [...], "schema_gap_orphans": [...]}`.

#### Stage 2: `orphan_connect` (LLM)

One LLM call per `OrphanChunkGroup`. The prompt includes:
- Full chunk text (~1000 tokens)
- All orphan node IDs and names from the group
- A sample of connected nodes from the same chunk
- All schema properties

The LLM returns a JSON array of edges. Each edge is validated (type must be in schema, `from`/`to` must be known node IDs). Valid edges are written to `intermediate/orphan_connections.json` and then merged directly into `intermediate/edge_metadata.json`.

**Confidence formula:**

```
final_conf = llm_conf × min(1.0, base + weight × heuristic_score)
```

Where `llm_conf` is the LLM's stated confidence (clamped to `[0.0, 1.0]`), `heuristic_score` is the normalized co-occurrence score from Stage 1, and `base` / `weight` are configurable.

**Schema-gap escalation:** If a group's orphans cannot be connected under the current schema (the LLM finds relationships but no schema property covers them), `propose_schema_additions()` asks the LLM to design new RDFS properties. If valid new properties are accepted, `SchemaUpdatedError` is raised to trigger an automated Pass 2 restart (see [Two-Tier Correction Model](#two-tier-correction-model)).

---

### Name Normalization

**Goal:** Resolve surface-form variants of the same entity to a single canonical name before deduplication.

The `normalize_names` step sends the full list of extracted names per concept type (capped at `max_names_per_type`) to the LLM with a prompt asking it to group synonyms. The LLM returns an `alias → canonical` mapping.

At assembly time, `step_assemble` inverts the map (`canonical → [aliases]`) and attaches the `aliases` list to each node. During deduplication, aliases are unioned across occurrences.

`chunk_node_index.json` is rebuilt at the end of `normalize_names` to update all pre-normalization stable IDs to their canonical equivalents. This ensures the orphan pass operates on the correct final IDs.

In `nodes.jsonl`, aliases appear as a flat sorted list of non-canonical surface forms. In `knowledge_graph.ttl`, each alias is emitted as a `skos:altLabel` triple.

---

### Cross-Session Merge

**Goal:** Combine two independently-produced pipeline sessions into a single unified knowledge graph.

#### File Namespacing

Before any merge operation, all file-keyed structures are namespaced:

```
session_a/notes.md
session_b/notes.md
```

This makes same-filename documents from different sessions structurally distinct. Node deduplication then works normally — same type + canonical name produces the same stable ID regardless of which session it came from.

`source_map.json` records the full provenance of every namespaced file key: original session name, alias, file path, SHA256, and role (`input_a`/`input_b`).

#### Schema Merge Chain

Both session schemas are wrapped as proposals and passed through the same three-stage chain as Pass 1:

```
merge_proposals([schema_a, schema_b]) → harmonize_schema() → review_schema_quality()
```

Schema history writes use trigger label `"session_merge"`.

#### Re-extraction Strategies

When the merged schema introduces properties absent from one session's original schema, those properties have no instances in that session's files unless extraction is re-run:

| Strategy | What happens | Cost |
|---|---|---|
| `none` | Accept gaps | Zero |
| `surgical` | Re-extract only chunks containing nodes of the affected property's domain/range type | O(affected chunks) |
| `full` | Re-run Pass 2 on all files from both sessions | O(all files) |

After surgical re-extraction, `_namespace_shards()` rewrites the `_fname` field in all newly-written shard files to include the session prefix (e.g., `"session_a/notes.md"`). This ensures `merge_raw` and the orphan pass can match shard keys against the rest of the merged session's namespaced data.

---

## Data Models

All structured data uses Pydantic `BaseModel`. No Python `dataclasses`.

### Schema

```python
# intermediate/schema.json
{
  "concepts": [
    {"type": "Person",       "parent": null,         "attributes": ["name", "email"]},
    {"type": "SoftwareEngineer", "parent": "Person", "attributes": ["github_handle"]}
  ],
  "properties": [
    {"name": "works_at", "domain": "Person", "range": "Organization",
     "attributes": ["role", "start_date", "end_date"]}
  ]
}
```

- Root classes have `"parent": null`
- Relationship types are `rdf:Property` predicates — never classes
- The abstract `Relationship` class does not exist; any LLM proposal containing it is filtered out

### Node (in nodes.jsonl)

```json
{
  "id": "person-alice-smith",
  "type": "Person",
  "confidence": 0.94,
  "source_files": ["team.md", "org.md"],
  "aliases": ["Alice Smith", "A. Smith"],
  "attributes": {
    "name":       {"value": "Alice",          "confidence": 1.0},
    "email":      {"value": "alice@acme.com", "confidence": 0.88},
    "birth_date": {"value": null,             "confidence": 0.0}
  }
}
```

- `aliases` is absent (not `[]`) when name normalization is disabled
- Missing attributes are always `{"value": null, "confidence": 0.0}`, never dropped

### Edge (in edge_metadata.json / edges.jsonl)

```json
{
  "id": "works_at-abc123",
  "type": "works_at",
  "from": "person-alice-smith",
  "to": "org-acme-corp",
  "confidence": 0.91,
  "method": "llm_extraction",
  "source_files": ["team.md"],
  "attributes": {
    "role":       {"value": "Engineer", "confidence": 0.88},
    "start_date": {"value": null,       "confidence": 0.0},
    "end_date":   {"value": null,       "confidence": 0.0}
  }
}
```

- `method`: `"llm_extraction"` (Pass 2) or `"orphan_inferred"` (orphan pass)
- Edge ID: `<type>-<hex6>` where hex6 is the first 6 hex chars of `SHA256(type + sep + from_id + sep + to_id)` (configurable separator, default `"|"`)

---

## Output Formats

### JSONL (nodes.jsonl + edges.jsonl)

Intended consumers: Neo4j, Kuzu, Memgraph, NetworkX, D3.js visualizers, LLM RAG context builders.

One JSON object per line. Both files are derived from `intermediate/nodes.json` and `intermediate/edge_metadata.json` at export time. `edges.jsonl` is always regenerated from the sidecar — it is never a source of truth.

### Turtle RDF (knowledge_graph.ttl)

Intended consumers: Protégé (schema authoring), HermiT/Pellet (OWL reasoning), Fuseki/GraphDB/Stardog (SPARQL).

Two sections:
1. **TBox**: RDFS class declarations (`rdfs:Class`, `rdfs:subClassOf`) + property declarations (`rdf:Property`, `rdfs:domain`, `rdfs:range`)
2. **ABox**: one `rdf:type` triple per node + `rdfs:label` + `skos:altLabel` triples for aliases + one direct object-property triple per edge

No edge metadata in the TTL. No blank nodes. No RDF reification. No RDF-star. Edge metadata lives exclusively in `edge_metadata.json`.

At export time, edges are filtered to only those whose `type` is declared in the schema's `properties[]`. The TTL is sanitized (`sanitize_abox_ttl`) and validated (`validate_knowledge_graph_ttl`) before writing.

### NetworkX Formats (networkx_output/)

Built from a `DiGraph` where node/edge attributes are flattened to GML-safe scalars: `attr_<name>_value` and `attr_<name>_confidence` pairs.

| Format | File | Consumer |
|---|---|---|
| GML | `knowledge_graph.gml` | Human-readable; most graph tools |
| GraphML | `knowledge_graph.graphml` | yEd, Gephi, Cytoscape |
| GEXF | `knowledge_graph.gexf` | Gephi native (rich metadata, dynamic support) |
| JSON node-link | `knowledge_graph.json` | D3.js, Sigma.js |
| Pajek | `knowledge_graph.net` | Network analysis (string attrs only) |
| Edge list | `edges_nx.txt` | Text pipelines |
| Adjacency list | `adjacency.txt` | Topology-only consumers |

### Interactive HTML (networkx_output/knowledge_graph.html)

Self-contained vis.js force-directed graph written inside `networkx_output/` by `export_networkx()`. No server required. Features: filter by node/edge type, filter by confidence threshold, search by name, hover popups with full attribute table, resizable sidebar.

---

## LLM Adapter Interface

The pipeline is decoupled from any specific LLM provider via a single abstract base class:

```python
class LLMAdapter(ABC):
    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        """Send a prompt and return the LLM response text.

        context_label: human-readable tag written to llm.log for each call.
        max_tokens: per-call override; None uses the adapter's configured default.
        timeout: per-call override in seconds; None uses the adapter's configured default.
        """

    @abstractmethod
    def endpoint_label(self) -> str:
        """Human-readable label for logging."""
```

Five implementations:

| Adapter | Provider | Notes |
|---|---|---|
| `AnthropicAdapter` | Anthropic API | Supports prompt caching |
| `OpenAIAdapter` | OpenAI API | Also works with Azure OpenAI and any OpenAI-compatible endpoint |
| `OllamaAdapter` | Ollama (local) | HTTP via `httpx` |
| `OpenRouterAdapter` | OpenRouter | Access many models via one API |
| `ClaudeCLIAdapter` | `claude -p` subprocess | No API key; serial only; `max_workers` must be 1 |

All adapters support:
- Configurable `timeout`
- 429 rate-limit retry with exponential backoff (`llm_complete_with_retry` / `retry_on_rate_limit`)
- Integration with `ErrorGate` — a thread-safe circuit breaker that pauses all workers when consecutive API errors exceed a threshold

Provider selection and all provider parameters (model, max_tokens, base_url, timeout) are set in `pipeline_config.yaml`. There are no hardcoded defaults in adapter code.

---

## Resumability and Re-entry

### Sentinel Files

Each step writes a sentinel file (typically `<step_name>.done`) after completion. `_is_done(step_name, ctx)` checks for the sentinel and/or the presence of all `Step.outputs` files. Completed steps are skipped on re-entry.

### Per-File Shards

Pass 2 writes a per-file shard immediately when each file completes. On restart, the shard existence check determines which files have already been extracted:

```python
skip = set(existing_raw.keys())   # files with shards → skip
```

`raw_extractions.json` is regenerated from all shards at the end of Pass 2 and on every re-entry. It is never a source of truth itself and should not be edited directly — edit the per-file shard instead.

### Four Re-entry Points

| Re-entry | Trigger | Files reused |
|---|---|---|
| **A — Schema** | Wrong schema; edit `schema.json` | None (all downstream invalidated) |
| **B — Extraction** | Wrong nodes/edges; edit shard files | `schema.json`, `flattened_schema.json` |
| **C — Assembly** | Bad dedup in `merge_log.json` | All above + `raw_extractions.json` |
| **D — Orphan pass** | Wrong candidates/confirmations | All above + `nodes.json`, `edge_metadata.json` |

### Cold Re-entry

Steps that need in-memory context (e.g., `merge_raw` needing `ctx.session_a`) check for `None` and reload from disk using `load_session()`. This ensures re-entry works correctly even after a process restart between steps.

---

## Two-Tier Correction Model

### Tier 1: KG-Level Correction (within a single run)

Each step gets:
1. One automatic retry (re-runs the step function)
2. If still failing and `is_llm_step=True`: an LLM feedback correction call via `feedback.apply(step_name, error, ctx)`, then a third attempt

Feedback handlers registered in `feedback._HANDLERS`:

| Step | Handler | What it does |
|---|---|---|
| `pass1` / `schema_validate` | `_fix_schema` | Corrects `schema.json` and regenerates `schema.ttl` |
| `schema_extend` | `_fix_schema_extend` | Corrects schema after invalid schema-gap proposal; uses `schema_gap_proposals.json` for context |
| `normalize_names` | `_fix_normalization` | Corrects `name_normalization.json` |
| `orphan_connect` | `_fix_orphan_connect` | Re-evaluates invalid orphan edge proposals |

`feedback.apply()` returns `True` when a handler ran (sets `llm_correction=True` in pipeline state), `False` when no handler exists for the step.

### Tier 2: Schema-Level Escalation (automated Re-entry A)

Triggered when `orphan_connect` discovers schema-gap orphans — nodes that cannot be connected under the current schema. The LLM proposes new RDFS properties via `propose_schema_additions()`. If valid new properties are accepted:

1. `SchemaUpdatedError` is raised inside `step_orphan_connect`
2. The orchestrator's outer `while True` loop catches it
3. The invalidation set `_SCHEMA_RESTART_INVALIDATE` is applied: sentinel files and outputs for `schema_validate`, `schema_flatten`, `pass2`, `normalize_names`, `assemble`, `orphan_score`, `orphan_connect`, and `validate_graph` are deleted
4. `schema_history/` and shard directories are preserved
5. The step loop restarts from the top; only the chunks named in `schema_hints.shared_chunks` are re-extracted (surgical re-extraction — O(affected chunks), not O(all files))
6. Restart count incremented; capped at `orphan_pass.schema_max_restarts`

The same pattern applies to the merge pipeline via `_MERGE_SCHEMA_RESTART_INVALIDATE` in `merge_run.py`.

---

## Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| **D3** — LLM backend | Provider-agnostic adapter ABC | Swap provider without touching pipeline logic |
| **D4** — Pipeline architecture | Sequential two-pass with global schema | Per-file schemas produce inconsistent vocabularies; merge is the hard part |
| **D5/D7** — Ontology model | `concepts[]` (RDFS classes) + `properties[]` (RDFS object properties) | Relationship types as predicates, not classes — clean standard RDFS; no intermediate node pattern |
| **D6** — Inheritance | Store own attributes only; flatten before Pass 2 | Compact schema, no duplication; LLM receives flat list and never sees inheritance |
| **D8/D15** — Edge metadata | JSON sidecar decoupled from TTL | Standard RDF cannot hold properties on edges; keeps TTL pure and valid |
| **D9** — Confidence | Every attribute, node, and edge carries `{value, confidence}` | Missing attributes are `{null, 0.0}`, never dropped — downstream consumers filter by threshold |
| **D10** — Deduplication | Key = `hash(type + canonical_name)` (nodes), `hash(type + from_id + to_id)` (edges) | Stable, human-readable IDs; deterministic across runs |
| **D21** — Synonym resolution | `synonym_match` — exact → normalized → SKOS thesaurus | Purely lexical; no embedding similarity; fast and reproducible |
| **D30** — Orphan pass | Two-stage: co-occurrence heuristic + LLM per chunk group | One LLM call per chunk (not per candidate pair) — 91 calls reduced to ~10 in test runs |
| **D37** — Surgical re-extraction | Preserve shards; re-extract only orphan-source chunks | O(affected chunks) cost rather than O(files × restarts) |
| **Invariant 7** — Config | `pipeline_config.yaml` is sole source of truth | No hardcoded defaults anywhere in pipeline or adapter code |
| **Invariant 8** — Data models | Pydantic `BaseModel` for all structured data | Free JSON serialization, validation, and type coercion at pipeline boundaries |

---

## Key Invariants

1. The LLM returns `nodes[]` + `edges[]`. Edges are direct (`from/to/type/attributes`), not wrapped in intermediate relationship nodes.
2. `knowledge_graph.ttl` contains only pure RDFS triples and `skos:altLabel` annotations. No edge metadata, no blank nodes, no reification, no RDF-star.
3. Edge metadata lives exclusively in `intermediate/edge_metadata.json`.
4. `edges.jsonl` is always regenerated from the sidecar — never edited directly.
5. The abstract `Relationship` class does not exist. Any LLM proposal containing it is filtered in `merge_proposals`.
6. Missing attributes are never dropped — always `{"value": null, "confidence": 0.0}`.
7. `pipeline_config.yaml` is the sole source of truth. No hardcoded literals in pipeline or adapter code.
8. All data models use Pydantic `BaseModel`. No Python `dataclasses`.
9. Each run is fully isolated. A run can always be resumed from its own snapshot without depending on external state.
10. Long-running extraction is resumable at the file granularity. Work already completed is never repeated on restart.
11. All data-processing stages that operate over independent items must be parallelised via `ThreadPoolExecutor`. Serial loops over collections are a bug.
12. `window_tokens + max_tokens` must never exceed the model's context window. A 429 response is a misconfiguration signal, not a transient error.
13. All output formats (JSONL, TTL, NetworkX) are validated and kept in sync at export time. `edge_metadata.json` is the unfiltered source; the type filter is applied only at export.
14. In surgical re-extraction, the full `run_pass2` output — including net-new nodes discovered under the richer merged schema — is merged back into session shards without post-filtering.
