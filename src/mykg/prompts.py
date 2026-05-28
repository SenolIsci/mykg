from __future__ import annotations

import pathlib

_PROMPTS_ROOT = pathlib.Path(__file__).parent / "prompts"


def load_prompt(name: str) -> str:
    """Load a prompt file. name is relative to prompts/ without extension, e.g. 'pass1/system'."""
    path = _PROMPTS_ROOT / f"{name}.txt"
    return path.read_text(encoding="utf-8").rstrip()
