"""Tests for `_install_agent_skill`, `_claude_skills_dir`, `_manual_copy_hint`,
and `_print_next_steps` in mykg.cli.

These tests do not touch ~/.claude/ — every test uses an isolated temp dir
via $CLAUDE_CONFIG_DIR or monkeypatching ``_claude_skills_dir``.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import click
import pytest


def _make_fake_source(tmp_path: Path) -> Path:
    """Create a fake bundled-skill source directory."""
    source = tmp_path / "src_skill" / "mykg"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("# fake skill\n")
    return source


def _patch_source(monkeypatch, tmp_path):
    """Make _install_agent_skill use a fake bundled-source dir."""
    source = _make_fake_source(tmp_path)

    class _FakeMykg:
        __file__ = str(tmp_path / "src_skill" / "__init__.py")
        __version__ = "9.9.9"

    # Build the layout that _install_agent_skill expects:
    # Path(mykg.__file__).parent / "data" / "skills" / "mykg" must exist.
    real_init = tmp_path / "mykg_pkg"
    skill_pkg = real_init / "data" / "skills" / "mykg"
    skill_pkg.mkdir(parents=True)
    (skill_pkg / "SKILL.md").write_text("# fake skill\n")
    (skill_pkg / "extra.txt").write_text("x")
    _FakeMykg.__file__ = str(real_init / "__init__.py")

    monkeypatch.setitem(
        sys.modules,
        "mykg",
        _FakeMykg,
    )
    return real_init, skill_pkg


def test_claude_skills_dir_uses_override(monkeypatch, tmp_path):
    from mykg import cli

    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "custom"))
    out = cli._claude_skills_dir()
    assert out == tmp_path / "custom" / "skills"


def test_claude_skills_dir_default_when_exists(monkeypatch, tmp_path):
    from mykg import cli

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    home_claude = tmp_path / "home" / ".claude" / "skills"
    home_claude.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))

    out = cli._claude_skills_dir()
    assert out == home_claude


def test_claude_skills_dir_default_when_missing(monkeypatch, tmp_path):
    from mykg import cli

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    # Not Windows
    monkeypatch.setattr(sys, "platform", "linux")
    out = cli._claude_skills_dir()
    assert out == tmp_path / "home" / ".claude" / "skills"


def test_claude_skills_dir_windows_appdata_fallback(monkeypatch, tmp_path):
    from mykg import cli

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")

    # ~/.claude/skills does NOT exist; APPDATA path DOES exist.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))
    appdata = tmp_path / "appdata"
    (appdata / "Claude" / "skills").mkdir(parents=True)
    monkeypatch.setenv("APPDATA", str(appdata))

    out = cli._claude_skills_dir()
    assert out == appdata / "Claude" / "skills"


def test_claude_skills_dir_windows_no_appdata_env(monkeypatch, tmp_path):
    """Windows but APPDATA env var is missing -> returns home claude path."""
    from mykg import cli

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("APPDATA", raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "nohome"))

    out = cli._claude_skills_dir()
    assert out == tmp_path / "nohome" / ".claude" / "skills"


def test_manual_copy_hint_unix(monkeypatch):
    from mykg import cli

    monkeypatch.setattr(sys, "platform", "linux")
    hint = cli._manual_copy_hint(Path("/src"), Path("/dst"))
    assert "cp -R" in hint
    assert "/src" in hint
    assert "/dst" in hint


def test_manual_copy_hint_windows(monkeypatch):
    from mykg import cli

    monkeypatch.setattr(sys, "platform", "win32")
    hint = cli._manual_copy_hint(Path("C:/src"), Path("C:/dst"))
    assert "xcopy" in hint


def test_install_agent_skill_fresh_install(monkeypatch, tmp_path, capsys):
    """First-time install copies and writes version stamp."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    captured = capsys.readouterr().out

    target = skills_dir / "mykg"
    assert target.is_dir()
    assert (target / "SKILL.md").is_file()
    stamp = target / cli._SKILL_VERSION_STAMP
    assert stamp.is_file()
    assert stamp.read_text() == "9.9.9"
    assert "Installed:" in captured


def test_install_agent_skill_idempotent(monkeypatch, tmp_path, capsys):
    """Same version already installed -> 'Already installed' message."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    target = skills_dir / "mykg"
    target.mkdir(parents=True)
    (target / cli._SKILL_VERSION_STAMP).write_text("9.9.9")
    (target / "SKILL.md").write_text("old")

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "Already installed" in out


def test_install_agent_skill_stale_version_warning(monkeypatch, tmp_path, capsys):
    """Installed older version -> warning, no overwrite."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    target = skills_dir / "mykg"
    target.mkdir(parents=True)
    (target / cli._SKILL_VERSION_STAMP).write_text("0.0.1")
    (target / "SKILL.md").write_text("old")

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "Re-run with --reinstall-skill" in out
    # The file is left untouched.
    assert (target / "SKILL.md").read_text() == "old"


def test_install_agent_skill_force_overwrites(monkeypatch, tmp_path, capsys):
    """force=True overwrites even when versions match."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    target = skills_dir / "mykg"
    target.mkdir(parents=True)
    (target / cli._SKILL_VERSION_STAMP).write_text("9.9.9")
    (target / "SKILL.md").write_text("old content")

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill(force=True)
    out = capsys.readouterr().out
    assert "Installed:" in out
    # Old content has been replaced by the source SKILL.md content.
    assert (target / "SKILL.md").read_text() == "# fake skill\n"


def test_install_agent_skill_legacy_symlink_no_force(monkeypatch, tmp_path, capsys):
    """Symlink at target without --force -> warns, returns."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    skills_dir.mkdir()
    target = skills_dir / "mykg"
    real_other = tmp_path / "other"
    real_other.mkdir()
    target.symlink_to(real_other)

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "legacy symlink" in out
    # Target is still a symlink (untouched).
    assert target.is_symlink()


def test_install_agent_skill_legacy_symlink_with_force(monkeypatch, tmp_path, capsys):
    """Symlink at target with --force -> replaces with copy."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    skills_dir.mkdir()
    target = skills_dir / "mykg"
    real_other = tmp_path / "other"
    real_other.mkdir()
    target.symlink_to(real_other)

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill(force=True)
    out = capsys.readouterr().out
    assert "Installed:" in out
    assert not target.is_symlink()
    assert target.is_dir()


def test_install_agent_skill_no_version_stamp_no_force(monkeypatch, tmp_path, capsys):
    """Hand-edited copy (no stamp) without --force -> warns, returns."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    target = skills_dir / "mykg"
    target.mkdir(parents=True)
    (target / "SKILL.md").write_text("hand edited")

    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "no version stamp" in out
    assert (target / "SKILL.md").read_text() == "hand edited"


def test_install_agent_skill_mkdir_failure(monkeypatch, tmp_path, capsys):
    """OSError on target_dir.mkdir -> prints fallback message and returns."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    # Patch Path.mkdir to raise for the target_dir.
    real_mkdir = Path.mkdir

    def fail_mkdir(self, *a, **kw):
        if self == skills_dir:
            raise OSError("denied")
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, "mkdir", fail_mkdir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "Could not create" in out
    assert "Copy manually" in out


def test_install_agent_skill_copytree_failure(monkeypatch, tmp_path, capsys):
    """OSError from shutil.copytree -> 'Failed to copy' message."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    def failing_copytree(*a, **kw):
        raise OSError("copy failed")

    monkeypatch.setattr(shutil, "copytree", failing_copytree)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "Failed to copy" in out


def test_install_agent_skill_version_stamp_write_failure(monkeypatch, tmp_path, capsys):
    """Stamp write fails but install proceeds; prints Warning."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    real_write_text = Path.write_text

    def fail_write_for_stamp(self, *a, **kw):
        if self.name == cli._SKILL_VERSION_STAMP:
            raise OSError("read-only")
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, "write_text", fail_write_for_stamp)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "could not write version stamp" in out
    # Target exists even though stamp failed
    assert (skills_dir / "mykg").is_dir()


def test_install_agent_skill_missing_source(monkeypatch, tmp_path, capsys):
    """Bundled source dir missing -> warning, no error."""
    from mykg import cli

    # Patch sys.modules['mykg'] with a fake whose data/skills/mykg does NOT exist
    class _FakeMykg:
        __file__ = str(tmp_path / "noexist" / "__init__.py")
        __version__ = "9.9.9"

    monkeypatch.setitem(sys.modules, "mykg", _FakeMykg)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "bundled skill not found" in out


def test_install_agent_skill_replace_failure(monkeypatch, tmp_path, capsys):
    """os.replace from tmp -> target failing surfaces error."""
    import os

    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    def fail_replace(*a, **kw):
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", fail_replace)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    assert "Failed to install" in out


def test_install_agent_skill_unreadable_stamp(monkeypatch, tmp_path, capsys):
    """Existing stamp file but read_text raises -> falls through cleanly."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)

    skills_dir = tmp_path / "skills_root"
    target = skills_dir / "mykg"
    target.mkdir(parents=True)
    (target / cli._SKILL_VERSION_STAMP).write_text("x")
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    real_read = Path.read_text

    def fail_read(self, *a, **kw):
        if self.name == cli._SKILL_VERSION_STAMP:
            raise OSError("denied")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(Path, "read_text", fail_read)

    cli._install_agent_skill()
    out = capsys.readouterr().out
    # Should hit the (unreadable) branch and likely warn (stale).
    assert "(unreadable)" in out or "Re-run" in out


def test_print_next_steps_reinstall_skill_non_agent_warns(capsys):
    from mykg import cli

    cli._print_next_steps("openrouter-free", reinstall_skill=True)
    out = capsys.readouterr().out
    assert "--reinstall-skill ignored" in out


@pytest.mark.parametrize(
    "profile,expected",
    [
        ("openrouter-free", "Next steps:"),
        ("anthropic-claude", "Next steps:"),
        ("ollama-local", "Ollama"),
        ("claude-cli", "claude CLI"),
    ],
)
def test_print_next_steps_each_profile(monkeypatch, capsys, profile, expected):
    from mykg import cli

    monkeypatch.setattr(cli, "_install_agent_skill", lambda *a, **kw: None)
    cli._print_next_steps(profile)
    out = capsys.readouterr().out
    assert expected in out


def test_print_next_steps_agent_profile_runs_install(monkeypatch, capsys):
    from mykg import cli

    called = {}
    monkeypatch.setattr(
        cli, "_install_agent_skill", lambda *, force=False: called.setdefault("force", force)
    )

    cli._print_next_steps("agent-claude-code", reinstall_skill=False)
    out = capsys.readouterr().out
    assert "/mykg" in out
    assert called.get("force") is False


def test_print_next_steps_agent_profile_force(monkeypatch, capsys):
    from mykg import cli

    called = {}
    monkeypatch.setattr(
        cli, "_install_agent_skill", lambda *, force=False: called.setdefault("force", force)
    )

    cli._print_next_steps("agent-claude-code", reinstall_skill=True)
    assert called.get("force") is True


def test_install_agent_skill_replaces_existing_tmp_file(monkeypatch, tmp_path, capsys):
    """If tmp path exists as a *file*, it gets unlinked and replaced cleanly."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)
    skills_dir = tmp_path / "skills_root"
    skills_dir.mkdir()
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    # Create a stray file at the tmp path so the unlink branch executes.
    stray_tmp = skills_dir / "mykg.tmp"
    stray_tmp.write_text("stale")

    cli._install_agent_skill(force=True)
    out = capsys.readouterr().out
    assert "Installed:" in out
    assert (skills_dir / "mykg").is_dir()
    assert not stray_tmp.exists()


def test_install_agent_skill_replaces_existing_tmp_dir(monkeypatch, tmp_path, capsys):
    """If tmp path exists as a *directory*, shutil.rmtree branch runs."""
    from mykg import cli

    real_init, skill_pkg = _patch_source(monkeypatch, tmp_path)
    skills_dir = tmp_path / "skills_root"
    skills_dir.mkdir()
    monkeypatch.setattr(cli, "_claude_skills_dir", lambda: skills_dir)

    stale = skills_dir / "mykg.tmp"
    stale.mkdir()
    (stale / "garbage").write_text("x")

    cli._install_agent_skill(force=True)
    out = capsys.readouterr().out
    assert "Installed:" in out
    assert (skills_dir / "mykg").is_dir()
