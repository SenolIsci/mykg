from mykg.pass2_concat import build_concat_batches, make_virtual_files

# A single ASCII word is roughly 1 token with cl100k_base, so "word " * N ≈ N tokens.
SMALL = "word " * 20  # ~21 tokens — well below any reasonable target
LARGE = (
    "word " * 2200
)  # ~2201 tokens — safely above the 2000-token pass-through threshold used in tests


# ---------------------------------------------------------------------------
# build_concat_batches
# ---------------------------------------------------------------------------


def test_large_files_pass_through_unchanged():
    """A file whose token count exceeds the target maps to itself with richer entry."""
    fc = {"big.md": LARGE}
    result = build_concat_batches(fc, batch_token_target=2000)
    assert result["big.md"]["files"] == ["big.md"]
    assert "file_tokens" in result["big.md"]
    assert "total_tokens" in result["big.md"]
    assert result["big.md"]["total_tokens"] == result["big.md"]["file_tokens"]["big.md"]


def test_small_files_grouped_by_directory():
    """Files in different directories are kept in separate batches."""
    fc = {
        "dir_a/note_1.md": SMALL,
        "dir_a/note_2.md": SMALL,
        "dir_b/note_1.md": SMALL,
    }
    result = build_concat_batches(fc, batch_token_target=100_000)

    # Collect which batch each file landed in
    membership: dict[str, str] = {}
    for vname, entry in result.items():
        for f in entry["files"]:
            membership[f] = vname

    # The two dir_a files share a batch; dir_b file is in a different batch
    assert membership["dir_a/note_1.md"] == membership["dir_a/note_2.md"]
    assert membership["dir_b/note_1.md"] != membership["dir_a/note_1.md"]


def test_prefix_grouping():
    """Files with the same stripped prefix in the same directory share a batch."""
    fc = {
        "notes_1.md": SMALL,
        "notes_2.md": SMALL,
        "notes_3.md": SMALL,
    }
    result = build_concat_batches(fc, batch_token_target=100_000)
    entries = list(result.values())
    # All three share the prefix "notes" → one batch
    assert len(entries) == 1
    assert set(entries[0]["files"]) == {"notes_1.md", "notes_2.md", "notes_3.md"}


def test_packing_respects_token_target():
    """Greedy bin-packing stops adding to a batch when the target would be exceeded."""
    # "word " * 40 ≈ 41 tokens each (cl100k_base counts trailing spaces separately).
    # target=85 → first two pack together (82 ≤ 85), third spills to a new bin (123 > 85).
    content = "word " * 40
    fc = {
        "chunk_1.md": content,
        "chunk_2.md": content,
        "chunk_3.md": content,
    }
    result = build_concat_batches(fc, batch_token_target=85)
    assert len(result) == 2
    lengths = sorted(len(e["files"]) for e in result.values())
    assert lengths == [1, 2]


def test_batch_names_are_deterministic():
    """Calling build_concat_batches twice with identical input yields identical keys."""
    fc = {
        "dir/a.md": SMALL,
        "dir/b.md": SMALL,
    }
    result1 = build_concat_batches(fc, batch_token_target=100_000)
    result2 = build_concat_batches(fc, batch_token_target=100_000)
    assert list(result1.keys()) == list(result2.keys())
    assert list(result1.values()) == list(result2.values())


def test_empty_input_returns_empty():
    """An empty file_contents dict produces an empty concat_map."""
    assert build_concat_batches({}, batch_token_target=100_000) == {}


def test_all_files_fit_in_one_batch():
    """Three tiny files sharing a prefix in the same directory and a generous target → 1 batch."""
    fc = {
        "docs/entry_1.md": SMALL,
        "docs/entry_2.md": SMALL,
        "docs/entry_3.md": SMALL,
    }
    result = build_concat_batches(fc, batch_token_target=100_000)
    assert len(result) == 1
    entry = next(iter(result.values()))
    assert set(entry["files"]) == {"docs/entry_1.md", "docs/entry_2.md", "docs/entry_3.md"}


def test_concat_map_keys_cover_all_inputs():
    """Every real filename appears in exactly one value list — no file lost or duplicated."""
    fc = {
        "dir_a/x.md": SMALL,
        "dir_a/y.md": SMALL,
        "dir_b/z.md": SMALL,
        "standalone.md": LARGE,
    }
    result = build_concat_batches(fc, batch_token_target=2000)
    all_mapped = [f for entry in result.values() for f in entry["files"]]
    assert sorted(all_mapped) == sorted(fc.keys())
    assert len(all_mapped) == len(set(all_mapped))


def test_entry_has_token_metadata():
    """Each entry carries file_tokens and total_tokens matching the sum."""
    fc = {
        "a.md": SMALL,
        "b.md": SMALL,
    }
    result = build_concat_batches(fc, batch_token_target=100_000)
    for entry in result.values():
        assert "file_tokens" in entry
        assert "total_tokens" in entry
        assert entry["total_tokens"] == sum(entry["file_tokens"].values())


# ---------------------------------------------------------------------------
# make_virtual_files
# ---------------------------------------------------------------------------


def test_make_virtual_files_single_file_unchanged():
    """A single-file concat entry passes content through without any delimiters."""
    fc = {"note.md": "Hello world"}
    concat_map = {
        "note.md": {"files": ["note.md"], "file_tokens": {"note.md": 2}, "total_tokens": 2}
    }
    result = make_virtual_files(fc, concat_map)
    assert result == {"note.md": "Hello world"}


def test_make_virtual_files_multi_file_has_delimiters():
    """A multi-file concat entry wraps each file's content with SOURCE delimiters."""
    fc = {"f1.md": "content one", "f2.md": "content two"}
    concat_map = {
        "concat_batch_0000.md": {
            "files": ["f1.md", "f2.md"],
            "file_tokens": {"f1.md": 2, "f2.md": 2},
            "total_tokens": 4,
        }
    }
    result = make_virtual_files(fc, concat_map)
    combined = result["concat_batch_0000.md"]
    assert "--- SOURCE: f1.md ---" in combined
    assert "--- SOURCE: f2.md ---" in combined
    assert "content one" in combined
    assert "content two" in combined
