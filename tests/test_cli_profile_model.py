"""Tests for the run-only ``--profile`` / ``--model`` overrides on ``extract-graph``.

Covers ``config.activate_profile`` (which re-resolves every profile-dependent
constant via ``importlib.reload``), the reload-persistence of the override, the
no-persistence-to-disk guarantee, and the CLI mutual-exclusion check.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from mykg.cli import cli

_ROOT_YAML = Path(__file__).parent.parent / "mykg_config.yaml"


def _clear_overrides_and_reload():
    os.environ.pop("MYKG_PROFILE_OVERRIDE", None)
    os.environ.pop("MYKG_MODEL_OVERRIDE", None)
    mod = sys.modules.get("mykg.config")
    if mod is None:
        importlib.import_module("mykg.config")
    else:
        importlib.reload(mod)


@pytest.fixture(autouse=True)
def _restore_active_profile():
    """Every test starts and ends on the YAML-declared active profile.

    activate_profile() mutates process env and reloads mykg.config; without this
    teardown the override would leak into unrelated tests.
    """
    _clear_overrides_and_reload()
    yield
    _clear_overrides_and_reload()


def test_activate_profile_rebinds_all_profile_constants():
    """Switching to claude-cli re-resolves model AND pass2.max_workers (=1)."""
    import mykg.config as cfg

    cfg.activate_profile("claude-cli")
    # Re-import after reload — the module object is mutated in place.
    import mykg.config as cfg

    assert cfg.RAW["llm"]["model"] == "sonnet"
    assert cfg.PASS2_MAX_WORKERS == 1  # serial provider (D3) — from the profile


def test_activate_profile_model_override():
    import mykg.config as cfg

    cfg.activate_profile("openrouter-free", model="some/custom-model")
    import mykg.config as cfg

    assert cfg.RAW["llm"]["model"] == "some/custom-model"


def test_activate_profile_bakes_override_then_stops_leaking():
    """activate_profile bakes the override into the reloaded constants, then
    clears the env vars so an UNRELATED later reload falls back to the YAML
    default profile (no process-global leak)."""
    import os

    import mykg.config as cfg

    default_model = cfg.RAW["llm"]["model"]  # YAML-active profile (openai)

    cfg.activate_profile("anthropic-claude")
    import mykg.config as cfg

    assert cfg.RAW["llm"]["model"] == "claude-sonnet-4-5"  # override baked in
    # Env vars cleared — the override does not persist for future reloads.
    assert "MYKG_PROFILE_OVERRIDE" not in os.environ
    assert "MYKG_MODEL_OVERRIDE" not in os.environ

    # An unrelated reload now resolves back to the YAML-default profile.
    importlib.reload(sys.modules["mykg.config"])
    import mykg.config as cfg

    assert cfg.RAW["llm"]["model"] == default_model


def test_activate_profile_unknown_raises_with_available_list():
    import mykg.config as cfg

    with pytest.raises(ValueError, match="not found"):
        cfg.activate_profile("does-not-exist")


def test_activate_profile_does_not_write_config_file():
    original = _ROOT_YAML.read_bytes()
    import mykg.config as cfg

    cfg.activate_profile("claude-cli", model="sonnet-override")
    assert _ROOT_YAML.read_bytes() == original  # run-only: disk untouched


def test_cli_model_without_profile_errors(tmp_path):
    """--model requires --profile."""
    input_dir = tmp_path / "notes"
    input_dir.mkdir()
    (input_dir / "a.md").write_text("# hello", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["extract-graph", str(input_dir), "--model", "x"]
    )
    assert result.exit_code != 0
    assert "--model requires --profile" in result.output


def test_cli_unknown_profile_errors(tmp_path):
    input_dir = tmp_path / "notes"
    input_dir.mkdir()
    (input_dir / "a.md").write_text("# hello", encoding="utf-8")

    result = CliRunner().invoke(
        cli, ["extract-graph", str(input_dir), "--profile", "nope"]
    )
    assert result.exit_code != 0
    assert "not found" in result.output.lower()
