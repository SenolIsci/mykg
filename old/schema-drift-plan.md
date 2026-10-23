# STATUS (updated after implementation and review fixes)

**All 5 units are implemented and open as stacked PRs; review fixes are applied. Merge in order #83, #84, #85, #86, #87.**

| # | Unit | PR | Branch | Status |
|---|---|---|---|---|
| 1 | Core analyzer, plan, apply | https://github.com/SenolIsci/mykg/pull/83 (base `main`) | `feat/schema-drift-1-core` | done + review fixes |
| 2 | CLI `detect-schema-drift`, `prune-schema` | https://github.com/SenolIsci/mykg/pull/84 | `feat/schema-drift-2-cli` | done + review fixes |
| 3 | Walkthrough "Schema Health" | https://github.com/SenolIsci/mykg/pull/85 | `feat/schema-drift-3-walkthrough` | done + review fixes |
| 4 | MCP tool `mykg_schema_drift` | https://github.com/SenolIsci/mykg/pull/86 | `feat/schema-drift-4-mcp` | done + review fixes |
| 5 | Docs + skill | https://github.com/SenolIsci/mykg/pull/87 | `feat/schema-drift-5-docs` | done + review fixes |

Last full run (`pytest -q -k "not live"` on the #87 branch): 1731 passed. `test_anthropic_live_accepts_temperature` needs network and fails without it.

**Where the implementation differs from the plan text below (the plan body is the original design; this list wins):**
- `apply_prune(plan, intermediate_dir, report)`: `report` is required; the plan is always validated against it (review 83.1/83.2). New public helper `recompute_plan(plan, report)` recomputes keep/totals/reasons and drops duplicates; stored `keep`/`totals` are ignored.
- The plan fingerprint covers schema + per-type node/edge counts + sorted locked class/property names.
- `apply_prune` itself regenerates `flattened_schema.json` (only if the file already exists) and writes `schema.ttl` atomically; the CLI no longer regenerates it. Write order: validate in memory, backup, `schema.ttl`, `flattened_schema.json`, then `schema.json` + history delta last (crash-window documented; re-running is idempotent; `approve-schema` repairs `schema.ttl`).
- An empty plan is a no-op: "Nothing to prune.", no backup, no history entry.
- Malformed JSONL rows, non-object attributes, non-string types, malformed schema entries and lock files raise `SchemaDriftError` (surfaced as ClickException in the CLI; degrade in walkthrough/MCP).
- Refresh = `run_validate_graph` called directly with an adapter-less `PipelineContext` (spike succeeded; no fallback). Refresh message lists outputs per config toggles; exports enabled only by a CLI flag on an earlier run are not refreshed.
- Undo text (printed by the CLI): copy `schema.pre_prune.json` over `schema.json`; `mykg approve-schema --session S`; delete `intermediate/flattened_schema.json`; `mykg extract-graph <dir> --session S --from-step validate_graph`; re-run `mykg detect-schema-drift --session S`. flattened_schema.json is NOT regenerated automatically on undo; never use `--from-step schema_flatten` (deletes pass2 outputs).
- Session names in suggested commands are shell-quoted (`shlex.quote`) in CLI, walkthrough and MCP.
- MCP tool: read-only, computed from the in-memory graph, adds an "Always-null attributes (info only)" section, and the registered MCP tool count is 16 (docs corrected from 13/14/15).
- Output wording uses "unused" (not "orphaned").
- Locks come only from a real `--base-schema` on a fresh run (`--append-with-grow-schema` never writes `base_schema_parsed.json`); a missing lock file means no locks and the commands print a notice. The unit-5 worker's "grow-schema locks everything" claim was checked and refuted.
- CLAUDE.md D62 and the D16/D36 edits exist only in the local, gitignored CLAUDE.md (not in any PR).

**Declined review items:** cross-process locking (CLI refuses while a step is `running`), `asyncio.to_thread` for the MCP scan (siblings scan synchronously too), regenerating `knowledge_graph.ttl` inside core (the CLI refresh does it).

**Known gaps / not done:** `schema.pre_prune.json` is overwritten on each prune (single backup); lock-file loading is duplicated between `cli.py` and `walkthrough.py`; POSIX-style quoting only; walkthrough staleness covers schema + per-type counts + locks, not attribute values; most e2e checks ran as CLI/unit tests on synthetic sessions, not hand-run CLI sessions, and no real grow-schema session was run through the CLI.

---

# Plan: Schema Drift Detection (`mykg detect-schema-drift`) + Pruning (`mykg prune-schema`)

## Contents
1. Summary and decisions
2. CLI commands and file-write contract
3. End-to-end workflow
4. Drift model (what is detected, how entries are classified)
5. Preview and plan file (editing and approval)
6. Pruning, instances, and continuing the session
7. Mapping to the article's 4-tier policy
8. Approach A vs B (decision record)
9. Technical design
10. Codebase findings
11. Work units
12. E2E test recipe
13. Worker instructions

---

## 1. Summary and decisions

**What gets built.** A way to notice that the induced schema (`schema.json`: concepts and properties) has drifted away from the actual graph, and a safe way to remove the dead parts. *Drift* = a declared concept or property with zero instances in the current graph (e.g. `Project` and `Service` still declared after `projects.md` was deleted). Source: the user's article "Staleness, Drift, and the Schema Nobody Cares About" (read via a mirror; the policy spectrum and diagnostic output are images I downloaded and read). Article diagnostic, our target output format:
```
declared concepts: Organization, Person, Team, Project, Service
orphaned concepts: Project (0 instances), Service (0 instances)
declared properties: 11 (8 unreferenced by active edges)
```
Our command prints the same block but labels them **"unused"** instead of "orphaned", because "orphan" already means a node with no edges in this codebase (D30, the orphan pass). Docs and the walkthrough use "unused" consistently.

**Decisions already made with you**
- Detection and pruning are **separate**, both **first-class commands** (not `extract-graph` flags, not a pipeline step). They share one analysis engine.
- **Approach A:** prune the schema, then refresh outputs. No re-extraction (Section 8).
- Pruning is **deterministic and LLM-free**; it runs only on an explicit operator command.
- Preview option is called `--preview`; there is no `--json` flag.
- Tier 4 of the article (automatic grace-period decay) is **not implemented**; see Section 7.

---

## 2. CLI commands and file-write contract

Both are session commands like `approve-schema` / `walkthrough` / `query`: `--session S` (defaults to the latest session). Neither loads an LLM adapter, so no API key or provider config is needed. `extract-graph` gets **no** new flags.

| Command | Purpose |
|---|---|
| `mykg detect-schema-drift --session S` | Read-only drift report; records `intermediate/schema_drift.json`. |
| `mykg prune-schema --session S --preview` | Show the removal plan; writes the plan file; schema untouched. |
| `mykg prune-schema --session S` | One-shot: compute the plan fresh, apply every `prunable` entry, refresh outputs. |
| `mykg prune-schema --session S --plan <file>` | Apply exactly the removals in a reviewed/edited plan file (default path `intermediate/schema_prune_plan.json`), after re-validation. `--plan` and `--preview` are mutually exclusive. |

Both commands need an existing `schema.json` (detection also `output/nodes.jsonl`) and raise a `ClickException` otherwise. They also refuse to run while any step in `pipeline_state.json` has status `running` (an extraction is in progress), since `write_schema` is not atomic. Machine-readable output needs no flag: scripts and CI read `schema_drift.json` and `schema_prune_plan.json`.

**Why commands rather than `extract-graph` flags:** `extract-graph` is the LLM-pipeline command; it loads a provider adapter and carries many interdependent flags with an existing mutual-exclusion matrix, none of which applies here. Separate commands need no API key, add no rows to that matrix, make `--session`-only semantics natural, and match the existing session commands.

**File-write contract**
| Operation | Writes |
|---|---|
| `detect-schema-drift` | `schema_drift.json` only |
| `prune-schema --preview` | `schema_drift.json`, `schema_prune_plan.json` only |
| `prune-schema` (apply) | the above, plus `schema.json`, `schema.ttl`, `schema.pre_prune.json`, a new `schema_history/<seq>_schema_prune.json`, `flattened_schema.json`, and the refreshed outputs (Section 6). `nodes.jsonl`/`edges.jsonl` content is never edited. |

Existing commands referenced, not changed: `mykg approve-schema` (manual path) and the `validate_graph` step (re-run internally to refresh outputs; same effect as `extract-graph --from-step validate_graph`).

---

## 3. End-to-end workflow
1. Run an extraction as usual (`extract-graph`, `--append`, `--sync`, ...).
2. **Detect:** `mykg detect-schema-drift --session S`. Streams `output/nodes.jsonl` / `edges.jsonl` once (no LLM), compares against `intermediate/schema.json`, prints the diagnostic block above, classifies each zero-instance entry (`prunable`, `structural`, `locked`), and records the result in `schema_drift.json` (the full report: counts, classification, reverse drift, plus a timestamp and the same fingerprint the plan file uses, so later consumers can tell whether it is stale; overwritten on each run). Exit code 0; advisory.
3. **Preview:** `mykg prune-schema --session S --preview` prints the exact removal plan and writes `schema_prune_plan.json`.
4. **Review/edit** the plan if wanted (Section 5).
5. **Prune:** `mykg prune-schema --session S` (or `--plan <file>`). Backs up `schema.json` to `schema.pre_prune.json`, removes the entries, writes a timestamped `schema_prune` history record (`concepts_removed` / `properties_removed` plus reasons), regenerates `schema.ttl` and `flattened_schema.json`, then re-runs `validate_graph` so `knowledge_graph.ttl`, exports and walkthrough match the pruned schema. Nodes and edges are never edited.
6. **Consumers:** the walkthrough shows a "Schema Health" section when `schema_drift.json` exists (with a hint to run `mykg prune-schema --preview`); an MCP tool `mykg_schema_drift` computes the same report live.

Typical order over a session's life: **sync first (instances reconcile), then detect, then prune (schema reconciles).**

---

## 4. Drift model

### 4.1 What "drift" means here
The schema (TBox) is an append-only vocabulary: Pass 1 and grow-schema add concepts and properties, and nothing ever removes them. The graph (ABox: `nodes.jsonl`, `edges.jsonl`) reconciles with the documents on `--append --sync`. After documents are deleted or edited, the vocabulary can therefore declare things the graph no longer uses. Drift is that gap. This plan detects **forward drift** (declared but unused) and also reports **reverse drift** (used but not declared).

### 4.2 What is measured (one streaming pass, no LLM)
Inputs: `intermediate/schema.json`, `output/nodes.jsonl`, `output/edges.jsonl`, and (if present) `intermediate/base_schema_parsed.json` for locks.
| Measure | Definition |
|---|---|
| Concept `instance_count` | number of nodes whose `type` equals the concept name |
| Concept `subtree_count` | own `instance_count` plus that of every descendant via the `parent` (is-a) chain; guarded against parent cycles |
| Property `edge_count` | number of edges whose `type` equals the property name (both `llm_extraction` and `orphan_inferred` edges count) |
| Unused concept / property | `subtree_count == 0` / `edge_count == 0` |
| Reverse drift (info) | node or edge `type` values present in the data but not declared in the schema |
| Always-null attribute (info) | declared attribute where every instance has `{"value": null}`; reported, never pruned (attributes are not pruned in this plan) |

### 4.3 Classification of each unused entry
Evaluated in this order; the first matching row wins.
| Class | Rule | Prune? |
|---|---|---|
| `locked` | in `base_schema_parsed.json` (user-supplied `--base-schema`, D27) | never |
| `structural` | has an instantiated descendant (zero direct instances but `subtree_count > 0`), or is the domain/range of a property that survives (has edges, or is locked), or has a surviving child | no, kept |
| `prunable` | none of the above: zero subtree instances, unlocked, every descendant also `prunable`, no surviving property depends on it | yes |

Properties use the same order with simpler rules: `locked` (from the base schema) -> `prunable` if `edge_count == 0`; a property with at least one edge is simply "used". A property is also removed when its domain or range concept is removed (cascade), but only if it has zero edges and is not locked; otherwise that concept is `structural` and stays.

**No re-parenting.** A concept is prunable only when its whole subtree is prunable, so a surviving child (locked or used) keeps its zero-instance parent as `structural`. This never changes a locked class's parent (forbidden by D27) and removes re-parenting code.

### 4.4 Worked example (the article's session)
Schema: concepts Organization, Person, Team, Project, Service (all roots); 11 properties. After `projects.md` is deleted and synced, the graph has Organization, Person, Team nodes and edges using 3 properties.
- `Project`, `Service`: `subtree_count = 0`, unlocked, no surviving property needs them (their 6 specialized properties, `owns_project`, `leads_project`, `contributes_to`, `depends_on`, `partners_with`, `delivers_service`, have zero edges) -> `prunable`, with those properties removed by cascade.
- 8 of the 11 properties are unused; the cascade covers those tied to the two concepts, and any other zero-edge property is `prunable` in its own right.
- Result: 5 concepts / 11 properties -> 3 / 3, matching the article's manual result.
Variants: if `Service` were declared with `parent: Project` and a `Service` child were locked, `Project` would stay as `structural`; if `delivers_service` had one edge, `Service` (its range) would stay as `structural`.

### 4.5 Interpreting the result (the policy question the article poses)
An unused entry is either *stale* (its documents are gone) or *temporarily unpopulated* (documents coming). The tool cannot know which, so it never decides silently: detection reports, the preview shows the plan, you approve. `locked` and `structural` are the machine-checkable reasons to keep; everything else is a human call.

---

## 5. Preview and plan file

**What the preview is for.** Pruning is the one step that rewrites the schema (a backup is kept, but there is no restore command; undo means copying `schema.pre_prune.json` back by hand), and the article's open question is "stale or just temporarily unpopulated?" Detection says *what is at zero*; the preview says *exactly what pruning would do about it*, before anything is written. It shows:
- **Will be removed** with reasons (e.g. `Project`: 0 instances, 0 in subtree; cascaded properties `leads_project`, `owns_project`, ...: 0 edges, domain removed).
- **Kept although unused** with why (`locked`, `structural`).
- **Side effects:** totals ("5 concepts / 11 properties -> 3 / 3").
- **Warnings:** a removed type is silently dropped from future extraction if the schema is frozen, so use `--append-with-grow-schema` when its documents return; never re-induce the schema on every sync.
- **Files that would change** (the apply row of the contract above).

What you do with it: (1) decide per entry (a type awaiting tomorrow's documents: do not prune yet); (2) edit the plan or hand-edit `schema.json` instead; (3) use it as a no-side-effect gate in scripts, CI or PR review ("would prune N entries"). It is repeatable: same inputs give the same plan.

**The plan file is editable; approval is an explicit human action, never automatic.** Nothing reads the plan by itself; only running `mykg prune-schema` applies one.

`intermediate/schema_prune_plan.json`:
```
{ "schema_fingerprint": "<sha256 of schema.json + instance counts>",
  "created_at": "...",
  "remove": [ {"kind": "concept", "name": "Project", "reason": "0 instances, 0 in subtree"},
              {"kind": "property", "name": "leads_project", "reason": "0 edges; domain removed"} ],
  "keep":   [ {"kind": "concept", "name": "Team", "reason": "structural: has instantiated child"} ],
  "totals": {"before": {"concepts": 5, "properties": 11}, "after": {"concepts": 3, "properties": 3}} }
```
- **Editing:** delete entries from `remove` (or move them to `keep`) to veto a removal. `keep` and `totals` are informational and recomputed.
- **Applying:** `mykg prune-schema --session S --plan intermediate/schema_prune_plan.json`. Without `--plan`, the one-shot form recomputes the plan and applies all `prunable` entries (preview followed by approving everything).
- **Guard at apply time (a safety check, not an approval):** the command re-runs detection and checks every entry. An entry that is `locked`, `structural`, has gained instances since the plan, or is not in the schema aborts the whole apply, naming the entry, with nothing changed. Edits can therefore only remove entries from the plan, never force pruning of something with instances or a lock.
- **Staleness:** `schema_fingerprint` must match the current `schema.json` and instance counts; if documents were synced or the schema edited after the preview, the plan is refused as stale and you re-run `--preview`.
- **Consistency:** removing a zero-edge property on its own is always allowed (so vetoing a concept while leaving its cascaded zero-edge properties in `remove` is fine). The one refused combination is removing a concept while *keeping* a property whose domain/range is that concept (it would dangle and fail schema validation); the apply aborts naming the pair.
- **Fully manual alternative (existing):** edit `schema.json` by hand, run `mykg approve-schema --session S` (regenerates `schema.ttl`, writes the review flag; does not refresh `knowledge_graph.ttl`), then `extract-graph --session S --from-step validate_graph`.

---

## 6. Pruning, instances, and continuing the session

**Pruning never touches instances.** There is no instance-level pruning logic. It is safe by construction: only entries with zero instances are `prunable`, so no node or edge can end up pointing at a removed type. A concept with direct instances is simply in use, one whose only instances are in descendants is `structural`, and a property with at least one edge is in use; all of these are kept. To remove *instances*, change the sources and run `mykg extract-graph <dir> --session S --append --sync` (D58), which removes that document's nodes/edges by recompute.

**What apply changes in the session (and nothing else)**
| File | Change |
|---|---|
| `intermediate/schema.json` | pruned entries removed (backup: `schema.pre_prune.json`) |
| `intermediate/schema.ttl` | regenerated from `schema.json` |
| `intermediate/schema_history/<seq>_schema_prune.json` | timestamped delta with `concepts_removed` / `properties_removed` and reasons |
| `intermediate/flattened_schema.json` | regenerated by calling the existing flatten function directly (no LLM) |
| `output/knowledge_graph.ttl` (TBox), other schema-dependent exports, `knowledge_graph_validation.json`, `walkthrough.md` | regenerated by re-running only `validate_graph`, no LLM |
| `nodes.jsonl`, `edges.jsonl` content, `raw_extractions*`, shards, `chunk_node_index.json`, `edge_metadata.json`, `pipeline_state.json` results | untouched: no step is marked invalid, no extraction repeated |

Implementation note: the refresh must not use `_delete_from_step("schema_flatten")`, which would also delete `pass2` and everything downstream; regenerate `flattened_schema.json` directly, then run `validate_graph`.

**Continuing the same session afterwards.** The pruned `schema.json` is simply the session's current schema, so every mode keeps working:
| Next command | What happens with the pruned schema |
|---|---|
| `--append` (new files) | Pass 1 skipped, schema frozen. New documents are extracted against the pruned vocabulary; if one is about a pruned type (`Project` returns), its entities get no concept and are **silently dropped or mis-typed** (the article's "frozen schema fallacy"; the preview prints this warning). |
| `--append-with-grow-schema` (recommended if documents about pruned types may return) | Loads the pruned `schema.ttl` as the locked base, runs locked Pass 1 on changed files only, can **re-add** `Project`/`Service`, and back-fills affected old chunks (D52). History shows both events. |
| `--append --sync` (edit/delete documents) | Instances reconcile (D58); schema untouched. Run detect again afterwards, then prune again if wanted. |
| `--from-step pass2` / `--pass2-kg-extraction-only` | Re-extracts against the pruned schema (now the schema of record). |
| `--from-step pass1` / a fresh full run | Re-induces the schema from scratch; the prune is superseded, as expected. |
| Orphan schema-gap restart (`orphan_connect`) | May propose a property again; pruned names are not special-cased. |
| Undo | Copy `schema.pre_prune.json` over `schema.json`, run `mykg approve-schema --session S`, then `extract-graph --session S --from-step validate_graph`. |

Everything is per session (Invariant 9); no state beyond `schema_drift.json` and the history entry.

---

## 7. Mapping to the article's 4-tier policy spectrum
1. **REPORT** (log counts, warn on zero-instance concepts, no state change): `mykg detect-schema-drift`, on demand rather than automatic at sync completion (your decision).
2. **AUDIT TRAIL** (timestamps in `concepts_removed`): `schema_history` already carries `concepts_removed` with timestamps; prune adds the `schema_prune` trigger and reasons.
3. **ON-DEMAND PRUNING** (`--prune-schema` with a preview): `mykg prune-schema` with `--preview` / `--plan`.
4. **GRACE-PERIOD DECAY** (auto-prune after N consecutive zero cycles): **not implemented** (no grace mode, no counters, no timestamps of first observation). Protection against premature pruning comes from the preview, the editable plan, `structural`/`locked` classification, and the backup.

---

## 8. Approach A vs B (decision record)

Both share the front half: **detect (counts) -> deterministic prune plan** (no LLM in either). They differ after approval:
- **A (chosen):** write the pruned schema as a `schema_history` version, regenerate `schema.ttl` and `flattened_schema.json`, refresh outputs from `validate_graph`. Existing extractions kept.
- **B (your suggestion, not built):** write the pruned schema as a `schema_history` version, re-enter at the Pass 1 side (`schema_validate`, `schema_flatten`; optionally locked Pass 1) and re-run Pass 2 and all downstream steps (`--from-step schema_validate` or `pass2`; D26 Re-entry A).

| Criterion | A: prune + refresh outputs | B: prune + re-run Pass 1 stages + Pass 2 |
|---|---|---|
| Schema change | Identical (same plan, same history entry) | Identical |
| LLM calls / cost | 0, seconds | Pass 2 over the whole corpus, O(files x chunks), minutes to hours; Pass 1 LLM stages too if re-run |
| Effect on instances | None: pruned types have zero instances | May shift attributes, confidence, entity placement for unrelated entities (nondeterminism, changed prompt vocabulary) |
| Artifact consistency | Shards/raw extractions made under the old schema; flattened schema refreshed directly | Everything consistent with the pruned schema, as if extracted with it from the start |
| Vocabulary churn | None | None if Pass 1 LLM stages are skipped; real risk if re-induction re-runs |
| Blast radius / resumability | One small operation | Invalidates `pass2` and downstream, wipes shards, long-running (Invariant 10) |
| Orphan pass | Not re-run | Re-run; may re-add edges; pruned properties unavailable for schema-gap restarts |
| New code | Prune module + two commands | Plus orchestrator delegation and cost estimate |
| Complexity (Invariant 16) | O(nodes + edges) | O(corpus) LLM cost per prune, independent of the prune's size |

**Verdict.** Removing a zero-instance type cannot change any extracted instance, so B mostly pays O(corpus) LLM cost to reproduce the same graph. Its only real benefit (artifact consistency) is mostly captured by A re-running `schema_flatten` without an LLM. **Decision: A only; no `--reextract` flag.**

---

## 9. Technical design

### Core: `src/mykg/schema_drift.py` (pure, no LLM; Pydantic models, Invariant 8)
- `analyze_drift(schema, nodes_iter, edges_iter, locked)`: single streaming pass; produces `DriftReport` (Section 4).
- `record_drift(report, intermediate_dir)`: atomic write of `schema_drift.json` (`atomic_write_json`), including timestamp and fingerprint.
- `plan_prune(report)`, `load_plan(path)`, `validate_plan(plan, report)` (fingerprint, safety, consistency; Section 5), `apply_prune(plan, intermediate_dir)`: backs up to `schema.pre_prune.json`, validates the pruned schema first (`validate_schema_ttl`, abort on errors), then writes through `write_schema(..., "schema_prune", extra={"pruned": [...]})` and regenerates `schema.ttl`.

### Config (Invariant 7)
No new config keys. Nothing here has a tunable value, so `config.py`, both `mykg_config.yaml` files (Invariant 17) and the profiles are untouched.

### Risks, bottlenecks and mitigations (from critique)
| # | Problem | Resolution in this plan |
|---|---|---|
| 1 | **Output refresh needs a `PipelineContext`.** `validate_graph` does not use the LLM adapter, but `extract-graph` builds the context with an adapter (cli.py:1088-1128) and `run_schema_flatten(ctx)` also takes a ctx. Re-entering via `run(STEPS, ctx)` could re-run preprocess/ingest. | Unit 2 starts with a **spike**: call `flatten_schema(schema)` (pure, schema_flattener.py:8) and the `validate_graph` step function directly with a minimal context (no adapter, never `run(STEPS)`). Fallback if that proves invasive: apply the prune and print the exact follow-up `extract-graph --session S --from-step validate_graph` command instead of refreshing. |
| 2 | **Optional exports are not refreshed** unless their toggles are on (`--obsidian-vault`, `--neo4j-csv` are CLI flags, others config). | Refresh runs with config toggles only; the TBox (`knowledge_graph.ttl`) is the schema-dependent output that matters. Pruned properties have zero edges, so Neo4j relationship CSVs and node vault notes do not change. State this in the docs. |
| 3 | **Concurrent run:** `write_schema` writes `schema.json` non-atomically; pruning while `extract-graph` is running would corrupt state. | Both commands refuse when any step in `pipeline_state.json` has status `running` (status values exist: pending/running/done/failed/waiting). |
| 4 | **Crash mid-apply** (schema.json written, ttl/history/refresh not). | Order: validate pruned schema in memory first, back up, then write. Re-running `prune-schema` is idempotent (plan recomputed; nothing left to prune), and `approve-schema` repairs `schema.ttl`. Documented. |
| 5 | **Invalid result:** pruning could produce a schema that fails validation. | Run `validate_schema_ttl` (schema_validator.py) on the pruned schema before writing; abort with the errors if it fails. |
| 6 | **Hand-edited plan is malformed** or belongs to another session. | `load_plan` validates structure (Pydantic) with a clear error; the fingerprint also rejects another session's plan. |
| 7 | **Locks unknown:** `base_schema_parsed.json` is written only on the first non-append run and is absent in merge-graphs sessions. | If absent, print "no locked schema recorded; treating all entries as unlocked" so the operator knows; merge sessions stay out of scope. |
| 8 | **Stale record shown elsewhere:** the walkthrough reads `schema_drift.json`, which may predate later syncs. | Walkthrough section shows the record's timestamp and fingerprint-match status ("stale: re-run detect-schema-drift"); never presents a stale count as current. |
| 9 | **MCP tool count in docs is already inconsistent** (docstring says 15, architecture table lists 13). | Unit 4 counts the registered tools in code and fixes the numbers, not "+1". |
| 10 | **Sequential critical path:** 5 stacked units mean latency, and a review change in unit 1 rebases everything after it. Unit 2 is the largest and riskiest; units 3 and 4 are small. | Accepted per your instruction. Order keeps the risky unit early (unit 2 spike) so problems surface before the small ones are built; units 3 and 4 could be merged into one if you want fewer hand-offs. |

### Complexity (Invariant 16)
One streaming pass, O(nodes + edges); memory O(concepts + properties); no LLM calls.

### Out of scope
LLM-assisted/proposal-based schema revision (merge/rename/re-parent); re-running Pass 1 LLM stages as part of pruning; merge-graphs pruning; cycle-counting automatic pruning (tier 4); bi-temporal validity; removing attributes from the schema (reported only).

---

## 10. Codebase findings (verified by exploration)
- Schema = `intermediate/schema.json` (`concepts[]{type,parent,attributes}`, `properties[]{name,domain,range,attributes}`). Writes go through `schema_history.write_schema(schema, intermediate_dir, trigger, extra=)` (src/mykg/schema_history.py:38): it diffs against the previous schema and writes `schema_history/<seq>_<trigger>.json` with `timestamp`, `concepts_removed`, `properties_removed`. The trigger list is at lines 28-35 (add `schema_prune`). Its `write_text` is non-atomic.
- Instance data: stream `output/nodes.jsonl` / `edges.jsonl` (Invariant 19); `intermediate/nodes.json` / `edge_metadata.json` are whole-file JSON. `validate_graph` silently drops edges with undeclared types (reverse-drift signal).
- Locks: `intermediate/base_schema_parsed.json` holds `--base-schema` locks (written only on non-append ingest). Never prune these.
- CLI: `approve-schema` (cli.py:1164, also the model for regenerating `schema.ttl` via `export_ttl`), `walkthrough` (1200) and `query` (2252, with `_resolve_session_root` at 2146) are the templates for new session subcommands. Reference only: `_delete_from_step` (1993) and the post-run walkthrough call (1154).
- Walkthrough: `_section_final_graph` (walkthrough.py:528), `_section_schema_evolution` (234); sections are numbered by string-replacement offset.
- MCP: `mykg_list_node_types` lists only types WITH nodes; read-only tool annotation pattern in mcp_server.py.
- Tests: flat `tests/test_*.py`; CLI tests use `CliRunner` + `monkeypatch.setattr("mykg.cli._sessions_root", ...)`; no shared session-builder fixture.

---

## 11. Work units (sequential, stacked)
**Execution model: one unit at a time, in order.** Each unit builds on the previous one. The coordinator launches unit N only after unit N-1 has reported its PR, and unit N's worktree/branch is created from unit N-1's branch (stacked PRs: each PR's base is the previous unit's branch; the first targets `main`). Each worker therefore sees the real code of the earlier units instead of a contract on paper, and each PR stays small and reviewable on its own diff. Merging in order (1, 2, 3, 4, 5) lands the feature; if unit N needs changes, later units are rebased. No units run in parallel. Every worker prompt names its base branch and the previous unit's PR URL.

| # | Unit | Builds on | Files |
|---|---|---|---|
| 1 | Core analyzer, plan and apply | `main` | `src/mykg/schema_drift.py`, `src/mykg/schema_history.py` (`schema_prune` trigger + docstring), `tests/test_schema_drift.py` (the article's 5/11 to 3/3 example, locked, structural, cascade, no-re-parenting rule (a locked child keeps its zero-instance parent), cycle guard, malformed plan, pruned-schema validation, plan validation: stale/unsafe/dangling, apply with backup and history delta) |
| 2 | CLI commands | 1 | `src/mykg/cli.py` (new `detect-schema-drift` and `prune-schema [--preview | --plan FILE]`, both with `--session`; after apply, regenerate `flattened_schema.json` directly with the flatten step's function, never `_delete_from_step("schema_flatten")`, then run only `validate_graph`; refuse to run while any step in `pipeline_state.json` is `running` (Section 9 risk #3); no LLM adapter is loaded; begins with the refresh spike described in Section 9 risk #1), `tests/test_cli_schema_drift.py` |
| 3 | Walkthrough "Schema Health" section | 1 (and 2 for the hint text) | `src/mykg/walkthrough.py` (shows record timestamp and stale status), `tests/test_walkthrough_sections.py` |
| 4 | MCP tool `mykg_schema_drift` | 1 | `src/mykg/mcp_server.py` (read-only, live computation; count the registered tools and correct the docstring/docs numbers), `tests/test_mcp_server.py` |
| 5 | Docs + skill | 1-4 | `CLAUDE.md` (new D62; D16 table rows for `schema_drift.json`, `schema_prune_plan.json`, `schema.pre_prune.json`; D36 trigger list), `docs/architecture.md`, `README.md` (command docs, "continuing the same session after a prune" table, "Schema Drift & Pruning" section), `src/mykg/data/skills/mykg/SKILL.md` (intent table and session-only list), `src/mykg/data/claude_md_snippet.md` if needed |

Each unit's worker runs the full e2e recipe steps that apply to what exists so far (Section 12 marks which steps belong to which unit).

---

## 12. E2E test recipe (for workers)
Step 1 applies to every unit. Unit 1 covers the behaviors of steps 3-5 through unit tests on the core module (no CLI yet). Unit 2 runs steps 2-6 against the real CLI. Units 3-5 re-run steps 3-4 as a regression check, plus their own checks (walkthrough section renders from `schema_drift.json`; MCP tool returns the same counts; docs examples match actual command output).
1. `pytest tests/test_schema_drift.py <unit's test file> -q`, then full `pytest -q`.
2. Build a synthetic session under a temp sessions dir (no LLM): `intermediate/schema.json` with 5 concepts (Organization, Person, Team, Project, Service) and 11 properties; `output/nodes.jsonl` + `edges.jsonl` using only 3 concepts / 3 properties; optional `base_schema_parsed.json` locking one unused concept.
3. `mykg detect-schema-drift --session <name>`: expect "unused concepts: Project (0 instances), Service (0 instances)" and "declared properties: 11 (8 unreferenced by active edges)"; `schema_drift.json` written; `schema.json` unchanged.
4. `mykg prune-schema --session <name> --preview`: plan printed, `schema_prune_plan.json` written, `schema.json`/`schema.ttl`/history unchanged. Then `mykg prune-schema --session <name>`: `schema.json` is 3 / 3, `schema.pre_prune.json` exists, a `*_schema_prune.json` delta lists timestamped `concepts_removed`, `schema.ttl` regenerated, `nodes.jsonl`/`edges.jsonl` byte-identical, `flattened_schema.json` no longer lists pruned types.
5. Plan editing: preview, delete one entry from `remove`, apply with `--plan`, and confirm only the remaining entries are removed; then try a plan with a non-prunable entry added (rejected, nothing changed) and a stale plan after changing `nodes.jsonl` (refused).
6. Validation: `--preview` together with `--plan` fails with a clear error; missing `schema.json` and an unknown session each fail with a clear error; neither command needs an API key (run with provider env vars unset).

---

## 13. Worker instructions (shared template, copied verbatim into each agent prompt)
After you finish implementing the change:
1. **Code review** — Invoke the `Skill` tool with `skill: "code-review"` to find correctness bugs (it reports findings; it does not edit code). Fix any findings it surfaces before continuing.
2. **Run unit tests** — Run the project's test suite (check for package.json scripts, Makefile targets, or common commands like `npm test`, `bun test`, `pytest`, `go test`). If tests fail, fix them.
3. **Test end-to-end** — Follow the e2e test recipe from the coordinator's prompt (below). If the recipe says to skip e2e for this unit, skip it.
4. **Commit and push** — Commit all changes with a clear message, push the branch, and create a PR with `gh pr create`. Use a descriptive title. If `gh` is not available or the push fails, note it in your final message.
5. **Report** — End with a single line: `PR: <url>` so the coordinator can track it. If no PR was created, end with `PR: none — <reason>`.

Each prompt must also include: the user's goal, the unit's file list and description (from Section 11), the base branch to build on and the previous unit's PR URL, Sections 1-6 and 9, the relevant conventions (Invariants 7/8/16/17/18/19/20: utf-8 file I/O, pathlib, Pydantic, streaming JSONL, config via `config.py`, no hardcoded values), and the e2e recipe. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`; PR bodies end with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
