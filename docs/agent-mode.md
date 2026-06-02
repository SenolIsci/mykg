# Agent mode

Agent mode is a sixth LLM backend for mykg in which LLM answers are produced not by an HTTP API or a subprocess but by a **Claude Code skill** running inside your coding assistant. The pipeline writes task envelopes to a session-local inbox folder; a skill drains the inbox, dispatches subagents, and writes answers back to an outbox folder. The pipeline polls the outbox for a `.done` sentinel before returning each `complete()` call.

This is useful when:

- you do not want to manage API keys or pay per-token fees, but you do have a Claude Code subscription
- you want to inspect, edit, or replay LLM responses at the filesystem level — every prompt is a `.task.json` and every answer is a `.answer.json` on disk
- you want the host coding assistant's tool palette (file reads, code execution, web fetch) available implicitly inside LLM responses

The 12-step pipeline, all 14 LLM call sites, all `prompts/*.txt` templates, the orchestrator, and the existing five adapters are **unchanged**. Agent mode is a thin filesystem-backed adapter that conforms to the existing `LLMAdapter` interface.

---

## Architecture

```
┌──────────────────────┐                ┌────────────────────┐
│ /mykg skill          │ ── runs ───▶  │ mykg extract-graph │
│ (Claude Code)        │                │ (subprocess)       │
│                      │                └─────────┬──────────┘
│ loop:                │                          │
│   ls inbox/*.json    │                          │ adapter.complete(s,u)
│   for each task:     │                          ▼
│     dispatch subagent│ ←── reads ─── intermediate/agent_inbox/<id>.task.json
│     write answer     │ ── writes ──▶ intermediate/agent_outbox/<id>.done
│   sleep 2s           │                          │
└──────────────────────┘                          │ poll loop sees .done
                                                  │ reads answer, returns
                                                  ▼
                                          step.fn() continues
```

Two directories per session, one sentinel file per task. The adapter writes-and-polls; the skill scans-and-dispatches.

---

## The contract

All paths are relative to the session's `intermediate/` directory.

**Task envelope** — `agent_inbox/<task_id>.task.json` — written by `AgentAdapter.complete()`, read by the skill:

```json
{
  "task_id": "abc123…",
  "step": "pass2",
  "context_label": "pass2:doc.md:chunk5",
  "system": "<full system prompt text>",
  "user":   "<full user prompt text>",
  "max_tokens": 10000,
  "timeout_seconds": 1800,
  "created_at": "2026-06-02T17:30:00Z"
}
```

**Answer envelope** — `agent_outbox/<task_id>.answer.json` — written by the skill subagent:

```json
{
  "task_id": "abc123…",
  "answer": "<the raw JSON string the pipeline expects>"
}
```

**Sentinel** — `agent_outbox/<task_id>.done` — zero-byte file created by the skill **after** the answer file. The adapter polls for this, not for `.answer.json`, so it never reads a half-written response.

**Atomicity rule** (both sides) — write to `<name>.tmp` then `os.rename` to the final name. Never write directly to the final path.

**`task_id`** — `sha256(system + "\n--user--\n" + user + "\n--ctx--\n" + context_label).hexdigest()`. Same inputs → same id → the existing answer is re-used (intra-session cache). Re-runs after a partial crash automatically pick up where they left off.

---

## Setting it up

### 1. Activate the profile

In `mykg_config.yaml`, set:

```yaml
profile: agent-claude-code
```

The `agent-claude-code` profile is bundled in both `mykg_config.yaml` (repo root) and `src/mykg/data/mykg_config.yaml` (packaging template). No API key is required.

### 2. Install the skill

Symlink the skill directory into your user-level skills folder:

```bash
ln -s "$(pwd)/src/mykg/data/skills/mykg" ~/.claude/skills/mykg
```

Restart Claude Code (or re-open the project) so the skill loader picks up the new entry.

### 3. Invoke

In Claude Code, type:

```
/mykg ./my_notes
```

The skill:

1. Confirms the active profile is `agent-claude-code`.
2. Launches `mykg extract-graph ./my_notes` in the background via `nohup`.
3. Watches `<session>/intermediate/agent_inbox/` for `*.task.json` files.
4. Dispatches one Agent-tool subagent per unanswered task (parallel calls per wave, up to the `pass2.max_workers` configured in the profile).
5. Sleeps 2 seconds between waves.
6. Exits when the pipeline subprocess exits, when `output/knowledge_graph.ttl` appears, or after 20 watch waves.

To resume after a 20-wave timeout, re-invoke:

```
/mykg --session 2026-06-02T17-30-00 --continue
```

The full skill body lives in `src/mykg/data/skills/mykg/SKILL.md`. It includes a CLI reference table for all six `mykg` subcommands and the exact subagent prompt template.

---

## Timeout and retry story

Agent mode uses the **same orchestrator retry path** as every other adapter. There is no agent-specific retry layer.

- The adapter's `complete()` polls the `.done` sentinel until `timeout_seconds` (default 1800). If no sentinel appears, it raises `TimeoutError`.
- A `TimeoutError` propagates to the orchestrator, which (for `is_llm_step=True` steps) automatically retries once.
- On the third attempt, the orchestrator's feedback path mutates the system prompt — producing a different `task_id` and therefore a different inbox file. The wasted second attempt cache-hits on the prior bad answer and costs one extra 2-second poll tick.

If the skill crashes or the user kills Claude Code, in-flight tasks stay in the inbox. The pipeline blocks until `timeout_seconds`, then fails the step. Re-invoking `/mykg --session <name> --continue` resurrects the inbox-watch loop and the pipeline resumes.

---

## Caching and re-runs

- Within a single session: a duplicate `complete()` call with identical `(system, user, context_label)` re-uses the existing `.answer.json` immediately — no inbox write, no skill dispatch.
- Across sessions: each session has its own `intermediate/agent_inbox/` and `agent_outbox/`. There is no cross-session cache by design.
- To force a re-prompt for a single task, delete the corresponding `<task_id>.done` (and optionally the `.answer.json`) before the next pipeline run.

---

## What stays unchanged

- The 12 pipeline steps in `src/mykg/pipeline.py`.
- All 14 LLM call sites across `pass1.py`, `pass2.py`, `name_normalizer.py`, `schema_merge.py`, `orphan_connector.py`, and `feedback.py`.
- All `prompts/*.txt` template files.
- The orchestrator's retry-once + feedback path.
- `ThreadPoolExecutor` parallelism in `pass1`, `pass2`, and `orphan_connect` — `max_workers` blocking threads each call `complete()` in parallel; the skill drains them in parallel waves.
- The five existing adapters (`anthropic`, `openai`, `openrouter`, `ollama`, `claude-cli`) — agent mode is additive.

---

## Limitations

- The skill loop is bounded at 20 waves per invocation to avoid runaway Claude Code sessions. Long pipelines require multiple `/mykg --continue` invocations.
- The agent provider does not record token counts in `llm.log` — the skill subagent's token usage is not visible to mykg.
- The skill produces best-effort JSON; the pipeline's own validators (TBox check, schema validate, ABox check) catch malformed output and trigger the existing feedback path.
- There is no heartbeat. A dead skill leaves in-flight pipeline threads blocked until `timeout_seconds`. If the user wants faster failure, Ctrl-C the pipeline subprocess and re-launch.
