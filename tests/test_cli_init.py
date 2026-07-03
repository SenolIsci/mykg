"""Tests for `mykg init` command.

Covers profile selection, model patching, API key writing, --reinstall-skill
short-circuit, and existing-config behaviour. Mocks _install_agent_skill so
tests never touch ~/.claude/.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner


@pytest.fixture(autouse=True)
def _mock_install_agent_skill(monkeypatch):
    """Block all real skill-install side-effects across this whole test module."""
    monkeypatch.setattr("mykg.cli._install_agent_skill", lambda *a, **kw: None)


def _runner_in(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return CliRunner()


def test_init_default_creates_config_with_openrouter_profile(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    # default profile, default model, skip API key (empty input)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "openrouter-free", "--model", "openrouter/free", "--api-key", ""],
    )

    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "profile: openrouter-free" in cfg


def test_init_interactive_prompt_selects_profile(tmp_path, monkeypatch):
    """When --profile omitted, init prompts. Feed '2' to pick anthropic-claude."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    # Choice 2 = anthropic-claude (second entry in _PROFILE_META)
    # Press Enter for model default, paste no API key.
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="2\n\n\n",
    )

    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "profile: anthropic-claude" in cfg


def test_init_interactive_model_matching_default_is_still_written(tmp_path, monkeypatch):
    """Retyping the exact default model must not silently no-op (previously
    compared model_input to default_model and dropped the write when equal,
    indistinguishable from a bare Enter — see openrouter-free whose
    default_model is itself 'openrouter/free')."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="1\nopenrouter/free\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "model: openrouter/free" in result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "model: openrouter/free" in cfg


def test_init_interactive_blank_model_reprompts(tmp_path, monkeypatch):
    """A blank/whitespace-only model entry is rejected and re-prompted, not
    silently accepted as an empty model name."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="1\n \ndsjcds\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Model name cannot be blank" in result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "model: dsjcds" in cfg


def test_init_interactive_model_with_spaces_reprompts(tmp_path, monkeypatch):
    """A model entry containing embedded whitespace is rejected and re-prompted."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="1\nthis is not a model\ndsjcds\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Model name cannot contain spaces" in result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "model: dsjcds" in cfg


def test_init_invalid_interactive_choice_falls_back_to_default(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    # Provide "abc" which is not parseable as int. Fall back to openrouter-free.
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="abc\n\n\n",
    )

    assert result.exit_code == 0, result.output
    out = result.output
    assert "Invalid choice" in out
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "profile: openrouter-free" in cfg


def test_init_invalid_interactive_index_falls_back_to_default(tmp_path, monkeypatch):
    """An out-of-range index also triggers the fallback message."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init"],
        input="999\n\n\n",
    )

    assert result.exit_code == 0, result.output
    assert "Invalid choice" in result.output


def test_init_unknown_profile_errors(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "does-not-exist"],
    )

    # Note: this branch echoes and returns without raising.
    assert result.exit_code == 0
    assert "Unknown profile" in result.output


def test_init_existing_config_without_force(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    (tmp_path / "mykg_config.yaml").write_text("profile: openrouter-free\n")

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init"])

    assert result.exit_code == 0
    assert "already exists" in result.output


def test_init_existing_config_with_force_overwrites(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    (tmp_path / "mykg_config.yaml").write_text("# manually edited\n")

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--force", "--profile", "ollama-local", "--model", "llama3.3"],
    )

    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    assert "profile: ollama-local" in cfg


def test_init_reinstall_skill_on_existing_agent_config(tmp_path, monkeypatch):
    """--reinstall-skill on existing agent config should short-circuit."""
    import mykg.cli as cli_mod

    (tmp_path / "mykg_config.yaml").write_text(
        "profile: agent-claude-code\nllm:\n  agent-claude-code: {}\n"
    )

    called = {}

    def _fake_install(*, force: bool = False):
        called["force"] = force

    monkeypatch.setattr("mykg.cli._install_agent_skill", _fake_install)

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init", "--reinstall-skill"])

    assert result.exit_code == 0, result.output
    assert called.get("force") is True


def test_init_reinstall_skill_on_non_agent_config_warns(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    (tmp_path / "mykg_config.yaml").write_text("profile: openrouter-free\n")

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init", "--reinstall-skill"])

    assert result.exit_code == 0
    assert "only meaningful" in result.output.lower()


def test_init_reinstall_skill_existing_config_unreadable(tmp_path, monkeypatch):
    """When existing file exists but read_text raises OSError, branch handles it."""
    import mykg.cli as cli_mod

    cfg_path = tmp_path / "mykg_config.yaml"
    cfg_path.write_text("profile: agent-claude-code\n")

    # Patch read_text on the specific Path instance via Path.read_text broadly:
    real_read_text = Path.read_text

    def fail_read_text(self, *a, **kw):
        if self.name == "mykg_config.yaml":
            raise OSError("simulated unreadable")
        return real_read_text(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init", "--reinstall-skill"])

    # Falls through the OSError branch; existing config doesn't contain agent profile
    # because we read empty string. Then prints "only meaningful" warning.
    assert result.exit_code == 0


def test_init_profile_no_api_key_required(tmp_path, monkeypatch):
    """ollama-local has key_var=None — branch prints 'No API key required'."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "ollama-local", "--model", "llama3.3"],
    )

    assert result.exit_code == 0, result.output
    assert "No API key required" in result.output


def test_init_writes_api_key_to_env(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        [
            "init",
            "--profile",
            "anthropic-claude",
            "--model",
            "claude-sonnet-4-5",
            "--api-key",
            "sk-ant-test-12345",
        ],
    )

    assert result.exit_code == 0, result.output
    env = (tmp_path / ".env.mykg").read_text()
    assert "ANTHROPIC_API_KEY=sk-ant-test-12345" in env


def test_init_skips_when_api_key_blank(tmp_path, monkeypatch):
    """Empty api_key + empty interactive input -> 'Skipped' message."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "openai", "--model", "gpt-4o", "--api-key", ""],
    )

    assert result.exit_code == 0, result.output
    assert "Skipped" in result.output


def test_init_detects_existing_env_key(tmp_path, monkeypatch):
    """If .env.mykg already has a non-empty key, init says 'already set'."""
    import mykg.cli as cli_mod

    (tmp_path / ".env.mykg").write_text("ANTHROPIC_API_KEY=existing-key\n")

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "anthropic-claude", "--model", "claude-sonnet-4-5"],
    )

    assert result.exit_code == 0, result.output
    assert "already set" in result.output


def test_init_claude_cli_profile_no_api_key(tmp_path, monkeypatch):
    """claude-cli profile has no key_var; should hit the no-api-key branch."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "claude-cli", "--model", "sonnet"],
    )

    assert result.exit_code == 0, result.output
    assert "No API key required" in result.output


def test_init_agent_claude_code_profile_runs_install(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    called = {}
    monkeypatch.setattr(
        "mykg.cli._install_agent_skill",
        lambda *, force=False: called.setdefault("force", force),
    )

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        ["init", "--profile", "agent-claude-code"],
    )

    assert result.exit_code == 0, result.output
    assert "force" in called
    # The agent-claude-code branch follows _print_next_steps and triggers install.


def test_init_openai_profile_writes_model(tmp_path, monkeypatch):
    """Patch model line in openai profile via --model override."""
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        [
            "init",
            "--profile",
            "openai",
            "--model",
            "gpt-4o-mini",
            "--api-key",
            "sk-test-openai",
        ],
    )

    assert result.exit_code == 0, result.output
    cfg = (tmp_path / "mykg_config.yaml").read_text()
    # The patched model line should appear inside the openai profile block.
    assert "gpt-4o-mini" in cfg


def test_patch_profile_model_matched():
    """_patch_profile_model replaces the right model line."""
    from mykg.cli import _patch_profile_model

    content = """profile: openai

llm:
  openrouter-free:
      model: openrouter/free
      max_tokens: 4000
  openai:
      model: gpt-4o
      max_tokens: 4000
"""
    out = _patch_profile_model(content, "openai", "gpt-4o-mini")
    assert "model: gpt-4o-mini" in out
    # openrouter-free was not touched
    assert "openrouter/free" in out


def test_patch_profile_model_not_found_returns_unchanged():
    """If the requested profile is not in the YAML, content is returned unchanged."""
    from mykg.cli import _patch_profile_model

    content = "profile: openai\n\nllm:\n  openrouter-free:\n      model: openrouter/free\n"
    out = _patch_profile_model(content, "does-not-exist", "whatever")
    assert out == content


def test_write_env_key_updates_existing(tmp_path):
    from mykg.cli import _write_env_key

    env = tmp_path / ".env.mykg"
    env.write_text("FOO=old\nBAR=keep\n")
    _write_env_key(env, "FOO", "new")
    lines = env.read_text().splitlines()
    assert "FOO=new" in lines
    assert "BAR=keep" in lines


def test_write_env_key_appends_new(tmp_path):
    from mykg.cli import _write_env_key

    env = tmp_path / ".env.mykg"
    env.write_text("EXISTING=value\n")
    _write_env_key(env, "NEW", "val2")
    lines = env.read_text().splitlines()
    assert "EXISTING=value" in lines
    assert "NEW=val2" in lines


def test_write_env_key_creates_file_if_missing(tmp_path):
    from mykg.cli import _write_env_key

    env = tmp_path / ".env.mykg"
    assert not env.exists()
    _write_env_key(env, "K", "v")
    assert env.exists()
    assert "K=v" in env.read_text()


# ---------------------------------------------------------------------------
# CLAUDE.md snippet behaviour (agent-claude-code profile only)
# ---------------------------------------------------------------------------

_SNIPPET_SENTINEL = "mykg knowledge graph"
_BEGIN_MARKER = "<!-- BEGIN mykg-section"
_END_MARKER = "<!-- END mykg-section -->"


def test_init_agent_creates_claude_md_when_missing(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init", "--profile", "agent-claude-code"])

    assert result.exit_code == 0, result.output
    claude_md = tmp_path / "CLAUDE.md"
    assert claude_md.exists()
    content = claude_md.read_text()
    assert _BEGIN_MARKER in content
    assert _END_MARKER in content
    assert _SNIPPET_SENTINEL in content


def test_init_agent_appends_section_to_existing_claude_md(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    claude_md = tmp_path / "CLAUDE.md"
    user_content = "# My Project\n\nUser-authored guidance that must not be lost.\n"
    claude_md.write_text(user_content)

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(cli_mod.cli, ["init", "--profile", "agent-claude-code"])

    assert result.exit_code == 0, result.output
    content = claude_md.read_text()
    assert content.startswith(user_content)
    assert _BEGIN_MARKER in content
    assert _END_MARKER in content
    assert _SNIPPET_SENTINEL in content


def test_init_agent_is_idempotent_when_marker_present(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    runner = _runner_in(tmp_path, monkeypatch)
    result1 = runner.invoke(cli_mod.cli, ["init", "--profile", "agent-claude-code"])
    assert result1.exit_code == 0, result1.output
    first = (tmp_path / "CLAUDE.md").read_bytes()

    result2 = runner.invoke(
        cli_mod.cli, ["init", "--force", "--profile", "agent-claude-code"]
    )
    assert result2.exit_code == 0, result2.output
    second = (tmp_path / "CLAUDE.md").read_bytes()

    assert first == second


def test_init_agent_reinstall_claude_md_replaces_block(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    claude_md = tmp_path / "CLAUDE.md"
    runner = _runner_in(tmp_path, monkeypatch)
    runner.invoke(cli_mod.cli, ["init", "--profile", "agent-claude-code"])

    user_tail = "\n\n## My own notes\n\nDo not touch me.\n"
    claude_md.write_text(claude_md.read_text() + user_tail)

    corrupted = claude_md.read_text().replace(_SNIPPET_SENTINEL, "REMOVED-BY-USER")
    claude_md.write_text(corrupted)
    assert _SNIPPET_SENTINEL not in claude_md.read_text()

    result = runner.invoke(
        cli_mod.cli,
        ["init", "--force", "--profile", "agent-claude-code", "--reinstall-claude-md"],
    )
    assert result.exit_code == 0, result.output

    restored = claude_md.read_text()
    assert _SNIPPET_SENTINEL in restored
    assert "Do not touch me." in restored


def test_init_non_agent_profile_does_not_touch_claude_md(tmp_path, monkeypatch):
    import mykg.cli as cli_mod

    claude_md = tmp_path / "CLAUDE.md"
    user_content = "# Plain project — no mykg section wanted\n"
    claude_md.write_text(user_content)

    runner = _runner_in(tmp_path, monkeypatch)
    result = runner.invoke(
        cli_mod.cli,
        [
            "init",
            "--profile",
            "openrouter-free",
            "--model",
            "openrouter/free",
            "--api-key",
            "",
        ],
    )

    assert result.exit_code == 0, result.output
    assert claude_md.read_text() == user_content
