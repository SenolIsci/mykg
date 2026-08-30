"""Tests for the D58 --sync CLI flag and the prefix-scoped mirror prune."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mykg.cli import _copy_input_files, cli


def _mirror(session_root: Path) -> list[str]:
    root = session_root / "input"
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())


def _build(tmp_path: Path) -> tuple[Path, Path]:
    src = tmp_path / "src"
    session = tmp_path / "session"
    src.mkdir(parents=True)
    (session / "input").mkdir(parents=True)
    (src / "a.md").write_text("A", encoding="utf-8")
    (src / "b.md").write_text("B", encoding="utf-8")
    return src, session


# ---------------------------------------------------------------------------
# Flag validation
# ---------------------------------------------------------------------------


def test_sync_requires_append(tmp_path):
    result = CliRunner().invoke(cli, ["extract-graph", str(tmp_path), "--sync"])

    assert result.exit_code != 0
    assert "--sync requires --append" in result.output


def test_sync_is_documented_in_help():
    result = CliRunner().invoke(cli, ["extract-graph", "--help"])

    assert "--sync" in result.output
    assert "MODIFIED" in result.output and "DELETED" in result.output


# ---------------------------------------------------------------------------
# --update: shorthand for --append --sync
# ---------------------------------------------------------------------------


def _ctx_flags(tmp_path: Path, *flags: str) -> dict:
    """Invoke extract-graph with `flags` and capture the flags on the built ctx.

    Asserts the spy actually fired. Without that check these tests pass
    vacuously whenever the CLI errors out before reaching `run` — `captured`
    stays empty, and comparing two empty dicts looks like a successful
    equivalence assertion.
    """
    captured: dict = {}

    def spy(steps, ctx):
        captured.update(append=ctx.append, sync=ctx.sync, grow_schema=ctx.grow_schema)
        raise SystemExit(0)

    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "a.md").write_text("A", encoding="utf-8")
    inter = tmp_path / "i"
    inter.mkdir(parents=True, exist_ok=True)
    # Preconditions for --append / --append-with-grow-schema.
    (inter / "schema.json").write_text(
        json.dumps({"concepts": [], "properties": []}), encoding="utf-8"
    )
    (inter / "schema.ttl").write_text("@prefix ex: <http://e/> .", encoding="utf-8")

    with patch("mykg.orchestrator.run", side_effect=spy):
        result = CliRunner().invoke(
            cli,
            [
                "extract-graph",
                str(src),
                *flags,
                "--output-dir",
                str(tmp_path / "o"),
                "--intermediate-dir",
                str(inter),
            ],
        )
    assert captured, (
        "orchestrator.run was never reached, so no ctx was built — the CLI "
        f"exited early. Output:\n{result.output}"
    )
    return captured


def test_update_is_equivalent_to_append_plus_sync(tmp_path):
    assert _ctx_flags(tmp_path / "a", "--update") == _ctx_flags(
        tmp_path / "b", "--append", "--sync"
    )


def test_update_sets_both_flags(tmp_path):
    flags = _ctx_flags(tmp_path, "--update")

    assert flags["append"] is True
    assert flags["sync"] is True


def test_update_alone_does_not_trip_the_sync_gate(tmp_path):
    """--update expands BEFORE the `--sync requires --append` check.

    Expanding after it would make the shorthand fail the very validation it
    already satisfies.
    """
    src = tmp_path / "src"
    src.mkdir()

    result = CliRunner().invoke(cli, ["extract-graph", str(src), "--update"])

    assert "--sync requires --append" not in result.output


def test_update_composes_with_grow_schema(tmp_path):
    flags = _ctx_flags(tmp_path, "--update", "--append-with-grow-schema")

    assert flags == {"append": True, "sync": True, "grow_schema": True}


def test_update_is_documented_in_help():
    result = CliRunner().invoke(cli, ["extract-graph", "--help"])

    assert "--update" in result.output
    assert "--append --sync" in result.output


# ---------------------------------------------------------------------------
# Mirror copy + prune
# ---------------------------------------------------------------------------


def test_default_copy_is_flat_and_never_prunes(tmp_path):
    """The no-flag path must stay byte-identical to pre-D58."""
    src, session = _build(tmp_path)
    _copy_input_files(src, session, copy_config=False)
    (src / "a.md").unlink()

    _copy_input_files(src, session, copy_config=False)

    assert _mirror(session) == ["a.md", "b.md"]


def test_prune_removes_files_absent_from_source(tmp_path):
    src, session = _build(tmp_path)
    _copy_input_files(src, session, copy_config=False)
    (src / "a.md").unlink()

    _copy_input_files(src, session, copy_config=False, prune=True)

    assert _mirror(session) == ["b.md"]


def test_mirror_prefix_namespaces_the_subtree(tmp_path):
    src, session = _build(tmp_path)

    _copy_input_files(src, session, copy_config=False, mirror_prefix="other.com/")

    assert _mirror(session) == ["other.com/a.md", "other.com/b.md"]


def test_prune_is_scoped_to_the_named_folder(tmp_path):
    """Reconciling one folder must never delete another folder's files.

    The first registered folder has an EMPTY prefix, so `dest` is the mirror
    root and the walk would otherwise sweep every sibling subtree. This is the
    scoping guarantee that replaces a blast-radius cap.
    """
    src_a, session = _build(tmp_path)
    src_b = tmp_path / "srcB"
    src_b.mkdir()
    (src_b / "index.md").write_text("B-index", encoding="utf-8")

    _copy_input_files(src_a, session, copy_config=False)
    _copy_input_files(src_b, session, copy_config=False, mirror_prefix="srcB/")
    (src_a / "a.md").unlink()

    _copy_input_files(
        src_a, session, copy_config=False, prune=True, other_prefixes=("srcB/",)
    )

    assert _mirror(session) == ["b.md", "srcB/index.md"]


def test_two_folders_with_the_same_basename_both_survive(tmp_path):
    """Pre-D58 the second copy silently overwrote the first."""
    src_a, session = _build(tmp_path)
    (src_a / "index.md").write_text("from A", encoding="utf-8")
    src_b = tmp_path / "srcB"
    src_b.mkdir()
    (src_b / "index.md").write_text("from B", encoding="utf-8")

    _copy_input_files(src_a, session, copy_config=False)
    _copy_input_files(src_b, session, copy_config=False, mirror_prefix="srcB/")

    root = session / "input"
    assert (root / "index.md").read_text(encoding="utf-8") == "from A"
    assert (root / "srcB" / "index.md").read_text(encoding="utf-8") == "from B"


def test_prune_never_touches_preprocessed_output(tmp_path):
    """Converted Markdown has no source counterpart by construction."""
    src, session = _build(tmp_path)
    _copy_input_files(src, session, copy_config=False)
    converted = session / "input" / "_preprocessed" / "report.md"
    converted.parent.mkdir(parents=True, exist_ok=True)
    converted.write_text("converted", encoding="utf-8")

    _copy_input_files(src, session, copy_config=False, prune=True)

    assert converted.exists()


def test_prune_on_a_brand_new_folder_deletes_nothing(tmp_path):
    """An auto-registered folder owns an empty subtree, so a typo'd path is inert."""
    src, session = _build(tmp_path)
    _copy_input_files(src, session, copy_config=False)
    fresh = tmp_path / "fresh"
    fresh.mkdir()
    (fresh / "c.md").write_text("C", encoding="utf-8")

    _copy_input_files(
        fresh, session, copy_config=False, mirror_prefix="fresh/", prune=True
    )

    assert _mirror(session) == ["a.md", "b.md", "fresh/c.md"]
