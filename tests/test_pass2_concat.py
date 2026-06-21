from mykg.pass2_concat import _strip_counter_suffix, concat_file_order

SMALL = "word " * 20


# ---------------------------------------------------------------------------
# _strip_counter_suffix
# ---------------------------------------------------------------------------


def test_strip_counter_suffix_patterns():
    assert _strip_counter_suffix("notes_1") == "notes"
    assert _strip_counter_suffix("notes-2") == "notes"
    assert _strip_counter_suffix("notes.3") == "notes"
    assert _strip_counter_suffix("notes(4)") == "notes"
    assert _strip_counter_suffix("standalone") == "standalone"


# ---------------------------------------------------------------------------
# concat_file_order
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty():
    assert concat_file_order({}) == []


def test_covers_all_inputs_no_loss_no_dupes():
    """Every real filename appears exactly once in the order."""
    fc = {
        "dir_a/x.md": SMALL,
        "dir_a/y.md": SMALL,
        "dir_b/z.md": SMALL,
        "standalone.md": SMALL,
    }
    order = concat_file_order(fc)
    assert sorted(order) == sorted(fc.keys())
    assert len(order) == len(set(order))


def test_same_directory_files_are_adjacent():
    """Files in the same directory sit contiguously in the order."""
    fc = {
        "dir_a/note_1.md": SMALL,
        "dir_b/note_1.md": SMALL,
        "dir_a/note_2.md": SMALL,
    }
    order = concat_file_order(fc)
    # The two dir_a files must be adjacent (not separated by the dir_b file).
    idx_a1 = order.index("dir_a/note_1.md")
    idx_a2 = order.index("dir_a/note_2.md")
    assert abs(idx_a1 - idx_a2) == 1


def test_prefix_grouping_within_directory():
    """Same-prefix files in one directory are ordered together by prefix then name."""
    fc = {
        "notes_3.md": SMALL,
        "notes_1.md": SMALL,
        "notes_2.md": SMALL,
    }
    order = concat_file_order(fc)
    # All share prefix 'notes' → sorted by full filename within the prefix group.
    assert order == ["notes_1.md", "notes_2.md", "notes_3.md"]


def test_deterministic():
    """concat_file_order returns identical output across calls and dict orderings."""
    fc1 = {"dir/a.md": SMALL, "dir/b.md": SMALL, "other/c.md": SMALL}
    fc2 = {"other/c.md": SMALL, "dir/b.md": SMALL, "dir/a.md": SMALL}
    assert concat_file_order(fc1) == concat_file_order(fc2)


def test_directories_sorted():
    """Directories are emitted in sorted order for cross-dir determinism."""
    fc = {"z_dir/a.md": SMALL, "a_dir/a.md": SMALL}
    order = concat_file_order(fc)
    assert order == ["a_dir/a.md", "z_dir/a.md"]
