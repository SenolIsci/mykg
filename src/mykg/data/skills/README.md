# mykg skills

The `mykg/` directory ships with the mykg Python package and contains the **`/mykg` Claude Code skill** that drives the pipeline when the active profile is `agent-claude-code` (provider: `agent`).

This is the skill side of agent mode. The mykg pipeline writes LLM tasks to a session-local inbox folder; this skill watches the inbox, dispatches Agent-tool subagents to answer them, and writes answers back to an outbox. The pipeline subprocess never makes an HTTP API call — every LLM answer comes from a subagent the host Claude Code session spawned.

---

## Install

`mykg init` does both jobs: select the agent profile and copy the bundled skill into your Claude Code skills folder.

```bash
pip install mykg
mykg init --profile agent-claude-code
# ...then restart Claude Code so the skill loader picks up the new entry.
```

The wizard copies `data/skills/mykg/` into `~/.claude/skills/mykg/` (honoring `$CLAUDE_CONFIG_DIR` if set) and writes a `.mykg_skill_version` stamp file so future invocations can detect drift.

**Upgrade after `pip install -U mykg`:**

```bash
mykg init --reinstall-skill
```

This re-copies the bundled skill on top of whatever is currently installed, atomically (write to `.tmp` then `os.replace`). The flag is also accepted alongside `--profile agent-claude-code` for a one-shot fresh install + force-refresh.

**Why copy instead of symlink?** Symlinks fail on Windows without Developer Mode, dangle if mykg is uninstalled, and don't sync through OneDrive. A copy is portable, decoupled from the package, and survives `pip uninstall mykg`. The cost — live edits to the bundled skill don't auto-propagate — only matters for mykg developers, who can pass `--reinstall-skill` to refresh between edits.

### Activate agent mode

The skill only does useful work when `mykg_config.yaml` selects the agent profile. `mykg init --profile agent-claude-code` does this in one step:

This writes the profile shown below. The `agent:` block configures the inbox/outbox paths and poll interval; the `pipeline.pass2.max_workers` value sets how many subagents the skill dispatches per wave:

```yaml
profile: agent-claude-code

profiles:
  agent-claude-code:
    provider: agent
    agent:
      inbox_dir: agent_inbox        # relative to <session>/intermediate/
      outbox_dir: agent_outbox
      poll_interval_seconds: 2
    pipeline:
      pass2:
        max_workers: 8              # how many subagents the skill dispatches per wave
```

---

## Why pick agent mode

- **No API key needed.** Uses your existing Claude Pro/Max plan via the skill subagents — same as `claude-cli`, but without invoking the `claude -p` binary.
- **Inspectable LLM I/O.** Every prompt lands as `intermediate/agent_inbox/<id>.task.json` and every answer as `intermediate/agent_outbox/<id>.answer.json`. Replay or edit any step by hand.
- **Parallel by default.** The skill dispatches up to `pass2.max_workers` subagents per wave in a single message — not serial like `claude-cli`. Pass-2 chunks complete in parallel waves.

---

## Invoke from inside Claude Code

The skill exposes one slash command — `/mykg` — that accepts free-form intent. You describe what you want; the skill figures out which `mykg` CLI command to run, reads the live `--help` to validate flags, confirms expensive actions, and (for `extract-graph`) drains the LLM inbox in parallel waves.

Examples:

| You type | The skill runs |
| --- | --- |
| `/mykg extract ./docs` | `mykg extract-graph ./docs` |
| `/mykg ./docs` | `mykg extract-graph ./docs` (legacy positional alias) |
| `/mykg extract ./docs with human review` | `mykg extract-graph ./docs --review` |
| `/mykg append the new notes in ./docs` | `mykg extract-graph ./docs --append --session <latest>` |
| `/mykg resume the last session` | `mykg extract-graph --session <latest>` |
| `/mykg approve the schema` | `mykg approve-schema --session <latest>` |
| `/mykg make a walkthrough` | `mykg walkthrough --session <latest>` |
| `/mykg convert pdfs in ./inbox to ./md` | `mykg parse-docs --input ./inbox --output ./md` |

Any flag mykg accepts on the CLI works here too — the skill reads `--help` rather than maintaining its own list, so `--from-step orphan_connect`, `--workers 8`, `--obsidian-vault`, etc. all flow through.

`mykg init` and `mykg merge-graphs` are intentionally not wrapped: init is interactive (run from a shell once per machine), and merge-graphs has additional design questions and will be added in a follow-up.

---

## What the skill does on screen

1. Confirms `mykg_config.yaml` has `profile: agent-claude-code` — aborts with a clear message if not.
2. Launches `mykg extract-graph` in the background via `nohup` so it survives the skill turn.
3. Watches `<session>/intermediate/agent_inbox/` for `*.task.json` files.
4. Dispatches one Agent-tool subagent per unanswered task (parallel calls in one message, up to `pass2.max_workers` per wave).
5. Exits when the pipeline subprocess exits, when `output/knowledge_graph.ttl` appears, or after **20 watch waves** — at which point it tells you to re-invoke `/mykg --session <name> --continue`.

---

## Limitations and notes

- The skill is bounded at **20 waves per invocation** to avoid runaway Claude Code sessions. Long pipelines may need multiple `/mykg --session <name> --continue` invocations.
- The pipeline subprocess survives via `nohup`, so closing your Claude Code session does not kill it — the run continues in the background and you can re-attach by re-invoking the skill with `--continue`.
- For non-Claude-Code hosts (Copilot CLI, Cursor, custom scripts), nothing prevents you from writing your own drainer against the same `agent_inbox`/`agent_outbox` contract — the protocol is just JSON files on disk.

---

## Full documentation

- Skill body (workflow stages, watch loop, subagent prompt template): [`mykg/SKILL.md`](mykg/SKILL.md)
- End-to-end agent-mode design and the inbox/outbox protocol: [`docs/agent-mode.md`](../../../../docs/agent-mode.md)
- Top-level project README and provider table: [`README.md`](../../../../README.md)
