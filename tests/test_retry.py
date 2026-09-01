from __future__ import annotations

from unittest.mock import patch

from mykg.llm.adapter import LLMAdapter
from mykg.llm.retry import llm_complete_with_retry


class _Adapter(LLMAdapter):
    """Adapter that returns responses from a pre-defined sequence."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict] = []

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        self.calls.append(
            {"max_tokens": max_tokens, "timeout": timeout, "temperature": temperature}
        )
        return next(self._responses)

    def endpoint_label(self) -> str:
        return "test"


def test_returns_immediately_on_non_empty_response():
    adapter = _Adapter(["good response"])
    result = llm_complete_with_retry(adapter, "sys", "user")
    assert result == "good response"


def test_retries_on_empty_response_and_returns_second():
    adapter = _Adapter(["", "good response"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 3):
        result = llm_complete_with_retry(adapter, "sys", "user")
    assert result == "good response"


def test_retries_on_whitespace_response():
    adapter = _Adapter(["   \n", "\t", "actual content"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 3):
        result = llm_complete_with_retry(adapter, "sys", "user")
    assert result == "actual content"


def test_returns_empty_string_when_all_retries_exhausted():
    # max_retries=2 → 1 original + 2 retries = 3 total calls, all empty
    adapter = _Adapter(["", "", ""])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 2):
        result = llm_complete_with_retry(adapter, "sys", "user")
    assert result == ""


def test_max_retries_zero_disables_retry():
    # max_retries=0 → only 1 attempt, no retries
    adapter = _Adapter(["", "should not reach"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 0):
        result = llm_complete_with_retry(adapter, "sys", "user")
    assert result == ""


def test_exactly_max_retries_plus_one_calls_made():
    # max_retries=2 → 3 total calls (1 original + 2 retries)
    calls = []

    class CountingAdapter(LLMAdapter):
        def complete(
            self, system, user, context_label="", max_tokens=None, timeout=None,
            temperature=None,
        ):
            calls.append(1)
            return ""

        def endpoint_label(self) -> str:
            return "counting"

    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 2):
        llm_complete_with_retry(CountingAdapter(), "sys", "user")
    assert len(calls) == 3


def test_context_label_appears_in_warning(caplog):
    import logging

    adapter = _Adapter(["", "ok"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 3):
        with caplog.at_level(logging.WARNING, logger="mykg.llm.retry"):
            llm_complete_with_retry(adapter, "sys", "user", context_label="pass1 batch 2/40")
    assert "pass1 batch 2/40" in caplog.text


def test_no_retry_needed_no_warning(caplog):
    import logging

    adapter = _Adapter(["immediate response"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 3):
        with caplog.at_level(logging.WARNING, logger="mykg.llm.retry"):
            llm_complete_with_retry(adapter, "sys", "user")
    assert caplog.text == ""


def test_temperature_is_forwarded_to_adapter():
    """llm_complete_with_retry forwards temperature like max_tokens/timeout."""
    adapter = _Adapter(["ok"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 0):
        llm_complete_with_retry(adapter, "sys", "user", temperature=0.2)
    assert adapter.calls[0]["temperature"] == 0.2


def test_temperature_defaults_to_none():
    """Omitting temperature forwards None, i.e. 'use the adapter default'."""
    adapter = _Adapter(["ok"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 0):
        llm_complete_with_retry(adapter, "sys", "user")
    assert adapter.calls[0]["temperature"] is None


def test_temperature_forwarded_on_every_retry():
    """A retried empty response must not silently drop the temperature override."""
    adapter = _Adapter(["", "", "ok"])
    with patch("mykg.llm.retry._cfg.LLM_RETRY_MAX_RETRIES", 3):
        assert llm_complete_with_retry(adapter, "sys", "user", temperature=0.0) == "ok"
    assert len(adapter.calls) == 3
    assert all(c["temperature"] == 0.0 for c in adapter.calls)
