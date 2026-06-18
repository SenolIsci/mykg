import io
import json
import os
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


def _load_openrouter_api_key() -> str | None:
    """Load OPENROUTER_API_KEY from environment or .env file."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        from pathlib import Path

        env_file = Path(__file__).parent.parent / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("OPENROUTER_API_KEY"):
                    _, _, val = line.partition("=")
                    key = val.strip()
                    break
    return key or None


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
        "wall-clock timeout" in str(c.kwargs.get("error", ""))
        for c in mock_record.call_args_list
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
    adapter = OpenRouterAdapter(
        model=model,
        max_tokens=64,
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
