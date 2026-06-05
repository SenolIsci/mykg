---
name: mykg
description: Run mykg knowledge-graph commands inside Claude Code from one slash command `/mykg`. The user describes intent in natural language (extract, append, resume, approve, walkthrough, parse-docs); the skill parses intent, builds the right `mykg` CLI command from the live `--help` output, confirms, runs it, and drives the inbox/outbox watch loop for LLM-bearing commands (extract-graph). Excludes `mykg init` (interactive shell command) and `mykg merge-graphs` (follow-up planning).
---

# mykg — single slash command, intent-driven CLI dispatcher

This skill is the agent-mode driver for **mykg**. The user types `/mykg <free text>` describing what they want; the skill parses the intent, assembles the matching `mykg` CLI command (with live `--help` as ground truth for flags), confirms expensive actions, and executes. For LLM-bearing subcommands (`extract-graph`), it then drives the inbox/outbox watch loop. For synchronous subcommands (`walkthrough`, `approve-schema`, `parse-docs`), it shells out and reports.

The pipeline code, the orchestrator, all prompts, all 12 pipeline steps, and the inbox/outbox contract are **unchanged**. This skill only changes how `mykg` is invoked from inside Claude Code.

---

## Default behaviour — fresh session unless told otherwise

**The default is to create a NEW session for every `extract-graph` invocation.** Pass no `--session` flag to `mykg extract-graph` and let mykg auto-create a fresh timestamped session under `mykg_sessions/`.

Only reuse an existing session when the user *explicitly* signals it. Explicit signals are any of:

- The verbs **resume**, **continue**, **redo**, **append**, **approve**, **walkthrough**.
- A direct reference: **"the last session"**, **"the existing session"**, **"the same session"**, or a literal session name (typed as `--session <name>` or "session <name>").
- A flag whose semantics require a session: **`--append`**, **`--from-step <step>`**.
- A subcommand that inherently targets a completed session: **`approve-schema`**, **`walkthrough`**.

For anything else — including bare `/mykg <dir>`, `/mykg extract <dir>`, `/mykg extract more from <dir>`, "extract this folder" — pass **NO** `--session` flag. Words like "more", "again", "now", "next" are NOT explicit signals; they trigger a fresh session like every other plain extract command.

Never auto-detect-most-recent purely because a previous skill turn produced a session. The previous-turn signal only matters when the *current* user message also contains one of the explicit signals above.

When in doubt, default to fresh and surface the choice in the Stage 2 confirmation.

---

## When to invoke — intent examples

Trigger this skill whenever the user types `/mykg <anything>`. Map the intent to a `mykg` CLI command using the table below as a guide; for anything not covered, fall back to the closest match and confirm before running.

| User typed | Skill should run |
| --- | --- |
| `/mykg extract this folder` (when cwd contains md files) | `mykg extract-graph .` (**fresh session — no `--session`**) |
| `/mykg ./docs` | `mykg extract-graph ./docs` (legacy positional alias — **fresh session — no `--session`**) |
| `/mykg extract ./docs` | `mykg extract-graph ./docs` (**fresh session — no `--session`**) |
| `/mykg extract more from ./more_docs` | `mykg extract-graph ./more_docs` (**fresh session** — "more" is NOT an explicit reuse signal; this is just another extract) |
| `/mykg extract ./docs with human review` | `mykg extract-graph ./docs --review` (**fresh session — no `--session`**) |
| `/mykg append the new notes in ./docs` | `mykg extract-graph ./docs --append --session <auto-detect-most-recent>` (explicit reuse via `append`) |
| `/mykg resume the last session` | `mykg extract-graph --session <most-recent>` (explicit reuse via `resume the last session`) |
| `/mykg approve the schema` | `mykg approve-schema --session <most-recent>` (session-only subcommand) |
| `/mykg make a walkthrough` | `mykg walkthrough --session <most-recent>` (session-only subcommand) |
| `/mykg make a walkthrough for 2026-06-02T17-30-00` | `mykg walkthrough --session 2026-06-02T17-30-00` (literal session name) |
| `/mykg convert pdfs in ./inbox to ./md` | `mykg parse-docs --input ./inbox --output ./md` (no session concept) |
| `/mykg from-step orphan_connect on the last session` | `mykg extract-graph --session <most-recent> --from-step orphan_connect` (explicit reuse via `the last session` + `--from-step`) |
| `/mykg rerun orphan-connect from scratch on the last session` | `mykg extract-graph --session <most-recent> --from-step orphan_connect_fullsweep` (explicit reuse via `the last session`) |
| `/mykg redo orphans but keep what we already confirmed` | `mykg extract-graph --session <most-recent> --from-step orphan_connect_incremental` (explicit reuse via `redo` — `--from-step` always operates on an existing session) |
| `/mykg init` | refuse: "Run `mykg init` from a shell — it is interactive." |
| `/mykg merge sessions A and B` | refuse: "Skill support for `mykg merge-graphs` is planned in a follow-up. Run from a shell." |

---

## Discovering CLI flags

The skill MUST NOT hand-code flag tables. The single source of truth is the live `--help` output. Once at the top of each skill turn, run the help commands for the subcommands you might dispatch and cache the output in shell variables for the rest of the turn:

```bash
EXTRACT_HELP=$(uv run mykg extract-graph --help 2>&1)
WALKTHROUGH_HELP=$(uv run mykg walkthrough --help 2>&1)
APPROVE_HELP=$(uv run mykg approve-schema --help 2>&1)
PARSE_HELP=$(uv run mykg parse-docs --help 2>&1)
```

Use these cached values to:
- validate that any flag the user mentioned actually exists,
- complain if the user typed a non-existent flag,
- automatically pick up new flags (e.g. tomorrow a `--use-cache` flag is added) with zero skill changes.

---

## Stage 1 — parse intent

From the user's `/mykg <free text>` message extract:

1. **Verb** — extract / append / approve / walkthrough / parse / resume / init / merge → maps to a CLI subcommand (or to a refusal).
2. **Input dir** — the path the user named, or `.` if they said "this folder", or absent for session-only commands.
3. **Session** — **default: do not pass `--session` at all** so mykg auto-creates a fresh timestamped session. Only override the default when the current user message contains an explicit reuse signal (see "Default behaviour" above). Resolution order:
   1. **Literal session name.** User typed `--session <name>` or "session <name>" → use that exact name.
   2. **Explicit reuse verb / phrase.** User said one of: **resume**, **continue**, **redo**, **append**, **approve**, **walkthrough**, **"the last session"**, **"the existing session"**, **"the same session"** → auto-detect the most-recent session: list `$SESSIONS_DIR` (read `sessions_dir` from `mykg_config.yaml`, default `mykg_sessions`), sort by mtime, pick newest.
   3. **Reuse-implying flag.** User specified `--append` or `--from-step <step>` → auto-detect-most-recent (these flags only make sense against an existing session).
   4. **Session-only subcommand.** Verb is `approve-schema` or `walkthrough` → auto-detect-most-recent.
   5. **Otherwise.** Do NOT pass `--session`. mykg creates a fresh session. This is the path for bare `/mykg <dir>`, `/mykg extract <dir>`, `/mykg extract more from <dir>`, "extract this folder", etc.
   6. **Reuse required but missing.** If rules 2/3/4 fire but no session exists under `$SESSIONS_DIR`, fail clearly: `"No existing sessions under <SESSIONS_DIR>. Run /mykg extract <dir> first to create one."`

**Never auto-detect-most-recent purely because a previous skill turn produced a session.** The previous-turn memory only matters when the *current* user message also contains one of the explicit signals in rules 1-4. A bare `/mykg ./more_docs` after a prior session must still create a fresh session.
4. **Flags** — anything the user named that maps to a flag the cached `--help` confirms (`--review`, `--append`, `--from-step <step>`, `--workers <N>`, `--obsidian-vault`, `--base-schema`, `--thesaurus`, `--verbose`, `--confidence-agg`, etc.). Forward verbatim.

`extract-graph` without `--append` or `--from-step` does not need a pre-existing session — it auto-creates one.

### Special `--from-step` values for the orphan-connect step

`--from-step` accepts every pipeline step name (`preprocess`, `ingest`, `pass1`, `schema_validate`, `human_review`, `schema_flatten`, `pass2`, `normalize_names`, `assemble`, `orphan_score`, `orphan_connect`, `validate_graph`) plus **two aliases** specific to the orphan-connection step. When the user describes intent that maps to either of these, pick the alias rather than bare `orphan_connect`:

| `--from-step` value | Semantics | Pick when the user says |
| --- | --- | --- |
| `orphan_connect` | Equivalent to `orphan_connect_fullsweep` — bare form is the default. | "rerun orphan connect", "redo the orphan pass" (with no qualifier) |
| `orphan_connect_fullsweep` | Deletes `orphan_connections.json`, `orphan_log.json`, `schema_gap_proposals.json` + all downstream outputs. The orphan-connect step recomputes every group from scratch — every orphan is re-sent to the LLM. Expensive but gives a clean redo. | "rerun from scratch", "fullsweep", "clean redo", "schema changed since last run", "model upgrade" |
| `orphan_connect_incremental` | Deletes downstream outputs **but preserves** `orphan_connections.json` + `orphan_log.json`. The step loads the prior file as a seed, treats every orphan endpoint already in a confirmed edge as "resolved", and only sends the remaining uncovered groups to the LLM. Old confirmations are merged with new ones. Cheap and additive. | "redo orphans but keep what we have", "additive", "only do the new ones", "after `--append`" |

If the user is ambiguous (e.g. "rerun orphans"), confirm in Stage 2 which one they want by presenting both options in one line.

**Precondition — `schema_max_restarts` must be ≥ 1** for `orphan_connect_fullsweep` and `orphan_connect_incremental` to fully exercise the schema-gap auto-proposal loop. With `schema_max_restarts: 0` (the shipped default in every profile) the aliases still execute, but the LLM is never asked to propose new schema properties for orphans the current schema cannot connect — those orphans remain orphans. The skill MUST handle this transparently via the auto-bump procedure below.

#### Auto-bump procedure (applies whenever Stage 1 lands on `orphan_connect_fullsweep` or `orphan_connect_incremental`)

Before launching the run, check the active profile's `schema_max_restarts` and temporarily bump it to `1` if needed:

```bash
# Resolve active profile (top-of-file `profile:` line).
ACTIVE_PROFILE=$(grep -E '^profile:\s' mykg_config.yaml | awk '{print $2}')

# Read schema_max_restarts inside the active profile block.
CURRENT=$(awk "/^  ${ACTIVE_PROFILE}:/,/^  [a-z]/" mykg_config.yaml \
  | grep -E '^\s+schema_max_restarts:' | head -1 | awk '{print $2}')

NEEDS_BUMP=0
if [ "$CURRENT" = "0" ]; then
  NEEDS_BUMP=1
fi
```

If `NEEDS_BUMP=1`, edit `mykg_config.yaml` in-place to set the active profile's `schema_max_restarts: 1`, then surface the change to the user as part of the Stage 2 confirmation:

```
About to run: uv run mykg extract-graph --session 2026-06-02T17-30-00 --from-step orphan_connect_fullsweep

Note: schema_max_restarts is currently 0 in profile `${ACTIVE_PROFILE}`. I will:
  1. Temporarily bump it to 1 (so the LLM may propose new schema properties for unconnected orphans).
  2. Run the alias.
  3. Revert schema_max_restarts back to 0 after the run finishes.

Reply "yes" to proceed, "no" to skip, or "keep at 1" to leave the value bumped permanently.
```

After the run finishes (success OR failure), **always revert** `schema_max_restarts: 1` → `0` in the same profile unless the user explicitly said "keep at 1". The bump is per-invocation; the configured behaviour returns to baseline. Emit a final line: `[skill] Restored schema_max_restarts: 0 in profile '${ACTIVE_PROFILE}'.`

The YAML edit is **scoped to the active profile block only** — there are multiple `schema_max_restarts:` lines in the file (one per profile). Use a Python sub-shell with a regex anchored on `^  ${ACTIVE_PROFILE}:` and looking inside the block until the next sibling `^  [a-z]` to target the right line:

```bash
python3 - <<PYEOF
import re, pathlib
p = pathlib.Path("mykg_config.yaml")
txt = p.read_text()
profile = "$ACTIVE_PROFILE"
new_value = "$NEW_VALUE"   # 1 to bump, 0 to revert
pat = re.compile(
    rf"(^  {re.escape(profile)}:.*?^\s+schema_max_restarts:\s*)\d+(\s*(?:#[^\n]*)?$)",
    re.MULTILINE | re.DOTALL,
)
out, n = pat.subn(rf"\g<1>{new_value}\g<2>", txt, count=1)
if n != 1:
    raise SystemExit(f"Could not patch schema_max_restarts in profile '{profile}'")
p.write_text(out)
PYEOF
```

After every YAML edit, show `git diff --no-color mykg_config.yaml | head -8` to the user as proof of the change. Never edit YAML without surfacing the diff.

---

## Stage 2 — confirm intent before running

For destructive or expensive actions (anything that calls LLMs, anything `--from-step`, anything `--append`), restate the parsed command in one line and ask the user to confirm:

```
About to run: uv run mykg extract-graph ./docs --append --session 2026-06-02T17-30-00

Reply "yes" to run, or correct me.
```

For obviously safe actions (`walkthrough`, `parse-docs`), skip the confirmation and run.

**Fresh-vs-reuse ambiguity:** when the user's intent is plausibly either a fresh extract or a continuation of a recent session (e.g. they typed `/mykg ./more_docs` and a session exists from earlier today), the proposed command MUST use a fresh session (no `--session`). Surface the alternative explicitly in the confirmation line so the user can correct it in one word:

```
About to run (fresh session): uv run mykg extract-graph ./more_docs

Reply "yes" to run, or say "resume the last session" / "append to the last session" to reuse session <most-recent>.
```

Never silently inherit a prior session.

**Orphan re-entry aliases require an extra check:** if Stage 1 resolved the command to `--from-step orphan_connect_fullsweep` or `--from-step orphan_connect_incremental`, follow the **auto-bump procedure** in the "Special `--from-step` values for the orphan-connect step" subsection of Stage 1 *before* running. That procedure temporarily sets the active profile's `schema_max_restarts` to `1`, surfaces the change in this Stage 2 confirmation, and always reverts the value after the run unless the user explicitly says "keep at 1".

---

## Stage 3 — verify agent mode is active

Two-step check. The first one catches the common "user installed mykg but never ran init" case before we waste a confusing CLI error.

**Step 3a — does `mykg_config.yaml` exist at all?**

```bash
if [ ! -f mykg_config.yaml ]; then
  echo "No mykg_config.yaml found in $(pwd)."
  echo "Run \`mykg init --profile agent-claude-code\` from a shell first, then re-invoke /mykg."
  exit 1
fi
```

If the file is missing, stop and tell the user to run `mykg init --profile agent-claude-code` from a shell. Do not try to call the CLI.

**Step 3b — is the active profile `agent-claude-code`?**

```bash
grep -E '^profile:\s' mykg_config.yaml
```

The output must be `profile: agent-claude-code`. If it is not, stop and tell the user:

> Active profile is not `agent-claude-code`. Edit `mykg_config.yaml` and set `profile: agent-claude-code`, or run `mykg <subcommand>` from a shell directly.

---

## Stage 4 — execute

Three execution paths depending on the subcommand the parser landed on.

### Stage 4a — LLM-bearing path (`extract-graph`)

For a fresh run:

```bash
SESSIONS_DIR=$(grep -E '^\s+sessions_dir:' mykg_config.yaml | head -1 | awk '{print $2}' || echo sessions)
mkdir -p "$SESSIONS_DIR"

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

For a resume / append / from-step run on an existing session:

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
- `SESSION_ROOT` — absolute path of the session directory.
- `INBOX_DIR=$SESSION_ROOT/intermediate/agent_inbox`
- `OUTBOX_DIR=$SESSION_ROOT/intermediate/agent_outbox`
- `MYKG_PID=$(cat /tmp/mykg.pid)`

Then enter the watch loop. Up to **20 waves**, each wave does:

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

For every line printed above, **dispatch one Agent tool call** using the subagent prompt template at the bottom of this file. All dispatches in a single wave **must go in the same assistant message** so they run in parallel.

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

> Watch budget exhausted after 20 waves. Pipeline is still running (PID `$MYKG_PID`). Re-invoke `/mykg resume the last session` (or `/mykg --session <name> --continue`) to keep draining the inbox.

### Stage 4b — synchronous path (`walkthrough`, `approve-schema`, `parse-docs`)

These subcommands do not write to the inbox. Run them in the foreground and report the resulting file path.

**`walkthrough`:**

```bash
uv run mykg walkthrough $ARGS
echo "Walkthrough: $SESSION_ROOT/walkthrough.md"
```

**`approve-schema`:**

```bash
uv run mykg approve-schema $ARGS
echo "Approved: $SESSION_ROOT/intermediate/schema_approved.flag"
```

**`parse-docs`:**

```bash
uv run mykg parse-docs $ARGS
echo "Converted markdown under: $OUTPUT_DIR"
```

Capture stdout/stderr; surface any non-zero exit to the user verbatim.

### Stage 4c — refused (`init`, `merge-graphs`)

- `/mykg init` → reply: "Run `mykg init` from a shell. It is interactive."
- `/mykg merge ...` → reply: "Skill support is planned in a follow-up. Run from a shell."

Do not dispatch anything.

---

## Stage 5 — final report

When the loop exits (or the synchronous command returns), print:

```bash
echo "Session:  $SESSION_ROOT"
echo "PID:      $MYKG_PID (alive: $(kill -0 $MYKG_PID 2>/dev/null && echo yes || echo no))"
echo "Inbox:    $(ls -1 $INBOX_DIR/*.task.json 2>/dev/null | wc -l) total tasks"
echo "Answered: $(ls -1 $OUTBOX_DIR/*.done 2>/dev/null | wc -l)"
if [ -f "$SESSION_ROOT/output/knowledge_graph.ttl" ]; then
  echo "Output:   $SESSION_ROOT/output/knowledge_graph.ttl"
fi
```

For synchronous paths, just print the produced file path.

---

## Notes for the implementer

- **Atomicity matters (LLM-bearing path).** Always write `<id>.answer.json.tmp` then `mv` it to the final name *before* touching `<id>.done`. The adapter polls the `.done` sentinel, not the answer file.
- **Caching is automatic.** If you accidentally answer the same task twice the second write overwrites — the adapter only reads the most recent answer once `.done` exists.
- **Do not validate.** The pipeline has its own retry + LLM-feedback path. If your JSON is malformed, the pipeline catches it and dispatches a corrective task on its own.
- **Stay parallel (LLM-bearing path).** Within a wave, multiple Agent-tool calls in one assistant message run concurrently. Sequential dispatch defeats the purpose.
- **Stay bounded.** 20 waves is a hard limit. If a run needs more, the user re-invokes `/mykg resume the last session`.
- **Synchronous paths are trivial.** No atomicity or parallelism concerns; just shell out and report.

---

## Subagent prompt template

Each Agent-tool dispatch in Stage 4a uses **exactly this prompt** (substitute `$TASK_PATH` and `$OUTBOX_DIR`):

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
