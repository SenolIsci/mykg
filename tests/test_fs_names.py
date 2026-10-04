from __future__ import annotations

import pytest

from mykg.utility.fs_names import _WINDOWS_RESERVED, safe_path_component

# Characters Windows rejects in a path component. ":" is the dangerous one in
# practice — an LLM-chosen type like "Person:Employee" is plausible, and ":" is
# reserved for drive letters.
WINDOWS_ILLEGAL = '<>:"|?*\\/'


@pytest.mark.parametrize("char", list(WINDOWS_ILLEGAL))
def test_illegal_characters_are_replaced(char: str) -> None:
    result = safe_path_component(f"A{char}B")

    assert char not in result
    assert result == "A_B"


def test_all_illegal_characters_at_once() -> None:
    assert safe_path_component('A<B>C:D"E|F?G*H\\I/J') == "A_B_C_D_E_F_G_H_I_J"


@pytest.mark.parametrize("name", sorted(_WINDOWS_RESERVED))
def test_reserved_device_names_are_suffixed(name: str) -> None:
    """CON, NUL, COM1 … are reserved by Windows and cannot be used bare."""
    for variant in (name, name.upper(), name.capitalize()):
        result = safe_path_component(variant)
        assert result.lower() not in _WINDOWS_RESERVED
        assert result == f"{variant}_"


def test_reserved_name_with_extension_is_also_suffixed() -> None:
    """Windows reserves device names with any extension, so the stem is what
    matters — "con.md" is refused just as "con" is."""
    assert safe_path_component("con.md") == "con.md_"
    assert safe_path_component("NUL.txt") == "NUL.txt_"


def test_reserved_substring_is_left_alone() -> None:
    """Only an exact match is reserved — "Console" and "Contract" are fine."""
    assert safe_path_component("Console") == "Console"
    assert safe_path_component("Contract") == "Contract"


@pytest.mark.parametrize(
    "raw",
    ["trailing.", "trailing-", "trailing_", ".leading", "-leading", "  spaced  "],
)
def test_leading_and_trailing_separators_are_trimmed(raw: str) -> None:
    """Windows silently strips trailing dots and spaces, so a name relying on
    one would not round-trip."""
    result = safe_path_component(raw)

    assert not result.startswith((".", "-", "_"))
    assert not result.endswith((".", "-", "_"))


@pytest.mark.parametrize("raw", ["", "   ", "...", "---", "___", ":::", "<>"])
def test_empty_result_falls_back(raw: str) -> None:
    assert safe_path_component(raw) == "unknown"


def test_fallback_is_configurable() -> None:
    assert safe_path_component("", fallback="Unknown") == "Unknown"


@pytest.mark.parametrize(
    "raw",
    ["Person", "Person:Employee", "CON", "con.md", "", "...", 'A<B>"C', "Organization"],
)
def test_is_idempotent(raw: str) -> None:
    """The writer and the reader derive the path independently, so applying the
    function twice must equal applying it once."""
    once = safe_path_component(raw)

    assert safe_path_component(once) == once


@pytest.mark.parametrize(
    "raw",
    ["Person:Employee", 'A<B>"C|D', "CON", "...", "", "Data|Set", "Ünïcödé Tÿpe"],
)
def test_output_charset_is_always_safe(raw: str) -> None:
    result = safe_path_component(raw)

    assert result, "must never return an empty component"
    assert not set(result) & set(WINDOWS_ILLEGAL)
    assert all(c.isalnum() or c in "._-" for c in result)


def test_ordinary_type_names_pass_through_unchanged() -> None:
    """The common case must not churn: existing vaults use these directory
    names, so sanitizing must be a no-op for them."""
    for name in ("Person", "Organization", "Project", "Technology", "Team", "Document"):
        assert safe_path_component(name) == name
