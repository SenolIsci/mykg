# Walkthrough — Session `2026-06-01T21-46-31`

**Run health:** ✓ Clean

## 1. Final Graph Summary

**Total nodes:** 56

| Type | Count |
|---|---|
| Technology | 17 |
| Person | 9 |
| Employee | 6 |
| Organization | 5 |
| Team | 5 |
| Company | 5 |
| Project | 3 |
| Product | 3 |
| Partnership | 2 |
| Contract | 1 |

**Total edges:** 86

**Edges by type:**

| Type | Count |
|---|---|
| uses_technology | 22 |
| works_at | 18 |
| manages | 9 |
| contributes_to | 6 |
| member_of | 5 |
| leads | 5 |
| owns | 5 |
| reports_to | 3 |
| involves_organization | 3 |
| covers_project | 3 |
| provides | 3 |
| has_contact | 2 |
| holds_contract | 1 |
| depends_on | 1 |

**Edges by method:**

| Method | Count |
|---|---|
| llm_extraction | 69 |
| orphan_inferred | 17 |

**Validation:** valid

**Output files:**

- `edges.jsonl` — 23.2 KB
- `knowledge_graph.ttl` — 24.4 KB
- `knowledge_graph_validation.json` — 0.1 KB
- `nodes.jsonl` — 20.7 KB
- `networkx_output/` — 8 file(s):
  - `adjacency.txt` — 3.2 KB
  - `edges_nx.txt` — 18.6 KB
  - `knowledge_graph.gexf` — 77.5 KB
  - `knowledge_graph.gml` — 43.0 KB
  - `knowledge_graph.graphml` — 56.4 KB
  - `knowledge_graph.html` — 58.3 KB
  - `knowledge_graph.json` — 56.3 KB
  - `knowledge_graph.net` — 21.5 KB

## 2. Run Overview

| Field | Value |
|---|---|
| Session | `2026-06-01T21-46-31` |
| Run date/time (UTC) | 2026-06-01 21:46:31 |
| LLM provider | anthropic |
| LLM model | claude-sonnet-4-5 |
| Input files | 4 |
| Total duration | 2m 25s |
| Schema-gap restarts | 0 |
| Run health | healthy |

## 3. Step Timeline

| Step | Status | Start | Duration |
|---|---|---|---|
| preprocess | done | 22:46:31 | 0s |
| ingest | done | 22:46:31 | 0s |
| pass1 | done | 22:46:31 | 35s |
| schema_validate | done | 22:47:06 | 0s |
| human_review | done | 22:47:06 | 0s |
| schema_flatten | done | 22:47:06 | 0s |
| pass2 | done | 22:47:06 | 58s |
| normalize_names | done | 22:48:04 | 40s |
| assemble | done | 22:48:44 | 0s |
| orphan_score | done | 22:48:44 | 0s |
| orphan_connect | done | 22:48:44 | 12s |
| validate_graph | done | 22:48:56 | 0s |

## 4. Schema Evolution

### History

| Seq | Trigger | Concepts +/- | Properties +/- |
|---|---|---|---|
| 1 | pass1_merge | +10 / -0 | +16 / -0 |
| 2 | schema_harmonize | +0 / -0 | +0 / -0 |
| 3 | schema_quality | +0 / -0 | +3 / -3 |

### Final Schema

**Concepts** (10 total):

- **Contract** — attrs: `name, type, signed_date, value`
- **Organization** — attrs: `name, description, headquarters_location, type`
  - **Company** *(is-a: Organization)* — attrs: `founding_year, annual_revenue`
  - **Team** *(is-a: Organization)* — attrs: `focus_area, member_count`
- **Partnership** — attrs: `name, type, start_date, scope`
- **Person** — attrs: `name, email, education`
  - **Employee** *(is-a: Person)* — attrs: `title, join_date`
- **Project** — attrs: `name, description, status, budget`
- **Technology** — attrs: `name, category, version`
  - **Product** *(is-a: Technology)* — attrs: `vendor`

**Properties** (17 total):

- `Person` →[**contributes_to**]→ `Project`  *(edge attrs: role, contribution_type)*
- `Partnership` →[**covers_project**]→ `Project`
- `Project` →[**depends_on**]→ `Project`
- `Partnership` →[**governed_by**]→ `Contract`
- `Company` →[**has_contact**]→ `Person`  *(edge attrs: contact_type)*
- `Company` →[**holds_contract**]→ `Contract`
- `Partnership` →[**involves_organization**]→ `Company`  *(edge attrs: role)*
- `Person` →[**leads**]→ `Organization`
- `Person` →[**manages**]→ `Organization`
- `Person` →[**member_of**]→ `Team`
- `Organization` →[**owns**]→ `Project`
- `Company` →[**partners_with**]→ `Company`
- `Company` →[**provides**]→ `Product`
- `Person` →[**reports_to**]→ `Person`
- `Project` →[**uses_technology**]→ `Technology`  *(edge attrs: purpose)*
- `Team` →[**uses_technology**]→ `Technology`  *(edge attrs: purpose)*
- `Person` →[**works_at**]→ `Organization`  *(edge attrs: role, start_date, end_date)*

## 5. LLM Call Statistics

| Stage | Calls | Fresh input | Cache read | Cache create | Output | Latency |
|---|---|---|---|---|---|---|
| Pass 1 batch induction | 1 | 2,088 | 0 | 0 | 1,098 | 12.7s |
| Schema harmonization | 1 | 3,066 | 0 | 0 | 1,252 | 11.0s |
| Schema quality review | 1 | 2,225 | 0 | 0 | 1,204 | 10.9s |
| Instance extraction (Pass 2) | 4 | 9,632 | 0 | 0 | 19,128 | 43.0s |
| Orphan connection | 2 | 2,070 | 0 | 0 | 1,386 | 8.4s |
| Other | 1 | 708 | 0 | 0 | 132 | 40.5s |
| **Total** | **10** | **19,789** | **0** | **0** | **24,200** | **26.4s** |

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
| team.md | 16 | 17 | 0 |
| partners.md | 19 | 18 | 0 |
| projects.md | 18 | 21 | 0 |
| technologies.md | 31 | 30 | 0 |

**Name normalization:** 9 aliases mapped across 2 concept type(s).

**Deduplication:** 19 node merge(s), 17 edge merge(s).

**Dangling edges dropped:** 0

## 7. Orphan Pass Summary

- Orphan chunk groups found: **2**
- Total orphans across groups: **12**
- Schema-gap orphans: **0**
- Orphan edges added (LLM confirmed): **17**
- Orphan edges rejected: **4**
- Promoted to schema-gap orphan: **4**

**Orphans remaining in final KG:** 4

- `organization-google` (Organization)
- `organization-datasystems-inc` (Organization)
- `organization-novatech-inc` (Organization)
- `organization-deepmind` (Organization)

## 8. Warnings & Retries

*No warnings or errors recorded.*

---
*Generated 2026-06-01T21:48:56 UTC*