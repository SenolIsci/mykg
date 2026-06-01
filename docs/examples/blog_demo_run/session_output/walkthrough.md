# Walkthrough — Session `2026-06-01T21-52-37`

**Run health:** ✓ Clean

## 1. Final Graph Summary

**Total nodes:** 50

| Type | Count |
|---|---|
| Technology | 17 |
| Person | 9 |
| Organization | 7 |
| Employee | 6 |
| Team | 5 |
| Project | 3 |
| Product | 2 |
| Agreement | 1 |

**Total edges:** 79

**Edges by type:**

| Type | Count |
|---|---|
| uses_technology | 20 |
| works_at | 19 |
| manages | 10 |
| co_founded | 4 |
| contributes_to | 4 |
| member_of | 3 |
| reports_to | 3 |
| leads | 3 |
| vendor_for | 3 |
| owns | 2 |
| has_partnership | 2 |
| provides | 2 |
| account_manager_for | 2 |
| depends_on | 1 |
| has_agreement | 1 |

**Edges by method:**

| Method | Count |
|---|---|
| llm_extraction | 57 |
| orphan_inferred | 22 |

**Validation:** valid

**Output files:**

- `edges.jsonl` — 20.3 KB
- `knowledge_graph.ttl` — 19.5 KB
- `knowledge_graph_validation.json` — 0.1 KB
- `nodes.jsonl` — 16.0 KB
- `networkx_output/` — 8 file(s):
  - `adjacency.txt` — 3.0 KB
  - `edges_nx.txt` — 15.5 KB
  - `knowledge_graph.gexf` — 64.2 KB
  - `knowledge_graph.gml` — 34.2 KB
  - `knowledge_graph.graphml` — 46.3 KB
  - `knowledge_graph.html` — 50.7 KB
  - `knowledge_graph.json` — 45.7 KB
  - `knowledge_graph.net` — 16.4 KB

## 2. Run Overview

| Field | Value |
|---|---|
| Session | `2026-06-01T21-52-37` |
| Run date/time (UTC) | 2026-06-01 21:52:37 |
| LLM provider | anthropic |
| LLM model | claude-sonnet-4-5 |
| Input files | 4 |
| Total duration | 2m 07s |
| Schema-gap restarts | 0 |
| Run health | healthy with warnings — 1 warning(s) |

## 3. Step Timeline

| Step | Status | Start | Duration |
|---|---|---|---|
| preprocess | done | 22:52:37 | 0s |
| ingest | done | 22:52:37 | 0s |
| pass1 | done | 22:52:37 | 34s |
| schema_validate | done | 22:53:11 | 0s |
| human_review | done | 22:53:11 | 0s |
| schema_flatten | done | 22:53:11 | 0s |
| pass2 | done | 22:53:11 | 45s |
| normalize_names | done | 22:53:56 | 36s |
| assemble | done | 22:54:32 | 0s |
| orphan_score | done | 22:54:32 | 0s |
| orphan_connect | done | 22:54:32 | 12s |
| validate_graph | done | 22:54:44 | 0s |

## 4. Schema Evolution

### History

| Seq | Trigger | Concepts +/- | Properties +/- |
|---|---|---|---|
| 1 | pass1_merge | +10 / -0 | +16 / -0 |
| 2 | schema_harmonize | +0 / -0 | +0 / -0 |
| 3 | schema_quality | +1 / -2 | +2 / -2 |

### Final Schema

**Concepts** (9 total):

- **Agreement** — attrs: `name, type, start_date`
- **Organization** — attrs: `name, headquarters_location, industry, founding_year`
  - **Company** *(is-a: Organization)* — attrs: `annual_spend`
- **Person** — attrs: `name, email, education`
  - **Employee** *(is-a: Person)* — attrs: `join_date, title`
- **Project** — attrs: `name, status, target_completion_date, budget`
- **Team** — attrs: `name, description, member_count`
- **Technology** — attrs: `name, type, version`
  - **Product** *(is-a: Technology)* — attrs: `description`

**Properties** (16 total):

- `Person` →[**account_manager_for**]→ `Organization`
- `Person` →[**co_founded**]→ `Organization`  *(edge attrs: year)*
- `Person` →[**contributes_to**]→ `Project`  *(edge attrs: role)*
- `Project` →[**depends_on**]→ `Project`
- `Organization` →[**has_agreement**]→ `Agreement`
- `Organization` →[**has_partnership**]→ `Organization`  *(edge attrs: type, start_date)*
- `Person` →[**leads**]→ `Project`  *(edge attrs: role)*
- `Person` →[**manages**]→ `Team`
- `Person` →[**member_of**]→ `Team`
- `Team` →[**owns**]→ `Project`
- `Organization` →[**provides**]→ `Product`
- `Person` →[**reports_to**]→ `Person`
- `Agreement` →[**supports**]→ `Project`
- `Project` →[**uses_technology**]→ `Technology`
- `Organization` →[**vendor_for**]→ `Organization`
- `Person` →[**works_at**]→ `Organization`  *(edge attrs: start_date, end_date, role)*

## 5. LLM Call Statistics

| Stage | Calls | Fresh input | Cache read | Cache create | Output | Latency |
|---|---|---|---|---|---|---|
| Pass 1 batch induction | 1 | 2,088 | 0 | 0 | 1,013 | 13.9s |
| Schema harmonization | 1 | 2,940 | 0 | 0 | 1,145 | 10.1s |
| Schema quality review | 1 | 2,118 | 0 | 0 | 1,100 | 10.0s |
| Instance extraction (Pass 2) | 4 | 9,296 | 0 | 0 | 16,808 | 37.3s |
| Orphan connection | 2 | 2,031 | 0 | 0 | 1,803 | 9.7s |
| Other | 1 | 650 | 0 | 0 | 141 | 35.4s |
| **Total** | **10** | **19,123** | **0** | **0** | **22,010** | **23.8s** |

## 6. Extraction Summary

### Pass 2 Retry Statistics

| Metric | Count |
|---|---|
| Chunks dispatched (total) | 4 |
| JSON parse error → retry | 0 |
| Validation error → retry | 0 |
| Retry also failed (JSON) | 0 |
| Chunks permanently skipped | 0 |
| Partial recoveries (degraded mode) | 0 |
| Nodes dropped (hallucinated anchors) | 0 |
| Edges dropped (partial recovery) | 0 |
| **Retry rate** | **0.0%** |

### Per-file extraction

| File | Nodes | Edges | Retries |
|---|---|---|---|
| team.md | 15 | 16 | 0 |
| projects.md | 17 | 21 | 0 |
| partners.md | 18 | 20 | 0 |
| technologies.md | 30 | 23 | 0 |

**Name normalization:** 8 aliases mapped across 2 concept type(s).

**Deduplication:** 18 node merge(s), 17 edge merge(s).

**Dangling edges dropped:** 0

## 7. Orphan Pass Summary

- Orphan chunk groups found: **2**
- Total orphans across groups: **13**
- Schema-gap orphans: **0**
- Orphan edges added (LLM confirmed): **22**
- Orphan edges rejected: **0**

**Orphans remaining in final KG:** 0

## 8. Warnings & Retries

### Other Warnings (1)
- `22:54:32` [WARNING] mykg.steps.normalize: Step 6b — normalization warning: Type 'Technology': canonical 'Amazon Web Services' not in inventory, dropping 'AWS'

---
*Generated 2026-06-01T21:54:44 UTC*