# mykg skills — install

The `mykg/` directory ships with the mykg Python package and contains a Claude Code skill that drives the pipeline when the active profile is `agent-claude-code` (provider: `agent`).

To install, symlink the skill directory into your user-level skills folder:

```bash
ln -s "$(pwd)/src/mykg/data/skills/mykg" ~/.claude/skills/mykg
```

After symlinking, restart Claude Code (or re-open the project). The skill activates on `/mykg <input_dir>` or `/mykg --session <name> --continue`. See `src/mykg/data/skills/mykg/SKILL.md` for the full contract and the watch-loop logic.

The skill assumes you have already set `profile: agent-claude-code` in `mykg_config.yaml`. See `docs/agent-mode.md` for the end-to-end story.
