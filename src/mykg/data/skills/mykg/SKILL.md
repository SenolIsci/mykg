---
name: mykg
description: Run the mykg knowledge-graph extractor in agent mode. Launches the mykg pipeline as a subprocess against a directory of Markdown files, then watches an inbox folder for LLM tasks and dispatches subagents to answer them. Use whenever the user types `/mykg <input_dir>` or asks to extract a knowledge graph in agent mode.
---

# mykg — agent mode runner

This skill drives the **mykg** knowledge-graph extractor when the active profile is `agent-claude-code`. In that profile, `mykg` does not call any LLM API directly — instead it writes task envelopes to a session-local `intermediate/agent_inbox/` directory and polls for `.done` sentinels in `intermediate/agent_outbox/`. This skill is the agent on the other side of that contract: it watches the inbox, dispatches one Agent-tool subagent per task, and writes the answers back.

The pipeline code, the orchestrator, all prompts, and all 12 pipeline steps are **unchanged**. Only the LLM delivery mechanism is different.

---

## When to invoke

Trigger this skill when the user:

- types `/mykg <input_dir>` to start a fresh run on a Markdown corpus
- types `/mykg --session <name> --continue` to resume a session whose pipeline subprocess died or whose 20-wave budget was exhausted
- asks to "run mykg in agent mode" or "extract a knowledge graph using subagents"

Do **not** invoke this skill when the user wants a normal API-backed run (`provider: anthropic`, `openai`, etc.) — for those, the user runs `mykg extract-graph` themselves directly.

---

## CLI reference

The mykg CLI has 6 subcommands. The skill normally only needs `extract-graph`, but the table is here for forwarding flags accurately.

| Subcommand | Purpose | Key flags |
| --- | --- | --- |
| `mykg init` | Create a starter `mykg_config.yaml` in the current directory. | `--force`, `--profile <name>`, `--model <id>`, `--api-key <key>` |
| `mykg extract-graph <input_dir>` | Run the 12-step pipeline on a Markdown corpus. | `--session <name>`, `--from-step <step>`, `--review`, `--base-schema <ttl>`, `--thesaurus <ttl>`, `--workers <N>`, `--confidence-agg mean\|max`, `--append`, `--obsidian-vault`, `--verbose`, `--log-file <path>`, `--output-dir <path>`, `--intermediate-dir <path>` |
| `mykg approve-schema` | Release the human-review gate after editing `schema.json`. | `--session <name>`, `--intermediate-dir <path>`, `--verbose`, `--log-file <path>` |
| `mykg walkthrough <session-name>` | Re-generate `walkthrough.md` for an existing session. | `--log-file <path>` |
| `mykg merge-graphs <session-a> <session-b>` | Merge two completed sessions into a new unified session. | `--from-step <step>`, `--session-name <name>`, `--verbose`, `--log-file <path>`, `--base-schema <ttl>`, `--thesaurus <ttl>`, `--human-review` |
| `mykg parse-docs <input> <output>` | Convert PDFs/DOCX/images to Markdown via MinerU. | passes through extra args to mineru |

Pipeline step names (for `--from-step`): `preprocess`, `ingest`, `pass1`, `schema_validate`, `human_review`, `schema_flatten`, `pass2`, `normalize_names`, `assemble`, `orphan_score`, `orphan_connect`, `validate_graph`.

---

## What you do — overview

1. **Parse the user's invocation.** Determine `input_dir`, optional `--session <name>`, and any pass-through flags from the `/mykg ...` arguments.
2. **Confirm agent mode is active.** Check that `mykg_config.yaml` has `profile: agent-claude-code` (or instruct the user to change it). If not, abort with a clear message.
3. **Launch the pipeline.** Run `mykg extract-graph` in the background via `nohup` so it survives this skill turn. Capture the session directory.
4. **Watch the inbox.** Loop scanning `<session>/intermediate/agent_inbox/`, dispatch one Agent-tool subagent per unanswered task (parallel calls in one response, up to the configured worker count), sleep 2 seconds between waves.
5. **Exit cleanly.** Stop when the pipeline subprocess exits, when `output/knowledge_graph.ttl` appears, or after **20 watch waves**. If the pipeline is still running after 20 waves, tell the user to re-invoke `/mykg --session <name> --continue` to resume.

---

## Step 1 — parse the invocation

The user typed something like one of:

```
/mykg ./docs
/mykg ~/notes --review --workers 8
/mykg --session 2026-06-02T17-30-00 --continue
/mykg ./corpus --from-step pass2 --session 2026-06-02T17-30-00
```

Extract:
- `INPUT_DIR` (or empty for `--continue`)
- `SESSION_NAME` (from `--session`)
- `EXTRA_FLAGS` (everything else — forward verbatim)

---

## Step 2 — confirm active profile

Run this Bash block to verify `agent-claude-code` is the active profile:

```bash
grep -E '^profile:\s' mykg_config.yaml
```

The output must be `profile: agent-claude-code`. If it is not, stop and tell the user:

> Active profile is not `agent-claude-code`. Edit `mykg_config.yaml` and set `profile: agent-claude-code`, then re-run `/mykg`.

---

## Step 3 — launch the pipeline (fresh run)

For a fresh run (no `--session` or `--session` but no existing session dir), launch:

```bash
SESSIONS_DIR=$(grep -E '^\s+sessions_dir:' mykg_config.yaml | head -1 | awk '{print $2}' || echo sessions)
mkdir -p "$SESSIONS_DIR"

# Auto-generated session timestamp; mykg will pick the same name and create the dir.
nohup uv run mykg extract-graph "$INPUT_DIR" $EXTRA_FLAGS \
  > /tmp/mykg_run.out 2>&1 &
echo $! > /tmp/mykg.pid

# Wait briefly for the session folder to materialise.
for i in $(seq 1 30); do
  SESSION_ROOT=$(ls -td "$SESSIONS_DIR"/* 2>/dev/null | head -1)
  if [ -n "$SESSION_ROOT" ] && [ -d "$SESSION_ROOT/intermediate/agent_inbox" ]; then
    echo "Session: $SESSION_ROOT"
    break
  fi
  sleep 1
done
```

For a `--continue` run on an existing session:

```bash
SESSION_ROOT="$SESSIONS_DIR/$SESSION_NAME"
if [ ! -d "$SESSION_ROOT" ]; then
  echo "Session $SESSION_NAME not found under $SESSIONS_DIR" >&2
  exit 1
fi
nohup uv run mykg extract-graph "$INPUT_DIR" --session "$SESSION_NAME" $EXTRA_FLAGS \
  > /tmp/mykg_run.out 2>&1 &
echo $! > /tmp/mykg.pid
```

Capture:
- `SESSION_ROOT` — the absolute path of the session directory.
- `INBOX_DIR=$SESSION_ROOT/intermediate/agent_inbox`
- `OUTBOX_DIR=$SESSION_ROOT/intermediate/agent_outbox`
- `MYKG_PID=$(cat /tmp/mykg.pid)`

---

## Step 4 — the watch loop

This is the main body. Up to **20 waves**, each wave does:

1. Scan the inbox for `*.task.json` files that do **not** have a matching `.done` in the outbox.
2. For each task (up to `MAX_TASKS_PER_WAVE = 8`), make one Agent-tool subagent call **in parallel within a single message**.
3. Check `MYKG_PID` is still alive. If not, exit.
4. Sleep 2 seconds before the next wave.

```bash
# Once per wave:
ls -1 "$INBOX_DIR"/*.task.json 2>/dev/null | while read TASK_PATH; do
  TASK_ID=$(basename "$TASK_PATH" .task.json)
  DONE_PATH="$OUTBOX_DIR/$TASK_ID.done"
  if [ ! -f "$DONE_PATH" ]; then
    echo "$TASK_PATH"
  fi
done | head -8
```

For every line printed above, **dispatch one Agent tool call** using the subagent prompt template below. All dispatches in a single wave **must go in the same assistant message** so they run in parallel.

Between waves:

```bash
if ! kill -0 "$MYKG_PID" 2>/dev/null; then
  echo "Pipeline subprocess exited."
  break
fi
if [ -f "$SESSION_ROOT/output/knowledge_graph.ttl" ]; then
  echo "Pipeline produced knowledge_graph.ttl — done."
  break
fi
sleep 2
```

Track the wave count yourself. After 20 waves, tell the user:

> Watch budget exhausted after 20 waves. Pipeline is still running (PID `$MYKG_PID`). Re-invoke `/mykg --session <name> --continue` to keep draining the inbox.

---

## Step 5 — subagent prompt template

Each Agent-tool dispatch in step 4 uses **exactly this prompt** (substitute `$TASK_PATH` and `$OUTBOX_DIR`):

```
You are an mykg agent-mode worker. Your only job is to answer the LLM task in
the file shown below and write the result atomically to the outbox.

Task file:   $TASK_PATH
Outbox dir:  $OUTBOX_DIR

Procedure:

1. Read the JSON file at $TASK_PATH. It has these fields:
   - task_id: a 64-char sha256 hex string
   - step: which pipeline step (e.g. "pass1", "pass2", "normalize_names")
   - context_label: short label for debugging
   - system: the system prompt the pipeline wants you to respond to
   - user: the user prompt
   - max_tokens: integer
   - timeout_seconds: integer

2. Treat the `system` field as the instructions you must follow and the `user`
   field as the user message. Produce the response the pipeline expects — for
   pass1 that is a JSON object with `concepts` and `properties`; for pass2 that
   is `{nodes: [...], edges: [...]}`; for normalize_names that is a mappings
   object; for orphan_connect that is an array of edges. The `system` prompt
   itself tells you the exact schema in detail. Output **only** the JSON
   (no prose, no markdown fences).

3. Write the answer JSON to a string and build the answer envelope:
   {"task_id": "<the task_id from the task file>", "answer": "<your JSON string>"}

4. Write the answer atomically:
   a. Write the envelope JSON to $OUTBOX_DIR/<task_id>.answer.json.tmp
   b. Rename it to $OUTBOX_DIR/<task_id>.answer.json (atomic on POSIX)
   c. Touch $OUTBOX_DIR/<task_id>.done  (zero-byte sentinel)

   The pipeline polls for the `.done` sentinel — never write `.done` before
   the `.answer.json` file is fully on disk.

5. Report a one-line summary: which step, which context_label, how big the
   answer was. Do not write anything else to the outbox.

If the system+user prompt is genuinely ambiguous or you cannot produce valid
JSON, still write a best-effort response — the pipeline has its own retry +
feedback path and will repair downstream. Never leave a task unanswered: a
missing `.done` sentinel will block the pipeline until its 1800-second
timeout.
```

---

## Step 6 — final report

When the loop exits, print:

```bash
echo "Session:  $SESSION_ROOT"
echo "PID:      $MYKG_PID (alive: $(kill -0 $MYKG_PID 2>/dev/null && echo yes || echo no))"
echo "Inbox:    $(ls -1 $INBOX_DIR/*.task.json 2>/dev/null | wc -l) total tasks"
echo "Answered: $(ls -1 $OUTBOX_DIR/*.done 2>/dev/null | wc -l)"
if [ -f "$SESSION_ROOT/output/knowledge_graph.ttl" ]; then
  echo "Output:   $SESSION_ROOT/output/knowledge_graph.ttl"
fi
```

---

## Notes for the implementer

- **Atomicity matters.** Always write `<id>.answer.json.tmp` then `mv` it to the final name *before* touching `<id>.done`. The adapter polls the `.done` sentinel, not the answer file.
- **Caching is automatic.** If you accidentally answer the same task twice the second write overwrites — the adapter only reads the most recent answer once `.done` exists.
- **Do not validate.** The pipeline has its own retry + LLM-feedback path. If your JSON is malformed, the pipeline catches it and dispatches a corrective task on its own.
- **Stay parallel.** Within a wave, multiple Agent-tool calls in one assistant message run concurrently. Sequential dispatch defeats the purpose.
- **Stay bounded.** 20 waves is a hard limit. If a run needs more, the user re-invokes `/mykg --session <name> --continue`.
