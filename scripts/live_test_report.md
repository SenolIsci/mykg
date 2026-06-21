# mykg `--append-with-grow-schema` live test report

_Generated: 2026-06-21 16:18:27Z_

- **Profile:** `openai`
- **Model:** `gpt-5.4-mini-2026-03-17`

## Commands run

```
mykg extract-graph _input_files --obsidian-vault
mykg extract-graph _input_files --append-with-grow-schema --session 2026-06-21T16-18-03 --obsidian-vault
```

## Stage 1 — initial extract

- Session: `2026-06-21T16-18-03`
- Concepts: 3
- Properties: 3
- Nodes: 8
- Edges: 8

## Stage 2 — append-with-grow-schema

- New file: copied
- **Schema delta empty?** False
- Concepts added: Technology
- Concepts removed: (none)
- Properties added: owned_by_organization, uses_technology
- Properties removed: (none)

### schema_history (stage-2 deltas)

- New history files: 0004_pass1_merge.json, 0005_schema_harmonize.json, 0006_schema_quality.json
  - `0004_pass1_merge.json` trigger=`pass1_merge` +concepts=['Technology'] -concepts=[] +props=['owned_by_organization', 'uses_technology'] -props=[]
  - `0005_schema_harmonize.json` trigger=`schema_harmonize` +concepts=[] -concepts=[] +props=[] -props=[]
  - `0006_schema_quality.json` trigger=`schema_quality` +concepts=[] -concepts=[] +props=[] -props=[]

### Back-fill evidence

- Pass 2 invalidated/re-extracted files (stage 2): Active_Projects_Q2_Q3_2026.md, tech_stack.md
- **OLD file re-extracted under grown schema:** True
- raw_extractions.json rewritten: True (sha changed: False)
- Old file shard: `None`
- Per-file shard rewritten: False (sha changed: False) — only meaningful in per_file prep mode
- New-concept nodes citing OLD file: 0
- Summary: OLD file re-extracted under grown schema: True (pass2 invalidated 2 file(s): ['Active_Projects_Q2_Q3_2026.md', 'tech_stack.md']); raw_extractions.json rewritten: True; per-file shard rewritten: False (shard absent/stale under concat/batch prep modes — raw_extractions.json + invalidation log are the authoritative signals); new-concept nodes citing OLD file: 0

## Node / edge change

- Stage-2 nodes: 8 (net +0)
- Stage-2 edges: 8 (net +0)

## Diagnostics

- failed_chunks entries: 0
- rate-limit / 429 / 402 notes: 0
