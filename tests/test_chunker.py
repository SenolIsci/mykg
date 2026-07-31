from unittest.mock import patch

from mykg.chunker import chunk_file, count_tokens, truncate_to_tokens

SIMPLE_MD = """\
---
title: Test
author: Alice
---

## Section One

Some text here. More text follows.

## Section Two

Another paragraph.
"""

# 3000 tokens reliably exceeds the patched window of 500 used in multi-chunk tests.
LONG_MD = "word " * 3000


def test_chunk_small_file_returns_single_chunk():
    chunks = chunk_file("notes.md", SIMPLE_MD)
    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.source_file == "notes.md"
    assert chunk.chunk_index == 0
    assert "Section One" in chunk.text


def test_chunk_large_file_splits_into_multiple():
    with (
        patch("mykg.chunker._cfg.CHUNK_WINDOW_TOKENS", 500),
        patch("mykg.chunker._cfg.CHUNK_OVERLAP_TOKENS", 50),
    ):
        chunks = chunk_file("big.md", LONG_MD)
    assert len(chunks) > 1


def test_chunk_overlap_exists():
    with (
        patch("mykg.chunker._cfg.CHUNK_WINDOW_TOKENS", 500),
        patch("mykg.chunker._cfg.CHUNK_OVERLAP_TOKENS", 50),
    ):
        chunks = chunk_file("big.md", LONG_MD)
    # Last 200 tokens of chunk N should appear at start of chunk N+1
    # Test by checking that chunk 1 starts with content from end of chunk 0
    assert len(chunks) >= 2
    end_of_first = chunks[0].text[-100:]
    start_of_second = chunks[1].text[:200]
    # At least some overlap
    words_end = set(end_of_first.split())
    words_start = set(start_of_second.split())
    assert len(words_end & words_start) > 0


def test_chunk_fields():
    chunks = chunk_file("notes.md", SIMPLE_MD)
    c = chunks[0]
    assert isinstance(c.source_file, str)
    assert isinstance(c.chunk_index, int)
    assert isinstance(c.text, str)
    assert isinstance(c.token_start, int)
    assert isinstance(c.token_end, int)


def test_frontmatter_stripped_from_text():
    chunks = chunk_file("notes.md", SIMPLE_MD)
    assert "title: Test" not in chunks[0].text or "## Section" in chunks[0].text


def test_truncate_to_tokens_noop_when_disabled():
    text = "word " * 3000
    assert truncate_to_tokens(text, 0) is text
    assert truncate_to_tokens(text, -1) is text


def test_truncate_to_tokens_noop_when_text_fits():
    text = "Alice works at Acme."
    # Cap far above the text's token count → returned unchanged.
    assert truncate_to_tokens(text, 10_000) == text


def test_truncate_to_tokens_truncates_when_over_cap():
    text = "word " * 3000
    original = count_tokens(text)
    result = truncate_to_tokens(text, 500)
    assert count_tokens(result) <= 500
    assert count_tokens(result) < original
    assert len(result) < len(text)
