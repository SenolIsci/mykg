# mykg `--append --grow-schema` live test report

_Generated: 2026-06-21 10:09:01Z_

- **Profile:** `openrouter-free`
- **Model:** `openrouter/free`

## Commands run

```
mykg extract-graph _input_files --obsidian-vault
mykg extract-graph _input_files --append --grow-schema --session 2026-06-21T09-54-15 --obsidian-vault
```

## Stage 1 — initial extract

- Session: `2026-06-21T09-54-15`
- Concepts: 3
- Properties: 4
- Nodes: 10
- Edges: 9

## Stage 2 — append --grow-schema

- New file: copied
- **Schema delta empty?** False
- Concepts added: Technology
- Concepts removed: (none)
- Properties added: has_organization_owner, has_person_owner, uses_technology
- Properties removed: has_contributor

### schema_history (stage-2 deltas)

- New history files: 0004_pass1_merge.json, 0005_schema_harmonize.json, 0006_schema_quality.json
  - `0004_pass1_merge.json` trigger=`pass1_merge` +concepts=['Technology'] -concepts=[] +props=['has_organization_owner', 'has_person_owner', 'uses_technology'] -props=[]
  - `0005_schema_harmonize.json` trigger=`schema_harmonize` +concepts=[] -concepts=[] +props=[] -props=['has_contributor']
  - `0006_schema_quality.json` trigger=`schema_quality` +concepts=[] -concepts=[] +props=[] -props=[]

### Back-fill evidence

- Pass 2 invalidated/re-extracted files (stage 2): Active_Projects_Q2_Q3_2026.md, tech_stack.md
- **OLD file re-extracted under grown schema:** True
- raw_extractions.json rewritten: True (sha changed: True)
- Old file shard: `None`
- Per-file shard rewritten: False (sha changed: False) — only meaningful in per_file prep mode
- New-concept nodes citing OLD file: 0
- Summary: OLD file re-extracted under grown schema: True (pass2 invalidated 2 file(s): ['Active_Projects_Q2_Q3_2026.md', 'tech_stack.md']); raw_extractions.json rewritten: True; per-file shard rewritten: False (shard absent/stale under concat/batch prep modes — raw_extractions.json + invalidation log are the authoritative signals); new-concept nodes citing OLD file: 0

## Node / edge change

- Stage-2 nodes: 10 (net +0)
- Stage-2 edges: 6 (net -3)

## Diagnostics

- failed_chunks entries: 0
- rate-limit / 429 / 402 notes: 0
