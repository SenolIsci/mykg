# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Status

Implementation is complete. The pipeline is fully operational end-to-end.

Key design document:
- `docs/implementation-alternatives.md` — architecture decisions, data models, output formats, and design trade-offs

All design decisions (D1–D54) below are authoritative for the current implementation.

## What This System Does

A two-pass knowledge graph extractor that reads Markdown files and produces a property graph with an RDFS-compatible ontology layer.

- **Pass 1** — Schema induction: LLM reads batched MD files and proposes concept types (`concepts[]`) and relationship properties (`properties[]`) → produces `intermediate/schema.json`
- **Pass 2** — Instance extraction: LLM extracts individuals (`nodes[]`) and relationships (`edges[]`) against the schema → assembler writes edge metadata sidecar, deduplicates, and produces final outputs

---

## All Design Decisions

### D1 — Input Format
Markdown files only. Sources are heterogeneous: personal notes, technical documentation, and domain-specific structured content. The parser must handle YAML/TOML frontmatter, headings, lists, and code blocks as structural signals. Large files are chunked into overlapping windows before being sent to the LLM. Window size and overlap are set via `pipeline_config.yaml → pipeline.chunking` (defaults: 2000 tokens, 200 token overlap).

### D2 — Primary Use Cases
Three equal-priority consumers: search & retrieval, LLM reasoning/Q&A, and visualization. The graph must be rich enough to serve all three without specialization.

### D3 — LLM Backend: Provider-Agnostic
A pluggable adapter interface separates pipeline logic from LLM calls. Any backend (Anthropic/Claude, OpenAI, Ollama, OpenRouter, ClaudeCLI) can be swapped without changing extraction or assembly logic. Provider selection and all provider parameters (model, max_tokens, base_url, timeout) are set in `pipeline_config.yaml → llm.<provider>`; there are no hardcoded defaults in adapter code. Five adapter implementations exist: `anthropic_adapter.py`, `openai_adapter.py`, `ollama_adapter.py`, `openrouter_adapter.py`, and `claude_cli_adapter.py`. The `claude_cli` provider uses a `claude -p` subprocess — no API key required, billing via Claude Pro/Max plan; `max_workers` must be 1 (the CLI is serial by design).

### D4 — Pipeline Architecture: Option A (Sequential Two-Pass with Global Schema)
Pass 1 batches all files together to induce one global schema. Pass 2 extracts instances per file in parallel against that schema. Chosen over:
- Option B (per-file schemas + late merge) — too complex; merge logic is the hardest part
- Option C (iterative refinement) — fully sequential, highest LLM cost, non-deterministic stabilization
Upgrade path: design the schema induction module with the Option B merge interface in mind so migration is possible if corpora grow beyond a few hundred files.

Pass 1 batch dispatch is fully parallelized via `ThreadPoolExecutor` (worker count configurable via `pass1.max_workers`). `pass1.per_file_batching` — when true, chunks from different files are never mixed in one batch (Option B-style per-file isolation within Pass 1).

`pass2.stateful_chunks` — when true, prior-chunk node IDs are passed to the next chunk within a file, enabling stable IDs across chunk boundaries without a full file-level dedup pass between chunks.

### D5 — Ontology Model: Concept Taxonomy + Standard RDFS Properties
Two ideas combined:
1. **Concept taxonomy** — `is-a` hierarchy (`SoftwareEngineer` is-a `Person`; root classes have `"parent": null`)
2. **Standard RDFS properties** — relationship types are `rdf:Property` predicates with `rdfs:domain` and `rdfs:range`, not classes

This replaces the earlier "intermediate node pattern" (which modeled relationships as OWL classes `Employment`, `Dependency`, etc.). The new approach produces clean standard RDFS triples in `knowledge_graph.ttl`; edge metadata (confidence scores, role, start_date, etc.) is stored in a separate sidecar file `intermediate/edge_metadata.json`.

### D6 — Inheritance Strategy: Store Canonical, Flatten for Extraction
The schema stores only own attributes per concept type (compact, DRY). Before Pass 2, the pipeline flattens each concept's full attribute list by walking the inheritance chain. The LLM receives the flat list and never sees the word "inheritance". Chosen over:
- Inherit silently — LLM is inconsistent; misses inherited attributes unpredictably
- Store flat — duplicates attributes; hierarchy is lost; manual updates required when parent changes

### D7 — Schema Format: `concepts[]` + `properties[]`
The schema produced by Pass 1 has two top-level arrays:
- **`concepts[]`** — RDFS classes with `is-a` hierarchy (`type`, `parent`, `attributes`). Own attributes only; pipeline flattens at runtime before Pass 2.
- **`properties[]`** — RDFS object properties (`name`, `domain`, `range`, `attributes`). The `attributes` list defines the edge-level metadata fields (role, start_date, etc.) captured in the sidecar.

```json
{
  "concepts": [
    { "type": "Person",       "attributes": ["name", "email", "birth_date"],   "parent": null },
    { "type": "Organization", "attributes": ["name", "industry"],              "parent": null }
  ],
  "properties": [
    { "name": "works_at", "domain": "Person", "range": "Organization",
      "attributes": ["role", "start_date", "end_date"] }
  ]
}
```

No hardcoded root class. Root classes have `"parent": null`. No abstract `Relationship` class. No `relation_type` field. Relationship types are properties, not classes.

### D8 — Edge Metadata Sidecar (`intermediate/edge_metadata.json`)
Edge-level metadata (confidence scores, role, start_date, etc.) cannot live in pure RDFS triples. It is stored in a separate sidecar file keyed by edge ID. The sidecar is the source for `edges.jsonl` assembly. `knowledge_graph.ttl` contains no metadata — only pure RDFS triples.

Every edge in the sidecar carries a `"method"` field indicating how it was produced:
- `"llm_extraction"` — extracted by Pass 2 LLM and assembled by `deduplicate_edges`
- `"orphan_inferred"` — inferred by the orphan-connection pass (Stage 1 co-occurrence + Stage 2 LLM confirmation)

```json
{
  "edge-001": {
    "type": "works_at", "from": "person-alice", "to": "org-acme-corp",
    "confidence": 0.96,
    "method": "llm_extraction",
    "attributes": { "role": {"value": "engineer", "confidence": 0.91} },
    "source_files": ["team.md"]
  }
}
```

### D9 — Confidence Scores on Everything
Every extracted attribute value, node, and relationship instance carries a confidence score `0.0–1.0`. Format:
```json
{ "value": "engineer", "confidence": 0.91 }
```
Missing attributes are never dropped — they are `{ "value": null, "confidence": 0.0 }`. Downstream consumers filter by threshold.

### D10 — Deduplication Strategy
Nodes are grouped for deduplication by key = `hash(type + canonical_name)` where canonical_name is lowercased and whitespace-normalized. The actual stable ID format assigned to each node is defined in D19 (human-readable `<type-prefix>-<name-slug>`). When the same node appears across multiple files:
- Attribute values: keep the value with highest confidence; if both sources have confidence 1.0 and different string values, concatenate with `"; "` (lossless merge) — null values and non-string types always keep first-seen
- Node confidence: mean or max (configurable)
- Provenance: list of source files recorded on every merged node
- All merge decisions logged to `intermediate/merge_log.json`

Edges deduplicated by `hash(type + from_id + to_id)` — merge attributes keeping highest confidence (same confidence-1.0 concatenation rule as nodes), aggregate confidence (mean), union source_files.

### D11 — Output Format: Four Parallel Outputs (JSONL + RDF/OWL + NetworkX + Neo4j CSV)
Four parallel output formats for different consumers:
- **JSONL** (`nodes.jsonl` + `edges.jsonl`) — for property graph consumers: Neo4j, NetworkX, visualizers, LLM RAG
- **Turtle RDF** (`knowledge_graph.ttl`) — for OWL consumers: Protégé, HermiT/Pellet reasoners, SPARQL endpoints
- **NetworkX formats** (`networkx_output/`) — GML, GraphML, GEXF, Pajek, JSON node-link, edge list, adjacency list; toggled via `pipeline_config.yaml → export.networkx_enabled`
- **Neo4j LOAD CSV bundle** (`neo4j_csv/`) — plain-header CSVs per node label and relationship type, plus `import_browser.cypher` (Neo4j Browser), `import_shell.cypher` (cypher-shell), and a per-bundle `README.md`. Idempotent MERGE script; requires Neo4j 5+. Toggled via `pipeline_config.yaml → export.neo4j_csv_enabled` (default off) or the `--neo4j-csv` CLI flag.

All four are generated from the same in-memory data in `step_validate_graph` (Step 12). None is primary. A standalone CLI `python -m mykg.exporters.neo4j.emit_load_csv` produces the same bundle against an existing session and is the fallback when the toggle was off at extraction time.

### D12 — `nodes.jsonl` — Concept Instances Only
`nodes.jsonl` contains all concept instances (Person, Organization, SoftwareEngineer, etc.) with full attributes and confidence scores. It does NOT contain relationship nodes — those no longer exist in the new design. Each record also carries an `aliases` field (see D29): a flat list of original surface-form strings for alternative names that were resolved to this canonical node during name normalization. The field is absent when the `normalize_names` step is disabled.

### D13 — `edges.jsonl` Derived from Sidecar
`edges.jsonl` is generated by the assembler from `intermediate/edge_metadata.json` — never edited directly. It contains flat `from/to/type/confidence/attributes` records for Neo4j importers and visualizers.

### D14 — `knowledge_graph.ttl` — RDFS + Standard Annotation Properties, Two Sections
The Turtle file has two sections: RDFS schema (TBox) and instance data (ABox). No edge metadata, no blank nodes, no reification, no RDF-star.
- **TBox**: class declarations (`rdfs:Class`, `rdfs:subClassOf`) + property declarations (`rdf:Property`, `rdfs:domain`, `rdfs:range`)
- **ABox**: node instance triples + `skos:altLabel` triples for aliases (when present) + one direct object property triple per edge (`:Alice ex:works_at :AcmeCorp`)

Confidence scores and edge attributes are absent from the Turtle file — they live in `edge_metadata.json` only. `skos:altLabel` (from the SKOS vocabulary) is used for alias annotation; it is a standard well-known predicate and does not require a TBox declaration. The ABox validator exempts the SKOS namespace from the `undeclared_predicate` check.

### D15 — RDFS Compatibility via Standard Properties + Sidecar
Standard RDF cannot hold properties on edges. The old approach (intermediate node pattern) is replaced with: relationship types become `rdf:Property` predicates in the schema, and edge metadata is stored in a JSON sidecar decoupled from the Turtle file. This keeps `knowledge_graph.ttl` clean and valid with any standard RDF toolchain.

### D16 — Intermediate JSON Files for All Pipeline Stages
All intermediate state is persisted as JSON between pipeline stages for debugging, resumability, and human review:

| File | Written | Contents |
|---|---|---|
| `intermediate/preprocess.done` | After Step 0 (always when preprocess runs) | Sentinel file; tells `_is_done` that preprocess completed so it is skipped on re-entry |
| `intermediate/preprocess_manifest.json` | After Step 0 | Preprocess summary + the `source_files` change-detection block (D49). For each non-md source: `sha256` of source bytes, relative `output_md` path, and `size_bytes`. Atomically rewritten (`*.tmp` → `os.replace`). Also records skipped suffixes and per-file HTML conversion records |
| `intermediate/preprocess_filelist.txt` | Before MinerU subprocess (Step 0, when ≥1 non-md file needs conversion) | Plain-text list of rel-paths (one per line) handed to `mykg parse-docs --file-list`. Avoids the OS `ARG_MAX` ceiling on corpora with thousands of source files. Audit trail of exactly what the pipeline asked MinerU to convert this run |
| `intermediate/base_schema_parsed.json` | Step 1 (only if `--base-schema` provided) | Locked classes + properties parsed from the user-supplied TTL file |
| `intermediate/thesaurus_parsed.json` | Step 1 (only if `--thesaurus` provided) | SKOS thesaurus metadata — source path, term count, relations used |
| `intermediate/schema.json` | After Pass 1 | Induced RDFS schema: `concepts[]` + `properties[]` — pipeline source of truth |
| `intermediate/schema.ttl` | After Pass 1 | TBox-only RDFS — validated by Step 3b; load in Protégé for review |
| `intermediate/schema_validation_errors.json` | After Step 3b (failure only) | rdflib syntax + semantic validation errors; absent if schema is valid |
| `intermediate/flattened_schema.json` | Before Pass 2 | Per-concept flattened attribute lists for LLM prompts |
| `intermediate/file_manifest.json` | After Step 1 | Map of filename → file content; enables Re-entry B after cold restart |
| `intermediate/pipeline_state.json` | After every step transition | Step status (pending/running/done/failed/waiting) and error details; written by orchestrator; used by `PipelineState.load` on re-entry |
| `intermediate/schema_validate.done` | After Step 3b (always) | Sentinel file; tells `_is_done` that schema validation completed so it is skipped on re-entry (the step has no data output) |
| `intermediate/raw_extractions_shards/` | During Pass 2 (per-file, written via `on_file_done`) | Per-file extraction shards — one `<slug>.json` per source file containing `{_fname, data}`; loaded on restart to skip already-extracted files (primary resumability mechanism) |
| `intermediate/chunk_index_shards/` | During Pass 2 (per-file, written via `on_file_done`) | Per-file chunk-node-index shards — one `<slug>.json` per source file; paired with `raw_extractions_shards/` |
| `intermediate/raw_extractions.json` | After Pass 2 completes (final merged write) | Raw `nodes[]` + `edges[]` per source file, merged from shards; overwritten from shards on every re-entry — do not edit directly (see D26 Re-entry B) |
| `intermediate/raw_extractions.done` | After Pass 2 completes | Sentinel file; tells `_is_done` that pass2 finished so it is skipped on re-entry |
| `intermediate/name_normalization.json` | After Step 6b (normalize_names) | LLM-produced alias→canonical name map + metadata; `mappings` key holds type-keyed map; empty sentinel written when normalization is disabled |
| `intermediate/edge_metadata.json` | After assembly | Edge attributes + confidence, keyed by edge ID — source for edges.jsonl |
| `intermediate/nodes.json` | After assembly | Deduplicated node list (JSON array); written by step_assemble, read by step_validate_graph on fresh-process re-entry (when `ctx.nodes` is None) |
| `intermediate/merge_log.json` | After assembly | Deduplication decisions audit trail |
| `output/knowledge_graph_validation.json` | After Step 12b (always) | TBox + ABox rdflib validation results — advisory, pipeline is complete at this point |
| `output/networkx_output/` | After Step 12c (when `networkx_enabled: true`) | NetworkX multi-format exports: GML, GraphML, GEXF, Pajek, JSON node-link, edge list, adjacency list |
| `output/neo4j_csv/` | After Step 12e (when `neo4j_csv_enabled: true` or `--neo4j-csv`) | Neo4j LOAD CSV bundle: one `nodes_<Label>.csv` per concept type, one `relationships_<TYPE>.csv` per property, `import_browser.cypher`, `import_shell.cypher`, `README.md` |
| `intermediate/chunk_node_index.json` | After Pass 2 | Map of `{filename: {chunk_idx: [stable_ids]}}` — built by `pass2._process_file`; prerequisite for Stage 1 orphan scoring |
| `intermediate/orphan_candidates.json` | After `orphan_score` | Dict with two keys: `"groups"` (list of OrphanChunkGroup records — one per source chunk) and `"schema_gap_orphans"` (list of SchemaGapOrphan records for orphans with unresolvable provenance) |
| `intermediate/schema_history/` | During Pass 1 and schema-gap restarts | Numbered delta files tracking schema evolution; one file per schema write (`<seq>_<trigger>.json`) |
| `intermediate/failed_chunks.json` | After pass2 (when chunks skipped) | List of `{filename, chunk_idx, reason}` for every chunk that returned a blank/unparseable response after all retries; absent if no chunks were skipped |
| `intermediate/orphan_connections.json` | After `orphan_connect` | Dict of confirmed orphan edges `{edge_id: edge}` after Stage 2 LLM confirmation; merged into `edge_metadata.json` |
| `intermediate/orphan_log.json` | After `orphan_connect` | Audit trail of all orphan Stage 2 events. `orphan_edge_added` events carry: `id`, `type`, `from`, `to`, `confidence`, `rationale`, `llm_confidence`, `chunk_key`. `orphan_edge_rejected` events carry: `orphan_id`, `candidate_id`, `reason` only. |
| `intermediate/schema_gap_proposals.json` | After `orphan_connect` (schema feedback loop) | Raw LLM proposal for new schema properties to connect schema-gap orphans; written even when no properties are added (empty `new_properties` list); absent if schema-gap loop never runs |
| `intermediate/schema_approved.flag` | After `approve-schema` CLI command | Sentinel file; written by `mykg approve-schema`; its presence allows the pipeline to proceed past the human review gate when `--review` mode is active |
| `run.log` | During the run (session mode) | Log file auto-placed at session root; relative `--log-file` paths are redirected here; absent when `--log-file` is omitted outside session mode |
| `llm.log` | During the run (session mode) | One JSON line per LLM call — provider, model, token counts, latency, cache stats; written alongside `run.log` in the session root; absent when `--log-file` is omitted outside session mode |
| `intermediate/llm_calls/` | During the run (when `capture_prompts: true`) | Full prompt/response pairs — one `<n>_<slug>_input.md` + `<n>_<slug>_output.md` pair per LLM call; absent if `logging.capture_prompts` is false |
| `walkthrough.md` | After the run completes (session mode) | Human-readable markdown summary of the pipeline run — stats, schema overview, and per-step outcomes; written at session root by `step_walkthrough` |
| `intermediate/source_map.json` | `merge_setup` (merge pipeline only) | Maps every namespaced file key (`session_alias/filename`) to provenance: original session name, alias, SHA256, role (`input_a`/`input_b`); `_meta` block records `prep_mode` of each source session |
| `intermediate/merge_manifest.json` | `merge_manifest` step (merge pipeline only) | Audit record: `session_a`, `session_b`, `merged_at` (ISO timestamp), `schema_synonym_log`, `reextraction_strategy`, `schema_delta_session_a`, `schema_delta_session_b` |
| `intermediate/merge_reextract.done` | After `merge_reextract` completes (merge pipeline only) | Sentinel file; tells `_is_done` that merge re-extraction finished so it is skipped on re-entry |

### D17 — Human Review Gate Between Passes
After Pass 1, the schema is written to `intermediate/schema.json` (source of truth) and `intermediate/schema.ttl` (TBox-only RDFS view). Before the human review gate, `schema.ttl` is validated automatically using rdflib (syntax) and custom semantic checks (domain/range refer to declared classes, no conflicting ranges). If validation fails, the errors are sent back to the LLM with a correction prompt for one retry — the LLM returns a corrected schema, `schema.json` and `schema.ttl` are regenerated, and validation runs once more. The pipeline then always proceeds to the human review gate (Step 4) regardless of the second result. All validation outcomes (both attempts) are written to `intermediate/schema_validation_errors.json` for the reviewer. The user edits `schema.json` if needed; `schema.ttl` is regenerated from it before Pass 2 runs. The gate is optional but recommended.

### D18 — Interface: Python Library + CLI Wrapper
The Python library is primary. The CLI wraps the library. This enables embedding in larger pipelines programmatically while also supporting standalone command-line use.

### D19 — Assembler and Export Materialization Algorithm
The pipeline splits materialization across two steps: `assemble` (Steps 7–9) and `export` (Steps 10–12).

**`step_assemble` is responsible for:**
1. **Stable ID assignment** — format: `<type-prefix>-<name-slug>` where type-prefix = `node.type.lower()` (e.g. `"softwareengineer"`, `"organization"`) and name-slug = canonical_name with spaces replaced by hyphens (e.g. `softwareengineer-alice`, `organization-acme-corp`). Canonical_name = lowercased, whitespace-normalized `name` attribute value.
2. **Node deduplication** — group by ID across all files; merge attributes keeping highest-confidence value; if two string values both have confidence 1.0, concatenate with `"; "` rather than silently discarding; aggregate node confidence (mean or max, configurable); record provenance (source file list); union aliases
3. **Edge deduplication** — hash by `hash(type + from_id + to_id)`; merge attributes keeping highest confidence (same confidence-1.0 concatenation rule as nodes); aggregate edge confidence (mean); union source_files
4. **Sidecar write** — write all deduplicated edges to `intermediate/edge_metadata.json`; write deduplicated node list to `intermediate/nodes.json`

**`step_validate_graph` is responsible for:**
5. **nodes.jsonl export** — serialize each deduplicated node to one JSONL line
6. **edges.jsonl export** — emit one flat JSONL record per sidecar entry from `edge_metadata.json`
7. **knowledge_graph.ttl export** — Section 1: RDFS TBox (classes + properties with domain/range); Section 2: ABox (node instance triples + `skos:altLabel` alias triples + one direct object property triple per edge)
8. **NetworkX export** (Step 12c, when `networkx_enabled: true`) — builds a `DiGraph` from the same in-memory nodes/edges and writes all formats to `output/networkx_output/`; node/edge attributes are flattened to GML-safe scalars (`attr_<name>_value` / `attr_<name>_confidence`)
9. **Neo4j CSV export** (Step 12e, when `neo4j_csv_enabled: true` or `--neo4j-csv`) — builds plain-header CSVs grouped by sanitized node label and relationship type, plus a `LOAD CSV` Cypher script (browser + cypher-shell variants) and a per-bundle README at `output/neo4j_csv/`; the script uses idempotent `MERGE` against the `_MykgNode` uniqueness constraint, requires Neo4j 5+, and runs against a live DBMS with no Python driver and no plugin

### D20 — Chunking Strategy for Pass 1
Large files are split into overlapping windows before Pass 1 LLM calls. Window size, overlap, and tiktoken encoding are configured via `pipeline_config.yaml → pipeline.chunking` (defaults: 2000 tokens, 200 token overlap, `cl100k_base`). Each batch of chunks produces a schema proposal. All proposals are merged by unioning concept types, deduplicating by exact name match, and resolving synonyms via `synonym_match` (exact + normalised string; SKOS thesaurus if provided — see D21, D28).

### D21 — Synonym Resolution in Pass 1 Schema Merge
After batching, the schema merge step unions all concept types and relationship types from all batch proposals, deduplicates by exact name match first, then resolves near-duplicates using `synonym_match(a, b)` (see D28). If no thesaurus is loaded, only exact and normalised string matching applies. If a SKOS thesaurus is provided: `skos:exactMatch` → collapse silently; `skos:closeMatch` → collapse with warning logged to `merge_log.json` including both names and thesaurus evidence. The result is written to `intermediate/schema.json` for optional human review before Pass 2.

### D22 — Edge Deduplication Key
Edges use a composite key: `hash(type + from_id + to_id)`. The `type` is the property name (e.g. `works_at`), `from_id` and `to_id` are stable node IDs. This ensures the same relationship extracted from multiple files is merged into one canonical edge record in the sidecar.

### D23 — Tool Targets per Output Format
- `nodes.jsonl` + `edges.jsonl` → Neo4j, Kuzu, Memgraph, NetworkX, visualizers (Gephi, D3, Sigma.js), LLM RAG context builders
- `knowledge_graph.ttl` → Protégé (schema authoring), HermiT/Pellet (OWL reasoning), SPARQL endpoints (Fuseki, GraphDB, Stardog)
- `networkx_output/knowledge_graph.graphml` → yEd, Gephi, Cytoscape (full attributes)
- `networkx_output/knowledge_graph.gexf` → Gephi native (richest metadata, dynamic graph support)
- `networkx_output/knowledge_graph.json` → D3.js, Sigma.js, web visualizers (JSON node-link format)
- `networkx_output/knowledge_graph.gml` → human-readable inspection, most graph tools
- `networkx_output/knowledge_graph.net` → Pajek network analysis (string attributes only)
- `networkx_output/edges_nx.txt` → simple text pipelines, quick inspection
- `networkx_output/adjacency.txt` → topology-only consumers
- `neo4j_csv/` → Neo4j 5+ via Neo4j Browser (paste `import_browser.cypher`) or `cypher-shell -f import_shell.cypher`; idempotent `MERGE` with `_MykgNode` uniqueness constraint, no driver and no plugin required

### D24 — Prompt Engineering
Full prompt templates are in `docs/implementation-alternatives.md` under "Prompt Engineering".

**Pass 1 system prompt must teach:**
- Output has two keys: `"concepts"` (RDFS classes) and `"properties"` (RDFS object properties)
- Each property entry has `name` (snake_case), `domain`, `range`, `attributes` (edge metadata fields)
- Do NOT output a `"relations"` array or a `"Relationship"` class

**Pass 2 system prompt must teach:**
- Output is `{ "nodes": [...], "edges": [...] }`
- `edges[]` entries: `type` = property name from schema, `from`/`to` = node IDs (not display names)
- Every attribute in `properties[].attributes` must appear in the edge output, null if unknown
- Every attribute in the flattened concept spec must appear in node output, null if unknown

**Assembler must validate after every LLM call:**
- Reject any edge whose `type` is not in the schema's `properties[]`
- Reject any edge whose `from`/`to` values are not valid node IDs from the same extraction
- On failure: log to `intermediate/raw_extractions.json`, warn, and optionally retry

### D25 — Step 12b: knowledge_graph.ttl Validation (Advisory)
After `knowledge_graph.ttl` is exported, it is validated by rdflib (syntax) and custom checks:
- **TBox checks** (same as Step 3b): all `rdfs:domain`/`rdfs:range` refer to declared classes, every non-null `rdfs:subClassOf` parent is a declared class
- **ABox checks**: every `rdf:type` object is a declared class, every predicate in ABox is a declared property, every object-property triple's object is a declared instance

The result is always written to `output/knowledge_graph_validation.json`. Errors are advisory only — the pipeline is already complete at this point. If ABox errors appear, use the Re-run Guide to diagnose whether the root cause is in raw extractions (Re-entry B) or assembler logic (Re-entry C).

### D26 — Re-run Guide: Four Re-entry Points
All intermediate files are preserved between runs. The pipeline can be re-entered at four points:

| Re-entry | Enter at | Trigger | Files reused |
|---|---|---|---|
| **A — Schema changed** | Step 3b | Wrong concept, missing property, bad parent; Step 3b errors unresolved | None — schema change invalidates all extractions |
| **A (automated — schema-gap restart)** | `orphan_connect` | Schema-gap orphans detected by `orphan_connect`; `propose_schema_additions()` proposes new properties; `SchemaUpdatedError` raised; orchestrator invalidates `schema_validate` + `schema_flatten` + `pass2` + all downstream; restarts from `pass2` (not Step 3b); skips human review gate; capped at `orphan_pass.schema_max_restarts`. Shard directories (`raw_extractions_shards/`, `chunk_index_shards/`) are intentionally preserved — only the specific chunks named in `schema_hints.shared_chunks` are re-extracted (surgical re-extraction, see D37); all other file shards are reused. This avoids paying full re-extraction cost on every schema-gap restart. | `schema.json`, `orphan_candidates.json` |
| **B — Extraction errors** | Step 6 | LLM missed entities, wrong attributes, invented edge types; ABox errors in `knowledge_graph_validation.json` traceable to `raw_extractions.json` | `schema.json`, `flattened_schema.json` |
| **C — Assembly errors** | Step 7 | Bad dedup in `merge_log.json`; ABox errors traceable to assembler logic, not LLM output | `schema.json`, `flattened_schema.json`, `raw_extractions.json` |
| **C (normalization)** | assemble step | Wrong alias→canonical mappings in `name_normalization.json` | `schema.json`, `flattened_schema.json`, `raw_extractions.json`, `name_normalization.json` |
| **D — Orphan pass** | orphan_score | Wrong candidates in `orphan_candidates.json`; delete it and re-run from `--from-step orphan_score` | `schema.json`, `nodes.json`, `edge_metadata.json`, `chunk_node_index.json` |
| **D (LLM only)** | orphan_connect | Wrong confirmations in `orphan_connections.json`; delete it and re-run from `--from-step orphan_connect` | `orphan_candidates.json` + everything above |

Re-entry A (manual): edit `intermediate/schema.json` → regenerate `schema.ttl` → rerun from Step 3b onward.
Re-entry A (automated): triggered by `SchemaUpdatedError` from `orphan_connect` — restarts from `pass2` with no manual intervention required.
Re-entry B: `raw_extractions.json` is regenerated from shard files on every re-entry and must not be edited directly. To edit individual extractions, edit the per-file shard in `intermediate/raw_extractions_shards/<file_slug>.json`, then rerun from `--from-step pass2 --session <name>`. All shard files are deleted by `--from-step pass2` so that all files are re-extracted from scratch; per-file selective re-extraction is not supported.
Re-entry C: review `merge_log.json`, optionally edit `raw_extractions.json` → rerun from Step 7 onward.
Re-entry C (normalization): edit `intermediate/name_normalization.json` → rerun from `--from-step assemble` (does NOT re-run the LLM normalization call; assembler derives aliases from the edited map at assembly time).

### D27 — Optional Base Schema TTL (`--base-schema`)
The pipeline accepts an optional `--base-schema <file>.ttl` argument. The TTL must be a valid TBox-only RDFS or OWL file (see D54 for supported OWL constructs). It is parsed in Step 1 into `intermediate/base_schema_parsed.json` and validated immediately — an invalid base schema halts the pipeline before any LLM calls.

**Lock semantics:** base schema classes and properties are locked throughout the pipeline.
- A locked class cannot be renamed, removed, or have its parent changed by LLM proposals
- A locked class can receive additional attributes (unioned from LLM proposals)
- A locked property cannot be renamed, removed, or have its domain/range changed
- A locked property can receive additional edge attributes (unioned from LLM proposals)
- LLM proposals that duplicate a locked name are merged into the locked entry (attributes unioned, structure from locked wins)
- Near-duplicate proposals (string similarity match) are collapsed into the locked entry with a warning in `merge_log.json`

**Pass 1 prompt injection:** every batch prompt includes a `EXISTING SCHEMA` block listing locked class and property names with an explicit instruction not to rename, remove, or duplicate them.

**Step 3b / Step 12b:** no special handling needed — locked classes enter the merge as declared classes and pass the same validation checks as any induced class.

### D28 — Optional External Thesaurus (`--thesaurus`)
The `--thesaurus <file>.skos.ttl` argument is optional. If omitted, `synonym_match` uses only exact and normalised string matching — no external lookup. `intermediate/thesaurus_parsed.json` is absent in that case.

**`synonym_match(a, b)` — the single resolution function used throughout Step 3:**
1. Exact string match → True
2. Normalised match (lowercase, whitespace/hyphen → underscore) → True
3. If SKOS thesaurus loaded: `skos:exactMatch` in either direction → True, collapse silently
4. If SKOS thesaurus loaded: `skos:closeMatch` in either direction → True, collapse with warning in `merge_log.json`
5. Otherwise → False

**Thesaurus vs base schema:** the thesaurus resolves synonyms among *induced* LLM proposals. The base schema (D27) locks the authoritative vocabulary. They compose: `synonym_match` is also applied between LLM proposals and locked names — if a proposal matches a locked entry, it is merged into the locked entry (lock wins).

**SKOS relations used:**
- `skos:exactMatch` — definite synonym, silent collapse
- `skos:closeMatch` — near-synonym, collapse with warning
- `skos:broader` / `skos:narrower` — advisory only (candidate parent/child hints, not enforced)

Thesaurus metadata written to `intermediate/thesaurus_parsed.json` only if `--thesaurus` was provided.

### D29 — Node Aliases: Source, Format, and Contract
After the `normalize_names` step (Step 6b), each node in `nodes.jsonl` and `intermediate/nodes.json` carries an `aliases` field containing the non-canonical surface forms that were resolved to that node.

**Source:** derived from `intermediate/name_normalization.json["mappings"]` at assembly time. `step_assemble` inverts the map (`alias→canonical` → `canonical→[aliases]`) and attaches aliases to nodes before `deduplicate_nodes` runs. Aliases are unioned across occurrences during deduplication.

**Format:** `aliases: list[str]` — flat list of original surface-form strings (not lowercased, not slugged). The canonical name itself is excluded. Lexicographically sorted for deterministic output. Field is absent (not `[]`) when `normalize_names` is disabled (`NORMALIZE_NAMES_ENABLED=false`).

**In `knowledge_graph.ttl`:** emitted as `skos:altLabel` triples in the ABox — one triple per alias per node. The `@prefix skos:` declaration is emitted only when at least one node has aliases.

**Edges do not have aliases.** Edges are structural triples `(type, from_id, to_id)` — not named entities. Relationship type synonyms are resolved at schema induction time by `synonym_match` in Pass 1, not at the instance level.

### D30 — Orphan-Connection Pass: Two-Stage Heuristic + LLM
An **orphan node** is a node present in `intermediate/nodes.json` whose stable ID appears as neither `from` nor `to` in any entry in `intermediate/edge_metadata.json` after `step_assemble` completes. Orphans are legitimate — they may represent singleton entities in the source corpus — but can degrade graph quality for traversal, visualization, and reasoning use cases.

The orphan-connection pass is two stages, registered as two separate pipeline steps (`orphan_score`, `orphan_connect`) to correctly scope the orchestrator retry/feedback loop:

**Stage 1 — `orphan_score` (`is_llm_step=False`):**
Uses `chunk_node_index.json` to map each orphan node to its source chunk(s). For normal orphans (present in the index), records all orphan IDs per `(filename, chunk_idx)` and all connected nodes from the same chunk. For blank-response orphans (absent from the index), cross-references `failed_chunks.json` and string-searches failed chunk texts from `file_manifest.json` to find the source chunk, then flags the node with `extraction_quality: "blank_response"`, `blank_chunk_file`, and `blank_chunk_idx`. Produces `OrphanChunkGroup` records — one per `(filename, chunk_idx)` — written to `orphan_candidates.json` as `{"groups": [...], "schema_gap_orphans": [...]}`. The schema type-pair filter from the previous design is removed — all orphans with a resolvable source chunk proceed to Stage 2 regardless of type compatibility.

**Stage 2 — `orphan_connect` (`is_llm_step=True`):**
For each `OrphanChunkGroup`, calls the LLM once to find all relationships between the group's orphan nodes and any connected node listed. The prompt includes the full chunk text (~1000 tokens), all orphan node IDs and names, a sample of connected graph nodes, and all schema properties. The LLM returns a JSON array of edges. Validates each edge (type must be in schema, from/to must be known node IDs); drops invalid edges. Updates `extraction_quality` on blank-response nodes: `blank_response → blank_recovered` if ≥1 edge found, `blank_response → blank_unresolved` if no edges found. Confirmed edges carry `"method": "orphan_inferred"`. Writes `intermediate/orphan_connections.json` and `intermediate/orphan_log.json`, then merges confirmed edges into `intermediate/edge_metadata.json`.

**Re-entry D:** `--from-step orphan_connect` reruns Stage 2 only; `--from-step orphan_score` reruns both stages (see D26).

Config keys for the orphan pass:
- `orphan_pass.excerpt_window` — character window around an orphan mention used as LLM context in Stage 2 (default 400)
- `orphan_pass.excerpt_context` — characters of surrounding context added around the window (default 150)
- `orphan_pass.blank_recovery_enabled` — whether blank-response orphan detection is active (default true)
- `orphan_pass.connected_sample_size` — max connected nodes included in the chunk recovery prompt (default 20)

### D31 — Two-Tier Correction Model
Corrections are organized into two tiers with an explicit escalation path:

**Tier 1 — KG-level corrections (within a single pipeline run):**
- `orphan_score` + `orphan_connect`: reconnect isolated nodes via co-occurrence heuristic + LLM confirmation
- `normalize_names` + `assemble`: resolve name variants before deduplication
- Per-step retry: every step gets one automatic retry before feedback is requested
- LLM feedback loop: for `is_llm_step=True` steps, the orchestrator calls `feedback.apply(step_name, error, ctx)` on a third attempt using a step-specific correction handler

**Tier 2 — Schema-level escalation (Re-entry A):**
Triggered when `orphan_connect` determines that schema-gap orphans cannot be connected with the current schema. The LLM proposes new RDFS properties; `propose_schema_additions()` validates that all proposed domain/range values are declared concepts before accepting them. When net-new properties are accepted, `step_orphan_connect` raises `SchemaUpdatedError`, which the orchestrator catches. The orchestrator then: (a) deletes outputs of all steps in `_SCHEMA_RESTART_INVALIDATE` (which includes `schema_flatten` so the new properties are flattened into LLM prompts), (b) resets in-memory state, and (c) restarts the step loop **iteratively** (not recursively) via an outer `while True` loop. The restart count is capped at `orphan_pass.schema_max_restarts` (default 1) to prevent infinite loops.

**Feedback handlers in `feedback.py`:**
- `pass1` / `schema_validate` → `_fix_schema`: correct `schema.json` and regenerate `schema.ttl`
- `schema_extend` → `_fix_schema_extend`: correct `schema.json` after a schema-gap proposal introduced invalid RDFS; reads both current schema and `schema_gap_proposals.json` for context
- `normalize_names` → `_fix_normalization`: correct `name_normalization.json`

The `schema_extend` handler is distinct from `schema_validate` because it has access to the proposal context (`schema_gap_proposals.json`) and can make a more targeted correction than a generic schema repair.

### D32 — Session-Based Run Isolation
Each `mykg extract-graph` run creates an isolated session folder under `mykg_sessions/` (configurable via `pipeline_config.yaml → pipeline.paths.sessions_dir`, default `mykg_sessions`). The session root contains three subdirectories: `input/` (copy of all input `.md` files), `intermediate/` (all pipeline state files), and `output/` (all final outputs). The log file is also placed here.

**Session directory layout:**
```
mykg_sessions/
  <YYYY-MM-DDTHH-MM-SS>/     ← UTC timestamp, auto-created per run
    input/                   ← recursive copy of all input Markdown files (subdirectory structure preserved)
    intermediate/            ← all intermediate pipeline files (D16)
    output/                  ← all final output files (D11)
    run.log                  ← log file (auto-placed; relative --log-file paths are redirected here)
```

**CLI behaviour:**
- `--session <name>` — selects an existing session; `intermediate/` and `output/` of that session become the working dirs; `input/` is refreshed
- `--session` is mutually exclusive with `--output-dir` / `--intermediate-dir`
- `approve-schema --session <name>` — finds `intermediate/` in the named session
- **Log file routing:** `setup()` is called after session resolution; if `--log-file` is omitted the log goes to `session_root/run.log`; relative paths are redirected to `session_root/<filename>`; absolute paths are used as-is
- **Bypass:** passing explicit `--output-dir` / `--intermediate-dir` skips all session logic; the old default paths from `pipeline_config.yaml` are used instead

**`_make_session_dirs(sessions_root)` helper** (`src/mykg/cli.py`): creates `<root>/<timestamp>/{input,intermediate,output}` and returns `(name, output_dir, intermediate_dir)`.

**`_copy_input_files(input_dir, session_root)`** (`src/mykg/cli.py`): copies all `.md` files from `input_dir` into `session_root/input/` using `rglob("*.md")`; subdirectory structure is preserved relative to `input_dir`.

### D32 — Hallucinated Anchor Node Removal in `_partial_recover`
When `_partial_recover` is invoked (degraded mode: retry failed), it drops edges that reference unknown or invalid node IDs. Without further action, nodes that were invented solely to anchor those edges survive — they have a valid schema type, so the type-whitelist filter passes them, but they carry no real content and become guaranteed orphans.

After computing `valid_edges`, `_partial_recover` performs a second pass: any node that is (a) new to this chunk — i.e. not present in `prior_nodes` — and (b) not referenced by any surviving edge is dropped as a hallucinated anchor. The `prior_nodes` exemption is essential: nodes extracted from earlier chunks are known-good entities; a later chunk may yet connect them and they must not be discarded.

This filter fires only in degraded mode, so the risk of false-positive drops (a real singleton entity with no edges in this chunk) is bounded. A genuine singleton would be in `prior_nodes` if it appeared in an earlier chunk, or will remain in `valid_nodes` of a later chunk that does connect it. The cost of dropping a genuine singleton here is that it does not appear in `prior_nodes` for the next chunk — the LLM may re-extract it, now with correct IDs.

### D33 — Blank-Response Orphan Flagging
When `_extract_chunk` returns `None` (blank or unparseable LLM response after all retries), pass2 records `{filename, chunk_idx, reason: "blank_response"}` to `intermediate/failed_chunks.json` via a thread-safe `FailedChunkLog`. In `orphan_score`, any orphan node whose stable ID is absent from `chunk_node_index.json` is cross-referenced against `failed_chunks.json`. If its source file had blank-response chunks and the node's display name appears in a failed chunk's text (string search via re-sliced `file_manifest.json`), the node is flagged with `extraction_quality: "blank_response"`, `blank_chunk_file`, and `blank_chunk_idx`. After recovery by `orphan_connect`, the flag updates to `blank_recovered` (≥1 edge found) or `blank_unresolved` (no edges found). Nodes with `blank_unresolved` are included in all final outputs — they are epistemically distinct from genuine singletons (`extraction_quality` absent = clean extraction, no field written).

### D34 — Unified Chunk-Level Orphan Pass
The orphan pass batches by source chunk rather than by candidate pair. Stage 1 (`orphan_score`) maps each orphan to its source chunk(s) and produces `OrphanChunkGroup` records — one per `(filename, chunk_idx)` — containing all orphan IDs and connected node IDs from that chunk. Stage 2 (`orphan_connect`) makes one LLM call per group with the full ~1000-token chunk text, not a 400-char excerpt per pair. This reduces total LLM calls (one per chunk vs one per candidate pair — 91 calls in a test run dropped to ~10) and gives the LLM full context to find relationships. The schema type-pair filter from the v1 design is removed — it was causing false schema-gap orphans by eliminating candidates before the LLM had a chance to evaluate them from the raw text.

### D35 — Pass 1: Three-Stage Schema Induction
Pass 1 runs four sequential stages after initial batching:

1. **Parallel batch induction** — `ThreadPoolExecutor` dispatches one LLM call per batch (max_workers=`pass1.max_workers`). Each batch returns a `{concepts, properties}` proposal.
2. **Schema merge** — `merge_proposals()` unions all batch results, deduplicating by exact name and `synonym_match`. Writes `intermediate/schema.json`. Config: `pass1.per_file_batching` (bool, default false — when true, chunks from different files are never mixed in the same batch).
3. **Schema harmonization** — `harmonize_schema()` makes one LLM call to collapse semantic near-duplicates (e.g. "MilitaryUnit" vs "ArmyUnit") that exact-match missed. Sees both the merged schema and all raw batch proposals. Uses the adapter's default max_tokens and timeout from the llm: profile block. Returns the original if the response is unparseable.
4. **Schema quality review** — `review_schema_quality()` makes one LLM call to remove overly narrow concept types (e.g. named-entity concepts like "FourthAirForce" → remove, extract as MilitaryUnit instance), fix singleton types, collapse subclasses that add no own attributes, deepen/flatten hierarchy as needed, and ensure every concept has at least a "name" attribute. Same config knobs as harmonization (uses default `max_tokens` from the active profile).

All four stages write delta records to `intermediate/schema_history/` via `schema_history.write_schema()` (see D36).

### D36 — Schema History Module
Every schema write is recorded in `intermediate/schema_history/` as a numbered delta file `<seq>_<trigger>.json` containing the trigger label, timestamp, lists of concepts/properties added and removed, and running totals. Trigger labels:
- `pass1_merge` — initial schema produced by Pass 1 merge step
- `schema_harmonize` — after the harmonization LLM call
- `schema_quality` — after the quality review LLM call
- `schema_validate` — LLM correction after RDFS validation failure
- `schema_gap` — new properties added by orphan schema-gap loop
- `schema_gap_correct` — LLM correction after schema-gap proposal introduced invalid RDFS
- `session_merge` — merged schema after cross-session `merge_schema` step

This directory is written by `src/mykg/schema_history.py` and can be used to reconstruct the schema evolution across a run.

### D37 — Surgical Re-extraction on Schema-Gap Restart
When `SchemaUpdatedError` fires (Re-entry A automated), the orchestrator does NOT delete the shard directories. Instead:
- `ctx.schema_hints` is populated with per-orphan data: `orphan_id`, `orphan_type`, `orphan_name`, `new_properties`, `shared_chunks` (list of `"filename::chunk_idx"` strings)
- Pass 2 receives `reextract_chunks` dict and `prior_extractions` from existing shards
- Only the specific chunks in `schema_hints.shared_chunks` are re-extracted; all other file shards are reused
- New edges from re-extracted chunks are merged back into existing shards via `_on_file_done_surgical`

This is more efficient than a full pass2 re-run: only the chunks where orphans appeared are re-processed, paying O(affected_chunks) LLM cost rather than O(files × restarts).

### D38 — Cross-Session Merge (`mykg merge-graphs`)
The `mykg merge-graphs <session-A> <session-B>` command merges two independently-produced pipeline sessions into a new unified session. Both source sessions are read-only; all output lands in a fresh timestamped session folder.

**Schema merge chain:** Both schemas are wrapped as proposals and passed to `merge_proposals([schema_a, schema_b], ...)`, then `harmonize_schema()`, then `review_schema_quality()` — the same chain used in Pass 1 schema induction (D35). Every schema write is recorded in `schema_history/` with trigger `"session_merge"`.

**File namespacing:** All file-keyed structures (raw_extractions keys, shard filenames, node/edge `source_files` lists) are namespaced as `<session_alias>/<original_filename>` before any merge. This makes same-filename documents from different sessions structurally distinct. Node deduplication then works normally — same type+name → same stable ID regardless of which session produced it.

**`source_map.json`:** Written at the start of every merge to `intermediate/source_map.json`. Maps every namespaced file key to its full provenance: original session name, original path, SHA256, and role (`input_a` / `input_b`). The `_meta` block records the `prep_mode` of each source session. See `docs/session-merge.md` for the full format.

**`merge_manifest.json`:** Written at the end of every merge to `intermediate/merge_manifest.json`. Fields: `session_a`, `session_b`, `merged_at` (ISO timestamp), `schema_synonym_log`, `reextraction_strategy`, `schema_delta_session_a`, `schema_delta_session_b`.

**Re-extraction strategy (`merge_graphs.reextraction_strategy`):** Controls what happens when the merged schema has new properties absent from a source session's original schema. Three mutually exclusive values in `pipeline_config.yaml`:
- `"none"` — accept gaps; no extra LLM cost
- `"surgical"` — targeted chunk re-extraction using `chunk_node_index`. For each new property, identifies chunks containing nodes of the property's domain or range type. Only those chunks are re-extracted; all other shards are reused. New nodes produced by the LLM are dropped — only new edges and enriched attribute values survive. Falls back to full chunk enumeration if `chunk_node_index` is unavailable. Bounded by `merge_graphs.surgical_top_k_chunks_per_property` (0 = disabled, zero candidates produced; >0 = top-K chunks per new property, ranked by domain/range node co-occurrence count).
- `"full"` — re-extract all files from both sessions

**`prep_mode` compatibility:** All three pass2 prep modes (`per_file`, `concat`, `batch_chunks`) produce identical shard formats. Sessions run with different prep_modes can be merged with no special handling.

**Extract pipeline steps (STEPS — `mykg extract-graph`):**

| # | Step | LLM | Key outputs |
|---|---|---|---|
| 1 | `preprocess` | — | `preprocess.done`, `preprocess_manifest.json` |
| 2 | `ingest` | — | `file_manifest.json` |
| 3 | `pass1` | ✓ (3 calls) | `schema.json`, `schema.ttl`, `schema_history/` |
| 4 | `schema_validate` | — | `schema_validate.done` |
| 5 | `human_review` | — | `schema_approved.flag` *(gate, opt-in via `--review`)* |
| 6 | `schema_flatten` | — | `flattened_schema.json` |
| 7 | `pass2` | ✓ | `raw_extractions.json`, `chunk_node_index.json`, `failed_chunks.json` |
| 8 | `normalize_names` | ✓ | `name_normalization.json` |
| 9 | `assemble` | — | `edge_metadata.json`, `nodes.json`, `merge_log.json` |
| 10 | `orphan_score` | — | `orphan_candidates.json` |
| 11 | `orphan_connect` | ✓ | `orphan_connections.json`, `orphan_log.json`, `schema_gap_proposals.json` |
| 12 | `validate_graph` | — | `nodes.jsonl`, `edges.jsonl`, `knowledge_graph.ttl`, `knowledge_graph_validation.json` |

**Step-based pipeline (MERGE_STEPS — `mykg merge-graphs`):**

The merge pipeline is implemented as a 12-step `MERGE_STEPS` registry in `merge_pipeline.py`, orchestrated by `merge_run.py`. Steps run via the same `PipelineState` / `_is_done` / retry pattern as the extract pipeline.

| # | Step | LLM | What it does |
|---|---|---|---|
| 1 | `merge_setup` | — | Loads both SessionData objects, namespaces and copies shards, writes `source_map.json` |
| 2 | `merge_schema` | ✓ (3 calls) | `merge_proposals()` + `harmonize_schema()` + `review_schema_quality()` → `schema.json`, `schema.ttl`, `schema_history/` |
| 3 | `schema_validate` | — | Reused from extract pipeline |
| 4 | `human_review` | — | Reused; gate controlled by `merge_graphs.human_review` config flag |
| 5 | `schema_flatten` | — | Reused from extract pipeline |
| 6 | `merge_reextract` | ✓ | Re-extracts affected chunks per strategy (`none`/`surgical`/`full`) |
| 7 | `merge_raw` | — | Namespaces + merges raw extractions from both sessions |
| 8 | `assemble` | — | Reused from extract pipeline |
| 9 | `orphan_score` | — | Maps orphan nodes to source chunks → `orphan_candidates.json` |
| 10 | `orphan_connect` | ✓ | LLM confirms edges for orphan groups → `orphan_connections.json` |
| 11 | `validate_graph` | — | Reused from extract pipeline |
| 12 | `merge_manifest` | — | Writes `merge_manifest.json` |

**MergeContext fields:**

`MergeContext(PipelineContext)` adds these merge-specific fields:
- `session_a_name: str` — name of source session A
- `session_b_name: str` — name of source session B
- `sessions_root: Path` — parent directory of all sessions
- `session_a: SessionData | None` — populated by `merge_setup`
- `session_b: SessionData | None` — populated by `merge_setup`
- `source_map: dict | None` — populated by `merge_setup`
- `synonym_log: list` — synonym collapse events from `merge_schema`
- `schema_delta_a: list` — new property names absent from session A's original schema
- `schema_delta_b: list` — new property names absent from session B's original schema

**Surgical re-extraction invariant:**

In surgical mode, `reextract_for_merge()` merges the full output of `run_pass2` back into the session shards — both new edges (using the merged property types) and any net-new nodes the LLM extracted under the richer schema survive.

**`walkthrough.md` for merge sessions:**

The walkthrough includes a Merge Provenance section automatically when `source_map.json` is present:
- **Before & After** — node/edge/concept/property counts per source session and merged
- **Node Provenance** — counts for A-only, B-only, deduplicated, net-new nodes
- **Edge Provenance** — A-to-A, B-to-B, cross-session, and edges using new merged property types

### D39 — Preprocess Step Placement
A new step `preprocess` is inserted at position 0 of `STEPS` (before `ingest`). It writes `intermediate/preprocess.done` sentinel + `intermediate/preprocess_manifest.json` data file (the manifest carries the `source_files` change-detection block — D49). `is_llm_step=False`, `blocking=False` — a single file's conversion failure logs a warning and is recorded in the manifest, but does not halt the pipeline; other files proceed.

**Skipped on re-entry only when the sentinel exists AND no source file has changed.** With the sentinel present, `step_preprocess` still reads the prior manifest and the current input tree and skips MinerU per file when the source SHA matches — see D47 for the default re-entry contract and D49 for the change-detection mechanism. The step is a no-op for pure-Markdown corpora.

**Single subprocess, multi-file loop.** `step_preprocess` issues exactly one `mykg parse-docs` invocation per pipeline run regardless of how many files need conversion — the subprocess builds one venv and loops MinerU per file inside it (D48). The list of changed files is handed to `parse-docs` via `--file-list <intermediate/preprocess_filelist.txt>` so argv stays O(1) in corpus size (D49).

### D40 — `mykg parse-docs` Subcommand
Standalone CLI and the single point in the codebase where MinerU is actually invoked — the `preprocess` pipeline step delegates to it via `python -m mykg parse-docs` **only for non-HTML files**. The command builds one ephemeral Python 3.12 venv via `uv`, installs `mineru[all]` into it, loops MinerU **once per input file** inside that single venv, and deletes the venv on exit (see D48). Does NOT create a session — purely a file-to-file utility for inspecting MinerU output independently of `extract-graph`. HTML files never reach this subcommand; they are converted in-process by `step_preprocess` before `parse-docs` is spawned (see D44).

**Input shape — three forms, all accepted in one invocation:**

- `--input <file>` — process a single file. One `mineru -p <file> -o <output>` call inside the venv. Same behaviour as a single-shot MinerU invocation.
- `--input <dir>` — **recursive directory mode** (no `--file`, no `--file-list`). `parse-docs` walks the input tree, picks up every non-`.md` file, and loops MinerU per file inside the single venv with subfolder structure preserved at the output: a source at `<dir>/sub/a.pdf` lands under `<output>/sub/...`. Used for ad-hoc bulk conversion from the shell.
- `--input <dir> --file <rel>` (repeatable, relative to `--input`) **OR** `--input <dir> --file-list <path>` (one rel-path per line, blank lines ignored) — restrict to the named files. `--file` and `--file-list` are **mutually exclusive**. The pipeline always uses `--file-list` (see D49) so its argv stays O(1) in corpus size and is not bounded by `ARG_MAX`.

**File-extension filter (applies to all three input shapes):** candidate files are filtered against `preprocess.extensions` from `mykg_config.yaml` — the same allowlist `step_preprocess` applies upstream of pipeline-driven calls. Files whose suffix is not on the list (`.DS_Store`, `.css`, `.svg` sidecars, etc.) are logged at INFO and skipped before MinerU is invoked. `.html` and `.htm` are **always hard-skipped** regardless of the allowlist — MinerU cannot convert HTML, so the skip carries a hint pointing to `mykg extract-graph` (which routes HTML through markdownify, see D44). If filtering leaves zero candidates, `parse-docs` exits clean (return code 0) **before** the ephemeral venv is built — no point paying the multi-GB MinerU install for an empty target list. Pass `--no-filter` to disable the `preprocess.extensions` allowlist (the HTML hard-skip still applies); useful when the input is already curated and you want MinerU to attempt every non-HTML file regardless of suffix. The filter logic lives in `_build_parse_docs_targets()` and `_PARSE_DOCS_HARDCODED_SKIP` in [src/mykg/cli.py](src/mykg/cli.py) — a pure helper that can be exercised without spinning up the venv.

**Per-file failure semantics:** when looping (any of the three shapes above except single-file input), per-file MinerU failures (e.g. `.DS_Store` or any unsupported format) are logged via `click.echo(..., err=True)` and the loop continues. `parse-docs` exits non-zero at the end if any file failed (`"N of M files failed conversion"`). Timeouts on any single file remain fatal — they signal the venv or the underlying process is stuck, not a per-file format issue.

### D41 — Converted-File Placement
Inside a session, converted `.md` files land under `input/<PREPROCESS_SUBDIR>/` (default `_preprocessed`) — *not* alongside the originals. With the default subdir, `input/foo.pdf` → `input/_preprocessed/foo.md` plus `input/_preprocessed/foo.mineru.json`. The original non-md source stays put under `input/`. Setting `preprocess.subdir` to an empty string restores the legacy in-place layout (converted `.md` next to source). The subsequent `ingest` step reads `*.md` recursively via `rglob` (its existing behaviour) and naturally picks up files from the subfolder; `_files_with_extensions` skips the subdir on the source-discovery side so re-running preprocess never feeds converted output back in as input. This keeps the session self-contained (Invariant 9), keeps originals visually distinct from machine-generated markdown, and makes the conversion fully visible and editable in `session/input/<subdir>/`.

### D42 — Output Discovery via Deepest Glob
MinerU writes its output into a nested per-file directory whose subdirectory layout varies by backend (`hybrid_ocr/`, `pipeline/`, etc.). After invoking MinerU on `<stem>.<ext>` with a unique per-file out dir `<out>/<stem>/`, locate the canonical markdown via `sorted((<out>/<stem>).rglob(f"{stem}.md"), key=lambda p: len(p.parts))[-1]` (deepest match wins). The pattern is implemented in `step_preprocess._discover_canonical_md`. This makes the wrapper resilient to MinerU output layout changes across versions.

**Cleanup gating:** the layout described here only persists when `preprocess.keep_artifacts: true` (D49). With the default `false`, `step_preprocess` flattens each canonical `.md` to `<output_dir>/<rel_parent>/<stem>.md` and rmtrees the per-file `<stem>/` subtree right after discovery — only the canonical `.md` survives. The discovery primitive itself is unchanged; the cleanup is a post-processing pass gated by the flag.

### D43 — Per-File Image Subfolder + Link Rewrite
The `images/` folder produced by MinerU lands under a per-file subdirectory `<output_dir>/<stem>/.../images/` (the exact depth depends on the MinerU backend; deepest-glob discovery handles it — D42). The chunker ignores image markup; images are inert ballast for the LLM.

**Cleanup gating:** the `images/` folder only persists when `preprocess.keep_artifacts: true` (D49). With the default `false`, `images/` is removed alongside the rest of the per-file MinerU subtree when `step_preprocess` rmtrees `<output_dir>/<rel_parent>/<stem>/` after flattening the canonical `.md`. The image-link references in the surviving `<stem>.md` are left as-is — they become dangling references, which is acceptable because the chunker and the LLM both ignore them. Setting `keep_artifacts: true` is the supported way to inspect the source figures.

Standalone `mykg parse-docs` ignores `keep_artifacts` and always keeps the full MinerU layout — the flag governs the pipeline path only (D49).

### D44 — HTML and TXT In-Process Converters
HTML is converted in-process by `step_preprocess._convert_html_files` using the `markdownify` library (declared as a core dependency in `pyproject.toml`). MinerU is **not** invoked for HTML — MinerU does not natively accept HTML input, so routing it through the ephemeral venv would be both wrong and wasteful. This also keeps the heavy MinerU venv unnecessary for HTML-only corpora.

Plain text (`.txt`) is handled in-process by `step_preprocess._convert_txt_files` using `shutil.copy2(src, dst)` where `dst` has a `.md` extension. No conversion logic is needed — the content is already plain text. Failures are logged and recorded in `preprocess_manifest.json["txt_records"]` with the same non-blocking semantics as HTML.

**Routing** — there is a **single** user-facing allowlist (`preprocess.extensions` in YAML, exposed as `PREPROCESS_EXTENSIONS`). The backend per allowed suffix is decided inside `step_preprocess` by two hardcoded mappings: `_HTML_BACKEND_SUFFIXES = {".html", ".htm"}` and `_TXT_BACKEND_SUFFIXES = {".txt"}`:
- Suffix in `_HTML_BACKEND_SUFFIXES` and in `PREPROCESS_EXTENSIONS` → `_convert_html_files` (markdownify, in-process)
- Suffix in `_TXT_BACKEND_SUFFIXES` and in `PREPROCESS_EXTENSIONS` → `_convert_txt_files` (shutil.copy2, in-process)
- Suffix in `PREPROCESS_EXTENSIONS` but not HTML/TXT → `mykg parse-docs` subprocess (MinerU)
- Suffix not in `PREPROCESS_EXTENSIONS` → logged + recorded under `preprocess_manifest.json["skipped_files"]`, left untouched on disk

This split is deliberate: *which backend can handle which format* is a property of the format, not a user preference, so it's hardcoded. *Whether the preprocess step should convert that format at all* is a user choice, so it's a single flat YAML list. A user opts out of HTML conversion by removing `.html`/`.htm` from `extensions:`; the files are then logged + skipped exactly like any other unmatched suffix. The same applies to `.txt`.

**HTML conversion details** — `markdownify(html, strip=["img", "a"])` is called with anchors and images stripped (link `href`s and `<img src>` paths would not resolve outside the original page; images are inert ballast to the LLM per D43). Output filename mirrors the source stem with `.md` substituted; subdirectory structure under `input/` is preserved relative to the source. Failures are logged and recorded in `preprocess_manifest.json["html_records"]` but do not halt the pipeline (matches D39 non-blocking semantics for per-file conversion errors).

### D45 — Configuration via `preprocess:` Block
YAML section under each profile in `mykg_config.yaml`. Only the keys actually wired into the pipeline are listed below — earlier drafts of this design enumerated additional knobs (`max_workers`, `backend`, `language`, `fail_fast`) that were never wired; they are not part of the current implementation.

```yaml
preprocess:
  enabled: true                  # master toggle for the preprocess step
  subdir: _preprocessed          # subfolder under input/ for converted .md + sidecars; empty string = legacy in-place layout
  keep_artifacts: false          # when false (default) keep only the final <stem>.md per source file; drop MinerU's nested subtree, images/, and .mineru.json sidecar. Set true to retain everything MinerU wrote (debugging). Pipeline-only; standalone parse-docs always keeps the full layout (D49).
  extra_args: []                 # passed through to mineru, e.g. ["--backend", "pipeline"]
  timeout_seconds: 1800          # mineru run-phase timeout (30 min)
  uv_path: uv                    # uv CLI path (uv is a core mykg dependency)
  uv_python_version: "3.12"     # interpreter pinned for the ephemeral venv
  mineru_spec: mineru[all]       # spec passed to `uv pip install -U`
  install_timeout_seconds: 1800  # install-phase timeout (30 min); first run downloads PyTorch/Ray
  extensions:                    # one flat allowlist; backend per suffix is hardcoded (HTML → markdownify; TXT → shutil.copy2; everything else → MinerU). Remove a line to skip that suffix.
    - .pdf
    - .docx
    - .doc
    - .pptx
    - .png
    - .jpg
    - .jpeg
    - .html
    - .htm
    - .txt
```

`preprocess.extensions` is exposed as `PREPROCESS_EXTENSIONS: frozenset[str]` in `config.py` (suffix matched case-insensitively). Per Invariant 7 (no hardcoded values), every knob — including the uv CLI path, the mineru install spec, and the extension allowlist — is read from YAML. The HTML and TXT backend mappings (`_HTML_BACKEND_SUFFIXES`, `_TXT_BACKEND_SUFFIXES`) are *not* in YAML by design: see D44 for the rationale (it's a property of the format, not a user preference).

**Skipped files** — any non-`.md` file whose suffix is in neither allowlist is logged at INFO and recorded in `preprocess_manifest.json["skipped_files"]` as `{path, ext}` records. The file is left untouched on disk and never reaches `ingest`. This is the right behaviour for sidecar assets next to HTML sources (e.g. `.php`, `.svg`, `.css` Wikipedia page bundles) that shouldn't be silently dropped *and* shouldn't be force-converted.

### D46 — Provenance Sidecar
MinerU writes `<stem>.mineru.json` next to each converted `.md`:

```json
{
  "source_file": "path/to/foo.pdf",
  "source_sha256": "…",
  "converter": "mineru",
  "converter_version": "3.2.1",
  "backend": "pipeline",
  "language": "en",
  "converted_at": "2026-05-29T12:34:56Z",
  "duration_seconds": 42.1,
  "output_md": "foo.md",
  "image_count": 20
}
```

Sidecar files are skipped by `ingest`'s `rglob("*.md")` (they are `.json`, not `.md`) — they exist purely for forensic provenance and downstream auditing.

**Cleanup gating:** with the default `preprocess.keep_artifacts: false` (D49), the sidecar is removed alongside the rest of the per-file MinerU subtree when `step_preprocess` rmtrees `<output_dir>/<rel_parent>/<stem>/`. The source-file SHA-256 the sidecar carried is *not* lost — `step_preprocess` now persists every non-md source's SHA in `preprocess_manifest.json["source_files"]` as the authoritative change-detection record (D49). The sidecar therefore becomes redundant when `keep_artifacts: false` and is dropped; with `true`, both records coexist.

Standalone `mykg parse-docs` always preserves the sidecar regardless of pipeline config.

### D47 — Re-entry Semantics for `preprocess`
Two re-entry behaviours, depending on whether the user forces a clean rebuild:

**Default re-entry (no `--from-step`)** — `step_preprocess` reads `preprocess_manifest.json["source_files"]` (D49), stream-hashes every non-`.md` source under `input/`, and **skips MinerU for any file whose hash matches an existing entry whose `output_md` still exists**. New and modified files are sent through `parse-docs --file-list` for conversion; sources removed since the last run have their leftover `.md` output unlinked. The next pipeline step (`ingest`) then sees only the markdown that should still be present. This is the change-detection mechanism described in D49 and is what makes resumed runs cheap.

**Forced re-entry (`extract-graph --from-step preprocess`)** — deletes `preprocess.done` + `preprocess_manifest.json` + `preprocess_filelist.txt` and clears the converted output. When `PREPROCESS_SUBDIR` is non-empty (the default), `cleanup_converted_outputs` removes the entire `input/<subdir>/` tree in a single `shutil.rmtree`; when `subdir` is empty, it falls back to the legacy per-file walk that uses the manifest to find each `.md` + sidecar + sibling `images/` to delete individually. Either way, original sources under `input/` are never touched. The step then re-runs MinerU on every non-Markdown file. Listed in `_FROM_STEP_INVALIDATE` like other steps. **No venv survives between runs** — each `parse-docs` invocation builds and tears down its own ephemeral venv (D48), so re-entry is a clean slate by construction; nothing extra needs cleaning up.

The distinction matters operationally: editing a single PDF and re-running without `--from-step` triggers re-conversion of just that PDF; passing `--from-step preprocess` re-converts everything from scratch. Choose based on whether you suspect the surviving manifest entries are correct.

### D48 — Ephemeral uv-managed venv (replaces the old optional-extras strategy)
`mineru` is **never** installed into mykg's own interpreter. It pulls in PyTorch, MLX, OpenCV, and Ray (gigabytes of footprint) and is pinned to Python 3.12, while mykg itself supports 3.11+. To keep these concerns fully decoupled, MinerU runs inside an **ephemeral virtualenv** created per `mykg parse-docs` invocation and destroyed on exit.

**One venv per `parse-docs` invocation, not per file.** The pipeline step `step_preprocess` issues exactly one `parse-docs` subprocess per run; the subprocess builds one venv and reuses it for every file it processes (the per-file loop runs inside the `with ephemeral_mineru_venv(...)` block). For a pipeline run with N changed source files, the multi-GB install cost is paid once; the per-file cost is just N MinerU model loads inside the same Python process. Standalone `parse-docs` follows the same pattern — one venv across whatever input shape the user supplied (single file, `--file`-list, `--file-list <path>`, or recursive directory).

The lifecycle lives in [src/mykg/uv_venv.py](src/mykg/uv_venv.py) as `ephemeral_mineru_venv(python_version, mineru_spec, uv_path, install_timeout)`, a context manager that:
1. Calls `tempfile.TemporaryDirectory(prefix="mykg-mineru-venv-")` — the OS-level guarantee that the tree is removed on context exit, including on exception.
2. Runs `uv venv --python <python_version> <tmp>/venv`. `uv` auto-downloads the requested interpreter if the host lacks it.
3. Runs `uv pip install --python <tmp>/venv/bin/python -U <mineru_spec>`.
4. Yields `<tmp>/venv/bin/mineru` to the caller.
5. On exit, the TemporaryDirectory deletes the venv whether the body succeeded or raised.

Failure modes (`uv` not on PATH, install failure, MinerU non-zero exit, timeouts) surface as `RuntimeError` / `ClickException` with truncated stderr. The pipeline step `step_preprocess.run_preprocess` does not duplicate any of this — it spawns `python -m mykg parse-docs` and lets the failure modes propagate through the subprocess exit code, exactly as before.

**`uv` is a core mykg dependency** (declared in `pyproject.toml`). The previous `[mykg-mineru]` extras group is removed: there is no longer any user-facing install command for MinerU. `markdownify` (HTML fallback, ~10 KB) stays in core deps so HTML always works without a venv.

Trade-off: each `parse-docs` invocation pays a multi-GB download on first use of a session. There is no cache by design — the operational simplicity of "one self-contained run, one self-cleaning venv" is judged worth more than caching, which would require lock files, cache invalidation, and a `mykg purge-mineru-cache` command. Note that the non-md change detection in D49 is the second-order optimisation that makes this trade-off bearable across re-runs: even though the venv is rebuilt, unchanged source files are skipped before MinerU is invoked at all.

### D49 — Incremental Non-md Conversion + Artifact Cleanup
`step_preprocess` performs SHA-256-based change detection on non-`.md` source files before invoking MinerU. The existing `*.md`-only content-hash mechanism in `step_ingest` (D26 Re-entry B, `--append`) covers the markdown side; D49 covers PDF/DOCX/image/HTML sources, the layer above. The two mechanisms compose: preprocess decides what MinerU needs to re-convert; ingest decides what Pass 2 needs to re-extract.

**Source-SHA manifest section.** `preprocess_manifest.json` carries a `source_files` block, keyed by path relative to `session/input/`:

```json
{
  "source_files": {
    "foo.pdf": {
      "sha256": "<hex of source bytes>",
      "output_md": "_preprocessed/foo.md",
      "size_bytes": 12345
    },
    "dir1/bar.pdf": { ... }
  }
}
```

The SHA is computed by `_sha256_path` (streaming 1 MB chunks via `hashlib.sha256.update`) so a 200 MB PDF never reaches memory all at once. Hashing is parallelised by `_hash_files_parallel` using `ctx.ingest_workers` — no new config knob; the same worker pool the ingest step already uses for `.md` hashing.

**Skip-vs-process decision.** For each discovered non-md file:

1. Compute its source SHA.
2. Look up the corresponding `prior_sources[rel]` entry from the previous manifest (if any).
3. **Skip** when: prior entry exists, prior `sha256` matches, and `(input_dir / prior_entry["output_md"]).exists()` — all three. Carry the prior manifest entry forward unchanged; do not invoke MinerU; do not touch the existing `.md`.
4. **Process** otherwise — the file is new (no prior entry), modified (sha differs), or its output was deleted (output_md missing on disk). Add to the to-process list; record a fresh manifest entry with `output_md: None` to be filled in after the backend writes.

Prior entries whose source no longer exists on disk have their `output_md` unlinked (`Path.unlink(missing_ok=True)`) — removing a PDF cleans up its converted markdown.

**Backend dispatch.** Changed MinerU files are passed to a single `parse-docs` subprocess via `--file-list <intermediate/preprocess_filelist.txt>` (see "ARG_MAX safety" below). Changed HTML files are looped through `markdownify` in-process. Both backends fill in `source_files[rel]["output_md"]` after each successful write. The manifest is then written atomically (`*.tmp` → `os.replace`).

**`preprocess.keep_artifacts` flag (default `false`).** Each MinerU invocation produces a per-file subtree under `<output_dir>/<rel_parent>/<stem>/<backend>/...` containing the canonical `.md`, an `images/` folder, a `<stem>.mineru.json` sidecar (D46), and assorted intermediate artifacts. After `_discover_canonical_md` locates the canonical `.md` (D42):

- `keep_artifacts: false` (default) — `_flatten_to_md(canonical, mineru_root, target)` moves the canonical `.md` up to `<output_dir>/<rel_parent>/<stem>.md` and `shutil.rmtree`s the per-file subtree. Only the canonical `.md` survives. `source_files[rel]["output_md"]` records the flat path.
- `keep_artifacts: true` — the full MinerU layout from D42/D43/D46 is preserved. `source_files[rel]["output_md"]` records the deep `<stem>/<backend>/<stem>.md` path.

The HTML branch (`_convert_html_files`) already writes a flat `<stem>.md`, so `keep_artifacts` is a no-op there.

**Standalone `parse-docs` is unaffected** by `keep_artifacts` — the flag is read by `step_preprocess`, not by the CLI handler. Users running `parse-docs` directly from a shell always see MinerU's full output layout. The rationale: a shell user inspecting MinerU output expects to see what MinerU produced; a pipeline run wants a tidy session folder.

**ARG_MAX safety.** Repeating `--file <rel>` once per changed source file hits the OS `ARG_MAX` ceiling (~1 MB on macOS, ~2 MB on Linux, ~32 KB on Windows) at roughly 10–17k files. `step_preprocess` therefore writes `intermediate/preprocess_filelist.txt` (one rel-path per line, blank lines ignored) and invokes `parse-docs --file-list <path>`. Argv stays O(1) in corpus size. The list file is auditable — it's the exact set of files the pipeline asked MinerU to convert, persisted under `intermediate/` for forensic review. `--file` and `--file-list` are mutually exclusive on the `parse-docs` CLI.

**Recursive directory mode in standalone `parse-docs`.** When `--input <dir>` is given with neither `--file` nor `--file-list`, `parse-docs` rglobs the directory, skips `.md` files, and loops MinerU per file inside the single venv with subfolder structure preserved at the output. The pipeline never takes this path — `step_preprocess` always passes `--file-list` — but it is useful for ad-hoc shell conversions like `mykg parse-docs --input raw_docs/ --output md_docs/`.

**Re-entry semantics** are described in D47.

### D50 — Website Fetching (`mykg fetch-web`)
Standalone command that crawls a website (full same-domain crawl) and writes raw
HTML + `fetch_manifest.json` into a folder consumable by `extract-graph`. Crawlee
for Python runs inside an ephemeral uv venv destroyed on exit (mirrors MinerU,
D48) — the crawler is never installed into mykg's interpreter. The crawler does
acquisition + provenance only; HTML→MD conversion stays in `step_preprocess`
(D44). Guardrails: robots.txt compliance, same-domain scope, `max_pages`/`max_depth`
caps, rate limiting (delay + concurrency), and SHA-based resume/dedup via the
manifest. All knobs live under the `fetch:` YAML block (Invariant 7), present in
both config files (Invariant 17). v1 records URL provenance in the manifest only —
the graph's `source_files` joins back to the URL via `fetch_manifest.json`; the
URL is not threaded into nodes/edges.

### D51 — GitHub Repo Scraping + Multi-Seed Fetch (`--url-list`)
Two extensions to `mykg fetch-web`, both opt-in by URL shape rather than by flag:

**GitHub repo cloning.** `is_github_repo_url(url)` detects
`https://github.com/<owner>/<repo>` (optionally with a trailing slash, `.git`,
or a sub-path like `/tree/main/...`); other `github.com` URLs (`/orgs/...`,
`/search`, bare `github.com`, `github.com/<owner>` with no repo) return `None`
and fall through to the existing Crawlee path unchanged. When it matches and
`fetch.github_clone_enabled` is true (default), Crawlee is skipped entirely —
no venv is built. `clone_github_repo()` shells out to `git clone --depth
<fetch.github_clone_depth>` directly in mykg's interpreter (git is a system
tool, no venv needed, mirrors the `shutil.which(uv_path)` check in
`uv_venv.py`), writing into `<output>/_repo/` (`.git/` retained for
provenance). `filter_repo_files()` then walks `_repo/` (skipping `.git/`) and
copies every `.md` + `PREPROCESS_EXTENSIONS` file into `<output>/input/`,
preserving directory structure — that `input/` folder is the
`extract-graph`-ready output. `default_output_dir()` names the per-repo
directory `fetched_web/github.com_<owner>_<repo>/` so different repos under
`github.com` never collide. `fetch_manifest.json` for this path sets
`strategy: "github_clone"`, `pages: {}`, and `stats: {files_total,
files_copied, files_skipped}`. Crawlee-only CLI options
(`--max-pages`/`--max-depth`/etc.) are accepted but ignored for a GitHub seed —
a one-line notice is echoed if any non-default value was passed.

**`--url-list <file>` multi-seed fetch.** Accepts one URL per line (`#`-comment
and blank lines ignored, mirrors the `preprocess_filelist.txt` convention from
D49) via `parse_url_list()`. Mutually exclusive with the positional `url`;
`--output` is required (no single auto-derived directory makes sense for N
seeds). Each line is routed independently through the same
GitHub-clone-vs-Crawlee branch as a single-URL invocation, and each seed gets
its **own independent caps** — no global budget across seeds. GitHub seeds land
in `<output>/github.com_<owner>_<repo>/{_repo,input}/`; Crawlee seeds land in
`<output>/<seed-domain>/` (via `seed_subdir_name()`). All Crawlee seeds across
the list share **one** ephemeral venv and **one** `_crawl_runner.py`
subprocess invocation — `_crawl_runner.py`'s `main()` branches on `"seeds" in
cfg`: the existing single-`cfg` shape is unchanged (zero behavior change for
`fetch-web <url>`), while `{"seeds": [...], "max_workers": N}` runs
`crawl(seed_cfg)` for each seed concurrently via `asyncio.Semaphore(N) +
asyncio.gather`, bounded by the new `fetch.max_workers` config key (default
`2`, Invariant 12/7). Results come back as `{"seeds": [...]}`, index-aligned
with the input seeds. The top-level `fetch_manifest.json` for `--url-list`
sets `seed_url`/`strategy` to `null` and adds `seeds: [...]` — one entry per
seed with its own `seed_url`/`strategy`/`output_subdir`/`stats`; `pages` and
`stats` at the top level are the union/sum across all seeds. Existing readers
checking `seed_url is not None` for the single-seed shape are unaffected.

**Per-seed depth inference.** New `infer_max_depth(url, configured_default)`:
a bare domain/origin (empty path after stripping one trailing `/`) gets
`fetch.max_depth`; a URL with a non-empty path (a specific page) gets
`max_depth=0` (no link-following). Applied per seed in `--url-list` and also
to the existing single-URL invocation when `--max-depth` isn't passed — an
explicit `--max-depth` always overrides inference, applied uniformly to every
seed.

**New config keys** under `fetch:` (all 6 profiles, both `mykg_config.yaml`
and `src/mykg/data/mykg_config.yaml` — Invariant 17): `github_clone_enabled`
(bool, default `true`), `github_clone_depth` (int, default `1`),
`github_clone_timeout_seconds` (int, default `1800`), `max_workers` (int,
default `2`).

### D52 — Locked-Incremental Schema Growth (`--append --grow-schema`)
A middle path between plain `--append` (cheap O(new files) but the schema is **frozen** — Pass 1 skipped, new entity/relationship kinds silently under-extracted) and a `--base-schema` rerun (schema grows but re-extracts the **whole corpus**, O(corpus)). Triggered by passing `--grow-schema` together with `--append`.

**Trigger & auto-load:** `--grow-schema` requires `--append`; it is mutually exclusive with `--from-step` (inherits append's rule) and with an explicit `--base-schema`. When set, the pipeline auto-loads the active session's `intermediate/schema.ttl` as the locked base via the existing `parse_base_schema(...)` path — no `--base-schema` needed — and fails fast with a `ClickException` if that file is missing. Sets `ctx.grow_schema = True`.

**Orchestrator:** in grow-schema mode `pass1` and `schema_validate` are removed from the append skip set (`APPEND_SKIP_STEPS`; `human_review` is still skipped unless `--review`) and are **force-run** so stale outputs don't make `_is_done` skip the locked re-induction.

**Locked Pass 1, changed files only:** Pass 1 runs in locked mode (existing concepts/properties cannot be renamed/removed/re-parented; the LLM may **add** new concepts/properties) but reads **only the changed files** (`ctx.append_new_files ∩ manifest`), keeping Pass 1 cost ~O(changed files).

**Schema-delta surgical back-fill:** after locked Pass 1 writes the new schema, the delta vs. the locked base is computed (reusing the `schema_history` set-diff) → `added_concepts`, `added_properties`. `compute_backfill_chunks(...)` in `src/mykg/steps/grow_schema_backfill.py` selects which **old** chunks to re-extract, using `chunk_node_index.json` (a stable ID's prefix is its concept type, D19, so old chunks' types are known without re-reading text):
- **New property** `p (domain D → range R)` → old chunks containing ≥1 node of type `D` **or** `R` (domain/range co-occurrence; mirrors `merge_graphs` surgical mode, D38).
- **New concept** `C` → **is-a hierarchy signal only**: old chunks containing nodes of `C`'s parent or sibling type(s); a **root** concept with no relatives contributes **zero** targeted chunks.
- **Cap:** ranked per type by co-occurrence count, top-K kept, bounded by `append.grow_schema_backfill_top_k_chunks_per_type` (default 10; `0` disables back-fill).

These old-chunk targets are fed to the existing surgical path `run_pass2(reextract_chunks=, prior_extractions=, prior_chunk_index=)` (D37) — only the named chunks are re-extracted, new edges merged back into existing shards. Changed files extract via the normal path. **When the delta is empty, the run collapses to plain `--append`** (changed files only, no back-fill, no full re-extract). It is a bounded heuristic (Invariant 16): false negatives are backstopped by the orphan pass + future runs; false positives cost one no-op LLM call, capped by top-K. The graph stays consistent (Invariant 14) because all downstream steps (assemble/orphan/validate) re-run over the whole corpus.

**Config:** `append.grow_schema_backfill_top_k_chunks_per_type` (int, default 10; `0` = disable) in all 6 profiles of both `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml` (Invariant 17), exposed as `config.APPEND_GROW_SCHEMA_BACKFILL_TOP_K_CHUNKS_PER_TYPE`.

**Relation to D26/D27:** lifts the "schema cannot grow via append" limitation noted around Re-entry B (D26) and provides a cheaper alternative to the full `--base-schema` re-extraction (D27) when only some new schema elements are introduced.

### D53 — Pass 2 Prep Modes + concat real-file-keyed shards (virtual names removed at the shard layer only)

`pass2.prep_mode` selects how source files are prepared for Pass 2 LLM calls. Three modes, dispatched in `src/mykg/steps/step_pass2.py` `_run`:

- **`per_file`** — one LLM call per real file via `run_pass2(...)`. Shards keyed by real filename.
- **`batch_chunks`** (shipped default) — every file is chunked, chunks are pooled and packed into token-bounded batches (`build_pass2_batches`), each batch is one LLM call via `run_pass2_batched(...)`. Shards keyed by real `source_file`; `batch_per_file: true` forbids cross-file batches.
- **`concat`** — bin-packs **whole files** (grouped by directory, prefix-sorted, never split at the packing stage) into virtual concatenations up to `pass2.concat_batch_token_target` via `build_concat_batches`/`make_virtual_files` (`src/mykg/pass2_concat.py`), then runs them through `run_pass2(...)`, which re-chunks each concatenation at `window_tokens` and makes **one LLM call per window**. Files are concatenated with `--- SOURCE: <path> ---` delimiters so the LLM sees related files together (cross-document reasoning — concat's purpose). This call pattern is **identical to the original concat**.

**The concat fix — shard keying only.** The original concat keyed its shards (and `raw_extractions.json`/`chunk_node_index.json`) by the **virtual** batch name (`concat_batch_NNNN.md`). That broke `--append`: `build_concat_batches` restarts its counter at `0000` each run, so the new run's virtual names collided with the prior run's shard names; `run_pass2(skip_files=skip)` then dropped every rebatched batch and newly-added files were silently not extracted (a live append+PDF run produced **zero** PDF nodes). Virtual names also accumulated orphan shards and broke the surgical schema-gap path.

The current design keeps the original execution path **unchanged** and changes **only** how the result is persisted: a concat-specific `on_file_done` **fans the virtual-batch result out to one real-file-keyed shard per member file** (member list from `concat_map[vname]["files"]`). So shards, `raw_extractions.json`, and `chunk_node_index.json` are keyed by **real filenames**. The virtual-keyed `new_raw`/`new_chunk` returned by `run_pass2` are NOT merged for concat (the fan-out already wrote real keys). `concat_map` is rebuilt in-memory each run and **not persisted** (no `pass2_concat_map.json`, no `pass2_batch_map.json` for concat). Consequences:
- **Append works**: `skip = set(existing_raw.keys())` holds real names → changed-file filter is correct → only new/changed files re-extract.
- **No orphan shards**: every shard maps to a real file in the manifest.
- **Surgical schema-gap + grow-schema back-fill (D37/D52) work natively** — `existing_raw` is real-keyed, so `fname in existing_raw` matches; the `concat_map`-based virtual-content resolution is removed.

**Over-attribution (shared with `batch_chunks`):** a multi-file virtual batch's single LLM result is fanned out to **every** member file's shard. The assembler's stable-ID node dedup (D10/D19) and edge-hash dedup (D22) collapse the duplication with no confidence inflation (mean/max over identical copies = same value); `source_files` lists all batch members (same imprecision `batch_chunks` already had — strictly better than concat's former non-existent virtual filename).

**Engine isolation:** `run_pass2_batched` and `run_pass2` are unchanged. Concat reuses the original `run_pass2` + `build_concat_batches`/`make_virtual_files`; the only new code is the fan-out `on_file_done` in `step_pass2`. `per_file` and `batch_chunks` are untouched.

**Legacy-session migration:** on a concat run, if any `concat_batch_*.json` shard from the old virtual-keyed layout is detected in `raw_extractions_shards/`, `step_pass2` clears the shard dirs + `raw_extractions.json`/`chunk_node_index.json`/`pass2_concat_map.json` once, forcing a clean real-keyed rebuild.

**Updates D34/D38:** "virtual batch" no longer appears at the shard/resumability layer (it remains an in-memory grouping for the LLM prompt only); all three prep modes produce real-file-keyed shards (D38 `prep_mode` compatibility still holds).

### D54 — OWL Ontology Support in Base Schema Parser
`parse_base_schema()` accepts both RDFS and OWL vocabulary in user-supplied `--base-schema` TTL files. This lets users supply formal OWL ontologies (e.g. exported from Protégé) without manual conversion to RDFS.

**Supported OWL constructs** (vocabulary declarations only):

| OWL Construct | myKG mapping |
|---|---|
| `owl:Class` | → `locked_classes` (same as `rdfs:Class`) |
| `owl:ObjectProperty` | → `locked_properties` (same as `rdf:Property` with class range) |
| `owl:DatatypeProperty` | → domain class `attributes` list (same as `rdf:Property` with `rdfs:Literal` range) |

`rdfs:subClassOf`, `rdfs:domain`, and `rdfs:range` are shared between RDFS and OWL — no additional handling needed.

**Not supported** (advanced OWL — reasoning constructs that don't map to myKG's flat concept+property model):
`owl:Restriction`, `owl:equivalentClass`, `owl:disjointWith`, `owl:inverseOf`, `owl:TransitiveProperty`, `owl:SymmetricProperty`, `owl:FunctionalProperty`, `owl:unionOf`, `owl:intersectionOf`, `owl:sameAs`, `owl:differentFrom`, `owl:allValuesFrom`, `owl:someValuesFrom`. Users needing reasoning should load `knowledge_graph.ttl` into a SPARQL endpoint with a reasoner (HermiT, Pellet).

**Output normalization:** myKG's own output (`exporter.py`, `knowledge_graph.ttl`) always emits RDFS (`rdfs:Class`, `rdf:Property`) regardless of input vocabulary. OWL→RDFS normalization happens at parse time in `base_schema.py`.

**Deduplication:** if the same URI is declared as both `rdfs:Class` and `owl:Class`, the first-seen entry wins; no duplicates are created. Same for properties declared as both `rdf:Property` and `owl:ObjectProperty`/`owl:DatatypeProperty`.

**For OWL properties**, the type declaration itself is definitive: `owl:ObjectProperty` is always an object property, `owl:DatatypeProperty` is always a datatype property — no range-based heuristic needed. The existing `rdf:Property` heuristic (check `range == rdfs:Literal`) is unchanged.

1. The LLM returns `nodes[]` + `edges[]`. Edges are direct (from/to/type/attributes), not wrapped in nodes.
2. `knowledge_graph.ttl` contains RDFS structural triples and standard SKOS annotation properties (`skos:altLabel` for aliases) — no edge metadata, no blank nodes, no reification, no RDF-star.
3. Edge metadata lives exclusively in `intermediate/edge_metadata.json`.
4. `edges.jsonl` is always regenerated from the sidecar — never edited directly.
5. The abstract `Relationship` class does not exist — no relationship classes in `concepts[]`.
6. Missing attributes are never dropped — always `{ "value": null, "confidence": 0.0 }`.
7. No hardcoded parameters inside code — all values (timeouts, token limits, model names, namespace URIs, overlap sizes, confidence defaults, etc.) are loaded at startup from `pipeline_config.yaml` by `src/mykg/config.py`. The YAML file is the single source of truth; `config.py` exposes named constants; adapters and pipeline steps read from those constants, never from inline literals.
8. All data models use Pydantic (`BaseModel`) — not Python `dataclasses`. Pydantic is used for all structured data passed between pipeline stages: schema objects, nodes, edges, extraction results, and intermediate representations. This gives free JSON serialization/deserialization, field validation, and type coercion at pipeline boundaries.
9. Each run is fully isolated — inputs, intermediate state, outputs, and logs are co-located and self-contained. A run can always be resumed from its own snapshot without depending on external state.
10. Long-running extraction is resumable at the finest meaningful granularity. Work already completed is never repeated on restart; only the remaining work is resubmitted.
11. Log output is bounded and durable. Logs are scoped to their run, rotate automatically when large, and are never silently discarded.
12. All data-processing stages that operate over independent items (files, chunks, candidates) must be parallelised using `ThreadPoolExecutor`. Serial loops over collections are a bug. Worker count is always configurable via `pipeline_config.yaml` — never hardcoded. This applies to ingest, Pass 1 batch dispatch, Pass 2 file extraction, orphan scoring, and any future bulk step.
13. The pipeline must respect the active LLM provider's context window and rate limits. `window_tokens + max_tokens` must never exceed the model's context window. Worker counts (`pass2.max_workers`, `orphan_pass.max_workers`) must be set conservatively enough to avoid 429 rate-limit errors from the provider. When a 429 is received, it is a misconfiguration signal — reduce `max_workers` in `pipeline_config.yaml`, not a transient error to silently retry.
14. All pipeline outputs must be validated before writing to disk, and all output formats must be kept in sync. In `step_validate_graph`, edges are filtered to `valid_edge_metadata` — only edges whose `type` is declared in `schema["properties"]` — before any output file is written. The TTL is then sanitized (`sanitize_abox_ttl`) and validated (`validate_knowledge_graph_ttl`) before `knowledge_graph.ttl`, `edges.jsonl`, and NetworkX files are written. `intermediate/edge_metadata.json` remains the unfiltered source of truth; the filter is applied only at export time. This ensures all output formats (TTL, JSONL, NetworkX) are always valid and consistent with each other.
15. In surgical re-extraction mode, the full `run_pass2` output is merged back into session shards without post-filtering. Both net-new nodes and new edges produced under the richer merged schema survive and flow into the deduplication step as normal.
16. Every new process or strategy must be evaluated for runtime complexity before implementation. Explicitly reason about how it performs when the input is large — thousands of files, tens of thousands of nodes, hundreds of schema-gap restarts, or deep iteration loops. Prefer designs whose cost grows sub-linearly with corpus size (e.g. chunk-targeted over file-targeted, surgical over full re-extraction). Any strategy whose cost is O(files × restarts) or worse must be explicitly justified, bounded by a configurable cap, and documented with its worst-case scaling behaviour.

17. `mykg_config.yaml` lives in two places by design: the repo root (runtime — discovered by `config.py` walking upward from cwd) and `src/mykg/data/mykg_config.yaml` (packaging — shipped inside the wheel, copied into a user's cwd by `mykg init`). The two are structurally a single file with two distribution paths; they must stay in sync **when adding or removing keys**. When introducing any new key under `preprocess:`, `pipeline:`, or any other YAML block, edit both files. The template under `src/mykg/data/` is what new users of `pip install mykg` get — drift means `mykg init` lays down a stale config for them. Per-developer values (e.g. the active `model:` line) may differ between the two without breaking this invariant; *structural* drift (a key present in one and absent in the other) is the failure mode this guards against.

Additional config keys governed by Invariant 7 (all values from `pipeline_config.yaml`):
- `error_gate.enabled` — bool; circuit breaker that pauses all LLM workers when consecutive API errors exceed threshold
- `error_gate.threshold` — int; number of consecutive errors before the gate trips
- `logging.max_bytes` — log rotation: max bytes per log file before rotation (RotatingFileHandler)
- `logging.backup_count` — log rotation: number of rotated files to keep
- `logging.capture_prompts` — bool; when true, full LLM prompts are written to `intermediate/llm_calls/` at DEBUG level
- `normalize_names.max_names_per_type` — cap on names per type sent to normalization LLM
- `ingest.max_workers` — parallel workers for file reading/hashing/chunking

18. Any agent, skill, or tool that answers user questions using LLM-generated text about the knowledge graph, input documents, or wiki notes must ground every claim in session artifacts. Training-data knowledge must never be silently mixed into answers. Concretely: (a) every fact stated must be traceable to a specific session artifact — a node ID, edge record, vault note, source file, or MCP tool response; (b) the LLM must not fill gaps in the graph with training knowledge, judge the correctness of graph data using training knowledge, or list "missing relationships" sourced from training knowledge; (c) if the user explicitly asks a question that requires outside knowledge (e.g. "is this graph accurate?"), the answer must separate graph-grounded facts from training-data claims in two clearly labelled sections — `**From the graph (session <name>):**` first, then `**From training data (not in the graph — may be inaccurate):**` with a caveat — and the training-data section must be omitted entirely when the user did not ask for it. This applies to the `/mykg query` skill path, the `walkthrough` narrative, the Obsidian vault generator, and any future consumer that presents graph data to users via LLM-generated prose.

19. All file I/O must prefer streaming over whole-file reads. When reading line-oriented data (JSONL, log files, manifests), iterate the file handle (`with open(path) as f: for line in f`) instead of `.read_text().splitlines()`. When writing large outputs, prefer incremental writes over building a full string in memory. Whole-file reads are acceptable only for small, bounded files (config YAML, schema JSON, single-record metadata). The default assumption is that any data file may grow large — design I/O accordingly.

20. All code must be platform-agnostic across macOS, Linux, and Windows. Concretely: (a) **File I/O encoding** — every `open()`, `.read_text()`, and `.write_text()` call must pass `encoding="utf-8"` explicitly; never rely on the platform default (cp1252 on Windows cannot encode μ, em-dash, or any non-Latin-1 character); (b) **JSON serialization** — use `json.dumps(obj, ensure_ascii=False)` when writing JSON that may contain non-ASCII content; `ensure_ascii=True` (the Python default) silently replaces characters with `\uXXXX` escapes, inflating token estimates and degrading LLM input quality; (c) **Console output** — any `StreamHandler` attached to stdout/stderr must be reconfigured with `encoding="utf-8", errors="backslashreplace"` on Windows (`sys.platform == "win32"` guard + `hasattr(_stream, "reconfigure")` guard for test-safety); (d) **Path handling** — always use `pathlib.Path` for filesystem operations; never concatenate path strings with `/` or `\\`; (e) **Platform-specific branches** — use `sys.platform == "win32"` when a Windows-only workaround is genuinely required; document why. New code that introduces a bare `open(path)`, `open(path, "w")`, `path.read_text()`, or `path.write_text(content)` without `encoding="utf-8"` is a bug.

<!-- BEGIN mykg-section (managed by `mykg init`; safe to edit) -->
## mykg knowledge graph

This project uses [mykg](https://github.com/SenolIsci/mykg) — a knowledge
graph extracted from source documents in this repo. The agent-mode skill is
installed; query it via `/mykg`.

### Find the latest session

Don't guess the session name. Run one of these from the project root:

```bash
# Path to latest session root (use this in subsequent commands):
ls -td mykg_sessions/*/ 2>/dev/null | head -1

# One-line wiki status (node count + session path):
ls -td mykg_sessions/*/output/nodes.jsonl 2>/dev/null | head -1 \
  | xargs -I{} sh -c 'echo "mykg wiki: $(wc -l < {}) nodes in $(dirname $(dirname {}))"'
```

If the first command prints nothing, there is no graph yet — tell the user to
run `/mykg extract <dir>` first instead of fabricating an answer.

### What's in a session

Under `<latest-session>/output/`:

- `nodes.jsonl` — entities with confidence-scored attributes
- `edges.jsonl` — typed relationships
- `knowledge_graph.ttl` — RDFS/OWL view (SPARQL-queryable)
- `obsidian_vault/` — markdown notes with wikilinks (when generated)

### Read before answering

Before answering any domain question about this corpus, read the latest
session's `nodes.jsonl` / `edges.jsonl` (or browse `obsidian_vault/`). The
graph is grounded in the source documents — your training data is not.
**Do not fill gaps with training knowledge** (Invariant 18). Every claim
must cite a session artifact. If training data is needed, label it
explicitly in a separate section.

### Extending the graph

To add new source documents: drop them under the input folder and run
`/mykg append the new notes in <dir>` (or, from a shell,
`mykg extract-graph <dir> --append --session <name> --obsidian-vault`). The
`--obsidian-vault` flag regenerates the markdown vault alongside the JSONL /
TTL outputs so the Obsidian view stays in sync.

### Do not edit outputs directly

`nodes.jsonl` / `edges.jsonl` are regenerated from
`intermediate/edge_metadata.json` on every run. To correct the graph, edit the
source markdown or `intermediate/schema.json` and re-run the affected pipeline
step (`/mykg from-step <step> on the last session`).
<!-- END mykg-section -->
