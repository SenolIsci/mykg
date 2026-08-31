import re
from abc import ABC, abstractmethod


class LLMAdapter(ABC):
    @abstractmethod
    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """Make a single LLM call. Returns raw response string (expected JSON).

        max_tokens: per-call override; None means use the adapter's configured default.
        timeout: per-call override in seconds; None means use the adapter's configured default.
        temperature: per-call override; None means use the adapter's configured default.
            The adapter default is itself None unless mykg_config.yaml sets llm.temperature,
            and a resolved None means the parameter is omitted from the provider payload
            entirely (rather than sent as an explicit null or a hardcoded value).
        """

    @abstractmethod
    def endpoint_label(self) -> str:
        """Human-readable description of the active provider/model/URL for startup logging."""

    @staticmethod
    def strip_code_fences(text: str) -> str:
        """Strip markdown code fences that models sometimes wrap JSON in."""
        match = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        match = re.search(r"```\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1).strip()
        return text.strip()
