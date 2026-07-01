#!/usr/bin/env python3
"""
context_calculator.py — suggest mykg mykg_config.yaml token-budget parameters.

Two modes:

  1. Manual mode — supply model parameters on the command line:
       python context_calculator.py --context 64000 --max-output 32000

  2. Auto mode — read the active profile from mykg_config.yaml and measure
     the actual input corpus to suggest an optimal chunk divisor:
       python context_calculator.py --from-config
       python context_calculator.py --from-config --input-dir ./input_files

In auto mode the script:
  - Loads context_window and max_output_tokens from the active profile's llm: block
  - Counts tokens in every .md file under --input-dir using the profile's tiktoken_encoding
    (rglob — picks up converted Markdown under input/_preprocessed/ when pointed at
    a session's input/ dir; pure non-md sources like raw .pdf/.docx count as 0 until
    they have been converted by the preprocess step)
  - Reads pass2.prep_mode and reports which Pass 2 budget the run will actually use
    (concat_batch_token_target for prep_mode=concat; batch_token_target for batch_chunks)
  - Computes how many chunks the corpus produces at the current window_tokens / overlap_tokens
  - Derives the optimal chunk_divisor so batch_token_target fits the corpus well
  - Prints a ready-to-paste YAML snippet for the active profile and writes a
    mykg_config_candidate.yaml that patches: llm.context_window, llm.max_output_tokens,
    chunking.window_tokens, chunking.overlap_tokens, pass1.batch_token_target,
    pass2.batch_token_target, pass2.concat_batch_token_target, feedback.max_file_chars,
    normalize_names.batch_token_target, and pass1.max_schema_proposals (shown as a
    fixed reminder; not derived from context window)
"""

import argparse
import math
from pathlib import Path

SYSTEM_PROMPT_OVERHEAD = 1000  # approximate tokens consumed by system prompt + JSON scaffolding
OVERLAP_RATIO = 0.10  # overlap_tokens = window_tokens * this
SAFETY_MARGIN_RATIO = (
    0.05  # batch_token_target = input_headroom * (1 - this); remainder = feedback reserve
)
DEFAULT_CHUNK_DIVISOR = 12  # window_tokens = batch_token_target / this
CHARS_PER_TOKEN = 4  # character-to-token ratio for JSON/prose (used to derive max_file_chars)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def round_to_nice(n: int) -> int:
    """Round down to the nearest 'nice' number (multiple of 1000, 500, or 100)."""
    for step in (10000, 5000, 2000, 1000, 500, 200, 100):
        rounded = (n // step) * step
        if rounded > 0:
            return rounded
    return n


def load_mykg_config() -> tuple[dict, Path]:
    """Find and load mykg_config.yaml, resolving the active profile.

    Returns (config_dict, config_path).
    """
    import yaml

    here = Path.cwd()
    for directory in [here, *here.parents]:
        config_path = directory / "mykg_config.yaml"
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                raw = yaml.safe_load(f)
            profile_name = raw.get("profile")
            if profile_name:
                profiles = raw.get("profiles", {})
                if profile_name not in profiles:
                    raise KeyError(f"Profile '{profile_name}' not found in mykg_config.yaml")
                import copy

                result = copy.deepcopy(raw)
                profile = profiles[profile_name]
                for key in ("provider", "pipeline", "llm", "llm_retry"):
                    if key in profile:
                        result[key] = profile[key]
                result["_active_profile"] = profile_name
            else:
                result = raw
                result["_active_profile"] = "(default)"
            return result, config_path
    raise FileNotFoundError("mykg_config.yaml not found")


def count_corpus_tokens(input_dir: Path, encoding_name: str) -> int:
    """Count total tokens across all .md files in input_dir (recursive)."""
    import tiktoken

    enc = tiktoken.get_encoding(encoding_name)
    total = 0
    files = list(input_dir.rglob("*.md"))
    if not files:
        raise FileNotFoundError(f"No .md files found under {input_dir}")
    for path in files:
        text = path.read_text(errors="replace")
        total += len(enc.encode(text))
    return total, len(files)


def count_chunks(total_tokens: int, window_tokens: int, overlap_tokens: int) -> int:
    """Estimate how many chunks the corpus produces given window and overlap."""
    if total_tokens <= window_tokens:
        return 1
    step = window_tokens - overlap_tokens
    if step <= 0:
        return 1
    return math.ceil((total_tokens - overlap_tokens) / step)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------


def calculate(
    context_window: int,
    max_output_tokens: int | None,
    input_headroom: int | None,
    chunk_divisor: int,
) -> dict:
    if max_output_tokens is not None and input_headroom is None:
        input_headroom = context_window - max_output_tokens
    elif input_headroom is not None and max_output_tokens is None:
        max_output_tokens = context_window - input_headroom
    elif max_output_tokens is None and input_headroom is None:
        raise ValueError("Provide either --max-output or --input-headroom")
    else:
        if max_output_tokens + input_headroom != context_window:
            print(
                f"⚠  Warning: max_output_tokens({max_output_tokens}) + "
                f"input_headroom({input_headroom}) = {max_output_tokens + input_headroom} "
                f"≠ context_window({context_window}). Using provided values as-is."
            )

    batch_token_target = round_to_nice(int(input_headroom * (1 - SAFETY_MARGIN_RATIO)))
    window_tokens = max(round_to_nice(int(batch_token_target / chunk_divisor)), 100)
    overlap_tokens = max(round_to_nice(int(window_tokens * OVERLAP_RATIO)), 10)

    # The safety margin IS the feedback reserve — tokens not consumed by batch_token_target.
    # Convert to characters so the value maps directly to mykg_config feedback.max_file_chars.
    feedback_token_reserve = input_headroom - batch_token_target
    max_file_chars = feedback_token_reserve * CHARS_PER_TOKEN

    return {
        "context_window": context_window,
        "max_output_tokens": max_output_tokens,
        "input_headroom": input_headroom,
        "batch_token_target": batch_token_target,
        "feedback_token_reserve": feedback_token_reserve,
        "max_file_chars": max_file_chars,
        "window_tokens": window_tokens,
        "overlap_tokens": overlap_tokens,
    }


def suggest_chunk_divisor(
    input_headroom: int,
    total_tokens: int,
    window_tokens: int,
    overlap_tokens: int,
) -> tuple[int, int]:
    """Return (suggested_divisor, chunk_count) that keeps batches well-sized.

    Strategy: find the divisor where window_tokens makes the corpus produce
    a reasonable number of chunks — aiming for ~100-500 chunks total
    (enough parallelism without overwhelming the LLM call budget).
    """
    batch_token_target = round_to_nice(int(input_headroom * (1 - SAFETY_MARGIN_RATIO)))
    best_divisor = DEFAULT_CHUNK_DIVISOR
    best_chunks = count_chunks(total_tokens, window_tokens, overlap_tokens)

    for divisor in range(4, 32):
        wt = max(round_to_nice(int(batch_token_target / divisor)), 100)
        ot = max(round_to_nice(int(wt * OVERLAP_RATIO)), 10)
        chunks = count_chunks(total_tokens, wt, ot)
        # Prefer chunk counts in the sweet spot: not too few (poor coverage), not too many (too many LLM calls)
        if 50 <= chunks <= 500:
            best_divisor = divisor
            best_chunks = chunks
            break
        if abs(chunks - 200) < abs(best_chunks - 200):
            best_divisor = divisor
            best_chunks = chunks

    return best_divisor, best_chunks


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


def write_candidate_config(config_path: "Path", profile_name: str, result: dict) -> "Path":
    """Write a candidate mykg_config.yaml next to the original with suggested token-budget values.

    Copies the source file verbatim and patches the token-budget keys
    in the active profile, preserving all comments and formatting.
    Returns the path of the written candidate file.
    """
    import re

    text = config_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    # `batch_token_target` appears under both pass1 and pass2 with the same
    # ≤ input_headroom constraint, so the same value satisfies both.
    # `concat_batch_token_target` is the pass2 budget for prep_mode=concat —
    # same constraint, same value.
    patch_map = {
        "context_window": result["context_window"],
        "max_output_tokens": result["max_output_tokens"],
        "batch_token_target": result["batch_token_target"],
        "window_tokens": result["window_tokens"],
        "overlap_tokens": result["overlap_tokens"],
        "max_file_chars": result["max_file_chars"],
        "concat_batch_token_target": result["batch_token_target"],
    }

    in_profile = False
    new_lines: list[str] = []

    for line in lines:
        stripped = line.lstrip()

        # Detect profile entry: "  openrouter-free:" (2-space indent)
        if re.match(rf"^\s{{2}}{re.escape(profile_name)}\s*:", line):
            in_profile = True
            new_lines.append(line)
            continue

        # Detect leaving the profile: another 2-space-indented non-comment key
        if in_profile and re.match(r"^  \S", line) and not stripped.startswith("#"):
            in_profile = False

        if in_profile:
            m = re.match(r"^(\s+)([\w_]+)(\s*:\s*)(\S+)(.*)", line)
            if m:
                indent, key, sep, _old_val, tail = m.groups()
                if key in patch_map:
                    line = f"{indent}{key}{sep}{patch_map[key]}{tail}\n"

        new_lines.append(line)

    stem = config_path.stem  # "mykg_config"
    suffix = config_path.suffix  # ".yaml"
    out_path = config_path.with_name(f"{stem}_candidate{suffix}")
    out_path.write_text("".join(new_lines), encoding="utf-8")
    return out_path


def print_report(
    result: dict,
    model: str,
    chunk_divisor: int,
    corpus_info: dict | None = None,
    prep_mode: str | None = None,
) -> None:
    cw = result["context_window"]
    mot = result["max_output_tokens"]
    ih = result["input_headroom"]
    btt = result["batch_token_target"]
    ftr = result["feedback_token_reserve"]
    mfc = result["max_file_chars"]
    wt = result["window_tokens"]
    ot = result["overlap_tokens"]

    print()
    print("=" * 60)
    print(f"  Token Budget Calculator — {model}")
    print("=" * 60)
    print()
    print("  INPUT")
    print(f"    context_window      = {cw:>8,}")
    print(f"    max_output_tokens   = {mot:>8,}   (① set by model cap)")
    print(f"    input_headroom      = {ih:>8,}   = context_window - max_output_tokens")

    if corpus_info:
        print()
        print("  CORPUS")
        print(f"    files               = {corpus_info['file_count']:>8,}")
        print(f"    total tokens        = {corpus_info['total_tokens']:>8,}")
        print(
            f"    chunk count         = {corpus_info['chunk_count']:>8,}   at window={wt}, overlap={ot}"
        )
        print(
            f"    suggested divisor   = {chunk_divisor:>8}   (window_tokens = batch_token_target ÷ this)"
        )

    print()
    print("  DERIVED PARAMETERS")
    print(
        f"    batch_token_target  = {btt:>8,}   = input_headroom × {1 - SAFETY_MARGIN_RATIO:.0%}  (safety margin)"
    )
    print(
        f"    feedback_reserve    = {ftr:>8,}   = input_headroom - batch_token_target  (safety margin remainder)"
    )
    print(
        f"    max_file_chars      = {mfc:>8,}   = feedback_reserve × {CHARS_PER_TOKEN} chars/token"
    )
    print(
        f"    window_tokens       = {wt:>8,}   = batch_token_target ÷ {chunk_divisor}  (chunk size)"
    )
    print(f"    overlap_tokens      = {ot:>8,}   = window_tokens × {OVERLAP_RATIO:.0%}")
    print()
    print("  VALIDATION")
    ok = mot + ih == cw
    print(
        f"    max_output + input_headroom = {mot + ih:,}  {'✓ = context_window' if ok else f'✗ ≠ context_window ({cw:,})'}"
    )
    fits = btt <= ih
    print(
        f"    batch_token_target ≤ input_headroom: {'✓' if fits else '✗ EXCEEDS — API will return context-length errors'}"
    )
    print()
    if prep_mode:
        print()
        print("  ACTIVE PASS 2 PREP MODE")
        if prep_mode == "concat":
            print(f"    prep_mode = concat       → concat_batch_token_target = {btt:,} drives Pass 2")
        elif prep_mode == "batch_chunks":
            print(f"    prep_mode = batch_chunks → pass2.batch_token_target = {btt:,} drives Pass 2")
        else:
            print(f"    prep_mode = {prep_mode:<13} → per-file chunking; pass2 budgets unused")

    print()
    print("  YAML SNIPPET — paste into the active profile in mykg_config.yaml")
    print("  " + "-" * 56)
    print("    llm:")
    print(f"      context_window: {cw}  # model total context limit")
    print(f"      max_output_tokens: {mot}  # ① output cap; input_headroom = {ih}")
    print("    pipeline:")
    print("      chunking:")
    print(f"        window_tokens: {wt}  # = batch_token_target ÷ {chunk_divisor}")
    print(f"        overlap_tokens: {ot}  # = window_tokens × {OVERLAP_RATIO:.0%}")
    print("      pass1:")
    print(f"        batch_token_target: {btt}  # = input_headroom × {1 - SAFETY_MARGIN_RATIO:.0%}")
    print("        max_schema_proposals: 50  # fixed cap; lower on small-context models")
    print("      pass2:")
    print(f"        batch_token_target: {btt}        # used when prep_mode=batch_chunks")
    print(f"        concat_batch_token_target: {btt}  # used when prep_mode=concat")
    print("      feedback:")
    print(
        f"        max_file_chars: {mfc}  # = safety margin remainder × {CHARS_PER_TOKEN} chars/token ({ftr:,} tokens)"
    )
    print("      normalize_names:")
    print(f"        batch_token_target: {btt}  # matches concat_batch_token_target")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Suggest mykg pipeline token-budget parameters from a model's context window.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto mode — read active profile from mykg_config.yaml, measure input corpus:
  python context_calculator.py --from-config
  python context_calculator.py --from-config --input-dir ./input_files/my_corpus

  # Manual mode — supply all parameters explicitly:
  python context_calculator.py --model openrouter-free --context 64000 --max-output 32000
  python context_calculator.py --model claude-cli      --context 200000 --max-output 32000
  python context_calculator.py --context 128000 --input-headroom 96000 --chunk-divisor 8
        """,
    )
    parser.add_argument(
        "--from-config",
        action="store_true",
        help="Read context_window and max_output_tokens from mykg_config.yaml active profile",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help=(
            "Directory of .md input files to measure, walked recursively "
            "(default: ./input_files or ./_input_files). Point at a session's "
            "input/ dir to include converted Markdown under input/_preprocessed/."
        ),
    )
    parser.add_argument("--model", default=None, help="Model name label (manual mode only)")
    parser.add_argument(
        "--context", type=int, default=None, help="Model context window in tokens (manual mode)"
    )
    parser.add_argument(
        "--max-output", type=int, default=None, help="Model max output tokens (manual mode)"
    )
    parser.add_argument(
        "--input-headroom",
        type=int,
        default=None,
        help="Desired input headroom in tokens (manual mode)",
    )
    parser.add_argument(
        "--chunk-divisor",
        type=int,
        default=None,
        help=f"window_tokens = batch_token_target ÷ this (default: auto-suggested from corpus, or {DEFAULT_CHUNK_DIVISOR})",
    )
    args = parser.parse_args()

    corpus_info = None

    if args.from_config:
        cfg, config_path = load_mykg_config()
        profile_name = cfg.get("_active_profile", "?")
        llm = cfg.get("llm", {})
        pipeline = cfg.get("pipeline", {})
        chunking = pipeline.get("chunking", {})

        context_window = llm.get("context_window")
        max_output_tokens = llm.get("max_output_tokens")
        if context_window is None or max_output_tokens is None:
            parser.error(
                "mykg_config.yaml active profile must have llm.context_window and "
                "llm.max_output_tokens set. Run the manual mode (--context, --max-output) instead."
            )

        encoding_name = chunking.get("tiktoken_encoding", "cl100k_base")
        current_window = chunking.get("window_tokens", 1000)
        current_overlap = chunking.get("overlap_tokens", 100)
        prep_mode = pipeline.get("pass2", {}).get("prep_mode")
        model_label = args.model or f"profile: {profile_name}"

        # Find input directory
        input_dir = args.input_dir
        if input_dir is None:
            here = Path.cwd()
            for candidate in [here / "input_files", here / "_input_files"]:
                if candidate.exists():
                    input_dir = candidate
                    break
        if input_dir is None or not input_dir.exists():
            parser.error(
                "Could not find input directory. Pass --input-dir <path> or create ./input_files/."
            )

        print(f"\n  Counting tokens in {input_dir} …", end="", flush=True)
        total_tokens, file_count = count_corpus_tokens(input_dir, encoding_name)
        print(f" {total_tokens:,} tokens across {file_count} files")

        input_headroom = context_window - max_output_tokens

        # Auto-suggest chunk divisor from corpus unless user supplied one
        if args.chunk_divisor is not None:
            chunk_divisor = args.chunk_divisor
            wt = max(
                round_to_nice(
                    int(
                        round_to_nice(int(input_headroom * (1 - SAFETY_MARGIN_RATIO)))
                        / chunk_divisor
                    )
                ),
                100,
            )
            ot = max(round_to_nice(int(wt * OVERLAP_RATIO)), 10)
            chunk_count = count_chunks(total_tokens, wt, ot)
        else:
            chunk_divisor, chunk_count = suggest_chunk_divisor(
                input_headroom, total_tokens, current_window, current_overlap
            )

        corpus_info = {
            "total_tokens": total_tokens,
            "file_count": file_count,
            "chunk_count": chunk_count,
        }

        result = calculate(
            context_window=context_window,
            max_output_tokens=max_output_tokens,
            input_headroom=None,
            chunk_divisor=chunk_divisor,
        )

    else:
        # Manual mode
        if args.context is None:
            parser.error(
                "Manual mode requires --context (or use --from-config to read from mykg_config.yaml)"
            )
        model_label = args.model or "custom-model"
        chunk_divisor = args.chunk_divisor or DEFAULT_CHUNK_DIVISOR
        prep_mode = None
        result = calculate(
            context_window=args.context,
            max_output_tokens=args.max_output,
            input_headroom=args.input_headroom,
            chunk_divisor=chunk_divisor,
        )

    print_report(
        result,
        model=model_label,
        chunk_divisor=chunk_divisor,
        corpus_info=corpus_info,
        prep_mode=prep_mode,
    )

    if args.from_config:
        out_path = write_candidate_config(config_path, profile_name, result)
        print(f"  ✓  Candidate written to: {out_path}")
        print("     Review, then rename to mykg_config.yaml when satisfied.")
        print()


if __name__ == "__main__":
    main()
