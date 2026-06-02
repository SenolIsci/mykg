"""Tests for the agent-claude-code profile and ``provider: agent`` loading."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest
import yaml

import mykg.config as _cfg
from mykg.llm.agent_adapter import AgentAdapter
from mykg.llm.config import load_adapter


def _load_agent_profile() -> dict:
    """Load the agent-claude-code profile flattened to top-level keys."""
    repo_root = Path(__file__).parent.parent
    raw = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())
    profile = raw["profiles"]["agent-claude-code"]
    cfg = deepcopy(raw)
    for key in ("provider", "llm", "llm_retry", "pipeline", "agent"):
        if key in profile:
            cfg[key] = profile[key]
    return cfg


def test_agent_profile_is_present_in_root_yaml():
    repo_root = Path(__file__).parent.parent
    raw = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())
    assert "agent-claude-code" in raw["profiles"]
    profile = raw["profiles"]["agent-claude-code"]
    assert profile["provider"] == "agent"
    assert "agent" in profile, "profile must declare an 'agent:' block"
    assert profile["agent"]["inbox_dir"]
    assert profile["agent"]["outbox_dir"]
    assert profile["agent"]["poll_interval_seconds"]


def test_agent_profile_is_present_in_packaged_template():
    """Invariant 17 — both YAML files must stay structurally in sync."""
    repo_root = Path(__file__).parent.parent
    packaged = yaml.safe_load(
        (repo_root / "src" / "mykg" / "data" / "mykg_config.yaml").read_text()
    )
    assert "agent-claude-code" in packaged["profiles"]
    profile = packaged["profiles"]["agent-claude-code"]
    assert profile["provider"] == "agent"
    assert "agent" in profile


def test_agent_profile_structurally_matches_root_and_packaged():
    """Both files must contain the same set of keys under the agent profile."""
    repo_root = Path(__file__).parent.parent
    root = yaml.safe_load((repo_root / "mykg_config.yaml").read_text())["profiles"][
        "agent-claude-code"
    ]
    packaged = yaml.safe_load(
        (repo_root / "src" / "mykg" / "data" / "mykg_config.yaml").read_text()
    )["profiles"]["agent-claude-code"]
    assert set(root.keys()) == set(packaged.keys())
    assert set(root["agent"].keys()) == set(packaged["agent"].keys())
    assert set(root["pipeline"].keys()) == set(packaged["pipeline"].keys())


def test_agent_constants_exposed_in_config_module():
    assert hasattr(_cfg, "AGENT_INBOX_DIR")
    assert hasattr(_cfg, "AGENT_OUTBOX_DIR")
    assert hasattr(_cfg, "AGENT_POLL_INTERVAL_SECONDS")
    # Defaults must be safe-ish strings/numbers — even when the active profile is not agent.
    assert isinstance(_cfg.AGENT_INBOX_DIR, str)
    assert isinstance(_cfg.AGENT_OUTBOX_DIR, str)
    assert isinstance(_cfg.AGENT_POLL_INTERVAL_SECONDS, (int, float))


def test_load_adapter_constructs_agent_adapter(tmp_path):
    cfg = _load_agent_profile()
    adapter = load_adapter(_raw=cfg, intermediate_dir=tmp_path)
    assert isinstance(adapter, AgentAdapter)
    label = adapter.endpoint_label()
    assert "agent" in label
    # Inbox/outbox dirs should be under the supplied intermediate_dir.
    assert (tmp_path / cfg["agent"]["inbox_dir"]).exists()
    assert (tmp_path / cfg["agent"]["outbox_dir"]).exists()


def test_load_adapter_agent_requires_intermediate_dir():
    cfg = _load_agent_profile()
    with pytest.raises(ValueError, match="intermediate_dir"):
        load_adapter(_raw=cfg)


def test_load_adapter_agent_requires_agent_block(tmp_path):
    cfg = _load_agent_profile()
    del cfg["agent"]
    with pytest.raises(ValueError, match="agent"):
        load_adapter(_raw=cfg, intermediate_dir=tmp_path)
