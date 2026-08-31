"""Tests for temperature resolution (src/mykg/llm/temperature.py)."""

from __future__ import annotations

import pytest

from mykg.llm.temperature import resolve_temperature, temperature_unsupported


@pytest.mark.parametrize(
    "model",
    ["o1", "o1-preview", "o3", "o3-mini", "o4", "o4-mini", "gpt-5", "gpt-5.4-mini-2026-03-17"],
)
def test_reasoning_families_reject_temperature(model):
    assert temperature_unsupported(model) is True


@pytest.mark.parametrize(
    "model",
    [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "chatgpt-4o-latest",
        "claude-sonnet-4-5",
        "gemini-3.7-flash",
        "gemma4:31b-cloud",
    ],
)
def test_ordinary_models_accept_temperature(model):
    assert temperature_unsupported(model) is False


@pytest.mark.parametrize("model", ["olmo-7b", "orca-2-13b", "openchat-3.5"])
def test_unrelated_models_starting_with_o_are_not_matched(model):
    """The prefixes are o1/o3/o4, not a bare 'o' — these must not false-positive."""
    assert temperature_unsupported(model) is False


def test_matching_is_case_insensitive():
    assert temperature_unsupported("GPT-5-Turbo") is True
    assert temperature_unsupported("O3-Mini") is True


@pytest.mark.parametrize(
    "model",
    ["openai/gpt-5-mini", "openai/o3-mini", "OpenAI/GPT-5"],
)
def test_vendor_namespaced_models_are_matched(model):
    """OpenRouter addresses models as vendor/model; the prefix check must see through it."""
    assert temperature_unsupported(model) is True


def test_vendor_prefix_does_not_create_false_positives():
    assert temperature_unsupported("o3-labs/llama-3-70b") is False


def test_empty_model_is_not_matched():
    assert temperature_unsupported("") is False


# --- resolve_temperature ---------------------------------------------------


def test_unconfigured_resolves_to_none():
    """No configured value -> omit, regardless of model."""
    assert resolve_temperature(None, "gpt-4o") is None
    assert resolve_temperature(None, "gpt-5") is None
    assert resolve_temperature(None) is None


def test_configured_value_passes_through_for_ordinary_models():
    assert resolve_temperature(0.0, "gpt-4o") == 0.0
    assert resolve_temperature(0.7, "claude-sonnet-4-5") == 0.7


def test_zero_is_a_real_value_not_a_falsy_omission():
    """0.0 is the most useful temperature for extraction — it must not be dropped."""
    assert resolve_temperature(0.0, "gpt-4o") == 0.0
    assert resolve_temperature(0.0, "gpt-4o") is not None


def test_configured_value_is_suppressed_for_reasoning_models():
    """The config says 0.0 but the model would 400 — omit rather than fail the call."""
    assert resolve_temperature(0.0, "gpt-5.4-mini-2026-03-17") is None
    assert resolve_temperature(0.7, "o3-mini") is None
    assert resolve_temperature(0.0, "openai/gpt-5-mini") is None


def test_no_model_supplied_trusts_the_configured_value():
    """Adapters with no per-model concern (e.g. ollama) call without a model."""
    assert resolve_temperature(0.0) == 0.0
    assert resolve_temperature(0.5) == 0.5
