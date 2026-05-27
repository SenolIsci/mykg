# Architecture

Last reviewed: 2026-05-25 (Third four-agent review — merge pipeline, walkthrough health status, merge re-entry correctness)

## System Overview

mykg is a two-pass knowledge graph extractor that reads a directory of Markdown files and produces three parallel output families: `nodes.jsonl` + `edges.jsonl` for property graph consumers, `knowledge_graph.ttl` (pure RDFS Turtle) for OWL toolchains, and seven NetworkX formats (GML, GraphML, GEXF, Pajek, JSON node-link, edge list, adjacency list) in `output/networkx_output/` for graph analysis and web visualization tools. Pass 1 induces a global RDFS schema from batched file chunks; Pass 2 extracts typed node/edge instances per file against that schema; the assembler deduplicates, confidence-scores, and materialises the sidecar and final outputs. All pipeline state is persisted to intermediate JSON files so any stage can be re-entered without re-running upstream work. A two-stage orphan-connection pass runs after assembly to reconnect zero-edge nodes via co-occurrence heuristic + LLM confirmation. A two-tier correction model (KG-level correction + schema-level escalation via `SchemaUpdatedError`) handles failures automatically before falling back to human re-entry.

## Architecture Diagram

```
CLI (cli.py)
  └── Orchestrator (orchestrator.py)
        └── while True loop (schema restart guard)
              └── Pipeline steps (pipeline.py → steps/)
                    │
                    ├── ingest          → intermediate/file_manifest.json
                    │                     intermediate/base_schema_parsed.json (if --base-schema)
                    │                     intermediate/thesaurus_parsed.json (if --thesaurus)
                    ├── pass1           → intermediate/schema.json
                    │                     intermediate/schema.ttl
                    │                     intermediate/merge_log.json (synonym events)
                    ├── schema_validate → intermediate/schema_validation_errors.json (failure only)
                    │                     intermediate/schema_validate.done (sentinel)
                    ├── human_review    → intermediate/schema_approved.flag (--review mode)
                    ├── schema_flatten  → intermediate/flattened_schema.json
                    ├── pass2           → intermediate/raw_extractions.json
                    │                     intermediate/chunk_node_index.json
                    ├── normalize_names → intermediate/name_normalization.json
                    ├── assemble        → intermediate/edge_metadata.json
                    │                     intermediate/nodes.json
                    │                     intermediate/merge_log.json (dedup events)
                    ├── orphan_score    → intermediate/orphan_candidates.json
                    ├── orphan_connect  → intermediate/orphan_connections.json
                    │                     intermediate/orphan_log.json
                    │                     intermediate/schema_gap_proposals.json (if schema-gap)
                    │                     (merges into edge_metadata.json in-place)
                    │                     ↑ may raise SchemaUpdatedError → restart while loop
                    └── export          → output/nodes.jsonl
                                          output/edges.jsonl
                                          output/knowledge_graph.ttl
                                          output/knowledge_graph_validation.json
                                          output/networkx_output/  (when networkx_enabled: true)

LLM adapters (llm/)
  ├── AnthropicAdapter    (provider: anthropic)
  ├── OllamaAdapter       (provider: ollama)
  ├── OpenAIAdapter       (provider: openai)
  ├── OpenRouterAdapter   (provider: openrouter)
  └── ClaudeCLIAdapter    (provider: claude-cli — uses `claude -p` subprocess; serial only, max_workers=1)
  All selected at startup by load_adapter() from pipeline_config.yaml → provider

Config (config.py)
  └── Loads pipeline_config.yaml at import time; exposes named constants.
      No hardcoded literals anywhere in pipeline or adapter code.
```

## Design Decisions

Key decisions from CLAUDE.md that shape the structure (full record in CLAUDE.md):

- **D3** — Provider-agnostic LLM via `LLMAdapter` ABC; one method (`complete`); swapped at startup.
- **D4** — Sequential two-pass with global schema; Pass 2 can be parallelised per-file.
- **D5/D7** — Schema is `concepts[]` + `properties[]`; relationship types are `rdf:Property`, never classes.
- **D6** — Store own attributes only; flatten per-concept inheritance chain before Pass 2 (`schema_flatten` step).
- **D8/D15** — Edge metadata lives in `edge_metadata.json` sidecar only; TTL is pure RDFS with no metadata.
- **D9** — Every attribute carries `{value, confidence}`; missing attributes are `{null, 0.0}`, never dropped.
- **D16/D26** — All intermediate state persisted; four re-entry points (A=schema, B=extraction, C=assembly, D=orphan pass).
- **D17** — Automated schema validation with one LLM correction retry; optional human review gate.
- **D18** — Python library is primary; CLI wraps it.
- **D21** — `synonym_match` is purely lexical (PascalCase split + normalise + optional SKOS thesaurus).
- **D29** — Node aliases: flat `list[str]` of non-canonical surface forms; absent (not `[]`) when normalization disabled; emitted as `skos:altLabel` in TTL ABox.
- **D30** — Two-stage orphan-connection pass: Stage 1 co-occurrence heuristic → Stage 2 LLM confirmation with all name mentions via `_extract_relevant_excerpt()`.
- **D31** — Two-tier correction model: Tier 1 KG-level (orphan reconnection, name normalization, per-step retry) and Tier 2 schema-level escalation (`SchemaUpdatedError` → iterative restart, capped at `schema_max_restarts`).
- **D35** — Pass 1 runs three LLM stages per run after parallel batch induction: (1) parallel batch induction via `ThreadPoolExecutor`, (2) algorithmic merge (`merge_proposals()`), (3) harmonization LLM call (`harmonize_schema()`), (4) quality review LLM call (`review_schema_quality()`). All four stages write delta records to `schema_history/`.
- **D36** — `schema_history` module (`src/mykg/schema_history.py`) tracks schema evolution via numbered delta files per trigger (`pass1_merge`, `schema_harmonize`, `schema_quality`, `schema_gap`, `schema_gap_correct`, `schema_validate`).
- **D37** — Surgical re-extraction on schema-gap restart: shard directories are preserved; only orphan-source chunks (from `schema_hints.shared_chunks`) are re-extracted; all other file shards are reused unchanged.
- **Invariant 7** — `pipeline_config.yaml` is the sole source of truth; `config.py` exposes constants.
- **Invariant 8** — All data models use Pydantic `BaseModel`; no Python `dataclasses`.
- **Invariant 9 (Run isolation)** — Each run is fully isolated; inputs, intermediate state, outputs, and logs are co-located and self-contained. A run can always be resumed from its own snapshot without depending on external state.
- **Invariant 10 (Fine-grained resumability)** — Long-running extraction is resumable at the finest meaningful granularity. Work already completed is never repeated on restart; only the remaining work is resubmitted.
- **Invariant 11 (Durable bounded logs)** — Log output is bounded and durable. Logs are scoped to their run, rotate automatically when large, and are never silently discarded.
- **Invariant 12 (Mandatory parallelism)** — All data-processing stages that operate over independent items (files, chunks, candidates) must be parallelised using `ThreadPoolExecutor`. Serial loops over collections are a bug. Worker count is always configurable via `pipeline_config.yaml` — never hardcoded. Applies to ingest, Pass 1 batch dispatch, Pass 2 file extraction, orphan scoring, and any future bulk step.
- **Invariant 13 (LLM context and rate limit respect)** — `window_tokens + max_tokens` must never exceed the active model's context window. Worker counts must be set conservatively enough to avoid 429 rate-limit errors. A 429 is a misconfiguration signal — reduce `max_workers` in `pipeline_config.yaml`; it is not a transient error to silently retry.

## Merge Pipeline

`mykg merge-graphs <session-A> <session-B>` merges two independently-produced pipeline sessions into a new unified session. Both source sessions are read-only; all output lands in a fresh timestamped session folder. The merge reuses the same pipeline infrastructure (steps, orchestrator, assembler, exporter) as the extract pipeline via a `MergeContext` subclass and a dedicated `MERGE_STEPS` list.

### MERGE_STEPS (12 steps, in order)

| Step | Phase | Description |
|------|-------|-------------|
| `merge_setup` | 0 | Loads both `SessionData` objects, namespaces and copies shard files into the merged `intermediate/`, writes `source_map.json` |
| `merge_schema` | 1 | Runs `merge_proposals()` + `harmonize_schema()` + `review_schema_quality()` on both session schemas; writes `schema.json`, `schema.ttl`; records delta in `schema_history/` with trigger `"session_merge"` |
| `schema_validate` | 2 | Reused from extract pipeline; validates `schema.ttl` with rdflib (non-blocking advisory) |
| `human_review` | 3 | Reused; optional gate controlled by `merge_graphs.human_review` config flag |
| `schema_flatten` | 4 | Reused; writes `flattened_schema.json` for LLM prompts |
| `merge_reextract` | 5 | Re-extracts only files from sessions where the merged schema introduced new properties absent from that session's original schema; strategy is `"surgical"` (default), `"full"`, or `"none"`; surgical mode re-extracts targeted chunks with the merged schema — both net-new edges and any net-new nodes under the richer schema survive into deduplication (D38, Invariant 15) |
| `merge_raw` | 6 | Namespaces raw extractions from both sessions as `session_alias/filename` and merges into `raw_extractions.json` |
| `assemble` | 7 | Reused; deduplicates nodes and edges across both sessions; same type+name → same stable ID regardless of source session |
| `orphan_score` | 8 | Reused; maps orphan nodes from the merged graph to source chunks → `orphan_candidates.json` |
| `orphan_connect` | 9 | Reused; LLM confirms edges for each orphan group → merges `orphan_connections.json` into `edge_metadata.json` |
| `validate_graph` | 10 | Reused; exports `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, NetworkX formats |
| `merge_manifest` | 11 | Writes `merge_manifest.json` with full audit fields (non-blocking) |

### MergeContext

`MergeContext` extends `PipelineContext` with merge-specific fields. All standard pipeline step functions accept `PipelineContext` and work unchanged with `MergeContext` via Pydantic subclassing.

- `session_a_name`, `session_b_name` — source session names passed at CLI invocation
- `sessions_root` — parent directory of all sessions
- `session_a`, `session_b` — `SessionData` objects populated by `merge_setup`
- `source_map` — dict populated by `merge_setup`; maps every namespaced file key to its provenance
- `synonym_log` — list of synonym collapse events from `merge_schema`
- `schema_delta_a`, `schema_delta_b` — lists of new property names absent from each source session's original schema; populated by `merge_reextract`

### Intermediate files specific to merge

| File | Written by | Contents |
|------|-----------|----------|
| `intermediate/source_map.json` | `merge_setup` | Maps every namespaced file key (`session_alias/filename`) to provenance: original session name, alias, SHA256, role (`input_a`/`input_b`) |
| `intermediate/merge_manifest.json` | `merge_manifest` | Audit record: `session_a`, `session_b`, `merged_at`, `schema_synonym_log`, `reextraction_strategy`, `schema_delta_session_a`, `schema_delta_session_b` |

All other intermediate files (`schema.json`, `flattened_schema.json`, `raw_extractions.json`, `edge_metadata.json`, `nodes.json`, `merge_log.json`) use the same format as the extract pipeline and are produced by reused steps.

### Re-entry points for merge

- **Schema review gate:** run `mykg approve-schema --session <merged-session>` then re-run with `--session <merged-session>` to continue past the gate.
- **Re-run from any step:** pass `--session <merged-session>` to the CLI; the orchestrator resumes from the last incomplete step using the standard `_is_done` sentinel mechanism.

---

---

## To-Do List

Items tagged: `[critical]` `[high]` `[medium]` `[low]` and `[done]` when complete.
New items added at top. Done items are never deleted — marked `[done]` for history.

| # | Priority | Area | Task | Added | Done |
|---|----------|------|------|-------|------|
