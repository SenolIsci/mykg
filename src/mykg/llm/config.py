from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

import mykg.config as _cfg
from mykg.llm.adapter import LLMAdapter

if TYPE_CHECKING:
    from mykg.llm.error_gate import ErrorGate


def _temperature_prefixes(section: dict) -> tuple[str, ...] | None:
    """Model-name prefixes that reject an explicit temperature, or None for the default.

    Internal, deliberately absent from the shipped profiles — the same
    read-but-not-shipped pattern as `thinking_level`. It exists so a provider's
    model lineup changing does not require a mykg release (Invariant 7).

    An explicitly empty list is honoured as "send temperature to everything",
    which is why this returns a tuple rather than falling back on falsiness.
    """
    raw = section.get("temperature_unsupported_prefixes")
    if raw is None:
        return None
    # An explicit list is required. A bare string would prefix-match per
    # character; a mapping would silently degrade to its keys; a scalar would
    # raise a bare TypeError naming neither the key nor the file.
    if not isinstance(raw, list):
        raise ValueError(
            "llm.temperature_unsupported_prefixes in mykg_config.yaml must be a "
            f"list of model-name prefixes, got {type(raw).__name__}: {raw!r}"
        )
    # Drop null entries as well as blanks — a trailing "- " in YAML parses as
    # None, and str(None) would otherwise become the literal prefix "none".
    return tuple(
        str(item).strip().lower()
        for item in raw
        if item is not None and str(item).strip()
    )


def load_adapter(
    _raw: dict | None = None,
    error_gate: ErrorGate | None = None,
    intermediate_dir: Path | None = None,
) -> LLMAdapter:
    """Build an LLM adapter from mykg_config.yaml.

    mykg_config.yaml is loaded by mykg.config at import time via auto-discovery.
    _raw is an escape hatch for tests that need to supply a custom config dict.

    intermediate_dir is required only when provider == "agent" — the agent
    adapter writes to <intermediate>/<inbox_dir>/ and <intermediate>/<outbox_dir>/.
    """
    cfg = _raw if _raw is not None else _cfg.RAW
    provider = cfg.get("provider", "")
    if not provider:
        raise ValueError('mykg_config.yaml must set "provider"')

    # llm: is a flat block for the active provider (inside the active profile).
    section = cfg.get("llm", {})

    if provider == "ollama":
        from mykg.llm.ollama_adapter import OllamaAdapter

        return OllamaAdapter(
            model=section["model"],
            base_url=section["base_url"],
            timeout=section["timeout"],
            stream=section["stream"],
            max_tokens=section["max_output_tokens"],
            context_window=section["context_window"],
            retry_429_max=section.get("retry_429_max", _cfg.LLM_RETRY_429_MAX),
            retry_429_base_delay=section.get("retry_429_base_delay", _cfg.LLM_RETRY_429_BASE_DELAY),
            error_gate=error_gate,
            temperature=section.get("temperature"),
        )

    if provider == "anthropic":
        from mykg.llm.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            model=section["model"],
            max_tokens=section["max_output_tokens"],
            timeout=section["timeout"],
            base_url=section.get("base_url") or os.environ.get("ANTHROPIC_BASE_URL") or None,
            api_key=(
                section.get("api_key")
                or os.environ.get("ANTHROPIC_AUTH_TOKEN")
                or os.environ.get("ANTHROPIC_API_KEY")
            ),
            retry_429_max=section.get("retry_429_max", _cfg.LLM_RETRY_429_MAX),
            retry_429_base_delay=section.get("retry_429_base_delay", _cfg.LLM_RETRY_429_BASE_DELAY),
            error_gate=error_gate,
            temperature=section.get("temperature"),
        )

    if provider == "openrouter":
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        return OpenRouterAdapter(
            model=section["model"],
            max_tokens=section["max_output_tokens"],
            timeout=section["timeout"],
            api_key=(
                section.get("api_key")
                or os.environ.get("OPENROUTER_AUTH_TOKEN")
                or os.environ.get("OPENROUTER_API_KEY")
            ),
            base_url=section.get("base_url") or None,
            retry_429_max=section.get("retry_429_max", _cfg.LLM_RETRY_429_MAX),
            retry_429_base_delay=section.get("retry_429_base_delay", _cfg.LLM_RETRY_429_BASE_DELAY),
            error_gate=error_gate,
            temperature=section.get("temperature"),
            temperature_unsupported_prefixes=_temperature_prefixes(section),
        )

    if provider == "openai":
        from mykg.llm.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(
            model=section["model"],
            max_tokens=section["max_output_tokens"],
            timeout=section["timeout"],
            api_key=section.get("api_key") or os.environ.get("OPENAI_API_KEY"),
            base_url=section.get("base_url") or None,
            retry_429_max=section.get("retry_429_max", _cfg.LLM_RETRY_429_MAX),
            retry_429_base_delay=section.get("retry_429_base_delay", _cfg.LLM_RETRY_429_BASE_DELAY),
            error_gate=error_gate,
            temperature=section.get("temperature"),
            temperature_unsupported_prefixes=_temperature_prefixes(section),
        )

    if provider == "gemini":
        from mykg.llm.gemini_adapter import GeminiAdapter

        return GeminiAdapter(
            model=section["model"],
            max_tokens=section["max_output_tokens"],
            timeout=section["timeout"],
            api_key=(
                section.get("api_key")
                or os.environ.get("GEMINI_API_KEY")
                or os.environ.get("GOOGLE_API_KEY")
            ),
            thinking_level=section.get("thinking_level", "low"),
            retry_429_max=section.get("retry_429_max", _cfg.LLM_RETRY_429_MAX),
            retry_429_base_delay=section.get("retry_429_base_delay", _cfg.LLM_RETRY_429_BASE_DELAY),
            error_gate=error_gate,
            temperature=section.get("temperature"),
        )

    if provider == "claude-cli":
        from mykg.llm.claude_cli_adapter import ClaudeCLIAdapter

        return ClaudeCLIAdapter(
            max_tokens=section["max_output_tokens"],
            timeout=section["timeout"],
            model=section.get("model", "auto"),
            effort=section.get("effort", "auto"),
            error_gate=error_gate,
            temperature=section.get("temperature"),
        )

    if provider == "agent":
        from mykg.llm.agent_adapter import AgentAdapter

        agent_section = cfg.get("agent")
        if agent_section is None:
            raise ValueError(
                "provider 'agent' requires an 'agent:' block in the active profile "
                "(set inbox_dir, outbox_dir, poll_interval_seconds)"
            )

        if intermediate_dir is None:
            raise ValueError(
                "provider 'agent' requires intermediate_dir to be supplied to "
                "load_adapter() — pass the session's intermediate path"
            )

        inbox_name = agent_section.get("inbox_dir", _cfg.AGENT_INBOX_DIR)
        outbox_name = agent_section.get("outbox_dir", _cfg.AGENT_OUTBOX_DIR)
        poll_interval = agent_section.get(
            "poll_interval_seconds", _cfg.AGENT_POLL_INTERVAL_SECONDS
        )

        return AgentAdapter(
            inbox_dir=Path(intermediate_dir) / inbox_name,
            outbox_dir=Path(intermediate_dir) / outbox_name,
            poll_interval=poll_interval,
            timeout=section["timeout"],
            max_tokens=section["max_output_tokens"],
            error_gate=error_gate,
            temperature=section.get("temperature"),
        )

    raise ValueError(f"Unknown provider in mykg_config.yaml: {provider!r}")
