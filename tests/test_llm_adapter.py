import pytest

from mykg.llm.adapter import LLMAdapter


def test_adapter_is_abstract():
    with pytest.raises(TypeError):
        LLMAdapter()


def test_adapter_complete_raises_not_implemented():
    class Concrete(LLMAdapter):
        pass

    with pytest.raises(TypeError):
        Concrete()


def test_concrete_adapter_works():
    class Echo(LLMAdapter):
        def complete(
            self,
            system: str,
            user: str,
            context_label: str = "",
            max_tokens: int | None = None,
            timeout: int | None = None,
            temperature: float | None = None,
        ) -> str:
            return f"system={system} user={user}"

        def endpoint_label(self) -> str:
            return "echo"

    adapter = Echo()
    result = adapter.complete("sys", "usr")
    assert result == "system=sys user=usr"


def test_concrete_adapter_accepts_temperature():
    """The ABC exposes temperature as a per-call override alongside max_tokens/timeout."""

    class Recorder(LLMAdapter):
        def __init__(self) -> None:
            self.seen: float | None | str = "unset"

        def complete(
            self,
            system: str,
            user: str,
            context_label: str = "",
            max_tokens: int | None = None,
            timeout: int | None = None,
            temperature: float | None = None,
        ) -> str:
            self.seen = temperature
            return "ok"

        def endpoint_label(self) -> str:
            return "recorder"

    adapter = Recorder()

    # Omitted -> None, meaning "use the adapter's configured default".
    adapter.complete("sys", "usr")
    assert adapter.seen is None

    # Explicitly supplied -> forwarded verbatim, including 0.0 (which must not
    # be conflated with None by any falsy check).
    adapter.complete("sys", "usr", temperature=0.0)
    assert adapter.seen == 0.0
