# STATUS: COMPLETE (all five review-fix units pushed)

| # | Unit | PR | Status |
|---|---|---|---|
| 1 | Fix #83 core | https://github.com/SenolIsci/mykg/pull/83 | done (commit c8152e6) |
| 2 | Fix #84 CLI | https://github.com/SenolIsci/mykg/pull/84 | done |
| 3 | Fix #85 walkthrough | https://github.com/SenolIsci/mykg/pull/85 | done |
| 4 | Fix #86 MCP | https://github.com/SenolIsci/mykg/pull/86 | done |
| 5 | Fix #87 docs | https://github.com/SenolIsci/mykg/pull/87 | done |

Outcome per resolution below: all "accept" items were implemented; 83.4 (cross-process lock), 83.11 (TTL regeneration in core) and 86.2 (`asyncio.to_thread`) were declined as planned; 87.2 (grow-schema "everything locked") was refuted and the docs paragraph removed; 83.3 was partly accepted (atomic `schema.ttl`/`flattened_schema.json`, ordered writes, no transaction). Last full run: 1731 passed (`-k "not live"`). CLAUDE.md D62 was updated locally only (gitignored). The original design plan with its implementation status is in `old/schema-drift-plan.md`.

---

# Plan: Address review feedback on the schema-drift PRs (#83-#87)

## Contents
1. Context
2. PR comments and resolutions (per PR)
3. Execution model (sequential, stacked)
4. Work units
5. Verification
6. Worker instructions

---

## 1. Context
Five stacked PRs implement schema drift detection and pruning: #83 core -> #84 CLI -> #85 walkthrough -> #86 MCP -> #87 docs. All review comments come from the Sourcery bot (no human reviews): 11 inline on #83, 1 on #85, 2 on #86, 1 on #87, none inline on #84. I triaged each against the code, together with the open items the unit-5 worker raised. Each resolution is one of: **accept** (fix), **partly accept**, **decline** (with reason), **refuted** (checked, not a bug).

---

## 2. PR comments and resolutions

### PR #83 core (`src/mykg/schema_drift.py`, `tests/test_schema_drift.py`)
| # | Sev | Comment | Resolution | Proposed change |
|---|---|---|---|---|
| 83.1 | High | `apply_prune` does not verify the report still matches the current graph (plan can prune entries that became used) | **accept** | `report` becomes a required argument of `apply_prune(plan, intermediate_dir, report)`; it always runs `validate_plan(plan, report)` first. The CLI already passes a freshly computed report. |
| 83.2 | High | Called without a report, `apply_prune` removes used/locked/structural entries named by a stale or hand-edited plan | **accept** | Same change as 83.1 removes the footgun. Test: apply with a plan naming a used entry is rejected, nothing written. |
| 83.3 | High | `schema.json`, history and `schema.ttl` are written separately; a crash leaves them inconsistent | **partly accept** | A full transaction is disproportionate. Write `schema.ttl` atomically and order the writes so a re-run is idempotent (re-running recomputes the plan and `approve-schema` repairs the TTL). `write_schema` is shared, pre-existing, non-atomic code and is not modified. Documented limitation. |
| 83.4 | Med | Concurrent writers can lose updates / history sequence collisions | **decline** | The CLI already refuses to run while any step is `running`; a cross-process lock is new infrastructure beyond this feature and also affects the pipeline's own writers. Documented limitation. |
| 83.5 | High | `flattened_schema.json` left stale after prune; a resumed pass2 uses the removed vocabulary (also after undo) | **accept** | `apply_prune` itself regenerates `flattened_schema.json` (`flatten_schema`, atomic write), so every caller gets it; remove the duplicate regeneration in the CLI. Test: flattened schema no longer lists pruned types after core apply alone. |
| 83.6 | Med | JSONL rows or `attributes` that are not objects raise a raw `AttributeError` | **accept** | `stream_jsonl` / `analyze_drift` validate shapes and raise `SchemaDriftError`; same for malformed schema entries and a malformed `base_schema_parsed.json` (the unit-5 worker's item about raw KeyError/AttributeError). |
| 83.7 | Med | Edited plan's `keep` / `totals` may disagree with `remove` | **accept** | Recompute `keep` and `totals` from the validated `remove` when applying and when printing; stored values are informational and ignored. |
| 83.8 | Med | Empty plan still writes a backup and a history entry (and overwrites the useful backup) | **accept** | Return early when `plan.remove` is empty: no backup, no history, CLI prints "nothing to prune". |
| 83.9 | Med | `test_article_example_counts_and_prune` checks only counts, not which properties | **accept** | Assert exact name sets (for example `works_at` is retained, the specific unused names are removed). |
| 83.10 | Med | `delta["pruned"]` history check uses `>=` | **accept** | Use equality with the plan's names. |
| 83.11 | Med | An existing `output/knowledge_graph.ttl` still declares pruned entries | **decline for core; handled in CLI** | Core stays schema-only by design. The CLI refresh (`validate_graph`) regenerates it, with the follow-up command printed as the fallback. Add a CLI test that the TTL no longer declares pruned entries after prune. |
| extra | - | Unit-5 worker: the plan fingerprint does not cover the lock set | **accept (small)** | Include the sorted locked names in the fingerprint so a changed lock file marks plans and records stale. |

### PR #84 CLI (`src/mykg/cli.py`, `tests/test_cli_schema_drift.py`): no bot comments; issues found by the unit-5 worker
| # | Finding | Resolution | Proposed change |
|---|---|---|---|
| 84.1 | The prune undo message says the flattened schema is regenerated by the next pass2 run; it is not (`_is_done` skips the step when the file exists) | **accept** | Fix the text. Safe undo = copy `schema.pre_prune.json` over `schema.json`, then `mykg approve-schema --session S` (regenerates `schema.ttl`), delete `intermediate/flattened_schema.json`, then `extract-graph --session S --from-step validate_graph`. The worker verifies the exact commands work and must NOT recommend `--from-step schema_flatten` (it deletes pass2 outputs). |
| 84.2 | "Refreshed ... exports" overstates: the Obsidian vault and Neo4j CSV are regenerated only when their config toggles are on, not when the CLI flags were passed to the earlier run | **accept** | Print what was actually regenerated (TTL, validation, walkthrough, and which optional exports). |
| 84.3 | Suggested commands interpolate the session name unquoted (same class as 85.1) | **accept** | `shlex.quote` in printed follow-up and undo commands. |
| 84.4 | Adapt to the new `apply_prune` signature (83.1) and flatten moving into core (83.5) | **accept** | Pass the fresh report; drop the duplicate flatten; handle the "nothing to prune" return (83.8). |
| 84.5 | Malformed `base_schema_parsed.json` or bad schema entry raises a raw exception | **accept** | Surface the new `SchemaDriftError` as a `ClickException`; catch `UnicodeDecodeError` when loading the lock file. |

### PR #85 walkthrough (`src/mykg/walkthrough.py`)
| # | Sev | Comment | Resolution | Proposed change |
|---|---|---|---|---|
| 85.1 | Med | Session name interpolated unquoted into the suggested `mykg detect-schema-drift` / `prune-schema --preview` commands (shell metacharacters in a directory name would run when copied) | **accept** | `shlex.quote` the session name at both hints (~lines 342, 370); test with a name containing spaces and `;`. Also adapt to the fingerprint change (83 extra). |

### PR #86 MCP (`src/mykg/mcp_server.py`)
| # | Sev | Comment | Resolution | Proposed change |
|---|---|---|---|---|
| 86.1 | Med | `UnicodeDecodeError` from `read_text` on `base_schema_parsed.json` aborts the tool | **accept** | Catch it and return the existing "could not be read" notice; test with invalid UTF-8 bytes. |
| 86.2 | Med | `analyze_drift` runs synchronously in the async handler and blocks the event loop on large sessions | **decline** | Sibling tools (`mykg_get_stats`, `mykg_orphan_nodes`) also scan the whole in-memory graph synchronously; consistency wins. If it ever matters, change all tools together (separate task). |

### PR #87 docs (`README.md`, `docs/architecture.md`, SKILL.md, `docs/agent-mode.md`; CLAUDE.md is local and gitignored)
| # | Sev | Comment / finding | Resolution | Proposed change |
|---|---|---|---|---|
| 87.1 | Med | Docs say MCP "reports the same data" but the MCP output omits `always_null_attributes` that the CLI prints | **accept** | Add the always-null attributes line to the MCP output (done in the #86 branch) and keep the docs wording accurate; docs mention it. |
| 87.2 | - | Unit-5 worker's limitation note: "a session that used `--append-with-grow-schema` may have everything locked" | **refuted** | Checked in code: `--append-with-grow-schema` goes through `_run_append_ingest` (`run_ingest` returns early when `ctx.append`), and `_write_base_schema_parsed` is only reached on the non-append path. So `base_schema_parsed.json` records only a real `--base-schema` from a fresh run. Remove the worker's limitation paragraph from README/architecture and add an e2e check that a grow-schema-style session (no `base_schema_parsed.json`) classifies unused entries as prunable. |
| 87.3 | - | Docs must reflect the fixes above | **accept** | Update docs for: apply regenerating the flattened schema, no-op prune behavior, lock names in the fingerprint, accurate undo steps, and which exports the refresh regenerates; update the local CLAUDE.md D62 text too (not part of the PR; report it). |

---

## 3. Execution model
The branches are stacked, so fixes go as **new commits on each PR's own existing branch**, in order #83 -> #84 -> #85 -> #86 -> #87, one worker at a time. Each worker first merges the already-updated previous branch into its own (so the new `apply_prune` signature and fingerprint reach later units), then pushes to its own branch and ends with `PR: <existing PR url>` (no new PRs). Sequential because each unit depends on the API changes of the previous one.

## 4. Work units
1. **#83 `feat/schema-drift-1-core`**: resolutions 83.1-83.3, 83.5-83.10, fingerprint lock names; new required-`report` `apply_prune`, flatten regeneration, empty-plan early return, shape validation, recomputed keep/totals, strengthened tests.
2. **#84 `feat/schema-drift-2-cli`**: 84.1-84.5 (adapt to core, honest messages, quoting, undo text, error handling, TTL-regenerated test).
3. **#85 `feat/schema-drift-3-walkthrough`**: 85.1 plus adaptation to the fingerprint change.
4. **#86 `feat/schema-drift-4-mcp`**: 86.1, `always_null_attributes` output (87.1), adaptation to the fingerprint change.
5. **#87 `feat/schema-drift-5-docs`**: 87.1-87.3 including removal of the refuted limitation paragraph.

## 5. Verification (every worker)
- `pytest -q -k "not live"` (known: `test_anthropic_live_accepts_temperature` needs network).
- Synthetic-session e2e through the real CLI (no API keys): 5 concepts / 11 properties, 3 / 3 used. `detect-schema-drift` -> `prune-schema --preview` -> `prune-schema`; then detect shows nothing unused, `flattened_schema.json` no longer lists pruned types, `nodes.jsonl`/`edges.jsonl` unchanged, `knowledge_graph.ttl` no longer declares pruned entries. Applying an empty plan creates no history entry and does not touch the backup. A plan naming a used entry is rejected with nothing changed. A malformed JSONL line and an invalid-UTF-8 lock file give clean errors. A session without `base_schema_parsed.json` (as after `--append-with-grow-schema`) classifies unused entries as `prunable`. A session name with spaces/`;` is shell-quoted in printed commands.

## 6. Worker instructions (shared template, verbatim in each prompt)
After you finish implementing the change:
1. **Code review** — Invoke the `Skill` tool with `skill: "code-review"` to find correctness bugs (it reports findings; it does not edit code). Fix any findings it surfaces before continuing.
2. **Run unit tests** — Run the project's test suite (check for package.json scripts, Makefile targets, or common commands like `npm test`, `bun test`, `pytest`, `go test`). If tests fail, fix them.
3. **Test end-to-end** — Follow the e2e test recipe from the coordinator's prompt (below). If the recipe says to skip e2e for this unit, skip it.
4. **Commit and push** — Commit all changes with a clear message, push the branch, and create a PR with `gh pr create`. Use a descriptive title. If `gh` is not available or the push fails, note it in your final message.
5. **Report** — End with a single line: `PR: <url>` so the coordinator can track it. If no PR was created, end with `PR: none — <reason>`.

Adaptation for this task: the PR already exists, so step 4 means "commit and push to the existing PR branch" (no `gh pr create`), and step 5 ends with `PR: <existing PR url>`. Commit messages end with `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
