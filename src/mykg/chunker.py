from __future__ import annotations

import re

import tiktoken
from pydantic import BaseModel, ConfigDict

from mykg import config as _cfg


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_file: str
    chunk_index: int
    text: str
    token_start: int
    token_end: int


def count_tokens(text: str) -> int:
    """Return the token count of text using the configured tiktoken encoding."""
    enc = tiktoken.get_encoding(_cfg.CHUNK_TIKTOKEN_ENCODING)
    return len(enc.encode(text))


def truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Return text truncated to its first max_tokens tokens.

    No-op when max_tokens <= 0 (cap disabled) or the text already fits. Uses the
    same configured tiktoken encoding as count_tokens/chunk_file so the token
    count is consistent across the pipeline.
    """
    if max_tokens <= 0:
        return text
    enc = tiktoken.get_encoding(_cfg.CHUNK_TIKTOKEN_ENCODING)
    ids = enc.encode(text)
    if len(ids) <= max_tokens:
        return text
    return enc.decode(ids[:max_tokens])


def _strip_frontmatter(text: str) -> str:
    # Remove YAML (---) or TOML (+++) frontmatter blocks
    pattern = r"^(?:---|\+\+\+)\n.*?\n(?:---|\+\+\+)\n"
    return re.sub(pattern, "", text, count=1, flags=re.DOTALL)


def chunk_file(source_file: str, content: str) -> list[Chunk]:
    enc = tiktoken.get_encoding(_cfg.CHUNK_TIKTOKEN_ENCODING)
    clean = _strip_frontmatter(content)
    token_ids = enc.encode(clean)

    if len(token_ids) <= _cfg.CHUNK_WINDOW_TOKENS:
        return [
            Chunk(
                source_file=source_file,
                chunk_index=0,
                text=clean,
                token_start=0,
                token_end=len(token_ids),
            )
        ]

    chunks: list[Chunk] = []
    step = _cfg.CHUNK_WINDOW_TOKENS - _cfg.CHUNK_OVERLAP_TOKENS
    start = 0
    idx = 0
    while start < len(token_ids):
        end = min(start + _cfg.CHUNK_WINDOW_TOKENS, len(token_ids))
        window_text = enc.decode(token_ids[start:end])
        chunks.append(
            Chunk(
                source_file=source_file,
                chunk_index=idx,
                text=window_text,
                token_start=start,
                token_end=end,
            )
        )
        if end == len(token_ids):
            break
        start += step
        idx += 1

    return chunks
