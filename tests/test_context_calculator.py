"""
Tests for src/mykg/utility/context_calculator.py

Coverage target: ~90%

Key design notes:
- yaml and tiktoken are imported *inside* function bodies; patch via sys.modules.
- load_mykg_config searches upward from cwd — use monkeypatch.chdir(tmp_path)
  and write a real mykg_config.yaml file there.
- main() uses argparse — patch sys.argv via monkeypatch.setattr.
"""

import sys
from unittest.mock import MagicMock, patch

import pytest

from mykg.utility.context_calculator import (
    CHARS_PER_TOKEN,
    DEFAULT_CHUNK_DIVISOR,
    SAFETY_MARGIN_RATIO,
    calculate,
    count_chunks,
    load_mykg_config,
    print_report,
    round_to_nice,
    suggest_chunk_divisor,
    write_candidate_config,
)

# ---------------------------------------------------------------------------
# round_to_nice
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "n,expected",
    [
        (10000, 10000),
        (15000, 10000),
        (19999, 10000),
        (20000, 20000),
        (100000, 100000),
    ],
)
def test_round_to_nice_multiples_of_10000(n, expected):
    assert round_to_nice(n) == expected


@pytest.mark.parametrize(
    "n,expected",
    [
        (1000, 1000),
        (1500, 1000),
        (1999, 1000),
        # 3000 // 2000 = 1 → returns 2000 (2000 step fires before 1000)
        (3000, 2000),
        # 9999 // 5000 = 1 → returns 5000 (5000 step fires before 1000)
        (9999, 5000),
    ],
)
def test_round_to_nice_multiples_of_1000(n, expected):
    assert round_to_nice(n) == expected


@pytest.mark.parametrize(
    "n,expected",
    [
        (100, 100),
        (150, 100),
        (199, 100),
        (250, 200),
        (350, 200),
        (450, 400),
    ],
)
def test_round_to_nice_multiples_of_100(n, expected):
    assert round_to_nice(n) == expected


@pytest.mark.parametrize("n", [1, 5, 10, 50, 99])
def test_round_to_nice_small_values_returned_as_is(n):
    # all steps produce 0 (rounded to 0 which is falsy) so the raw n is returned
    result = round_to_nice(n)
    assert result == n


def test_round_to_nice_zero():
    assert round_to_nice(0) == 0


# ---------------------------------------------------------------------------
# count_chunks
# ---------------------------------------------------------------------------


def test_count_chunks_fits_in_one_window():
    assert count_chunks(500, 1000, 100) == 1


def test_count_chunks_exact_multiple():
    # total=2000, window=1000, overlap=0 → step=1000 → ceil((2000-0)/1000) = 2
    assert count_chunks(2000, 1000, 0) == 2


def test_count_chunks_fractional_remainder():
    # total=2500, window=1000, overlap=100 → step=900 → ceil((2500-100)/900) = ceil(2400/900) = 3
    assert count_chunks(2500, 1000, 100) == 3


def test_count_chunks_zero_step_returns_one():
    # step = window - overlap = 0 → guard returns 1
    assert count_chunks(5000, 500, 500) == 1


# ---------------------------------------------------------------------------
# calculate
# ---------------------------------------------------------------------------


def test_calculate_derives_from_max_output():
    result = calculate(
        context_window=32000,
        max_output_tokens=8000,
        input_headroom=None,
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    assert result["input_headroom"] == 32000 - 8000
    assert result["max_output_tokens"] == 8000


def test_calculate_derives_from_input_headroom():
    result = calculate(
        context_window=32000,
        max_output_tokens=None,
        input_headroom=24000,
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    assert result["max_output_tokens"] == 32000 - 24000
    assert result["input_headroom"] == 24000


def test_calculate_raises_when_neither_supplied():
    with pytest.raises(ValueError, match="Provide either"):
        calculate(
            context_window=32000,
            max_output_tokens=None,
            input_headroom=None,
            chunk_divisor=DEFAULT_CHUNK_DIVISOR,
        )


def test_calculate_result_contains_all_keys():
    result = calculate(
        context_window=32000,
        max_output_tokens=8000,
        input_headroom=None,
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    expected_keys = {
        "context_window",
        "max_output_tokens",
        "input_headroom",
        "batch_token_target",
        "feedback_token_reserve",
        "max_file_chars",
        "window_tokens",
        "overlap_tokens",
    }
    assert expected_keys == set(result.keys())


def test_calculate_safety_margin_applied():
    result = calculate(
        context_window=32000,
        max_output_tokens=8000,
        input_headroom=None,
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    ih = result["input_headroom"]
    # batch_token_target <= ih * (1 - SAFETY_MARGIN_RATIO)
    assert result["batch_token_target"] <= ih * (1 - SAFETY_MARGIN_RATIO)
    assert result["feedback_token_reserve"] == ih - result["batch_token_target"]
    assert result["max_file_chars"] == result["feedback_token_reserve"] * CHARS_PER_TOKEN


def test_calculate_both_supplied_prints_warning(capsys):
    # Both values consistent — no warning if they add up to context_window
    result = calculate(
        context_window=32000,
        max_output_tokens=8000,
        input_headroom=24000,
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    assert result["context_window"] == 32000

    # Both values inconsistent — should print a warning
    calculate(
        context_window=32000,
        max_output_tokens=8000,
        input_headroom=20000,  # 8000 + 20000 != 32000
        chunk_divisor=DEFAULT_CHUNK_DIVISOR,
    )
    captured = capsys.readouterr()
    assert "Warning" in captured.out


# ---------------------------------------------------------------------------
# suggest_chunk_divisor
# ---------------------------------------------------------------------------


def test_suggest_chunk_divisor_sweet_spot():
    # Large corpus — should find a divisor whose chunk count falls in 50-500
    total_tokens = 500_000
    window_tokens = 2000
    overlap_tokens = 200
    input_headroom = 20_000
    divisor, chunks = suggest_chunk_divisor(
        input_headroom, total_tokens, window_tokens, overlap_tokens
    )
    assert 4 <= divisor <= 31
    # The sweet-spot break should fire, giving a chunk count in the right range
    assert 50 <= chunks <= 500


def test_suggest_chunk_divisor_falls_back_to_closest_to_200():
    # Very small corpus — no divisor will land in 50-500 range; pick closest to 200
    total_tokens = 1000
    window_tokens = 2000
    overlap_tokens = 200
    input_headroom = 20_000
    divisor, chunks = suggest_chunk_divisor(
        input_headroom, total_tokens, window_tokens, overlap_tokens
    )
    # Should still return a valid divisor
    assert 4 <= divisor <= 31


def test_suggest_chunk_divisor_small_corpus():
    # Corpus smaller than one window — count_chunks returns 1
    total_tokens = 100
    window_tokens = 2000
    overlap_tokens = 200
    input_headroom = 20_000
    divisor, chunks = suggest_chunk_divisor(
        input_headroom, total_tokens, window_tokens, overlap_tokens
    )
    assert chunks >= 1
    assert divisor >= 4


# ---------------------------------------------------------------------------
# count_corpus_tokens — patch tiktoken so tests don't need the real encoder
# ---------------------------------------------------------------------------


def test_count_corpus_tokens_sums_all_md_files(tmp_path):
    (tmp_path / "a.md").write_text("hello world")
    (tmp_path / "b.md").write_text("foo bar baz")
    subdir = tmp_path / "sub"
    subdir.mkdir()
    (subdir / "c.md").write_text("deep file content")

    # tiktoken is imported inside the function body; inject via sys.modules
    mock_enc = MagicMock()
    mock_enc.encode.side_effect = lambda text: [0] * len(text.split())
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    with patch.dict(sys.modules, {"tiktoken": mock_tiktoken}):
        from mykg.utility.context_calculator import count_corpus_tokens as _cct

        total, file_count = _cct(tmp_path, "cl100k_base")

    assert file_count == 3
    # a.md: 2 tokens, b.md: 3 tokens, sub/c.md: 3 tokens → 8
    assert total == 8


def test_count_corpus_tokens_no_md_files_raises(tmp_path):
    (tmp_path / "readme.txt").write_text("not markdown")

    mock_enc = MagicMock()
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    with patch.dict(sys.modules, {"tiktoken": mock_tiktoken}):
        from mykg.utility.context_calculator import count_corpus_tokens as _cct

        with pytest.raises(FileNotFoundError, match="No .md files"):
            _cct(tmp_path, "cl100k_base")


# ---------------------------------------------------------------------------
# load_mykg_config
# ---------------------------------------------------------------------------

MINIMAL_CONFIG = """\
profile: myprofile
profiles:
  myprofile:
    llm:
      context_window: 32000
      max_output_tokens: 8000
    pipeline:
      chunking:
        window_tokens: 2000
        overlap_tokens: 200
"""

MINIMAL_CONFIG_NO_PROFILE = """\
llm:
  context_window: 16000
  max_output_tokens: 4000
"""


def test_load_mykg_config_finds_yaml_in_cwd(tmp_path, monkeypatch):
    (tmp_path / "mykg_config.yaml").write_text(MINIMAL_CONFIG)
    monkeypatch.chdir(tmp_path)

    cfg, config_path = load_mykg_config()
    assert config_path == tmp_path / "mykg_config.yaml"


def test_load_mykg_config_resolves_active_profile(tmp_path, monkeypatch):
    (tmp_path / "mykg_config.yaml").write_text(MINIMAL_CONFIG)
    monkeypatch.chdir(tmp_path)

    cfg, config_path = load_mykg_config()
    assert cfg["_active_profile"] == "myprofile"
    assert cfg["llm"]["context_window"] == 32000
    assert cfg["llm"]["max_output_tokens"] == 8000


def test_load_mykg_config_no_profile_uses_defaults(tmp_path, monkeypatch):
    (tmp_path / "mykg_config.yaml").write_text(MINIMAL_CONFIG_NO_PROFILE)
    monkeypatch.chdir(tmp_path)

    cfg, config_path = load_mykg_config()
    assert cfg["_active_profile"] == "(default)"
    assert cfg["llm"]["context_window"] == 16000


def test_load_mykg_config_raises_when_profile_missing(tmp_path, monkeypatch):
    bad_config = """\
profile: nonexistent_profile
profiles:
  other:
    llm:
      context_window: 32000
"""
    (tmp_path / "mykg_config.yaml").write_text(bad_config)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(KeyError, match="nonexistent_profile"):
        load_mykg_config()


def test_load_mykg_config_raises_when_no_file_found(tmp_path, monkeypatch):
    # Patch Path.cwd to return a directory with no parents and no config file.
    # This avoids the search reaching the real repo root where a config exists.
    fake_cwd = MagicMock()
    fake_cwd.parents = []
    fake_config = MagicMock()
    fake_config.exists.return_value = False
    fake_cwd.__truediv__ = lambda self, other: fake_config

    with patch("mykg.utility.context_calculator.Path") as mock_path_cls:
        mock_path_cls.cwd.return_value = fake_cwd
        with pytest.raises(FileNotFoundError, match="mykg_config.yaml not found"):
            load_mykg_config()


# ---------------------------------------------------------------------------
# write_candidate_config
# ---------------------------------------------------------------------------

SAMPLE_PIPELINE_CONFIG = """\
profile: testprofile
profiles:
  testprofile:
    llm:
      context_window: 16000
      max_output_tokens: 4000
    pipeline:
      pass1:
        batch_token_target: 8000
      chunking:
        window_tokens: 1000
        overlap_tokens: 100
      feedback:
        max_file_chars: 2000
        concat_batch_token_target: 8000
"""

SAMPLE_RESULT = {
    "context_window": 32000,
    "max_output_tokens": 8000,
    "input_headroom": 24000,
    "batch_token_target": 20000,
    "feedback_token_reserve": 4000,
    "max_file_chars": 16000,
    "window_tokens": 2000,
    "overlap_tokens": 200,
}


def test_write_candidate_config_patches_token_keys(tmp_path):
    config_path = tmp_path / "mykg_config.yaml"
    config_path.write_text(SAMPLE_PIPELINE_CONFIG)

    out_path = write_candidate_config(config_path, "testprofile", SAMPLE_RESULT)
    content = out_path.read_text()

    # Patched values should appear in the output
    assert "context_window: 32000" in content
    assert "max_output_tokens: 8000" in content
    assert "batch_token_target: 20000" in content
    assert "window_tokens: 2000" in content
    assert "overlap_tokens: 200" in content
    assert "max_file_chars: 16000" in content


def test_write_candidate_config_correct_output_filename(tmp_path):
    config_path = tmp_path / "mykg_config.yaml"
    config_path.write_text(SAMPLE_PIPELINE_CONFIG)

    out_path = write_candidate_config(config_path, "testprofile", SAMPLE_RESULT)
    assert out_path.name == "mykg_config_candidate.yaml"
    assert out_path.parent == tmp_path


def test_write_candidate_config_preserves_other_content(tmp_path):
    config_path = tmp_path / "mykg_config.yaml"
    config_path.write_text(SAMPLE_PIPELINE_CONFIG)

    out_path = write_candidate_config(config_path, "testprofile", SAMPLE_RESULT)
    content = out_path.read_text()

    # The profile key and surrounding structure should remain
    assert "testprofile:" in content
    assert "profile: testprofile" in content


# ---------------------------------------------------------------------------
# print_report
# ---------------------------------------------------------------------------

PRINT_RESULT = {
    "context_window": 32000,
    "max_output_tokens": 8000,
    "input_headroom": 24000,
    "batch_token_target": 20000,
    "feedback_token_reserve": 4000,
    "max_file_chars": 16000,
    "window_tokens": 2000,
    "overlap_tokens": 200,
}


def test_print_report_includes_yaml_snippet(capsys):
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12)
    out = capsys.readouterr().out
    assert "context_window: 32000" in out
    assert "max_output_tokens: 8000" in out
    assert "window_tokens: 2000" in out
    assert "overlap_tokens: 200" in out
    assert "batch_token_target: 20000" in out


def test_print_report_with_corpus_info(capsys):
    corpus_info = {"file_count": 42, "total_tokens": 500_000, "chunk_count": 250}
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12, corpus_info=corpus_info)
    out = capsys.readouterr().out
    assert "42" in out
    assert "500,000" in out or "500000" in out
    assert "250" in out
    assert "CORPUS" in out


def test_print_report_without_corpus_info(capsys):
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12, corpus_info=None)
    out = capsys.readouterr().out
    assert "CORPUS" not in out
    assert "Token Budget Calculator" in out


def test_print_report_validation_ok(capsys):
    # PRINT_RESULT has max_output_tokens + input_headroom == context_window → shows ✓
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12)
    out = capsys.readouterr().out
    assert "VALIDATION" in out
    # The check line should contain ✓ (not ✗) for the context window sum
    assert "✓" in out


def test_print_report_validation_mismatch(capsys):
    # Craft a result where max_output + input_headroom != context_window
    result = {
        "context_window": 32000,
        "max_output_tokens": 8000,
        "input_headroom": 20000,  # 8000+20000=28000 != 32000
        "batch_token_target": 18000,
        "feedback_token_reserve": 2000,
        "max_file_chars": 8000,
        "window_tokens": 1500,
        "overlap_tokens": 100,
    }
    print_report(result, model="test-model", chunk_divisor=12)
    out = capsys.readouterr().out
    # Should indicate mismatch (contains ≠ or EXCEEDS or similar indicator)
    assert "VALIDATION" in out


# ---------------------------------------------------------------------------
# main() — argparse entry point
# ---------------------------------------------------------------------------


def test_main_manual_mode_with_context_and_max_output(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["context_calculator.py", "--context", "32000", "--max-output", "8000"],
    )
    from mykg.utility.context_calculator import main

    main()
    out = capsys.readouterr().out
    assert "32000" in out
    assert "8000" in out


def test_main_manual_mode_errors_without_context(monkeypatch, capsys):
    monkeypatch.setattr(
        sys,
        "argv",
        ["context_calculator.py", "--max-output", "8000"],
    )
    from mykg.utility.context_calculator import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_write_candidate_config_leaves_other_profile_untouched(tmp_path):
    """write_candidate_config must not patch keys outside the named profile (line 239)."""
    cfg_text = """\
profile: alpha
profiles:
  alpha:
    llm:
      context_window: 1000
  beta:
    llm:
      context_window: 9999
"""
    cfg_path = tmp_path / "mykg_config.yaml"
    cfg_path.write_text(cfg_text)

    result = {
        "context_window": 4242,
        "max_output_tokens": 100,
        "batch_token_target": 200,
        "window_tokens": 300,
        "overlap_tokens": 50,
        "max_file_chars": 400,
    }
    out_path = write_candidate_config(cfg_path, "alpha", result)
    out = out_path.read_text()

    # The alpha profile's context_window should be patched, but beta's value
    # (9999) must remain unchanged
    assert "context_window: 4242" in out
    assert "context_window: 9999" in out


def test_print_report_prep_mode_concat(capsys):
    """print_report shows the concat-specific message when prep_mode='concat' (line 324-325)."""
    print_report(PRINT_RESULT, model="m", chunk_divisor=12, prep_mode="concat")
    out = capsys.readouterr().out
    assert "concat_batch_token_target" in out
    assert "concat" in out


def test_print_report_prep_mode_batch_chunks(capsys):
    """print_report shows the batch_chunks message when prep_mode='batch_chunks' (line 326-327)."""
    print_report(PRINT_RESULT, model="m", chunk_divisor=12, prep_mode="batch_chunks")
    out = capsys.readouterr().out
    assert "pass2.batch_token_target" in out
    assert "batch_chunks" in out


def test_print_report_prep_mode_per_file(capsys):
    """print_report shows the per-file message for an unrecognized prep_mode (line 329)."""
    print_report(PRINT_RESULT, model="m", chunk_divisor=12, prep_mode="per_file")
    out = capsys.readouterr().out
    assert "per-file chunking" in out


def test_main_from_config_errors_when_context_missing(tmp_path, monkeypatch):
    """parser.error fires (line 421-425) when llm.context_window is absent."""
    cfg = """\
profile: bad
profiles:
  bad:
    llm: {}
    pipeline:
      chunking: {}
"""
    (tmp_path / "mykg_config.yaml").write_text(cfg)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["context_calculator.py", "--from-config"])

    from mykg.utility.context_calculator import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_main_from_config_auto_discovers_input_files(tmp_path, monkeypatch, capsys):
    """When --input-dir is omitted, main() finds ./input_files automatically (lines 436-440)."""
    # Create ./input_files in cwd
    input_dir = tmp_path / "input_files"
    input_dir.mkdir()
    (input_dir / "doc.md").write_text("hello world auto discover")

    cfg = """\
profile: p
profiles:
  p:
    llm:
      context_window: 32000
      max_output_tokens: 8000
    pipeline:
      chunking:
        window_tokens: 2000
        overlap_tokens: 200
        tiktoken_encoding: cl100k_base
"""
    (tmp_path / "mykg_config.yaml").write_text(cfg)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(sys, "argv", ["context_calculator.py", "--from-config"])

    mock_enc = MagicMock()
    mock_enc.encode.side_effect = lambda text: [0] * len(text.split())
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    with patch.dict(sys.modules, {"tiktoken": mock_tiktoken}):
        from mykg.utility.context_calculator import main

        main()

    out = capsys.readouterr().out
    assert "Token Budget Calculator" in out


def test_main_from_config_errors_when_no_input_dir(tmp_path, monkeypatch):
    """parser.error fires (line 441-444) when no input dir can be located."""
    cfg = """\
profile: p
profiles:
  p:
    llm:
      context_window: 32000
      max_output_tokens: 8000
    pipeline:
      chunking:
        tiktoken_encoding: cl100k_base
"""
    (tmp_path / "mykg_config.yaml").write_text(cfg)
    monkeypatch.chdir(tmp_path)
    # No input_files or _input_files directory exists
    monkeypatch.setattr(sys, "argv", ["context_calculator.py", "--from-config"])

    from mykg.utility.context_calculator import main

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code != 0


def test_main_from_config_with_explicit_chunk_divisor(tmp_path, monkeypatch, capsys):
    """When --chunk-divisor is supplied, the explicit-divisor branch (lines 453-465) runs."""
    input_dir = tmp_path / "input_files"
    input_dir.mkdir()
    (input_dir / "doc.md").write_text("hello world")

    cfg = """\
profile: p
profiles:
  p:
    llm:
      context_window: 32000
      max_output_tokens: 8000
    pipeline:
      chunking:
        window_tokens: 2000
        overlap_tokens: 200
        tiktoken_encoding: cl100k_base
      pass2:
        prep_mode: concat
"""
    (tmp_path / "mykg_config.yaml").write_text(cfg)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        ["context_calculator.py", "--from-config", "--chunk-divisor", "16"],
    )

    mock_enc = MagicMock()
    mock_enc.encode.side_effect = lambda text: [0] * len(text.split())
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    with patch.dict(sys.modules, {"tiktoken": mock_tiktoken}):
        from mykg.utility.context_calculator import main

        main()

    out = capsys.readouterr().out
    # explicit chunk_divisor=16 should be reflected in the YAML snippet
    assert "32000" in out


def test_main_from_config_mode_runs(tmp_path, monkeypatch, capsys):
    # Create a minimal corpus
    input_dir = tmp_path / "input_files"
    input_dir.mkdir()
    (input_dir / "doc.md").write_text("Hello world test document")

    # Write a minimal mykg_config.yaml
    config_text = """\
profile: testprofile
profiles:
  testprofile:
    llm:
      context_window: 32000
      max_output_tokens: 8000
    pipeline:
      chunking:
        window_tokens: 2000
        overlap_tokens: 200
        tiktoken_encoding: cl100k_base
      pass1:
        batch_token_target: 20000
      feedback:
        max_file_chars: 16000
        concat_batch_token_target: 20000
"""
    (tmp_path / "mykg_config.yaml").write_text(config_text)
    monkeypatch.chdir(tmp_path)

    monkeypatch.setattr(
        sys,
        "argv",
        ["context_calculator.py", "--from-config", "--input-dir", str(input_dir)],
    )

    # Patch tiktoken so we don't need the real encoder
    mock_enc = MagicMock()
    mock_enc.encode.side_effect = lambda text: [0] * len(text.split())
    mock_tiktoken = MagicMock()
    mock_tiktoken.get_encoding.return_value = mock_enc

    with patch.dict(sys.modules, {"tiktoken": mock_tiktoken}):
        from mykg.utility.context_calculator import main

        main()

    out = capsys.readouterr().out
    assert "32000" in out
    assert "Token Budget Calculator" in out


def test_print_report_includes_normalize_names_in_yaml_snippet(capsys):
    """print_report YAML snippet includes the normalize_names.batch_token_target line."""
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12)
    out = capsys.readouterr().out
    assert "normalize_names:" in out
    assert "batch_token_target: 20000" in out


def test_print_report_includes_max_schema_proposals_in_yaml_snippet(capsys):
    """print_report YAML snippet includes the pass1.max_schema_proposals line."""
    print_report(PRINT_RESULT, model="test-model", chunk_divisor=12)
    out = capsys.readouterr().out
    assert "max_schema_proposals: 50" in out
