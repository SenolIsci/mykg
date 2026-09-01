import io
import json
import os
import pathlib
import urllib.error
from unittest.mock import MagicMock, call, patch

import pytest


def test_openai_adapter_complete():
    """OpenAIAdapter.complete sends system + user messages and returns text."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=4096, timeout=30, api_key="test-key")
        result = adapter.complete("system prompt", "user prompt")

    assert result == "hello"
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "system prompt"}
    assert messages[1] == {"role": "user", "content": "user prompt"}


def test_openai_adapter_uses_given_model():
    """OpenAIAdapter stores and uses the model passed to it."""
    with patch("openai.OpenAI"):
        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=4096, timeout=30, api_key="test-key")
        assert adapter._model == "gpt-4o"


def test_openai_adapter_uses_max_tokens_for_gpt4o():
    """Legacy models (gpt-4o) must receive the `max_tokens` parameter."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hi"

    with patch("openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=4096, timeout=30, api_key="test-key")
        adapter.complete("sys", "user")

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs.get("max_tokens") == 4096
    assert "max_completion_tokens" not in kwargs


def test_openai_adapter_uses_max_completion_tokens_for_gpt5():
    """gpt-5* models must receive `max_completion_tokens`, not `max_tokens`."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hi"

    with patch("openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-5.4-mini-2026-03-17", max_tokens=8192, timeout=30, api_key="test-key"
        )
        adapter.complete("sys", "user")

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs.get("max_completion_tokens") == 8192
    assert "max_tokens" not in kwargs


def test_openai_adapter_uses_max_completion_tokens_for_o1():
    """o1/o3/o4 reasoning models must receive `max_completion_tokens`."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hi"

    with patch("openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="o1-mini", max_tokens=4096, timeout=30, api_key="test-key")
        adapter.complete("sys", "user")

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs.get("max_completion_tokens") == 4096
    assert "max_tokens" not in kwargs


def test_openai_adapter_falls_back_on_400_unsupported_max_tokens():
    """If an unknown model rejects `max_tokens` with the canonical 400 message,
    the adapter swaps to `max_completion_tokens` and retries once."""
    import openai

    bad_req = openai.BadRequestError(
        message=(
            "Unsupported parameter: 'max_tokens' is not supported with this model. "
            "Use 'max_completion_tokens' instead."
        ),
        response=MagicMock(status_code=400, headers={}),
        body={
            "error": {
                "message": (
                    "Unsupported parameter: 'max_tokens' is not supported with this model. "
                    "Use 'max_completion_tokens' instead."
                ),
                "type": "invalid_request_error",
                "param": "max_tokens",
                "code": "unsupported_parameter",
            }
        },
    )
    success_response = MagicMock()
    success_response.choices[0].message.content = "after fallback"

    with patch("openai.OpenAI") as mock_cls:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [bad_req, success_response]

        from mykg.llm.openai_adapter import OpenAIAdapter

        # Model name not in the new-prefix allowlist — first call uses max_tokens,
        # API rejects it, adapter swaps and retries.
        adapter = OpenAIAdapter(
            model="some-future-model", max_tokens=4096, timeout=30, api_key="test-key"
        )
        result = adapter.complete("sys", "user")

    assert result == "after fallback"
    assert mock_client.chat.completions.create.call_count == 2
    first_kwargs = mock_client.chat.completions.create.call_args_list[0][1]
    second_kwargs = mock_client.chat.completions.create.call_args_list[1][1]
    assert first_kwargs.get("max_tokens") == 4096
    assert "max_completion_tokens" not in first_kwargs
    assert second_kwargs.get("max_completion_tokens") == 4096
    assert "max_tokens" not in second_kwargs
    # Adapter remembers the swap for subsequent calls.
    assert adapter._use_max_completion_tokens is True


def test_anthropic_adapter_raises_without_api_key():
    """AnthropicAdapter raises ValueError when no API key is available."""
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}, clear=False):
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            from mykg.llm.anthropic_adapter import AnthropicAdapter

            AnthropicAdapter(model="claude-opus-4-7", max_tokens=4096, timeout=30)


def test_openai_adapter_raises_without_api_key():
    """OpenAIAdapter raises ValueError when no API key is available."""
    with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=False):
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            from mykg.llm.openai_adapter import OpenAIAdapter

            OpenAIAdapter(model="gpt-4o", max_tokens=4096, timeout=30)


def test_config_creates_openai_adapter():
    """load_adapter creates OpenAIAdapter when provider='openai' in config."""
    raw = {
        "provider": "openai",
        "llm": {"model": "gpt-4o-mini", "max_output_tokens": 4096, "timeout": 30},
    }

    with patch("openai.OpenAI"):
        import os

        os.environ["OPENAI_API_KEY"] = "test-key"
        try:
            from mykg.llm.config import load_adapter
            from mykg.llm.openai_adapter import OpenAIAdapter

            adapter = load_adapter(_raw=raw)
            assert isinstance(adapter, OpenAIAdapter)
            assert adapter._model == "gpt-4o-mini"
        finally:
            del os.environ["OPENAI_API_KEY"]


def test_ollama_adapter_complete_with_max_tokens():
    """OllamaAdapter.complete includes num_predict in options."""
    import json
    from unittest.mock import MagicMock, patch

    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"response": "hello"}).encode()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=8096,
            context_window=64000,
            retry_429_max=3,
            retry_429_base_delay=1.0,
        )
        result = adapter.complete("system prompt", "user prompt")

    assert result == "hello"
    # Verify the payload includes options with num_predict and num_ctx
    call_args = mock_urlopen.call_args
    request = call_args[0][0]
    payload = json.loads(request.data.decode())
    assert "options" in payload
    assert payload["options"]["num_predict"] == 8096
    # num_ctx must be sent so large prompts are not truncated by Ollama's
    # small default context window.
    assert payload["options"]["num_ctx"] == 64000


def test_ollama_adapter_stores_max_tokens():
    """OllamaAdapter stores and uses max_tokens passed to it."""
    from mykg.llm.ollama_adapter import OllamaAdapter

    adapter = OllamaAdapter(
        model="gemma4:31b",
        base_url="http://localhost:11434",
        timeout=120,
        stream=False,
        max_tokens=4096,
        context_window=64000,
        retry_429_max=3,
        retry_429_base_delay=1.0,
    )
    assert adapter._max_tokens == 4096


def test_config_creates_ollama_adapter_with_max_tokens():
    """load_adapter creates OllamaAdapter with max_tokens from config."""
    raw = {
        "provider": "ollama",
        "llm": {
            "model": "gemma4:31b",
            "base_url": "http://localhost:11434",
            "timeout": 120,
            "stream": False,
            "max_output_tokens": 8096,
            "context_window": 64000,
            "retry_429_max": 3,
            "retry_429_base_delay": 1.0,
        },
    }

    from mykg.llm.config import load_adapter
    from mykg.llm.ollama_adapter import OllamaAdapter

    adapter = load_adapter(_raw=raw)
    assert isinstance(adapter, OllamaAdapter)
    assert adapter._model == "gemma4:31b"
    assert adapter._max_tokens == 8096
    assert adapter._context_window == 64000


# ---------------------------------------------------------------------------
# OllamaAdapter — 429 retry tests
# ---------------------------------------------------------------------------


def _make_http_error(code: int) -> urllib.error.HTTPError:
    """Build a urllib.error.HTTPError with the given status code."""
    return urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=code,
        msg="Too Many Requests",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )


def _ollama_adapter(retry_max: int = 3, base_delay: float = 1.0) -> "OllamaAdapter":  # noqa: F821
    from mykg.llm.ollama_adapter import OllamaAdapter

    return OllamaAdapter(
        model="gemma4:31b",
        base_url="http://localhost:11434",
        timeout=30,
        stream=False,
        max_tokens=4096,
        context_window=64000,
        retry_429_max=retry_max,
        retry_429_base_delay=base_delay,
    )


def test_ollama_429_retries_and_succeeds():
    """OllamaAdapter retries on 429 and returns the response when a later attempt succeeds."""
    success_response = MagicMock()
    success_response.read.return_value = json.dumps({"response": "ok"}).encode()

    with patch("urllib.request.urlopen") as mock_urlopen, patch("time.sleep") as mock_sleep:
        mock_urlopen.side_effect = [
            _make_http_error(429),
            _make_http_error(429),
            MagicMock(__enter__=lambda s: success_response, __exit__=MagicMock(return_value=False)),
        ]

        adapter = _ollama_adapter(retry_max=3, base_delay=1.0)
        result = adapter.complete("sys", "user")

    assert result == "ok"
    assert mock_sleep.call_count == 2
    # Exponential backoff: attempt 0 → 1.0s, attempt 1 → 2.0s
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


def test_ollama_429_exhausts_retries_and_raises():
    """OllamaAdapter raises HTTPError after exhausting all 429 retries."""
    exc = _make_http_error(429)

    with patch("urllib.request.urlopen", side_effect=exc), patch("time.sleep"):
        adapter = _ollama_adapter(retry_max=2, base_delay=1.0)
        with pytest.raises(urllib.error.HTTPError):
            adapter.complete("sys", "user")


def test_ollama_429_exponential_backoff_delays():
    """OllamaAdapter sleep durations follow base_delay * 2**attempt."""
    exc = _make_http_error(429)

    with patch("urllib.request.urlopen", side_effect=exc), patch("time.sleep") as mock_sleep:
        adapter = _ollama_adapter(retry_max=3, base_delay=2.0)
        with pytest.raises(urllib.error.HTTPError):
            adapter.complete("sys", "user")

    expected = [call(2.0), call(4.0), call(8.0)]
    assert mock_sleep.call_args_list == expected


def test_ollama_non_429_http_error_not_retried():
    """OllamaAdapter does not retry on non-429 HTTP errors."""
    exc = _make_http_error(503)

    with patch("urllib.request.urlopen", side_effect=exc), patch("time.sleep") as mock_sleep:
        adapter = _ollama_adapter(retry_max=3, base_delay=1.0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# AnthropicAdapter — 429 retry tests
# ---------------------------------------------------------------------------


def _anthropic_adapter(retry_max: int = 3, base_delay: float = 1.0) -> "AnthropicAdapter":  # noqa: F821
    with patch("anthropic.Anthropic"):
        from mykg.llm.anthropic_adapter import AnthropicAdapter

        return AnthropicAdapter(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=retry_max,
            retry_429_base_delay=base_delay,
        )


def test_anthropic_429_retries_and_succeeds():
    """AnthropicAdapter retries on RateLimitError and returns response on success."""
    import anthropic

    rate_limit_exc = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )
    success_block = MagicMock()
    success_block.text = "hello from claude"
    success_response = MagicMock()
    success_response.content = [success_block]

    with patch("anthropic.Anthropic") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = [
            rate_limit_exc,
            rate_limit_exc,
            success_response,
        ]

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=1.0,
        )
        result = adapter.complete("sys", "user")

    assert result == "hello from claude"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


def test_anthropic_429_exhausts_retries_and_raises():
    """AnthropicAdapter raises RateLimitError after exhausting retries."""
    import anthropic

    rate_limit_exc = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("anthropic.Anthropic") as mock_cls, patch("time.sleep"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = rate_limit_exc

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=2,
            retry_429_base_delay=1.0,
        )
        with pytest.raises(anthropic.RateLimitError):
            adapter.complete("sys", "user")


def test_anthropic_429_exponential_backoff_delays():
    """AnthropicAdapter sleep durations follow base_delay * 2**attempt."""
    import anthropic

    rate_limit_exc = anthropic.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("anthropic.Anthropic") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = rate_limit_exc

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=2.0,
        )
        with pytest.raises(anthropic.RateLimitError):
            adapter.complete("sys", "user")

    expected = [call(2.0), call(4.0), call(8.0)]
    assert mock_sleep.call_args_list == expected


# ---------------------------------------------------------------------------
# OpenAIAdapter — 429 retry tests
# ---------------------------------------------------------------------------


def test_openai_429_retries_and_succeeds():
    """OpenAIAdapter retries on RateLimitError and returns response on success."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )
    success_response = MagicMock()
    success_response.choices[0].message.content = "hello from openai"

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            rate_limit_exc,
            rate_limit_exc,
            success_response,
        ]

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=1.0,
        )
        result = adapter.complete("sys", "user")

    assert result == "hello from openai"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


def test_openai_429_exhausts_retries_and_raises():
    """OpenAIAdapter raises RateLimitError after exhausting retries."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = rate_limit_exc

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=2,
            retry_429_base_delay=1.0,
        )
        with pytest.raises(openai.RateLimitError):
            adapter.complete("sys", "user")


def test_openai_429_exponential_backoff_delays():
    """OpenAIAdapter sleep durations follow base_delay * 2**attempt."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = rate_limit_exc

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=2.0,
        )
        with pytest.raises(openai.RateLimitError):
            adapter.complete("sys", "user")

    expected = [call(2.0), call(4.0), call(8.0)]
    assert mock_sleep.call_args_list == expected


# ---------------------------------------------------------------------------
# load_adapter — passes retry_429 params from config to each adapter
# ---------------------------------------------------------------------------


def test_config_load_adapter_ollama_passes_retry_429():
    """load_adapter passes retry_429_max and retry_429_base_delay to OllamaAdapter."""
    raw = {
        "provider": "ollama",
        "llm": {
            "model": "gemma4:31b",
            "base_url": "http://localhost:11434",
            "timeout": 120,
            "stream": False,
            "max_output_tokens": 8096,
            "context_window": 64000,
            "retry_429_max": 7,
            "retry_429_base_delay": 3.0,
        },
    }
    from mykg.llm.config import load_adapter
    from mykg.llm.ollama_adapter import OllamaAdapter

    adapter = load_adapter(_raw=raw)
    assert isinstance(adapter, OllamaAdapter)
    assert adapter._retry_429_max == 7
    assert adapter._retry_429_base_delay == 3.0


def test_config_load_adapter_anthropic_passes_retry_429():
    """load_adapter passes retry_429_max and retry_429_base_delay to AnthropicAdapter."""
    raw = {
        "provider": "anthropic",
        "llm": {
            "model": "claude-sonnet-4-6",
            "max_output_tokens": 4096,
            "timeout": 120,
            "retry_429_max": 6,
            "retry_429_base_delay": 4.0,
        },
    }
    with patch("anthropic.Anthropic"), patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key"}):
        from mykg.llm.anthropic_adapter import AnthropicAdapter
        from mykg.llm.config import load_adapter

        adapter = load_adapter(_raw=raw)
    assert isinstance(adapter, AnthropicAdapter)
    assert adapter._retry_429_max == 6
    assert adapter._retry_429_base_delay == 4.0


def test_config_load_adapter_openai_passes_retry_429():
    """load_adapter passes retry_429_max and retry_429_base_delay to OpenAIAdapter."""
    raw = {
        "provider": "openai",
        "llm": {
            "model": "gpt-4o",
            "max_output_tokens": 4096,
            "timeout": 120,
            "retry_429_max": 4,
            "retry_429_base_delay": 5.0,
        },
    }
    with patch("openai.OpenAI"), patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        from mykg.llm.config import load_adapter
        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = load_adapter(_raw=raw)
    assert isinstance(adapter, OpenAIAdapter)
    assert adapter._retry_429_max == 4
    assert adapter._retry_429_base_delay == 5.0


# ---------------------------------------------------------------------------
# OpenRouterAdapter — unit tests
# ---------------------------------------------------------------------------


def test_openrouter_adapter_complete():
    """OpenRouterAdapter.complete sends system + user messages and returns text."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello from openrouter"

    with patch("openai.OpenAI") as mock_client_cls:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
        )
        result = adapter.complete("system prompt", "user prompt")

    assert result == "hello from openrouter"
    mock_client.chat.completions.create.assert_called_once()
    call_kwargs = mock_client.chat.completions.create.call_args[1]
    messages = call_kwargs["messages"]
    assert messages[0] == {"role": "system", "content": "system prompt"}
    assert messages[1] == {"role": "user", "content": "user prompt"}


def test_openrouter_adapter_uses_given_model():
    """OpenRouterAdapter stores and uses the model passed to it."""
    with patch("openai.OpenAI"):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
        )
        assert adapter._model == "meta-llama/llama-3.1-8b-instruct:free"


def test_openrouter_adapter_raises_without_api_key():
    """OpenRouterAdapter raises ValueError when neither key env var is available."""
    with patch.dict(
        os.environ, {"OPENROUTER_AUTH_TOKEN": "", "OPENROUTER_API_KEY": ""}, clear=False
    ):
        with pytest.raises(ValueError, match="OPENROUTER_AUTH_TOKEN"):
            from mykg.llm.openrouter_adapter import OpenRouterAdapter

            OpenRouterAdapter(
                model="meta-llama/llama-3.1-8b-instruct:free", max_tokens=4096, timeout=30
            )


def test_openrouter_adapter_accepts_openrouter_api_key():
    """OpenRouterAdapter falls back to OPENROUTER_API_KEY when OPENROUTER_AUTH_TOKEN is absent."""
    with (
        patch("openai.OpenAI"),
        patch.dict(
            os.environ,
            {"OPENROUTER_AUTH_TOKEN": "", "OPENROUTER_API_KEY": "test-key"},
            clear=False,
        ),
    ):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free", max_tokens=4096, timeout=30
        )
        assert adapter is not None


def test_openrouter_adapter_default_base_url():
    """OpenRouterAdapter uses the OpenRouter base URL by default."""
    with patch("openai.OpenAI"):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
        )
        assert adapter._base_url == "https://openrouter.ai/api/v1"


def test_openrouter_adapter_custom_base_url():
    """OpenRouterAdapter uses a custom base_url when supplied."""
    with patch("openai.OpenAI"):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="any/model",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            base_url="https://custom.example.com/v1",
        )
        assert adapter._base_url == "https://custom.example.com/v1"


def test_config_creates_openrouter_adapter():
    """load_adapter creates OpenRouterAdapter when provider='openrouter' in config."""
    raw = {
        "provider": "openrouter",
        "llm": {
            "model": "meta-llama/llama-3.1-8b-instruct:free",
            "max_output_tokens": 4096,
            "timeout": 30,
        },
    }

    with patch("openai.OpenAI"), patch.dict(os.environ, {"OPENROUTER_AUTH_TOKEN": "test-key"}):
        from mykg.llm.config import load_adapter
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = load_adapter(_raw=raw)
        assert isinstance(adapter, OpenRouterAdapter)
        assert adapter._model == "meta-llama/llama-3.1-8b-instruct:free"


# ---------------------------------------------------------------------------
# OpenRouterAdapter — 429 retry tests
# ---------------------------------------------------------------------------


def test_openrouter_429_retries_and_succeeds():
    """OpenRouterAdapter retries on RateLimitError and returns response on success."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )
    success_response = MagicMock()
    success_response.choices[0].message.content = "hello from openrouter"

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = [
            rate_limit_exc,
            rate_limit_exc,
            success_response,
        ]

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=1.0,
        )
        result = adapter.complete("sys", "user")

    assert result == "hello from openrouter"
    assert mock_sleep.call_count == 2
    mock_sleep.assert_any_call(1.0)
    mock_sleep.assert_any_call(2.0)


def test_openrouter_429_exhausts_retries_and_raises():
    """OpenRouterAdapter raises RateLimitError after exhausting retries."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = rate_limit_exc

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=2,
            retry_429_base_delay=1.0,
        )
        with pytest.raises(openai.RateLimitError):
            adapter.complete("sys", "user")


def test_openrouter_429_exponential_backoff_delays():
    """OpenRouterAdapter sleep durations follow base_delay * 2**attempt."""
    import openai

    rate_limit_exc = openai.RateLimitError(
        message="rate limited",
        response=MagicMock(status_code=429, headers={}),
        body={"error": {"type": "rate_limit_error", "message": "rate limited"}},
    )

    with patch("openai.OpenAI") as mock_cls, patch("time.sleep") as mock_sleep:
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = rate_limit_exc

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="meta-llama/llama-3.1-8b-instruct:free",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            retry_429_max=3,
            retry_429_base_delay=2.0,
        )
        with pytest.raises(openai.RateLimitError):
            adapter.complete("sys", "user")

    expected = [call(2.0), call(4.0), call(8.0)]
    assert mock_sleep.call_args_list == expected


def test_config_load_adapter_openrouter_passes_retry_429():
    """load_adapter passes retry_429_max and retry_429_base_delay to OpenRouterAdapter."""
    raw = {
        "provider": "openrouter",
        "llm": {
            "model": "meta-llama/llama-3.1-8b-instruct:free",
            "max_output_tokens": 4096,
            "timeout": 120,
            "retry_429_max": 4,
            "retry_429_base_delay": 5.0,
        },
    }
    with patch("openai.OpenAI"), patch.dict(os.environ, {"OPENROUTER_AUTH_TOKEN": "test-key"}):
        from mykg.llm.config import load_adapter
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = load_adapter(_raw=raw)
    assert isinstance(adapter, OpenRouterAdapter)
    assert adapter._retry_429_max == 4
    assert adapter._retry_429_base_delay == 5.0


# ---------------------------------------------------------------------------
# OpenRouterAdapter — timeout / max_tokens forwarding tests
#
# These verify that the timeout set in mykg_config.yaml (e.g. timeout: 45)
# reaches chat.completions.create() on every call, and that the per-call
# override mechanism actually forwards the override value rather than silently
# falling back to the default.
#
# Model slug is read from OPENROUTER_MODEL env var when set (useful for live
# runs); otherwise falls back to a known free-tier slug. The tests themselves
# are pure unit tests — they mock the OpenAI client and never hit the network.
# ---------------------------------------------------------------------------

_OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "openrouter/free")


def _openrouter_adapter_with_mock_client(mock_cls, timeout=45, max_tokens=4096):
    """Build an OpenRouterAdapter with a mocked OpenAI client."""
    from mykg.llm.openrouter_adapter import OpenRouterAdapter

    return OpenRouterAdapter(
        model=_OPENROUTER_MODEL,
        max_tokens=max_tokens,
        timeout=timeout,
        api_key="test-key",
    )


def _mock_create_response():
    r = MagicMock()
    r.choices[0].message.content = '{"nodes": [], "edges": []}'
    r.usage.prompt_tokens = 10
    r.usage.completion_tokens = 5
    return r


def test_openrouter_constructor_timeout_forwarded_to_create():
    """The timeout from mykg_config.yaml is used as the wall-clock deadline.

    The adapter enforces the timeout via future.result(timeout=...), not as a
    kwarg to chat.completions.create(). Verify the call completes successfully
    and create() is invoked (timeout enforcement is tested via TimeoutError tests).
    """
    with patch("openai.OpenAI") as mock_cls, patch("mykg.llm.openrouter_adapter.record_llm_call"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_create_response()

        adapter = _openrouter_adapter_with_mock_client(mock_cls, timeout=45)
        result = adapter.complete("sys", "user")

    assert mock_client.chat.completions.create.called
    assert result == '{"nodes": [], "edges": []}'


def test_openrouter_per_call_timeout_override_reaches_create():
    """complete(timeout=1200) overrides the 45s constructor default for that call.

    The timeout is used as the wall-clock deadline via future.result(timeout=...),
    not forwarded as a kwarg to chat.completions.create().
    """
    with patch("openai.OpenAI") as mock_cls, patch("mykg.llm.openrouter_adapter.record_llm_call"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_create_response()

        adapter = _openrouter_adapter_with_mock_client(mock_cls, timeout=45)
        result = adapter.complete("sys", "user", timeout=1200)

    assert mock_client.chat.completions.create.called
    assert result == '{"nodes": [], "edges": []}'


def test_openrouter_per_call_max_tokens_override_reaches_create():
    """complete(max_tokens=16384) overrides the constructor max_tokens for that call."""
    with patch("openai.OpenAI") as mock_cls, patch("mykg.llm.openrouter_adapter.record_llm_call"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_create_response()

        adapter = _openrouter_adapter_with_mock_client(mock_cls, max_tokens=4096)
        adapter.complete("sys", "user", max_tokens=16384)

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["max_tokens"] == 16384, (
        f"per-call max_tokens override not forwarded; got {kwargs.get('max_tokens')!r}"
    )


def test_openrouter_no_override_uses_constructor_defaults():
    """complete() without overrides uses constructor max_tokens.

    The timeout is enforced via future.result(timeout=...), not as a kwarg to create().
    """
    with patch("openai.OpenAI") as mock_cls, patch("mykg.llm.openrouter_adapter.record_llm_call"):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = _mock_create_response()

        adapter = _openrouter_adapter_with_mock_client(mock_cls, timeout=45, max_tokens=8192)
        adapter.complete("sys", "user")

    kwargs = mock_client.chat.completions.create.call_args[1]
    assert kwargs["max_tokens"] == 8192


# ---------------------------------------------------------------------------
# OpenRouterAdapter — live integration tests
#
# These make a real network call to OpenRouter. They are skipped automatically
# when OPENROUTER_API_KEY is not set. Run explicitly with:
#   .venv/bin/pytest tests/test_llm_adapters.py -m live -v
# ---------------------------------------------------------------------------


def _skip_if_quota_exhausted(exc: BaseException) -> None:
    """Skip rather than fail when the account is out of quota, not the code.

    A live test exists to prove the provider accepts our request shape. A 429
    for an exhausted free-tier allowance says nothing about that — it reports
    the state of the account — so failing on it is a false negative that makes
    the suite unusable on free keys. Genuine rejections (400 on an unsupported
    parameter, auth errors) still fail loudly.
    """
    msg = str(exc).lower()
    markers = ("resource_exhausted", "exceeded your current quota", "quota exceeded")
    if any(marker in msg for marker in markers):
        pytest.skip(f"provider quota exhausted, not a code failure: {str(exc)[:120]}")


def _load_openrouter_api_key() -> str | None:
    """Load OPENROUTER_API_KEY from the environment or .env.mykg."""
    return _load_api_key("OPENROUTER_AUTH_TOKEN", "OPENROUTER_API_KEY")


def test_openrouter_endpoint_label_includes_model_and_base_url():
    """endpoint_label() returns a string with model and base URL (line 59)."""
    with patch("openai.OpenAI"):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="some/model",
            max_tokens=100,
            timeout=10,
            api_key="test-key",
        )
        label = adapter.endpoint_label()
    assert "some/model" in label
    assert "openrouter.ai" in label


def test_openrouter_wall_clock_timeout_raises_timeouterror(monkeypatch):
    """When future.result raises concurrent.futures.TimeoutError, the adapter raises
    TimeoutError and records the call with the timeout error annotation (lines 94-109)."""
    import concurrent.futures as _cf

    class _SlowFuture:
        def result(self, timeout=None):
            raise _cf.TimeoutError

    class _FakeExec:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn):
            return _SlowFuture()

    with (
        patch("openai.OpenAI"),
        patch("mykg.llm.openrouter_adapter.concurrent.futures.ThreadPoolExecutor", _FakeExec),
        patch("mykg.llm.openrouter_adapter.record_llm_call") as mock_record,
    ):
        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="m",
            max_tokens=10,
            timeout=1,
            api_key="test-key",
            retry_429_max=0,  # don't retry through the rate-limit harness
        )
        with pytest.raises(TimeoutError, match="wall-clock timeout"):
            adapter.complete("s", "u", context_label="ctx-tw")

    # record_llm_call should have been invoked with the wall-clock error
    found = any(
        "wall-clock timeout" in str(c.kwargs.get("error", "")) for c in mock_record.call_args_list
    )
    assert found, "record_llm_call should record the wall-clock timeout error"


def test_openrouter_api_status_error_4xx_records_and_raises():
    """APIStatusError with status<500 is recorded and re-raised (lines 129-141, 150)."""
    import openai

    api_err = openai.APIStatusError(
        message="bad request",
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": "bad request"}},
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        patch("mykg.llm.openrouter_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="m",
            max_tokens=10,
            timeout=10,
            api_key="test-key",
            retry_429_max=0,
        )
        with pytest.raises(openai.APIStatusError):
            adapter.complete("s", "u")

    # A 4xx is recorded with status_code in the metadata
    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any(k.get("status_code") == 400 for k in call_kwargs_list)


def test_openrouter_api_status_error_5xx_converted_to_rate_limit(monkeypatch):
    """APIStatusError with status>=500 is converted to RateLimitError (lines 144-149)."""
    import openai

    api_err = openai.APIStatusError(
        message="upstream",
        response=MagicMock(status_code=502, headers={}),
        body={"error": {"message": "upstream"}},
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        patch("mykg.llm.openrouter_adapter.record_llm_call"),
        patch("time.sleep"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="m",
            max_tokens=10,
            timeout=10,
            api_key="test-key",
            retry_429_max=1,
            retry_429_base_delay=0.0,
        )
        # The 5xx is converted to RateLimitError, which after retries surfaces
        with pytest.raises(openai.RateLimitError):
            adapter.complete("s", "u")


@pytest.mark.live
def test_openrouter_live_call_respects_timeout():
    """Live call: confirms the adapter actually connects and returns a non-empty response
    within the configured timeout. Also verifies that a tight per-call timeout raises
    rather than silently returning empty.

    Uses OPENROUTER_MODEL env var if set, otherwise openrouter/free.
    Requires OPENROUTER_API_KEY in environment or .env.
    """
    api_key = _load_openrouter_api_key()
    if not api_key:
        pytest.skip("OPENROUTER_API_KEY not set")

    model = os.environ.get("OPENROUTER_MODEL", "openrouter/free")

    from mykg.llm.openrouter_adapter import OpenRouterAdapter

    # --- normal call: should succeed within a generous timeout ---
    # openrouter/free routes to whatever free model is currently available. A
    # reasoning model spends output tokens on thinking, so a 64-token budget
    # truncates it before any visible text (finish_reason=length) and this
    # assertion fails intermittently for reasons unrelated to the timeout under
    # test. The tight-timeout adapter below keeps its small budget on purpose.
    adapter = OpenRouterAdapter(
        model=model,
        max_tokens=2000,
        timeout=120,
        api_key=api_key,
    )
    response = adapter.complete(
        system="You are a helpful assistant. Reply only with the word PONG.",
        user="PING",
        context_label="live_timeout_test",
    )
    assert response.strip(), f"expected a non-empty response from {model}, got empty"
    print(f"\n[live] model={model!r} response={response.strip()!r}")

    # --- tight timeout: should raise, not silently return empty ---
    adapter_tight = OpenRouterAdapter(
        model=model,
        max_tokens=64,
        timeout=1,
        api_key=api_key,
    )
    with pytest.raises(Exception) as exc_info:
        adapter_tight.complete(
            system="You are a helpful assistant.",
            user="Write a 500-word essay on the history of computing.",
            context_label="live_timeout_test_tight",
        )
    print(f"[live] tight timeout raised: {type(exc_info.value).__name__}: {exc_info.value}")
    # Accept any exception — the SDK raises openai.APITimeoutError or httpx.ReadTimeout
    assert exc_info.value is not None


# ── finish_reason (truncation) detection ─────────────────────────────────────


def test_anthropic_adapter_truncated_response_logs_finish_reason():
    """stop_reason == 'max_tokens' is surfaced as finish_reason='max_tokens'."""
    truncated_block = MagicMock()
    truncated_block.text = "{ incomplete json"
    truncated_response = MagicMock()
    truncated_response.content = [truncated_block]
    truncated_response.stop_reason = "max_tokens"

    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = truncated_response

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user")

    assert mock_record.call_args.kwargs.get("finish_reason") == "max_tokens"


def test_anthropic_adapter_normal_response_omits_finish_reason():
    """stop_reason == 'end_turn' does not set finish_reason."""
    ok_block = MagicMock()
    ok_block.text = "{}"
    ok_response = MagicMock()
    ok_response.content = [ok_block]
    ok_response.stop_reason = "end_turn"

    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = ok_response

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user")

    assert mock_record.call_args.kwargs.get("finish_reason") is None


def test_anthropic_adapter_context_exceeded_logs_and_reraises():
    """A context-length-exceeded APIStatusError is logged with a marker and re-raised."""
    import anthropic

    api_err = anthropic.APIStatusError(
        message="prompt is too long: 250000 tokens > 200000 maximum",
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": "prompt is too long: 250000 tokens > 200000 maximum"}},
    )

    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = api_err

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        with pytest.raises(anthropic.APIStatusError):
            adapter.complete("sys", "user")

    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any("context_length_exceeded" in str(k.get("error", "")) for k in call_kwargs_list)


def test_openai_adapter_truncated_response_logs_finish_reason():
    """finish_reason == 'length' is surfaced as finish_reason='length'."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{ incomplete"
    mock_response.choices[0].finish_reason = "length"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        patch("mykg.llm.openai_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        adapter.complete("system prompt", "user prompt")

    assert mock_record.call_args.kwargs.get("finish_reason") == "length"


def test_openai_adapter_normal_response_omits_finish_reason():
    """finish_reason == 'stop' does not set finish_reason."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    mock_response.choices[0].finish_reason = "stop"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        patch("mykg.llm.openai_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        adapter.complete("system prompt", "user prompt")

    assert mock_record.call_args.kwargs.get("finish_reason") is None


def test_openai_adapter_context_exceeded_logs_and_reraises():
    """A context-length-exceeded BadRequestError is logged with a marker and re-raised."""
    import openai

    api_err = openai.BadRequestError(
        message="This model's maximum context length is 128000 tokens",
        response=MagicMock(status_code=400, headers={}),
        body={
            "error": {
                "message": "This model's maximum context length is 128000 tokens",
            }
        },
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        patch("mykg.llm.openai_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        with pytest.raises(openai.BadRequestError):
            adapter.complete("sys", "user")

    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any("context_length_exceeded" in str(k.get("error", "")) for k in call_kwargs_list)


def test_openrouter_adapter_truncated_response_logs_finish_reason():
    """finish_reason == 'length' is surfaced as finish_reason='length'."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{ incomplete"
    mock_response.choices[0].finish_reason = "length"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        patch("mykg.llm.openrouter_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(model="m", max_tokens=10, timeout=10, api_key="test-key")
        adapter.complete("s", "u")

    assert mock_record.call_args.kwargs.get("finish_reason") == "length"


def test_openrouter_adapter_normal_response_omits_finish_reason():
    """finish_reason == 'stop' does not set finish_reason."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    mock_response.choices[0].finish_reason = "stop"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        patch("mykg.llm.openrouter_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(model="m", max_tokens=10, timeout=10, api_key="test-key")
        adapter.complete("s", "u")

    assert mock_record.call_args.kwargs.get("finish_reason") is None


def test_openrouter_adapter_context_exceeded_marks_error():
    """A context-length-exceeded 4xx APIStatusError gets the marker prefix on error."""
    import openai

    api_err = openai.APIStatusError(
        message="maximum context length exceeded",
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": "maximum context length exceeded"}},
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        patch("mykg.llm.openrouter_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="m", max_tokens=10, timeout=10, api_key="test-key", retry_429_max=0
        )
        with pytest.raises(openai.APIStatusError):
            adapter.complete("s", "u")

    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any("context_length_exceeded" in str(k.get("error", "")) for k in call_kwargs_list)


def test_ollama_adapter_truncated_response_logs_finish_reason():
    """done_reason == 'length' is surfaced as finish_reason='length'."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"response": "trunc", "done_reason": "length"}
    ).encode()

    with (
        patch("urllib.request.urlopen") as mock_urlopen,
        patch("mykg.llm.ollama_adapter.record_llm_call") as mock_record,
    ):
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=10,
            context_window=64000,
        )
        adapter.complete("system prompt", "user prompt")

    assert mock_record.call_args.kwargs.get("finish_reason") == "length"


def test_ollama_adapter_normal_response_omits_finish_reason():
    """done_reason == 'stop' does not set finish_reason."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"response": "hello", "done_reason": "stop"}
    ).encode()

    with (
        patch("urllib.request.urlopen") as mock_urlopen,
        patch("mykg.llm.ollama_adapter.record_llm_call") as mock_record,
    ):
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=10,
            context_window=64000,
        )
        adapter.complete("system prompt", "user prompt")

    assert mock_record.call_args.kwargs.get("finish_reason") is None


def test_ollama_adapter_context_exceeded_http_error_logs_and_reraises():
    """A context-length-exceeded HTTPError is logged with a marker and re-raised."""
    # looks_like_context_exceeded matches on str(exc), which for HTTPError is
    # "HTTP Error <code>: <msg>" — the marker must be in msg, not the body.
    exc = urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=400,
        msg="maximum context length exceeded",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )

    with (
        patch("urllib.request.urlopen", side_effect=exc),
        patch("mykg.llm.ollama_adapter.record_llm_call") as mock_record,
    ):
        adapter = _ollama_adapter(retry_max=0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any("context_length_exceeded" in str(k.get("error", "")) for k in call_kwargs_list)


def test_ollama_adapter_context_exceeded_url_error_logs_and_reraises():
    """A context-length-exceeded URLError is logged with a marker and re-raised."""
    exc = urllib.error.URLError("maximum context length exceeded")

    with (
        patch("urllib.request.urlopen", side_effect=exc),
        patch("mykg.llm.ollama_adapter.record_llm_call") as mock_record,
    ):
        adapter = _ollama_adapter(retry_max=0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    call_kwargs_list = [c.kwargs for c in mock_record.call_args_list]
    assert any("context_length_exceeded" in str(k.get("error", "")) for k in call_kwargs_list)


def test_ollama_adapter_non_context_url_error_not_logged():
    """A plain URLError unrelated to context overflow does not get the marker."""
    exc = urllib.error.URLError("connection refused")

    with (
        patch("urllib.request.urlopen", side_effect=exc),
        patch("mykg.llm.ollama_adapter.record_llm_call") as mock_record,
    ):
        adapter = _ollama_adapter(retry_max=0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    mock_record.assert_not_called()


def test_looks_like_context_exceeded_matches_known_markers():
    """The shared heuristic matches common cross-provider context-overflow phrasing."""
    from mykg.llm.retry import looks_like_context_exceeded

    assert looks_like_context_exceeded(Exception("maximum context length is 128000 tokens"))
    assert looks_like_context_exceeded(Exception("prompt is too long for this model"))
    assert looks_like_context_exceeded(RuntimeError("n_ctx exceeded"))
    assert not looks_like_context_exceeded(Exception("rate limit exceeded"))
    assert not looks_like_context_exceeded(Exception("connection refused"))


# ── run.log warnings for finish_reason / context-overflow (independent of llm.log) ──


def test_anthropic_truncation_warns_on_standard_logger(caplog):
    """Truncated output is warned via mykg.llm.retry's logger, reaching run.log
    regardless of the llm_log/LOG_LLM_LOG toggle."""
    truncated_block = MagicMock()
    truncated_block.text = "{ incomplete"
    truncated_response = MagicMock()
    truncated_response.content = [truncated_block]
    truncated_response.stop_reason = "max_tokens"

    with (
        patch("anthropic.Anthropic") as mock_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = truncated_response

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user", context_label="ctx-1")

    assert any("output truncated" in r.message for r in caplog.records)
    assert any("anthropic/claude-sonnet-4-6" in r.message for r in caplog.records)


def test_anthropic_normal_completion_emits_no_warning(caplog):
    """A clean completion must not emit a truncation/overflow warning."""
    ok_block = MagicMock()
    ok_block.text = "{}"
    ok_response = MagicMock()
    ok_response.content = [ok_block]
    ok_response.stop_reason = "end_turn"

    with (
        patch("anthropic.Anthropic") as mock_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = ok_response

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user")

    assert caplog.records == []


def test_anthropic_context_overflow_warns_on_standard_logger(caplog):
    """A context-length-exceeded APIStatusError is warned before re-raising."""
    import anthropic

    api_err = anthropic.APIStatusError(
        message="prompt is too long: 250000 tokens > 200000 maximum",
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": "prompt is too long: 250000 tokens > 200000 maximum"}},
    )

    with (
        patch("anthropic.Anthropic") as mock_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.side_effect = api_err

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        with pytest.raises(anthropic.APIStatusError):
            adapter.complete("sys", "user", context_label="ctx-2")

    assert any("context length exceeded" in r.message for r in caplog.records)
    assert any("anthropic/claude-sonnet-4-6" in r.message for r in caplog.records)


def test_openai_truncation_warns_on_standard_logger(caplog):
    """finish_reason == 'length' is warned via the standard logger."""
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{ incomplete"
    mock_response.choices[0].finish_reason = "length"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        adapter.complete("system prompt", "user prompt")

    assert any("output truncated" in r.message for r in caplog.records)
    assert any("openai/gpt-4o" in r.message for r in caplog.records)


def test_openai_normal_completion_emits_no_warning(caplog):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    mock_response.choices[0].finish_reason = "stop"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        adapter.complete("system prompt", "user prompt")

    assert caplog.records == []


def test_openai_context_overflow_warns_on_standard_logger(caplog):
    """A context-length-exceeded BadRequestError is warned before re-raising."""
    import openai

    api_err = openai.BadRequestError(
        message="This model's maximum context length is 128000 tokens",
        response=MagicMock(status_code=400, headers={}),
        body={
            "error": {
                "message": "This model's maximum context length is 128000 tokens",
            }
        },
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=10, timeout=30, api_key="test-key")
        with pytest.raises(openai.BadRequestError):
            adapter.complete("sys", "user")

    assert any("context length exceeded" in r.message for r in caplog.records)
    assert any("openai/gpt-4o" in r.message for r in caplog.records)


def test_openrouter_truncation_warns_on_standard_logger(caplog):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{ incomplete"
    mock_response.choices[0].finish_reason = "length"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(model="m", max_tokens=10, timeout=10, api_key="test-key")
        adapter.complete("s", "u")

    assert any("output truncated" in r.message for r in caplog.records)
    assert any("openrouter/m" in r.message for r in caplog.records)


def test_openrouter_normal_completion_emits_no_warning(caplog):
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "hello"
    mock_response.choices[0].finish_reason = "stop"

    with (
        patch("openai.OpenAI") as mock_client_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(model="m", max_tokens=10, timeout=10, api_key="test-key")
        adapter.complete("s", "u")

    assert caplog.records == []


def test_openrouter_context_overflow_warns_on_standard_logger(caplog):
    import openai

    api_err = openai.APIStatusError(
        message="maximum context length exceeded",
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": "maximum context length exceeded"}},
    )

    with (
        patch("openai.OpenAI") as mock_cls,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.chat.completions.create.side_effect = api_err

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="m", max_tokens=10, timeout=10, api_key="test-key", retry_429_max=0
        )
        with pytest.raises(openai.APIStatusError):
            adapter.complete("s", "u")

    assert any("context length exceeded" in r.message for r in caplog.records)
    assert any("openrouter/m" in r.message for r in caplog.records)


def test_ollama_truncation_warns_on_standard_logger(caplog):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"response": "trunc", "done_reason": "length"}
    ).encode()

    with (
        patch("urllib.request.urlopen") as mock_urlopen,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=10,
            context_window=64000,
        )
        adapter.complete("system prompt", "user prompt")

    assert any("output truncated" in r.message for r in caplog.records)
    assert any("ollama/gemma4:31b" in r.message for r in caplog.records)


def test_ollama_normal_completion_emits_no_warning(caplog):
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps(
        {"response": "hello", "done_reason": "stop"}
    ).encode()

    with (
        patch("urllib.request.urlopen") as mock_urlopen,
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=10,
            context_window=64000,
        )
        adapter.complete("system prompt", "user prompt")

    assert caplog.records == []


def test_ollama_context_overflow_http_error_warns_on_standard_logger(caplog):
    exc = urllib.error.HTTPError(
        url="http://localhost:11434/api/generate",
        code=400,
        msg="maximum context length exceeded",
        hdrs=None,  # type: ignore[arg-type]
        fp=io.BytesIO(b""),
    )

    with (
        patch("urllib.request.urlopen", side_effect=exc),
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        adapter = _ollama_adapter(retry_max=0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    assert any("context length exceeded" in r.message for r in caplog.records)


def test_ollama_context_overflow_url_error_warns_on_standard_logger(caplog):
    exc = urllib.error.URLError("maximum context length exceeded")

    with (
        patch("urllib.request.urlopen", side_effect=exc),
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        adapter = _ollama_adapter(retry_max=0)
        with pytest.raises(RuntimeError, match="Ollama request failed"):
            adapter.complete("sys", "user")

    assert any("context length exceeded" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# AnthropicAdapter — prompt caching
# ---------------------------------------------------------------------------


class _Usage:
    """Minimal usage object with only the attributes the response carries.

    Using a plain class (not MagicMock) lets a test omit the cache attributes
    entirely so the adapter's getattr(..., 0) default path is exercised.
    """

    def __init__(self, input_tokens=10, output_tokens=5, **extra):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        for k, v in extra.items():
            setattr(self, k, v)


def _anthropic_response(text="{}", usage=None):
    block = MagicMock()
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    resp.usage = usage if usage is not None else _Usage()
    return resp


def test_anthropic_adapter_sends_cache_control():
    """complete() passes top-level cache_control={'type': 'ephemeral'} to messages.create."""
    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call"),
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _anthropic_response()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("system prompt", "user prompt")

    kwargs = mock_client.messages.create.call_args.kwargs
    assert kwargs.get("cache_control") == {"type": "ephemeral"}
    # system stays a plain string — top-level cache_control auto-caches it.
    assert kwargs.get("system") == "system prompt"


def test_anthropic_adapter_reports_cache_usage():
    """Cache read/creation token counts from usage reach record_llm_call."""
    usage = _Usage(
        input_tokens=42,
        output_tokens=7,
        cache_read_input_tokens=1234,
        cache_creation_input_tokens=56,
    )

    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _anthropic_response(usage=usage)

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs.get("cache_read_tokens") == 1234
    assert kwargs.get("cache_creation_tokens") == 56


def test_anthropic_adapter_cache_usage_defaults_to_zero():
    """When usage lacks the cache attributes, record_llm_call gets 0 (no crash)."""
    # _Usage() built without the cache attrs — the getattr default path.
    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = _anthropic_response(usage=_Usage())

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs.get("cache_read_tokens") == 0
    assert kwargs.get("cache_creation_tokens") == 0


def test_anthropic_adapter_missing_usage_defaults_all_to_zero():
    """A response with usage=None does not raise; all four counts default to 0."""
    resp = _anthropic_response()
    resp.usage = None  # SDK omitted usage entirely

    with (
        patch("anthropic.Anthropic") as mock_cls,
        patch("mykg.llm.anthropic_adapter.record_llm_call") as mock_record,
    ):
        mock_client = MagicMock()
        mock_cls.return_value = mock_client
        mock_client.messages.create.return_value = resp

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6", max_tokens=10, timeout=10, api_key="test-key"
        )
        # Must not raise AttributeError even though usage is None.
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs.get("input_tokens") == 0
    assert kwargs.get("output_tokens") == 0
    assert kwargs.get("cache_read_tokens") == 0
    assert kwargs.get("cache_creation_tokens") == 0


# ---------------------------------------------------------------------------
# GeminiAdapter
# ---------------------------------------------------------------------------


class _GeminiUsage:
    """usage_metadata stand-in.

    Plain class rather than MagicMock so a test can omit fields entirely and
    exercise the adapter's absent-field default path. Gemini reports these as
    present-but-None when a count does not apply, so None is the default here
    rather than 0.
    """

    def __init__(
        self,
        prompt_token_count=100,
        candidates_token_count=20,
        thoughts_token_count=None,
        cached_content_token_count=None,
    ):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count
        self.thoughts_token_count = thoughts_token_count
        self.cached_content_token_count = cached_content_token_count


def _gemini_response(text="{}", finish_reason="STOP", usage=None):
    """Build a generate_content response double.

    finish_reason is an enum in the real SDK, so the double exposes `.name`
    exactly as FinishReason does.
    """
    candidate = MagicMock()
    candidate.finish_reason = MagicMock()
    candidate.finish_reason.name = finish_reason
    resp = MagicMock()
    resp.candidates = [candidate]
    resp.text = text
    resp.usage_metadata = usage if usage is not None else _GeminiUsage()
    return resp


def _gemini_client(response=None, side_effect=None):
    """Patch google.genai.Client and return (patcher_cm, mock_client)."""
    mock_client = MagicMock()
    if side_effect is not None:
        mock_client.models.generate_content.side_effect = side_effect
    else:
        mock_client.models.generate_content.return_value = response or _gemini_response()
    return mock_client


def _api_error(status: int, message: str = "boom"):
    """Construct a google-genai APIError carrying an HTTP status code."""
    from google.genai import errors as genai_errors

    exc = genai_errors.APIError.__new__(genai_errors.APIError)
    Exception.__init__(exc, message)
    exc.code = status
    exc.message = message
    return exc


def test_gemini_adapter_complete():
    """complete() sends system as system_instruction and user as contents."""
    with patch("google.genai.Client") as mock_cls:
        mock_client = _gemini_client(_gemini_response(text='{"ok": true}'))
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash", max_tokens=4096, timeout=30, api_key="test-key"
        )
        result = adapter.complete("system prompt", "user prompt")

    assert result == '{"ok": true}'
    kwargs = mock_client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.7-flash"
    assert kwargs["contents"] == "user prompt"
    assert kwargs["config"].system_instruction == "system prompt"
    assert kwargs["config"].max_output_tokens == 4096


def test_gemini_adapter_requests_json_and_thinking_level():
    """JSON mime type and the configured thinking_level reach the request config."""
    with patch("google.genai.Client") as mock_cls:
        mock_client = _gemini_client()
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            thinking_level="medium",
        )
        adapter.complete("sys", "user")

    config = mock_client.models.generate_content.call_args.kwargs["config"]
    assert config.response_mime_type == "application/json"
    # The SDK coerces the string into a ThinkingLevel enum, so compare on value.
    assert str(config.thinking_config.thinking_level.value).lower() == "medium"


def test_gemini_thinking_level_none_omits_thinking_config():
    """thinking_level=None sends no thinking_config, letting the model decide.

    Kept configurable because thinking tokens are billed as output and drawn from
    the max_output_tokens allowance; "low" is only a measured default, not a
    requirement.
    """
    with patch("google.genai.Client") as mock_cls:
        mock_client = _gemini_client()
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=4096,
            timeout=30,
            api_key="test-key",
            thinking_level=None,
        )
        adapter.complete("sys", "user")

    assert mock_client.models.generate_content.call_args.kwargs["config"].thinking_config is None


def test_gemini_adapter_per_call_max_tokens_override():
    """A per-call max_tokens overrides the adapter default."""
    with patch("google.genai.Client") as mock_cls:
        mock_client = _gemini_client()
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash", max_tokens=4096, timeout=30, api_key="test-key"
        )
        adapter.complete("sys", "user", max_tokens=99)

    assert mock_client.models.generate_content.call_args.kwargs["config"].max_output_tokens == 99


def test_gemini_adapter_forwards_timeout_as_milliseconds():
    """The configured timeout reaches the SDK, converted from seconds to ms."""
    with patch("google.genai.Client") as mock_cls:
        mock_client = _gemini_client()
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash", max_tokens=10, timeout=30, api_key="test-key"
        )
        adapter.complete("sys", "user")
        adapter.complete("sys", "user", timeout=7)

    calls = mock_client.models.generate_content.call_args_list
    assert calls[0].kwargs["config"].http_options.timeout == 30_000
    # per-call override wins
    assert calls[1].kwargs["config"].http_options.timeout == 7_000


def test_gemini_adapter_raises_without_api_key():
    """Missing GEMINI_API_KEY and GOOGLE_API_KEY raises a helpful ValueError."""
    with patch("google.genai.Client"), patch.dict(os.environ, {}, clear=True):
        from mykg.llm.gemini_adapter import GeminiAdapter

        with pytest.raises(ValueError, match="GEMINI_API_KEY"):
            GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10)


def test_gemini_adapter_falls_back_to_google_api_key():
    """GOOGLE_API_KEY is accepted when GEMINI_API_KEY is absent."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch.dict(os.environ, {"GOOGLE_API_KEY": "goog-key"}, clear=True),
    ):
        from mykg.llm.gemini_adapter import GeminiAdapter

        GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10)

    assert mock_cls.call_args.kwargs["api_key"] == "goog-key"


def test_gemini_endpoint_label_includes_model():
    with patch("google.genai.Client"):
        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
    label = adapter.endpoint_label()
    assert "gemini" in label
    assert "gemini-3.7-flash" in label


def test_config_creates_gemini_adapter():
    """load_adapter dispatches provider 'gemini' and forwards retry settings."""
    raw = {
        "provider": "gemini",
        "llm": {
            "model": "gemini-3.7-flash",
            "max_output_tokens": 4096,
            "timeout": 120,
            "thinking_level": "high",
            "retry_429_max": 4,
            "retry_429_base_delay": 5.0,
        },
    }
    with patch("google.genai.Client"), patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}):
        from mykg.llm.config import load_adapter
        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = load_adapter(_raw=raw)

    assert isinstance(adapter, GeminiAdapter)
    assert adapter._model == "gemini-3.7-flash"
    assert adapter._max_tokens == 4096
    assert adapter._thinking_level == "high"
    assert adapter._retry_429_max == 4
    assert adapter._retry_429_base_delay == 5.0


def test_gemini_429_retries_and_succeeds():
    """A 429 is retried and the subsequent success is returned."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch("time.sleep"),
    ):
        mock_client = _gemini_client(
            side_effect=[_api_error(429, "quota"), _gemini_response(text='{"ok":1}')]
        )
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=10,
            timeout=10,
            api_key="k",
            retry_429_max=2,
            retry_429_base_delay=0.01,
        )
        assert adapter.complete("sys", "user") == '{"ok":1}'

    assert mock_client.models.generate_content.call_count == 2


def test_gemini_5xx_is_retried():
    """A transient 5xx is retried rather than surfaced immediately."""
    with patch("google.genai.Client") as mock_cls, patch("time.sleep"):
        mock_client = _gemini_client(
            side_effect=[_api_error(503, "overloaded"), _gemini_response(text="{}")]
        )
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=10,
            timeout=10,
            api_key="k",
            retry_429_max=2,
            retry_429_base_delay=0.01,
        )
        adapter.complete("sys", "user")

    assert mock_client.models.generate_content.call_count == 2


def test_gemini_400_is_not_retried():
    """A 400 is a caller error — surfaced immediately, never retried (cf. PR #44)."""
    from google.genai import errors as genai_errors

    with patch("google.genai.Client") as mock_cls, patch("time.sleep"):
        mock_client = _gemini_client(side_effect=_api_error(400, "invalid argument"))
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=10,
            timeout=10,
            api_key="k",
            retry_429_max=3,
            retry_429_base_delay=0.01,
        )
        with pytest.raises(genai_errors.APIError):
            adapter.complete("sys", "user")

    assert mock_client.models.generate_content.call_count == 1


def test_gemini_exhausts_retries_and_raises_provider_error():
    """After retries are exhausted the provider's own exception surfaces."""
    from google.genai import errors as genai_errors

    with patch("google.genai.Client") as mock_cls, patch("time.sleep"):
        mock_client = _gemini_client(side_effect=_api_error(429, "quota"))
        mock_cls.return_value = mock_client

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=10,
            timeout=10,
            api_key="k",
            retry_429_max=2,
            retry_429_base_delay=0.01,
        )
        with pytest.raises(genai_errors.APIError):
            adapter.complete("sys", "user")

    assert mock_client.models.generate_content.call_count == 3


def test_gemini_reports_cached_token_usage():
    """cached_content_token_count is forwarded as cache_read_tokens.

    Implicit caching is automatic and server-side; the adapter only reports it.
    """
    usage = _GeminiUsage(
        prompt_token_count=7005,
        candidates_token_count=12,
        thoughts_token_count=30,
        cached_content_token_count=4037,
    )
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(_gemini_response(usage=usage))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=100, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs["input_tokens"] == 7005
    # thinking tokens are billed output, so they are counted as output
    assert kwargs["output_tokens"] == 42
    assert kwargs["cache_read_tokens"] == 4037
    # implicit caching has no creation step
    assert kwargs.get("cache_creation_tokens", 0) == 0


def test_gemini_absent_usage_counts_default_to_zero():
    """None-valued usage fields coerce to 0 rather than raising."""
    usage = _GeminiUsage(
        prompt_token_count=None,
        candidates_token_count=None,
        thoughts_token_count=None,
        cached_content_token_count=None,
    )
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(_gemini_response(usage=usage))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs["input_tokens"] == 0
    assert kwargs["output_tokens"] == 0
    assert kwargs["cache_read_tokens"] == 0


def test_gemini_truncated_response_logs_finish_reason():
    """MAX_TOKENS is normalised to 'max_tokens' for record_llm_call."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(
            _gemini_response(text='{"partial": ', finish_reason="MAX_TOKENS")
        )

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    assert mock_record.call_args.kwargs["finish_reason"] == "max_tokens"


def test_gemini_normal_response_omits_finish_reason():
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(_gemini_response(finish_reason="STOP"))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    assert mock_record.call_args.kwargs["finish_reason"] is None


def test_gemini_empty_output_at_cap_warns_about_thinking_budget(caplog):
    """An empty body at MAX_TOKENS names the thinking budget as the cause.

    Gemini draws thinking tokens from max_output_tokens, so a too-small budget
    returns finish_reason=MAX_TOKENS with no text at all. Without this warning
    the failure surfaces downstream as an unexplained blank chunk (D33).
    """
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = _gemini_client(
            _gemini_response(text="", finish_reason="MAX_TOKENS")
        )

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        with caplog.at_level("WARNING", logger="mykg.llm.gemini_adapter"):
            assert adapter.complete("sys", "user") == ""

    assert any("thinking budget" in r.getMessage().lower() for r in caplog.records)
    assert any("max_output_tokens" in r.getMessage() for r in caplog.records)


def test_gemini_context_exceeded_logs_and_reraises(caplog):
    """A context-overflow error is logged with the standard marker and re-raised."""
    from google.genai import errors as genai_errors

    with (
        patch("google.genai.Client") as mock_cls,
        patch("time.sleep"),
        caplog.at_level("WARNING", logger="mykg.llm.retry"),
    ):
        mock_cls.return_value = _gemini_client(
            side_effect=_api_error(400, "input token count exceeds the maximum")
        )

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k", retry_429_max=0
        )
        with pytest.raises(genai_errors.APIError):
            adapter.complete("sys", "user")

    assert any("context length exceeded" in r.message for r in caplog.records)
    assert any("gemini/gemini-3.7-flash" in r.message for r in caplog.records)


def test_gemini_strips_code_fences():
    """A fenced JSON body is unwrapped like every other adapter."""
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = _gemini_client(_gemini_response(text='```json\n{"a": 1}\n```'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        assert adapter.complete("sys", "user") == '{"a": 1}'


@pytest.mark.live
def test_gemini_live_call_returns_json():
    """Real API call — skipped unless GEMINI_API_KEY is set."""
    key = _load_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")

    from mykg.llm.gemini_adapter import GeminiAdapter

    adapter = GeminiAdapter(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.7-flash"),
        max_tokens=2000,
        timeout=120,
        api_key=key,
    )
    try:
        out = adapter.complete("Reply with JSON only.", 'Return {"pong": true}')
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise
    assert out.strip()
    assert json.loads(out)["pong"] is True


def test_gemini_safety_blocked_response_warns_and_records(caplog):
    """A SAFETY-blocked empty body is diagnosed instead of returning silently.

    Gemini returns HTTP 200 with an empty body and finish_reason=SAFETY when it
    refuses. Without an explicit branch this looks identical to a successful
    empty extraction and lands in failed_chunks.json unexplained (D33).
    """
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(_gemini_response(text="", finish_reason="SAFETY"))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=500, timeout=10, api_key="k")
        with caplog.at_level("WARNING", logger="mykg.llm.gemini_adapter"):
            assert adapter.complete("sys", "user") == ""

    assert any("blocked" in r.getMessage().lower() for r in caplog.records)
    assert any("SAFETY" in r.getMessage() for r in caplog.records)
    assert "SAFETY" in (mock_record.call_args.kwargs.get("error") or "")


def test_gemini_recitation_block_is_reported():
    """RECITATION is treated the same as any other non-STOP empty response."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(
            _gemini_response(text="", finish_reason="RECITATION")
        )

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=500, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    assert "RECITATION" in (mock_record.call_args.kwargs.get("error") or "")


def test_gemini_successful_response_records_no_error():
    """A normal STOP response carries no error field."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(
            _gemini_response(text='{"ok": true}', finish_reason="STOP")
        )

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=500, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    assert mock_record.call_args.kwargs.get("error") is None


def test_gemini_empty_body_with_stop_is_not_flagged_as_blocked():
    """An empty body with finish_reason=STOP is a genuine empty answer, not a block."""
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        mock_cls.return_value = _gemini_client(_gemini_response(text="", finish_reason="STOP"))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=500, timeout=10, api_key="k")
        assert adapter.complete("sys", "user") == ""

    assert mock_record.call_args.kwargs.get("error") is None


def test_gemini_output_cap_error_not_mislabelled_as_context_overflow():
    """A max_output_tokens rejection must not be reported as context overflow.

    The two have different fixes — one is a chunking-budget problem, the other a
    max_output_tokens problem — so conflating them misdirects the operator.
    """
    from mykg.llm.retry import looks_like_context_exceeded

    output_cap = Exception(
        "Requested max_output_tokens exceeds the maximum number of tokens allowed"
    )
    input_overflow = Exception(
        "The input token count (1200000) exceeds the maximum number of tokens allowed (1048576)"
    )
    assert looks_like_context_exceeded(output_cap) is False
    assert looks_like_context_exceeded(input_overflow) is True


def test_gemini_missing_usage_metadata_defaults_to_zero():
    """A response with no usage_metadata at all records zero counts, not an error.

    Guards the `getattr(usage, field, 0)` default path in `_count` against a
    malformed or usage-free response (raised in review of PR #61).
    """
    with (
        patch("google.genai.Client") as mock_cls,
        patch("mykg.llm.gemini_adapter.record_llm_call") as mock_record,
    ):
        resp = _gemini_response()
        resp.usage_metadata = None
        mock_cls.return_value = _gemini_client(resp)

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    kwargs = mock_record.call_args.kwargs
    assert kwargs["input_tokens"] == 0
    assert kwargs["output_tokens"] == 0
    assert kwargs["cache_read_tokens"] == 0


def test_gemini_count_helper_tolerates_absent_usage():
    """_count returns 0 for a None usage object, a bare object, and non-int values."""
    from mykg.llm.gemini_adapter import _count

    class _Bare:
        pass

    class _NoneValued:
        prompt_token_count = None

    class _NonInt:
        prompt_token_count = "12"

    assert _count(None, "prompt_token_count") == 0
    assert _count(_Bare(), "prompt_token_count") == 0
    assert _count(_NoneValued(), "prompt_token_count") == 0
    assert _count(_NonInt(), "prompt_token_count") == 0


def test_gemini_afc_notice_filtered_without_muting_real_warnings():
    """The AFC notice is dropped, but genuine google_genai warnings still pass.

    Raised in review of PR #61: raising the logger's level would have suppressed
    legitimate warnings from the same logger, so a message-specific filter is
    used instead.
    """
    import logging as _logging

    with patch("google.genai.Client"):
        from mykg.llm.gemini_adapter import GeminiAdapter

        GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")

    logger = _logging.getLogger("google_genai.models")
    # The level is untouched — only a filter was added.
    assert logger.level == _logging.NOTSET

    def _rec(msg):
        return _logging.LogRecord(
            "google_genai.models", _logging.WARNING, __file__, 1, msg, None, None
        )

    # Both AFC variants the SDK emits must be dropped.
    for noisy in (
        "Direct use of automatic function calling (AFC) is not recommended",
        "AFC is enabled with max remote calls: 10.",
    ):
        assert any(not f(_rec(noisy)) for f in logger.filters), f"should be filtered: {noisy}"

    assert all(f(_rec("quota exceeded for this project")) for f in logger.filters), (
        "genuine warnings must still pass through"
    )


def test_gemini_afc_filter_installed_only_once():
    """Constructing many adapters does not stack duplicate filters."""
    import logging as _logging

    logger = _logging.getLogger("google_genai.models")
    with patch("google.genai.Client"):
        from mykg.llm.gemini_adapter import GeminiAdapter

        GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")
        before = len(logger.filters)
        for _ in range(5):
            GeminiAdapter(model="gemini-3.7-flash", max_tokens=10, timeout=10, api_key="k")

    assert len(logger.filters) == before


def test_gemini_status_of_falls_back_to_status_code():
    """_status_of reads .status_code when .code is absent or non-integer."""
    from mykg.llm.gemini_adapter import _status_of

    class _NoCode:
        status_code = 503

    class _StringCode:
        code = "RESOURCE_EXHAUSTED"
        status_code = 429

    class _Neither:
        pass

    assert _status_of(_NoCode()) == 503
    # a non-int .code must not be returned verbatim
    assert _status_of(_StringCode()) == 429
    assert _status_of(_Neither()) is None


def test_gemini_raw_finish_reason_edge_cases():
    """_raw_finish_reason handles absent candidates, a None reason, and enum reprs."""
    from mykg.llm.gemini_adapter import GeminiAdapter

    read = GeminiAdapter._raw_finish_reason

    class _NoCandidates:
        candidates = []

    class _NoneReason:
        def __init__(self):
            c = MagicMock()
            c.finish_reason = None
            self.candidates = [c]

    class _PlainStringEnum:
        """finish_reason whose str() is a dotted enum repr and has no .name."""

        def __init__(self):
            c = MagicMock()
            c.finish_reason = "FinishReason.MAX_TOKENS"
            self.candidates = [c]

    assert read(_NoCandidates()) is None
    assert read(_NoneReason()) is None
    # dotted enum repr is reduced to the bare member name
    assert read(_PlainStringEnum()) == "MAX_TOKENS"


def test_config_gemini_thinking_level_defaults_when_key_absent():
    """Omitting llm.thinking_level yields the adapter's "low" default.

    The shipped gemini profile deliberately does not carry the key, so the
    default must survive its absence rather than becoming None.
    """
    raw = {
        "provider": "gemini",
        "llm": {
            "model": "gemini-3.7-flash",
            "max_output_tokens": 4096,
            "timeout": 120,
        },
    }
    with patch("google.genai.Client"), patch.dict(os.environ, {"GEMINI_API_KEY": "k"}):
        from mykg.llm.config import load_adapter

        adapter = load_adapter(_raw=raw)

    assert adapter._thinking_level == "low"


# ---------------------------------------------------------------------------
# temperature — Anthropic
# ---------------------------------------------------------------------------


def _anthropic_client(text: str = "ok"):
    """A mocked anthropic client whose messages.create returns a text block."""
    block = MagicMock()
    block.text = text
    response = MagicMock()
    response.content = [block]
    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_anthropic_omits_temperature_when_unset():
    """No configured temperature -> the key is absent from the payload entirely."""
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = client = _anthropic_client()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-5", max_tokens=4096, timeout=30, api_key="k"
        )
        adapter.complete("sys", "user")

    assert "temperature" not in client.messages.create.call_args[1]


def test_anthropic_sends_configured_temperature():
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = client = _anthropic_client()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.2,
        )
        adapter.complete("sys", "user")

    assert client.messages.create.call_args[1]["temperature"] == 0.2


def test_anthropic_sends_zero_temperature():
    """0.0 is a real value, not an omission — a falsy check here would drop it."""
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = client = _anthropic_client()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.0,
        )
        adapter.complete("sys", "user")

    assert client.messages.create.call_args[1]["temperature"] == 0.0


def test_anthropic_per_call_temperature_overrides_configured():
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = client = _anthropic_client()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-5",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.2,
        )
        adapter.complete("sys", "user", temperature=0.9)

    assert client.messages.create.call_args[1]["temperature"] == 0.9


def test_anthropic_temperature_does_not_disturb_other_payload_keys():
    """Converting the call to a kwargs dict must preserve the existing payload."""
    with patch("anthropic.Anthropic") as mock_cls:
        mock_cls.return_value = client = _anthropic_client()

        from mykg.llm.anthropic_adapter import AnthropicAdapter

        adapter = AnthropicAdapter(
            model="claude-sonnet-4-5", max_tokens=4096, timeout=30, api_key="k"
        )
        adapter.complete("sys", "user")

    kwargs = client.messages.create.call_args[1]
    assert kwargs["model"] == "claude-sonnet-4-5"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["system"] == "sys"
    assert kwargs["messages"] == [{"role": "user", "content": "user"}]
    assert kwargs["timeout"] == 30
    assert kwargs["cache_control"] == {"type": "ephemeral"}


# ---------------------------------------------------------------------------
# temperature — OpenAI
# ---------------------------------------------------------------------------


def _openai_client(text: str = "ok"):
    """A mocked OpenAI client whose chat.completions.create returns `text`."""
    response = MagicMock()
    response.choices[0].message.content = text
    response.choices[0].finish_reason = "stop"
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


def test_openai_omits_temperature_when_unset():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(model="gpt-4o", max_tokens=4096, timeout=30, api_key="k")
        adapter.complete("sys", "user")

    assert "temperature" not in client.chat.completions.create.call_args[1]


def test_openai_sends_configured_temperature_on_ordinary_model():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.0
        )
        adapter.complete("sys", "user")

    assert client.chat.completions.create.call_args[1]["temperature"] == 0.0


def test_openai_omits_temperature_for_reasoning_model():
    """A gpt-5 model rejects an explicit temperature, so a configured value is dropped.

    This is the case that protects mykg's shipped default profile.
    """
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-5.4-mini-2026-03-17",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.0,
        )
        adapter.complete("sys", "user")

    kwargs = client.chat.completions.create.call_args[1]
    assert "temperature" not in kwargs
    # The max_completion_tokens routing for this family is unaffected.
    assert kwargs["max_completion_tokens"] == 4096


def test_openai_per_call_temperature_overrides_configured():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.2
        )
        adapter.complete("sys", "user", temperature=0.9)

    assert client.chat.completions.create.call_args[1]["temperature"] == 0.9


def _openai_bad_request(message: str):
    import openai

    return openai.BadRequestError(
        message=message,
        response=MagicMock(status_code=400, headers={}),
        body={"error": {"message": message}},
    )


def test_openai_recovers_when_api_rejects_temperature(caplog):
    """An unlisted family that 400s on temperature is retried once without it."""
    import logging

    response = MagicMock()
    response.choices[0].message.content = "recovered"
    response.choices[0].finish_reason = "stop"

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_bad_request("Unsupported value: 'temperature' is not supported"),
            response,
        ]

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.5
        )
        with caplog.at_level(logging.WARNING, logger="mykg.llm.openai_adapter"):
            assert adapter.complete("sys", "user") == "recovered"

    assert client.chat.completions.create.call_count == 2
    first, second = client.chat.completions.create.call_args_list
    assert first[1]["temperature"] == 0.5
    assert "temperature" not in second[1]
    assert "rejected an explicit temperature" in caplog.text


def test_openai_temperature_rejection_is_latched():
    """After one rejection the adapter stops sending temperature entirely."""
    ok = MagicMock()
    ok.choices[0].message.content = "ok"
    ok.choices[0].finish_reason = "stop"

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_bad_request("'temperature' is not supported with this model"),
            ok,
            ok,
        ]

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.5
        )
        adapter.complete("sys", "user")
        adapter.complete("sys", "user")

    # 2 calls for the first complete() (reject + retry), 1 for the second.
    assert client.chat.completions.create.call_count == 3
    assert "temperature" not in client.chat.completions.create.call_args_list[2][1]


def test_openai_unrelated_bad_request_still_raises():
    """The temperature branch must not swallow other 400s."""
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = _openai_bad_request(
            "Invalid value for 'messages'"
        )

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.5
        )
        with pytest.raises(openai.BadRequestError):
            adapter.complete("sys", "user")

    assert client.chat.completions.create.call_count == 1


def test_openai_max_tokens_swap_still_carries_temperature():
    """The pre-existing max_tokens fallback keeps sending the configured temperature."""
    ok = MagicMock()
    ok.choices[0].message.content = "ok"
    ok.choices[0].finish_reason = "stop"

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_bad_request(
                "Unsupported parameter: 'max_tokens' is not supported; use "
                "'max_completion_tokens' instead"
            ),
            ok,
        ]

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.3
        )
        assert adapter.complete("sys", "user") == "ok"

    second = client.chat.completions.create.call_args_list[1][1]
    assert second["max_completion_tokens"] == 4096
    assert second["temperature"] == 0.3


# ---------------------------------------------------------------------------
# temperature — OpenRouter
# ---------------------------------------------------------------------------


def test_openrouter_omits_temperature_when_unset():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="openrouter/free", max_tokens=4096, timeout=30, api_key="k"
        )
        adapter.complete("sys", "user")

    assert "temperature" not in client.chat.completions.create.call_args[1]


def test_openrouter_sends_configured_temperature():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="anthropic/claude-sonnet-4-5",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.0,
        )
        adapter.complete("sys", "user")

    assert client.chat.completions.create.call_args[1]["temperature"] == 0.0


def test_openrouter_omits_temperature_for_namespaced_reasoning_model():
    """openai/gpt-5-mini must be caught despite the vendor prefix."""
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="openai/gpt-5-mini",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.0,
        )
        adapter.complete("sys", "user")

    assert "temperature" not in client.chat.completions.create.call_args[1]


def test_openrouter_temperature_preserves_other_payload_keys():
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="openrouter/free",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.4,
        )
        adapter.complete("sys", "user")

    kwargs = client.chat.completions.create.call_args[1]
    assert kwargs["model"] == "openrouter/free"
    assert kwargs["max_tokens"] == 4096
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["temperature"] == 0.4


# ---------------------------------------------------------------------------
# temperature — Gemini
# ---------------------------------------------------------------------------


def _gemini_config_of(client):
    """The GenerateContentConfig passed to the mocked generate_content call."""
    return client.models.generate_content.call_args[1]["config"]


def test_gemini_temperature_unset_is_dropped_from_the_request():
    """The SDK omits a None temperature from the serialized payload."""
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = client = _gemini_client(_gemini_response(text='{"a": 1}'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(model="gemini-3.7-flash", max_tokens=100, timeout=10, api_key="k")
        adapter.complete("sys", "user")

    config = _gemini_config_of(client)
    assert config.temperature is None
    assert "temperature" not in config.model_dump(exclude_none=True)


def test_gemini_sends_configured_temperature():
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = client = _gemini_client(_gemini_response(text='{"a": 1}'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=100,
            timeout=10,
            api_key="k",
            temperature=0.3,
        )
        adapter.complete("sys", "user")

    assert _gemini_config_of(client).temperature == 0.3


def test_gemini_sends_zero_temperature():
    """0.0 must survive into the serialized request, not be treated as unset."""
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = client = _gemini_client(_gemini_response(text='{"a": 1}'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=100,
            timeout=10,
            api_key="k",
            temperature=0.0,
        )
        adapter.complete("sys", "user")

    config = _gemini_config_of(client)
    assert config.temperature == 0.0
    assert "temperature" in config.model_dump(exclude_none=True)


def test_gemini_per_call_temperature_overrides_configured():
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = client = _gemini_client(_gemini_response(text='{"a": 1}'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=100,
            timeout=10,
            api_key="k",
            temperature=0.3,
        )
        adapter.complete("sys", "user", temperature=0.9)

    assert _gemini_config_of(client).temperature == 0.9


def test_gemini_temperature_does_not_disturb_thinking_or_timeout():
    """The new _build_config parameter must not perturb the existing config."""
    with patch("google.genai.Client") as mock_cls:
        mock_cls.return_value = client = _gemini_client(_gemini_response(text='{"a": 1}'))

        from mykg.llm.gemini_adapter import GeminiAdapter

        adapter = GeminiAdapter(
            model="gemini-3.7-flash",
            max_tokens=100,
            timeout=10,
            api_key="k",
            thinking_level="low",
            temperature=0.2,
        )
        adapter.complete("sys", "user")

    config = _gemini_config_of(client)
    assert config.temperature == 0.2
    assert config.max_output_tokens == 100
    assert config.system_instruction == "sys"
    assert config.response_mime_type == "application/json"
    # The SDK coerces the string to a ThinkingLevel enum.
    assert str(config.thinking_config.thinking_level.value).lower() == "low"
    assert config.http_options.timeout == 10_000


# ---------------------------------------------------------------------------
# temperature — Ollama
# ---------------------------------------------------------------------------


def _ollama_options(temperature=None, **overrides):
    """Run a mocked Ollama call and return the decoded options sub-dict."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"response": "hello"}).encode()

    kwargs = {
        "model": "gemma4:31b",
        "base_url": "http://localhost:11434",
        "timeout": 120,
        "stream": False,
        "max_tokens": 8096,
        "context_window": 64000,
    }
    kwargs.update(overrides)
    if temperature is not None:
        kwargs["temperature"] = temperature

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        OllamaAdapter(**kwargs).complete("sys", "user")

    body = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
    return body


def test_ollama_omits_temperature_when_unset():
    """Unset -> Ollama applies the model's own default from the modelfile."""
    assert "temperature" not in _ollama_options()["options"]


def test_ollama_sends_configured_temperature_inside_options():
    """Ollama takes sampling params in the options sub-dict, not at the top level."""
    body = _ollama_options(temperature=0.2)
    assert body["options"]["temperature"] == 0.2
    assert "temperature" not in body


def test_ollama_sends_zero_temperature():
    assert _ollama_options(temperature=0.0)["options"]["temperature"] == 0.0


def test_ollama_temperature_preserves_existing_options():
    """num_ctx and num_predict must survive the options-dict refactor."""
    options = _ollama_options(temperature=0.4)["options"]
    assert options["num_ctx"] == 64000
    assert options["num_predict"] == 8096
    assert options["temperature"] == 0.4


def test_ollama_payload_keeps_non_ascii_unescaped():
    """ensure_ascii=False keeps prompts compact (Invariant 20b)."""
    mock_response = MagicMock()
    mock_response.read.return_value = json.dumps({"response": "ok"}).encode()

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__.return_value = mock_response

        from mykg.llm.ollama_adapter import OllamaAdapter

        adapter = OllamaAdapter(
            model="gemma4:31b",
            base_url="http://localhost:11434",
            timeout=120,
            stream=False,
            max_tokens=8096,
            context_window=64000,
        )
        adapter.complete("sys", "réunion München 15 µm")

    data = mock_urlopen.call_args[0][0].data
    assert "réunion".encode() in data
    assert b"\\u00e9" not in data
    assert json.loads(data.decode("utf-8"))["prompt"].endswith("réunion München 15 µm")


# ---------------------------------------------------------------------------
# temperature — load_adapter wiring
# ---------------------------------------------------------------------------


_TEMP_PROVIDER_CASES = [
    ("openai", {"model": "gpt-4o", "max_output_tokens": 4096, "timeout": 30}, "openai.OpenAI"),
    (
        "anthropic",
        {"model": "claude-sonnet-4-5", "max_output_tokens": 4096, "timeout": 30},
        "anthropic.Anthropic",
    ),
    (
        "openrouter",
        {"model": "openrouter/free", "max_output_tokens": 4096, "timeout": 30},
        "openai.OpenAI",
    ),
    (
        "gemini",
        {"model": "gemini-3.7-flash", "max_output_tokens": 4096, "timeout": 30},
        "google.genai.Client",
    ),
    (
        "ollama",
        {
            "model": "gemma4:31b",
            "max_output_tokens": 4096,
            "timeout": 30,
            "base_url": "http://localhost:11434",
            "stream": False,
            "context_window": 64000,
        },
        None,
    ),
]


@pytest.mark.parametrize("provider,llm,patch_target", _TEMP_PROVIDER_CASES)
def test_load_adapter_defaults_temperature_to_none(provider, llm, patch_target, monkeypatch):
    """A config with no temperature key builds fine and omits the parameter.

    This is the guard on the shipped mykg_config.yaml files, which intentionally
    do not carry the key: existing users must see no behaviour change at all.
    """
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "test-key")

    from mykg.llm.config import load_adapter

    raw = {"provider": provider, "llm": llm}
    if patch_target:
        with patch(patch_target):
            adapter = load_adapter(_raw=raw)
    else:
        adapter = load_adapter(_raw=raw)

    assert adapter._temperature is None


@pytest.mark.parametrize("provider,llm,patch_target", _TEMP_PROVIDER_CASES)
def test_load_adapter_passes_configured_temperature(provider, llm, patch_target, monkeypatch):
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(var, "test-key")

    from mykg.llm.config import load_adapter

    raw = {"provider": provider, "llm": {**llm, "temperature": 0.0}}
    if patch_target:
        with patch(patch_target):
            adapter = load_adapter(_raw=raw)
    else:
        adapter = load_adapter(_raw=raw)

    # 0.0 must survive the whole config path, not be lost to a falsy check.
    assert adapter._temperature == 0.0


def test_load_adapter_claude_cli_accepts_temperature():
    from mykg.llm.config import load_adapter

    raw = {
        "provider": "claude-cli",
        "llm": {"model": "sonnet", "max_output_tokens": 4096, "timeout": 30, "temperature": 0.3},
    }
    with patch("shutil.which", return_value="/usr/bin/claude"):
        adapter = load_adapter(_raw=raw)
    assert adapter._temperature == 0.3


def test_load_adapter_agent_accepts_temperature(tmp_path):
    from mykg.llm.config import load_adapter

    raw = {
        "provider": "agent",
        "llm": {"model": "claude", "max_output_tokens": 4096, "timeout": 30, "temperature": 0.4},
        "agent": {"inbox_dir": "in", "outbox_dir": "out", "poll_interval_seconds": 0.1},
    }
    adapter = load_adapter(_raw=raw, intermediate_dir=tmp_path)
    assert adapter._temperature == 0.4


def test_shipped_config_has_no_temperature_key():
    """The two shipped YAML files intentionally omit llm.temperature.

    Temperature is an internal knob, not a user-facing setting: it is absent
    from the shipped profiles and from the README. Adding it here would both
    change extraction behaviour for every existing user and promote it to
    public API. If this fails, that decision was reversed by accident.
    """
    import mykg.config as _cfg

    assert "temperature" not in _cfg.RAW.get("llm", {})


# ---------------------------------------------------------------------------
# temperature — live smoke tests
#
# These prove the parameter is accepted by the real APIs rather than 400-ing,
# which no amount of mock-payload assertion can establish. Each skips cleanly
# when its key is absent, and all are excluded from default runs by -m "not live".
# ---------------------------------------------------------------------------


def _load_api_key(*names: str) -> str | None:
    """First of `names` resolvable from the environment or .env.mykg.

    Delegates to conftest's _load_key — the canonical loader already shared with
    the healthiness suite. pytest does not load .env.mykg the way the CLI does,
    so tests needing a real key have to read it themselves.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_mykg_test_conftest", pathlib.Path(__file__).parent / "conftest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    for name in names:
        key = module._load_key(name)
        if key:
            return key
    return None


_LIVE_PROMPT = ("Reply with JSON only.", 'Return exactly {"pong": true}')


@pytest.mark.live
def test_anthropic_live_accepts_temperature():
    key = _load_api_key("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    if not key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    from mykg.llm.anthropic_adapter import AnthropicAdapter

    adapter = AnthropicAdapter(
        model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        max_tokens=64,
        timeout=120,
        api_key=key,
        temperature=0.0,
    )
    try:
        out = adapter.complete(*_LIVE_PROMPT, context_label="live_temperature")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise
    assert out.strip(), "expected a non-empty response with temperature=0.0"


@pytest.mark.live
def test_openai_live_accepts_temperature_on_ordinary_model():
    """A non-reasoning model actually receives the temperature."""
    key = _load_api_key("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")

    from mykg.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(
        model=os.environ.get("OPENAI_TEMPERATURE_MODEL", "gpt-4o-mini"),
        max_tokens=64,
        timeout=120,
        api_key=key,
        temperature=0.0,
    )

    # The mirror of the reasoning-model test below: here the value must actually
    # be transmitted, not merely accepted.
    sent: list[dict] = []
    original = adapter._client.chat.completions.create

    def _spy(**kwargs):
        sent.append(kwargs)
        return original(**kwargs)

    adapter._client.chat.completions.create = _spy

    try:
        out = adapter.complete(*_LIVE_PROMPT, context_label="live_temperature")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise

    assert out.strip(), "expected a non-empty response with temperature=0.0"
    assert sent[0].get("temperature") == 0.0, "temperature was not sent to a standard model"


@pytest.mark.live
def test_openai_live_reasoning_model_succeeds_because_temperature_is_omitted():
    """The guard in action: a gpt-5 model would 400 if temperature were sent.

    This is the case that protects mykg's shipped default profile.
    """
    key = _load_api_key("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")

    from mykg.llm.openai_adapter import OpenAIAdapter

    adapter = OpenAIAdapter(
        model=os.environ.get("OPENAI_REASONING_MODEL", "gpt-5-mini"),
        max_tokens=2000,
        timeout=180,
        api_key=key,
        temperature=0.0,
    )

    # Success alone is a weak assertion — it would also pass if OpenAI silently
    # started accepting temperature on this family. Record what actually went
    # over the wire so the omission itself is what is verified.
    sent: list[dict] = []
    original = adapter._client.chat.completions.create

    def _spy(**kwargs):
        sent.append(kwargs)
        return original(**kwargs)

    adapter._client.chat.completions.create = _spy

    try:
        out = adapter.complete(*_LIVE_PROMPT, context_label="live_temperature_omitted")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise

    assert out.strip(), "expected a non-empty response; temperature should have been omitted"
    assert sent, "the adapter never issued a request"
    assert "temperature" not in sent[0], (
        "temperature reached a reasoning model; it returns 400 "
        "\"Only the default (1) value is supported\" for an explicit value"
    )


@pytest.mark.live
def test_openrouter_live_accepts_temperature():
    key = _load_api_key("OPENROUTER_API_KEY", "OPENROUTER_AUTH_TOKEN")
    if not key:
        pytest.skip("OPENROUTER_API_KEY not set")

    from mykg.llm.openrouter_adapter import OpenRouterAdapter

    # openrouter/free routes to whatever free model is currently available, which
    # may be a reasoning model that spends output tokens on thinking. A 64-token
    # budget truncates those before any JSON is emitted (finish_reason=length),
    # so this needs the same headroom as the other reasoning-capable live tests.
    adapter = OpenRouterAdapter(
        model=os.environ.get("OPENROUTER_MODEL", "openrouter/free"),
        max_tokens=2000,
        timeout=180,
        api_key=key,
        temperature=0.0,
    )
    try:
        out = adapter.complete(*_LIVE_PROMPT, context_label="live_temperature")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise
    assert out.strip(), "expected a non-empty response with temperature=0.0"


@pytest.mark.live
def test_gemini_live_accepts_temperature():
    key = _load_api_key("GEMINI_API_KEY", "GOOGLE_API_KEY")
    if not key:
        pytest.skip("GEMINI_API_KEY not set")

    from mykg.llm.gemini_adapter import GeminiAdapter

    adapter = GeminiAdapter(
        model=os.environ.get("GEMINI_MODEL", "gemini-3.7-flash"),
        max_tokens=2000,
        timeout=120,
        api_key=key,
        temperature=0.0,
    )
    try:
        out = adapter.complete(*_LIVE_PROMPT, context_label="live_temperature")
    except Exception as exc:  # noqa: BLE001 - re-raised unless it is a quota 429
        _skip_if_quota_exhausted(exc)
        raise
    assert out.strip()
    assert json.loads(out)["pong"] is True


def test_openai_recovers_when_a_single_400_names_both_parameters():
    """A 400 naming max_tokens AND temperature must be fixed in one retry.

    Handling these as mutually exclusive branches meant the max_tokens retry
    re-sent the still-rejected temperature; that second error was raised from
    inside the except block, escaped uncaught, and left nothing latched — so
    every subsequent call repeated the same doomed sequence.
    """
    ok = MagicMock()
    ok.choices[0].message.content = "ok"
    ok.choices[0].finish_reason = "stop"

    both = (
        "Unsupported parameter: 'max_tokens' is not supported; use "
        "'max_completion_tokens' instead. Also 'temperature' is not supported."
    )

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = [_openai_bad_request(both), ok]

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.5
        )
        assert adapter.complete("sys", "user") == "ok"

    assert client.chat.completions.create.call_count == 2
    retry = client.chat.completions.create.call_args_list[1][1]
    assert retry["max_completion_tokens"] == 4096
    assert "temperature" not in retry
    assert adapter._temperature_rejected is True


def test_openai_incidental_temperature_mention_does_not_latch():
    """A top_p/temperature conflict is not a rejection; the value must survive."""
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = _openai_bad_request(
            "temperature and top_p cannot both be specified"
        )

        from mykg.llm.openai_adapter import OpenAIAdapter

        adapter = OpenAIAdapter(
            model="gpt-4o", max_tokens=4096, timeout=30, api_key="k", temperature=0.5
        )
        with pytest.raises(openai.BadRequestError):
            adapter.complete("sys", "user")

    assert client.chat.completions.create.call_count == 1
    assert adapter._temperature_rejected is False


def test_openrouter_recovers_when_model_rejects_temperature(caplog):
    """OpenRouter proxies reasoning models beyond the openai/* families."""
    import logging

    ok = MagicMock()
    ok.choices[0].message.content = "ok"
    ok.choices[0].finish_reason = "stop"

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = [
            _openai_bad_request("'temperature' is not supported with this model"),
            ok,
            ok,
        ]

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="deepseek/deepseek-r1",
            max_tokens=4096,
            timeout=30,
            api_key="k",
            temperature=0.0,
        )
        with caplog.at_level(logging.WARNING, logger="mykg.llm.openrouter_adapter"):
            assert adapter.complete("sys", "user") == "ok"
        # Latched: the next call omits temperature without a failed request.
        adapter.complete("sys", "user")

    assert client.chat.completions.create.call_count == 3
    assert "temperature" not in client.chat.completions.create.call_args_list[1][1]
    assert "temperature" not in client.chat.completions.create.call_args_list[2][1]
    assert "rejected an explicit temperature" in caplog.text


def test_openrouter_unrelated_bad_request_still_raises():
    import openai

    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = MagicMock()
        client.chat.completions.create.side_effect = _openai_bad_request("Invalid 'messages'")

        from mykg.llm.openrouter_adapter import OpenRouterAdapter

        adapter = OpenRouterAdapter(
            model="openrouter/free", max_tokens=4096, timeout=30, api_key="k", temperature=0.0
        )
        with pytest.raises(openai.BadRequestError):
            adapter.complete("sys", "user")

    assert client.chat.completions.create.call_count == 1


# ---------------------------------------------------------------------------
# temperature — configurable unsupported-prefix list
# ---------------------------------------------------------------------------


def _openai_wire(raw: dict) -> dict:
    """Run one mocked call through load_adapter and return the request kwargs."""
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()
        from mykg.llm.config import load_adapter

        load_adapter(_raw=raw).complete("sys", "user")
    return client.chat.completions.create.call_args[1]


def _openai_raw(**llm) -> dict:
    base = {"model": "gpt-5-mini", "max_output_tokens": 100, "timeout": 30, "temperature": 0.0}
    return {"provider": "openai", "llm": {**base, **llm}}


def test_shipped_config_uses_the_default_prefix_list(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert "temperature" not in _openai_wire(_openai_raw())


def test_config_can_disable_the_prefix_guard(monkeypatch):
    """An empty list means the endpoint accepts temperature on every model."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    kwargs = _openai_wire(_openai_raw(temperature_unsupported_prefixes=[]))
    assert kwargs["temperature"] == 0.0


def test_config_can_add_a_family_mykg_does_not_know(monkeypatch):
    """The point of the knob: a new rejecting family needs no code change."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    kwargs = _openai_wire(_openai_raw(model="gpt-4o", temperature_unsupported_prefixes=["gpt-4o"]))
    assert "temperature" not in kwargs


def test_config_prefixes_are_normalised(monkeypatch):
    """Case and stray whitespace in YAML must not defeat the match."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    kwargs = _openai_wire(_openai_raw(temperature_unsupported_prefixes=["  GPT-5 "]))
    assert "temperature" not in kwargs


def test_a_string_prefix_list_is_rejected(monkeypatch):
    """`prefixes: gpt-5` in YAML would otherwise match per-character."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    with pytest.raises(ValueError, match="must be a list"):
        _openai_wire(_openai_raw(temperature_unsupported_prefixes="gpt-5"))


def test_openrouter_honours_configured_prefixes(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    raw = {
        "provider": "openrouter",
        "llm": {
            "model": "deepseek/deepseek-r1",
            "max_output_tokens": 100,
            "timeout": 30,
            "temperature": 0.0,
            "temperature_unsupported_prefixes": ["deepseek-r1"],
        },
    }
    with patch("openai.OpenAI") as mock_cls:
        mock_cls.return_value = client = _openai_client()
        from mykg.llm.config import load_adapter

        load_adapter(_raw=raw).complete("sys", "user")
    assert "temperature" not in client.chat.completions.create.call_args[1]


def test_shipped_config_has_no_temperature_prefix_key():
    """The knob is internal: readable, but never shipped as an active key."""
    import mykg.config as _cfg

    assert "temperature_unsupported_prefixes" not in _cfg.RAW.get("llm", {})


def test_shipped_yaml_files_never_mention_temperature():
    """The shipped configs must not mention temperature at all — not as a key,
    and not as a comment either.

    Both files are the user's first contact with mykg's configuration surface,
    and this knob is deliberately internal. A comment is still an invitation, so
    the check is on the raw text rather than the parsed mapping.
    """
    from pathlib import Path

    repo_root = Path(__file__).parent.parent
    shipped = [repo_root / "mykg_config.yaml", repo_root / "src" / "mykg" / "data" / "mykg_config.yaml"]

    for path in shipped:
        assert path.exists(), f"{path} is missing"
        text = path.read_text(encoding="utf-8")
        assert "temperature" not in text.lower(), (
            f"{path.name} mentions temperature; the shipped configs are left "
            "untouched by design — document the knob in docs/architecture.md instead"
        )
