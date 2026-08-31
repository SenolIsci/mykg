"""Temperature resolution shared by the adapters that support the parameter.

The rule this module encodes: **None means "omit the parameter entirely."**
Temperature is injected into a provider payload only when it resolves to a
non-None float. That single rule covers three otherwise-awkward cases — models
that reject an explicit temperature, providers with no temperature concept at
all, and users who simply have no opinion and want the provider default.
"""

from __future__ import annotations

# Model-name prefixes whose families reject an explicit temperature parameter.
# OpenAI reasoning models (o-series, gpt-5) return 400 unsupported_parameter:
# "Only the default (1) value is supported". Naming mirrors the existing
# _NEW_TOKEN_PARAM_PREFIXES convention in openai_adapter.py.
#
# This matters for mykg's shipped default profile, which is `openai` on a gpt-5
# model: without this guard a user who sets llm.temperature would break the
# out-of-the-box configuration.
#
# The prefixes are deliberately broad. Some gpt-5 variants (e.g. gpt-5-chat-*)
# do accept a temperature and have theirs dropped here. That asymmetry is
# intentional: over-omitting silently loses a sampling preference, while
# over-sending fails the request outright, and only the former is recoverable
# — the adapters' BadRequestError fallbacks can stop sending a rejected
# temperature, but nothing can retroactively apply one that was never sent.
_TEMPERATURE_UNSUPPORTED_PREFIXES = ("o1", "o1-", "o3", "o3-", "o4", "o4-", "gpt-5")


def _bare_model_name(model: str) -> str:
    """Strip a leading `vendor/` segment from a namespaced model name.

    OpenRouter addresses upstream models as `openai/gpt-5-mini`, so a bare
    prefix match against the full string would miss the very families this
    module exists to catch.
    """
    return model.rsplit("/", 1)[-1].strip().lower()


def temperature_unsupported(model: str) -> bool:
    """True if `model` rejects an explicit temperature parameter."""
    if not model:
        return False
    name = _bare_model_name(model)
    return name.startswith(_TEMPERATURE_UNSUPPORTED_PREFIXES)


def resolve_temperature(configured: float | None, model: str = "") -> float | None:
    """Return the temperature to send, or None to omit the parameter entirely.

    Resolves to None when nothing is configured, or when the target model
    belongs to a family that rejects an explicit temperature. Note that a
    configured 0.0 is a real value and must survive — hence the explicit
    `is None` check rather than a falsy test.
    """
    if configured is None:
        return None
    if temperature_unsupported(model):
        return None
    return configured


# Corroborating markers that a 400 is specifically *rejecting* temperature,
# rather than merely mentioning it (e.g. a top_p/temperature conflict, where
# the configured value is still valid and must not be discarded).
_TEMPERATURE_REJECTION_MARKERS = (
    "unsupported",
    "not supported",
    "does not support",
    "only the default",
)


def rejects_temperature(msg: str) -> bool:
    """True if a 400 message indicates the model refuses an explicit temperature."""
    lowered = msg.lower()
    if "temperature" not in lowered:
        return False
    return any(marker in lowered for marker in _TEMPERATURE_REJECTION_MARKERS)
