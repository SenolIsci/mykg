"""Tests for alias stripping in the merge pipeline (U26).

Merge namespaces every file key as ``{alias}/{original}``. Recovering the
original by splitting on the FIRST "/" is wrong for any key that is not
namespaced with this alias: it strips a real path component instead, the file
then fails to resolve under ``input/``, and it is silently dropped from
re-extraction with only a log warning.
"""

from __future__ import annotations

from mykg.merger import _strip_alias


def test_strips_the_alias_from_a_flat_key():
    assert _strip_alias("session_a/notes.md", "session_a") == "notes.md"


def test_preserves_subdirectories_in_the_original_name():
    assert _strip_alias("session_a/sub/deep/note.md", "session_a") == "sub/deep/note.md"


def test_preserves_a_mirror_prefix():
    """D58 mirror prefixes make multi-segment originals the norm."""
    assert _strip_alias("session_a/other.com/index.md", "session_a") == "other.com/index.md"


def test_leaves_an_un_namespaced_key_untouched():
    """The regression: `sub/note.md` must not become `note.md`.

    A legacy key with a subdirectory carries no alias. Stripping its first
    segment yields a path that does not exist under input/, so the file is
    dropped from re-extraction.
    """
    assert _strip_alias("sub/note.md", "session_a") == "sub/note.md"


def test_leaves_another_sessions_key_untouched():
    assert _strip_alias("session_b/notes.md", "session_a") == "session_b/notes.md"


def test_leaves_a_bare_filename_untouched():
    assert _strip_alias("notes.md", "session_a") == "notes.md"


def test_does_not_strip_a_merely_similar_prefix():
    """`session_a2/` starts with the alias text but is a different alias."""
    assert _strip_alias("session_a2/notes.md", "session_a") == "session_a2/notes.md"


# ---------------------------------------------------------------------------
# End to end: the file must reach pass2 rather than being silently dropped
# ---------------------------------------------------------------------------


def _reextract_files_seen(tmp_path, namespaced_key: str, subdir: str | None) -> list[str]:
    """Run reextract_for_merge and report which files it handed to pass2."""
    from unittest.mock import patch

    from mykg.merger import reextract_for_merge

    session = tmp_path / "session"
    inp = session / "input" / subdir if subdir else session / "input"
    inp.mkdir(parents=True)
    (inp / "note.md").write_text("Alice is here.", encoding="utf-8")
    intermediate = tmp_path / "intermediate"
    intermediate.mkdir()

    seen: dict[str, list[str]] = {}

    def spy(files=None, **kwargs):
        seen["files"] = sorted(files or {})
        return ({}, {}, [], {})

    with patch("mykg.merger.run_pass2_batched", side_effect=spy):
        reextract_for_merge(
            session_alias="session_a",
            session_path=session,
            raw_extractions_namespaced={namespaced_key: {"nodes": [], "edges": []}},
            merged_schema={
                "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
                "properties": [],
            },
            flattened_schema={},
            intermediate_dir=intermediate,
            adapter=None,
            config={},
            strategy="full",
        )
    return seen.get("files", [])


def test_reextract_resolves_a_namespaced_subdirectory_file(tmp_path):
    assert _reextract_files_seen(tmp_path, "session_a/sub/note.md", "sub") == ["sub/note.md"]


def test_reextract_resolves_a_namespaced_flat_file(tmp_path):
    assert _reextract_files_seen(tmp_path, "session_a/note.md", None) == ["note.md"]


def test_reextract_resolves_an_un_namespaced_subdirectory_file(tmp_path):
    """The regression, end to end.

    Under the old first-segment split this became `note.md`, which does not
    exist under input/, so the file was dropped with only a log warning.
    """
    assert _reextract_files_seen(tmp_path, "sub/note.md", "sub") == ["sub/note.md"]
