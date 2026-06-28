---
name: mykg
description: Run mykg knowledge-graph commands inside Claude Code from one slash command `/mykg`. The user describes intent in natural language (extract, append, resume, approve, walkthrough, parse-docs, fetch-web, query); the skill parses intent, builds the right `mykg` CLI command from the live `--help` output, confirms, runs it, and drives the inbox/outbox watch loop for LLM-bearing commands (extract-graph). For read-only queries, prefers MCP tools when the mykg MCP server is online, falling back to reading session files directly. Ensures `.mcp.json` is configured (with user approval). Excludes `mykg init` (interactive shell command) and `mykg merge-graphs` (follow-up planning).
---

# mykg — single slash command, intent-driven CLI dispatcher

This skill is the agent-mode driver for **mykg**. The user types `/mykg <free text>` describing what they want; the skill parses the intent, assembles the matching `mykg` CLI command (with live `--help` as ground truth for flags), confirms expensive actions, and executes. For LLM-bearing subcommands (`extract-graph`), it then drives the inbox/outbox watch loop. For synchronous subcommands (`walkthrough`, `approve-schema`, `parse-docs`), it shells out and reports. For the read-only `query` verb, it prefers MCP tools when the mykg MCP server is online, falling back to reading session files directly when MCP is unavailable.

The pipeline code, the orchestrator, all prompts, all 12 pipeline steps, and the inbox/outbox contract are **unchanged**. This skill only changes how `mykg` is invoked from inside Claude Code.

---

## Read before answering — discipline rule

Before answering any domain question about the corpus this project's mykg sessions cover, **read the latest session's graph files first**. Your training data is not grounded in this project's source documents; the graph is. Use `/mykg query <question>` (Stage 4d below) to do this — it returns the relevant nodes/edges/notes into your context so you can answer from them rather than guessing.

This rule applies to *every* `/mykg query …` invocation and to every domain question asked outside the skill *when* the project's CLAUDE.md carries the managed mykg-section block (installed by `mykg init --profile agent-claude-code`).

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
| `/mykg append and grow schema from ./docs` | `mykg extract-graph ./docs --append-with-grow-schema --session <auto-detect-most-recent>` (explicit reuse via `append`; locked Pass 1 runs over changed files to expand the schema) |
| `/mykg expand the schema with new docs in ./docs` | `mykg extract-graph ./docs --append-with-grow-schema --session <auto-detect-most-recent>` ("expand schema" → `--append-with-grow-schema`) |
| `/mykg resume the last session` | `mykg extract-graph --session <most-recent>` (explicit reuse via `resume the last session`) |
| `/mykg approve the schema` | `mykg approve-schema --session <most-recent>` (session-only subcommand) |
| `/mykg make a walkthrough` | `mykg walkthrough --session <most-recent>` (session-only subcommand) |
| `/mykg make a walkthrough for 2026-06-02T17-30-00` | `mykg walkthrough --session 2026-06-02T17-30-00` (literal session name) |
| `/mykg convert pdfs in ./inbox to ./md` | `mykg parse-docs --input ./inbox --output ./md` (no session concept) |
| `/mykg fetch https://example.com` | `mykg fetch-web https://example.com` (no session concept) |
| `/mykg fetch https://example.com into ./my_output_dir` (user names the output folder) | `mykg fetch-web https://example.com --output ./my_output_dir` (no session concept) |
| `/mykg fetch https://example.com and extract` | `mykg fetch-web https://example.com`, then on success `mykg extract-graph <printed output dir>` (**fresh session**) — chained two-step intent |
| `/mykg download the github repo SenolIsci/mykg` | `mykg fetch-web https://github.com/SenolIsci/mykg` (GitHub URL → clone path, no session concept) |
| `/mykg fetch these urls: urls.txt into ./mykg_web_fetch/batch` | `mykg fetch-web --url-list urls.txt --output ./mykg_web_fetch/batch` (no session concept) |
| `/mykg fetch these urls: <url1> <url2> <url3> ...` (URLs typed inline, not a file path) | write each URL on its own line to a temp file `mykg_urls.txt` (in cwd), then `mykg fetch-web --url-list mykg_urls.txt --output ./mykg_web_fetch/batch` (no session concept) |
| `/mykg fetch these urls: <url1> <url2> <url3> ... and extract` (URLs typed inline) | same temp-file step as above, then `mykg fetch-web --url-list mykg_urls.txt --output ./mykg_web_fetch/batch`; on success, for **each** per-seed output subdir reported in the manifest, run `mykg extract-graph <subdir>` (**fresh session per subdir**) — chained multi-seed intent |
| `/mykg query who is Alice` | read-only — Stage 4d on the latest session; vault-first because the phrasing names an entity (wiki-style) |
| `/mykg query what does the wiki say about <topic>` | read-only — Stage 4d on the latest session; **vault path** (`obsidian_vault/`); word "wiki" is explicit |
| `/mykg query most connected node in the knowledge graph` | read-only — Stage 4d on the latest session; **jsonl path** (`nodes.jsonl` + `edges.jsonl`); words "knowledge graph" / "most connected" are structural |
| `/mykg query which entities link Alice to Bob` | read-only — Stage 4d on the latest session; **jsonl path**; relationship-traversal question |
| `/mykg query <free text> on session <name>` | read-only — Stage 4d on the named session instead of the latest |
| `/mykg from-step orphan_connect on the last session` | `mykg extract-graph --session <most-recent> --from-step orphan_connect` (explicit reuse via `the last session` + `--from-step`) |
| `/mykg rerun orphan-connect from scratch on the last session` | `mykg extract-graph --session <most-recent> --from-step orphan_connect_fullsweep` (explicit reuse via `the last session`) |
| `/mykg redo orphans but keep what we already confirmed` | `mykg extract-graph --session <most-recent> --from-step orphan_connect_incremental` (explicit reuse via `redo` — `--from-step` always operates on an existing session) |
| `/mykg start mcp server` | `mykg mcp-serve --transport streamable_http --port 3100` (starts MCP server on HTTP; no session concept) |
| `/mykg start mcp` | `mykg mcp-serve` (starts MCP server with defaults from config; no session concept) |
| `/mykg start mcp for session <name>` | `mykg mcp-serve --session <name>` (MCP server for a specific session) |
| `/mykg stop mcp` | `mykg mcp-serve --stop` (stops a running HTTP MCP server) |
| `/mykg mcp status` | check if MCP server is running: `ps aux \| grep "mcp-serve" \| grep -v grep` |
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
FETCH_HELP=$(uv run mykg fetch-web --help 2>&1)
```

Use these cached values to:
- validate that any flag the user mentioned actually exists,
- complain if the user typed a non-existent flag,
- automatically pick up new flags (e.g. tomorrow a `--use-cache` flag is added) with zero skill changes.

---

## MCP configuration — ensure `.mcp.json` exists

At the start of every skill turn, check whether the project has a `.mcp.json` file that configures the mykg MCP server for Claude Code. If it does not exist, **ask the user for approval** before creating it:

```
I noticed this project doesn't have a .mcp.json file to configure the mykg
MCP server for Claude Code. The MCP server provides 14 structured read-only
tools (search, neighbors, shortest path, hub nodes, subgraph queries, etc.)
that are faster and more precise than manual grep/Read for graph queries.

Shall I create .mcp.json with this content?

  {
    "mcpServers": {
      "mykg": {
        "command": "mykg",
        "args": ["mcp-serve"]
      }
    }
  }

This tells Claude Code to start `mykg mcp-serve` as an MCP subprocess,
making the `mcp__mykg__*` tools available in this session. The server
auto-discovers the latest session on startup.
```

If the user approves, write the file. If the user declines, proceed without it — the skill falls back to manual grep/Read in Stage 4d as before.

If `.mcp.json` already exists but does **not** contain a `mykg` server entry, ask the user whether to add one (preserve the existing entries). If it already has a `mykg` entry, do nothing.

**Do not create `.mcp.json` without user approval.** This file affects the Claude Code session and the user must consent.

---

## Stage 1 — parse intent

From the user's `/mykg <free text>` message extract:

1. **Verb** — extract / append / approve / walkthrough / parse / fetch / download / resume / init / merge / **query** → maps to a CLI subcommand, a refusal, or the read-only file-read path (`query`). Fetch / download (URL or GitHub repo) maps to `fetch-web` — no session, same category as `parse-docs`.
2. **Input dir** — the path the user named, or `.` if they said "this folder", or absent for session-only commands (including `query`).
3. **Session** — **default: do not pass `--session` at all** so mykg auto-creates a fresh timestamped session. Only override the default when the current user message contains an explicit reuse signal (see "Default behaviour" above). Resolution order:
   1. **Literal session name.** User typed `--session <name>` or "session <name>" → use that exact name.
   2. **Explicit reuse verb / phrase.** User said one of: **resume**, **continue**, **redo**, **append**, **approve**, **walkthrough**, **query**, **"the last session"**, **"the existing session"**, **"the same session"** → auto-detect the most-recent session: list `$SESSIONS_DIR` (read `sessions_dir` from `mykg_config.yaml`, default `mykg_sessions`), sort by mtime, pick newest.
   3. **Reuse-implying flag.** User specified `--append` or `--from-step <step>` → auto-detect-most-recent (these flags only make sense against an existing session).
   4. **Session-only verb.** Verb is `approve-schema`, `walkthrough`, or `query` → auto-detect-most-recent. (`query` is read-only and always operates against an existing session.)
   5. **Otherwise.** Do NOT pass `--session`. mykg creates a fresh session. This is the path for bare `/mykg <dir>`, `/mykg extract <dir>`, `/mykg extract more from <dir>`, "extract this folder", etc.
   6. **Reuse required but missing.** If rules 2/3/4 fire but no session exists under `$SESSIONS_DIR`, fail clearly: `"No existing sessions under <SESSIONS_DIR>. Run /mykg extract <dir> first to create one."`

**Never auto-detect-most-recent purely because a previous skill turn produced a session.** The previous-turn memory only matters when the *current* user message also contains one of the explicit signals in rules 1-4. A bare `/mykg ./more_docs` after a prior session must still create a fresh session.
4. **Flags** — anything the user named that maps to a flag the cached `--help` confirms (`--review`, `--append`, `--from-step <step>`, `--workers <N>`, `--obsidian-vault`, `--base-schema`, `--thesaurus`, `--verbose`, `--confidence-agg`, `--append-with-grow-schema`, etc.). Forward verbatim.

`extract-graph` without `--append` or `--from-step` does not need a pre-existing session — it auto-creates one.

### `--append-with-grow-schema` — expanding the schema incrementally (D52)

**Use case:** you have an existing session with an induced schema (e.g. Project, Person, Organization) and you add new documents that introduce entity types or relationships the current schema doesn't cover (e.g. a tech-stack document that describes technologies). Plain `--append` freezes the schema — Pass 1 is skipped, so new concept types and properties are never induced, and the new documents are extracted against the old vocabulary. `--append-with-grow-schema` solves this: it implies `--append` and runs a **locked Pass 1** over the changed files only, allowing the LLM to propose new concepts and properties while preserving everything already in the schema.

**How it works:**
1. The session's existing `schema.ttl` is auto-loaded as a locked base schema — existing classes and properties cannot be renamed, removed, or re-parented.
2. Pass 1 runs over **only the changed files** (not the whole corpus), so cost is O(changed files).
3. The LLM may add new concepts, new properties, or new attributes to existing types. It cannot modify locked entries.
4. Pass 2 extracts the new files against the grown schema. If new properties were added, a **surgical back-fill** may re-extract old chunks that contain nodes of the new properties' domain/range types (configurable via `append.grow_schema_backfill_top_k_chunks_per_type`, default 10; set 0 to disable).
5. All downstream steps (assemble, orphan pass, validate) re-run over the full corpus so the graph stays consistent.

**When the schema delta is empty** (the new documents don't introduce new types), the run collapses to a plain `--append` — no wasted LLM cost.

**Intent triggers** — use `--append-with-grow-schema` when the user says any of: "grow schema", "expand schema", "grow the schema", "expand the vocabulary", "add new types", "learn new concepts from", "update the schema with". The flag implies `--append` (no need to pass both). `--append-with-grow-schema` is mutually exclusive with `--from-step` and `--base-schema`.

**Confirmation note:** in Stage 2, mention that locked Pass 1 will run (costs LLM calls) vs plain `--append` which skips Pass 1:

```
About to run: uv run mykg extract-graph ./docs --append-with-grow-schema --session 2026-06-21T11-22-38

This will run a locked Pass 1 over the new files (LLM calls) to expand the schema,
then extract. Plain --append would skip Pass 1 and keep the schema frozen.

Reply "yes" to run, or "just append" to skip schema growth.
```

### `fetch-web` flags and special cases

`fetch-web` is a **no-session** verb, same category as `parse-docs` — Stage 1
item 3's session-resolution logic never fires for it. Forward `--url-list`,
`--output`, `--max-pages`, `--max-depth`, `--strategy`,
`--download-assets`/`--no-download-assets`, `--delay`, `--concurrency`,
`--no-robots`, `--force`, `-v`/`--verbose` verbatim when the user names them,
validated against `$FETCH_HELP`.

**`--output`:** when the user names a destination folder ("into ./X", "save to
./X", "output ./X"), pass `--output ./X` verbatim — do not rewrite or
normalize the path beyond what the user typed. When the user doesn't name one
and the intent is single-seed, omit `--output` and let the CLI default
(`./mykg_web_fetch/<domain>/`) apply. For `--url-list` (including the
inline-tempfile case below), `--output` is **required** by the CLI — if the
user didn't name one, default to `./mykg_web_fetch/batch`.

**Inline URL list → temp file.** If the user pastes multiple URLs directly in
the message (not a path to an existing file), `--url-list` can't be used
as-is — it requires a file. Write each URL on its own line to `mykg_urls.txt`
(cwd), one URL per line, no comments/blank lines needed since the skill
controls the content, then pass `--url-list mykg_urls.txt`. Mention the temp
file's path to the user in the Stage 5 report so they know it was created (it
is not auto-deleted — leaving it is harmless and lets the user re-run/edit the
list).

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

For obviously safe actions (`walkthrough`, `parse-docs`, `fetch-web`), skip the confirmation and run.

**`fetch-web` chained with `extract-graph`:** when the user's intent is "fetch
and extract" (single seed or `--url-list`), run `fetch-web` directly (no
confirmation — same as above), then confirm once before the `extract-graph`
step(s), since those are the expensive/LLM-bearing part:

```
Fetched → <output dir> (N pages / GitHub clone).
About to run: uv run mykg extract-graph <output dir>  (fresh session)

Reply "yes" to extract, or "no" to stop here.
```

For the **multi-seed chained intent** (`--url-list`, including the
inline-URL-list-to-tempfile case), confirm once listing every per-seed subdir
that will get its own `extract-graph` run:

```
Fetched 3 seeds → ./mykg_web_fetch/batch/{a.com, b.com, github.com_owner_repo/input}
About to run, one fresh session each:
  uv run mykg extract-graph ./mykg_web_fetch/batch/a.com
  uv run mykg extract-graph ./mykg_web_fetch/batch/b.com
  uv run mykg extract-graph ./mykg_web_fetch/batch/github.com_owner_repo/input

Reply "yes" to extract all, "no" to stop here, or name which ones to run.
```

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

### Stage 4b — synchronous path (`walkthrough`, `approve-schema`, `parse-docs`, `fetch-web`)

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

**`fetch-web`:**

```bash
uv run mykg fetch-web $ARGS
# Single-seed: output ends with "Next: mykg extract-graph <path>" — capture <path>.
# Multi-seed (--url-list): read fetch_manifest.json["seeds"][*]["output_subdir"]
# under --output to get one <path> per seed.
```

Report the printed output directory (or all per-seed subdirs, for
`--url-list`) and page/asset counts to the user. If the user's intent was the
chained "fetch and extract" form (see Stage 1 intent table), proceed to Stage
4a for each captured path (`extract-graph <path>`, fresh session per path,
after the Stage 2 confirmation) using the captured path(s) as `INPUT_DIR`.

Capture stdout/stderr; surface any non-zero exit to the user verbatim.

### Stage 4b2 — MCP server path (`mcp-serve`)

MCP server commands are synchronous — run in the foreground and report.

**Start:**

```bash
uv run mykg mcp-serve $ARGS
```

This blocks — the server runs until stopped. For streamable HTTP, the
server writes a PID file to `~/.mykg/mcp-serve.pid`. Report the transport
and port to the user.

**Stop:**

```bash
uv run mykg mcp-serve --stop
```

Reports whether the server was stopped or was not running.

**Status:**

```bash
ps aux | grep "mcp-serve" | grep -v grep
```

Report whether a server is running and on which transport/port.

No confirmation needed — MCP server commands are safe (no LLM cost, no data writes).

### Stage 4c — refused (`init`, `merge-graphs`)

- `/mykg init` → reply: "Run `mykg init` from a shell. It is interactive."
- `/mykg merge ...` → reply: "Skill support is planned in a follow-up. Run from a shell."

Do not dispatch anything.

### Stage 4d — read-only query path (`query`)

No CLI call, no subprocess, no LLM call from inside the skill. The skill answers the user's question using the target session's graph data (latest unless the user named one).

#### Source-attribution discipline — NO training-data contamination

**Every claim in a query answer must be traceable to a specific session artifact** (a node ID, an edge record, a vault note filename, an MCP tool response). If the session data does not contain the information, **say so** — do not fill gaps with your training knowledge.

Concrete rules:

1. **Never state a fact about the domain unless the session data supports it.** If the graph has Owen Lars with two edges (`located_at Tatooine`, `member_of Jedi Knight`), report exactly those two edges. Do not add "Owen is Luke's uncle" or "he was a moisture farmer" — those facts are not in the graph.
2. **Never judge correctness of graph data using training knowledge.** Do not say an edge is "correct" or "incorrect" based on what you know from pre-training. You may say an edge has confidence 0.0 (that is a graph fact), but not that the edge is "wrong because Owen was never a Jedi" (that is training-data reasoning).
3. **Never list "missing relationships" sourced from training data.** If the user asks "what's missing?", answer only from what the graph *does* contain and what structural signals suggest (orphan status, low confidence, absent attributes). Do not invent expected relationships from general knowledge.
4. **If you must use training data, label it explicitly.** Occasionally the user asks a question that genuinely requires outside knowledge (e.g., "is this graph accurate?"). In that case, separate the answer into two clearly labelled sections:

   ```
   **From the graph (session <name>):**
   <facts with node IDs, edge types, confidence scores, source files>

   **From training data (not in the graph — may be inaccurate):**
   <any claims sourced from pre-training, with a caveat>
   ```

   The graph section always comes first. The training-data section must carry the caveat that it may be inaccurate or outdated. If the user did not ask for an accuracy judgment, **omit the training-data section entirely**.

5. **Cite sources for every fact.** Every claim must end with a parenthetical citation: a node ID (`person-owen-lars`), an edge record (`located_at, confidence 1.0, method: orphan_inferred`), a vault note filename (`Owen Lars.md`), or an MCP tool call name. No uncited claims.

**This rule is non-negotiable.** It is better to give a short, accurate, graph-only answer than a rich answer contaminated with ungrounded training-data assertions.

**Routing priority: MCP first, file-read fallback.**

If `mcp__mykg__*` tools are available in the current session (configured via `.mcp.json`), use them to answer the query. The MCP tools are indexed, return structured JSON, and support graph algorithms (shortest path, hub analysis, traversal, subgraph filtering) that manual file reading cannot do. Pick whichever MCP tool fits the question — the tool names and descriptions are self-documenting.

If MCP tools are not available or the call fails, fall back to reading session files directly as described below.

**File-read fallback — vault vs. jsonl**

Pick the read source from the wording of the user's question:

- **Prefer `obsidian_vault/`** (wiki path) when the user says or implies:
  - "wiki", "notes", "what does the wiki say", "tell me about X"
  - A named entity ("who is Alice", "what is project Phoenix")
  - Prose / explanatory questions
- **Prefer `nodes.jsonl` + `edges.jsonl`** (graph path) when the user says or implies:
  - "knowledge graph", "graph", "network"
  - "most connected", "central", "hub", "bridge", "blocking link", "shortest path"
  - "how does X connect to Y", "what links A and B"
  - Structural / topology / aggregate questions
- **Both** when the question genuinely needs structure *and* prose (e.g. "summarize what the wiki says about the most connected entity"). Read the jsonl first to identify the entity, then read the vault note for that entity.
- **Ambiguous** → prefer the vault if it exists (more human-readable); fall back to jsonl.

**Session resolution**

Same as the rest of Stage 1: latest under `$SESSIONS_DIR` unless the user named a session literally. `query` requires an existing session; if none exists, surface `"No existing sessions under <SESSIONS_DIR>. Run /mykg extract <dir> first to create one."` and stop.

#### Find the latest session

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

#### What's in a session

Under `<latest-session>/output/`:

- `nodes.jsonl` — entities with confidence-scored attributes
- `edges.jsonl` — typed relationships
- `knowledge_graph.ttl` — RDFS/OWL view (SPARQL-queryable)
- `obsidian_vault/` — markdown notes with wikilinks (when generated)

**Vault path — read steps**

```bash
SESSION_ROOT=$(ls -td "$SESSIONS_DIR"/*/ 2>/dev/null | head -1)
VAULT="$SESSION_ROOT/output/obsidian_vault"

# Sanity-check the vault exists. If not, fall through to the jsonl path with
# a one-line note: "vault not generated for this session — falling back to
# jsonl. Re-run extract with --obsidian-vault to enable wiki queries."
if [ ! -d "$VAULT" ]; then
  echo "[query] obsidian_vault/ not found at $VAULT — falling back to jsonl path."
fi
```

When the vault exists:
1. List candidate note files with `ls "$VAULT"`.
2. Identify likely matches by stem (Obsidian note filenames are derived from canonical node names).
3. Use the `Read` tool to load the matching `.md` notes. Follow `[[wikilinks]]` to neighbours when the question implies a relationship.
4. Answer the user from the note content. **Cite the note filenames** so the user can verify.

**Jsonl path — read steps**

```bash
SESSION_ROOT=$(ls -td "$SESSIONS_DIR"/*/ 2>/dev/null | head -1)
NODES="$SESSION_ROOT/output/nodes.jsonl"
EDGES="$SESSION_ROOT/output/edges.jsonl"

# Sanity check.
[ -f "$NODES" ] || { echo "[query] $NODES missing"; exit 1; }
[ -f "$EDGES" ] || { echo "[query] $EDGES missing"; exit 1; }
```

When the files exist:
1. Use the `Read` tool on `nodes.jsonl` / `edges.jsonl` directly. Each line is one JSON record (the records are documented under D12 / D13 in the project's CLAUDE.md when one is present).
2. For specific lookups (single node, one-hop neighbours), grep first then Read the matched lines:
   ```bash
   grep -F '"name": "Alice"' "$NODES" | head -20
   grep -F '"from": "person-alice"' "$EDGES" | head -50
   ```
3. For aggregate / topology questions (most-connected node, hub identification), it is usually fine to Read the whole `edges.jsonl` and tally with the host LLM's reasoning — these files are typically a few hundred to a few thousand lines. For >50k-edge graphs the skill should warn the user and offer to drop into Python (`networkx`) via the `Bash` tool instead.
4. Answer the user from the records. **Quote the matched ids/edge types** so the user can verify.

**Hybrid path — read steps**

Use the jsonl path to identify the target node(s), then resolve `<node>.md` in the vault and Read it for prose context. Cite both.

**Confirmation behaviour**

`query` is read-only and free, so **do not** ask the user to confirm. Just run it. Do echo a one-line summary of the path used before answering:

```
[query] MCP: answered via 2 MCP tool calls.
[query] vault: read 3 notes from $VAULT (Alice.md, AcmeCorp.md, Project_Phoenix.md).
[query] jsonl: read 47 nodes + 89 edges from $SESSION_ROOT/output/.
```

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
