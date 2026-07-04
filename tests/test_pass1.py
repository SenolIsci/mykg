import json
import threading
from unittest.mock import MagicMock

from mykg.chunker import Chunk
from mykg.llm.adapter import LLMAdapter
from mykg.orchestrator import PipelineContext
from mykg.pass1 import PASS1_SYSTEM_PROMPT, run_pass1
from mykg.schema_merge import review_schema_quality
from mykg.steps.step_pass1 import run_pass1_step

VALID_PROPOSAL = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name", "email"]},
        ],
        "properties": [
            {
                "name": "works_at",
                "domain": "Person",
                "range": "Organization",
                "attributes": ["role"],
            }
        ],
    }
)

INVALID_JSON = "not json {"


class MockAdapter(LLMAdapter):
    def __init__(self, response: str):
        self._response = response

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        return self._response

    def endpoint_label(self) -> str:
        return "mock"


class SequenceAdapter(LLMAdapter):
    """Returns responses from a list in order; records each (system, user) call.

    Thread-safe: index advancement and call recording are protected by a lock.
    """

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self._index = 0
        self.calls: list[tuple[str, str]] = []
        self._lock = threading.Lock()

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
    ) -> str:
        with self._lock:
            self.calls.append((system, user))
            response = self._responses[self._index]
            self._index = min(self._index + 1, len(self._responses) - 1)
        return response

    def endpoint_label(self) -> str:
        return "sequence"


CHUNKS = [
    Chunk(
        source_file="a.md", chunk_index=0, text="Alice works at Acme.", token_start=0, token_end=10
    ),
    Chunk(
        source_file="a.md", chunk_index=1, text="Bob is a manager.", token_start=10, token_end=20
    ),
]


def test_run_pass1_returns_proposals():
    adapter = MockAdapter(VALID_PROPOSAL)
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert len(proposals) >= 1
    assert "concepts" in proposals[0]
    assert "properties" in proposals[0]


def test_run_pass1_skips_invalid_json():
    adapter = MockAdapter(INVALID_JSON)
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert proposals == []


def test_pass1_system_prompt_contains_key_rules():
    assert "concepts" in PASS1_SYSTEM_PROMPT
    assert "properties" in PASS1_SYSTEM_PROMPT
    assert "Relationship" in PASS1_SYSTEM_PROMPT


def test_run_pass1_with_locked_schema_block():
    adapter = MockAdapter(VALID_PROPOSAL)
    block = "EXISTING SCHEMA: Classes: Vehicle"
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block=block)
    assert len(proposals) >= 1


# ---------------------------------------------------------------------------
# JSON parse retry tests
# ---------------------------------------------------------------------------


def test_run_pass1_retries_on_json_error():
    """First call returns invalid JSON; second (retry) returns valid JSON → proposal included."""
    adapter = SequenceAdapter([INVALID_JSON, VALID_PROPOSAL])
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert len(proposals) == 1
    assert "concepts" in proposals[0]
    assert "properties" in proposals[0]


def test_run_pass1_skips_after_double_json_failure():
    """Both the initial call and the retry return invalid JSON → no proposals returned."""
    adapter = SequenceAdapter([INVALID_JSON, INVALID_JSON])
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert proposals == []


def test_run_pass1_json_retry_uses_correct_context_label():
    """Retry call includes 'json-retry' in its user text (which is the distinguishing prefix)."""
    adapter = SequenceAdapter([INVALID_JSON, VALID_PROPOSAL])
    run_pass1(CHUNKS, adapter, locked_schema_block="")
    # Two calls must have been made: original + retry
    assert len(adapter.calls) == 2
    _system_retry, user_retry = adapter.calls[1]
    assert user_retry.startswith(
        "Your previous response was not valid JSON. "
        "Return only a JSON object with 'concepts' and 'properties' keys."
    )


# ---------------------------------------------------------------------------
# Parallel dispatch tests (Invariant 12 / to-do #117)
# ---------------------------------------------------------------------------

# Build chunks large enough to force two separate batches (each ~100K tokens,
# batch_token_target defaults to 192K → two batches).
_BIG_CHUNKS = [
    Chunk(
        source_file="a.md",
        chunk_index=0,
        text="Alice works at Acme.",
        token_start=0,
        token_end=100_000,
    ),
    Chunk(
        source_file="a.md",
        chunk_index=1,
        text="Bob is a manager.",
        token_start=100_000,
        token_end=200_000,
    ),
]

PROPOSAL_A = json.dumps(
    {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
)

PROPOSAL_B = json.dumps(
    {
        "concepts": [{"type": "Organization", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
)


def test_run_pass1_parallel_collects_all_proposals():
    """All batches are processed in parallel and every valid proposal is returned."""
    adapter = MockAdapter(VALID_PROPOSAL)
    proposals = run_pass1(_BIG_CHUNKS, adapter, locked_schema_block="")
    assert len(proposals) == 2
    for p in proposals:
        assert "concepts" in p
        assert "properties" in p


def test_run_pass1_parallel_skips_failed_batch():
    """A batch that produces invalid JSON is skipped; other batches are still returned."""

    class ContentAdapter(LLMAdapter):
        """Returns invalid JSON for the Alice batch, valid JSON for the Bob batch."""

        def complete(
            self,
            system: str,
            user: str,
            context_label: str = "",
            max_tokens: int | None = None,
            timeout: int | None = None,
        ) -> str:
            if "Alice" in user:
                return INVALID_JSON
            return VALID_PROPOSAL

        def endpoint_label(self) -> str:
            return "content"

    proposals = run_pass1(_BIG_CHUNKS, ContentAdapter(), locked_schema_block="")
    # Both the initial call and the retry for batch 1 return invalid JSON → 1 proposal.
    assert len(proposals) == 1
    assert "concepts" in proposals[0]


def test_run_pass1_proposal_order_deterministic():
    """Proposals are sorted by batch index regardless of thread completion order."""

    class IndexedAdapter(LLMAdapter):
        """Returns PROPOSAL_A for the Alice batch, PROPOSAL_B for the Bob batch."""

        def complete(
            self,
            system: str,
            user: str,
            context_label: str = "",
            max_tokens: int | None = None,
            timeout: int | None = None,
        ) -> str:
            return PROPOSAL_A if "Alice" in user else PROPOSAL_B

        def endpoint_label(self) -> str:
            return "indexed"

    proposals = run_pass1(_BIG_CHUNKS, IndexedAdapter(), locked_schema_block="")
    assert len(proposals) == 2
    # Batch 1 (Alice) → Person; batch 2 (Bob) → Organization
    assert proposals[0]["concepts"][0]["type"] == "Person"
    assert proposals[1]["concepts"][0]["type"] == "Organization"


def test_run_pass1_samples_batches_when_over_cap(monkeypatch):
    """When batches exceed max_schema_proposals, only cap-many are dispatched."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS1_MAX_SCHEMA_PROPOSALS", 1)
    # _BIG_CHUNKS produces 2 batches; cap=1 → only 1 LLM call → 1 proposal
    proposals = run_pass1(_BIG_CHUNKS, MockAdapter(VALID_PROPOSAL), locked_schema_block="")
    assert len(proposals) == 1


def test_run_pass1_no_sample_when_minus_one(monkeypatch):
    """When cap is -1, all batches are dispatched regardless of count."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS1_MAX_SCHEMA_PROPOSALS", -1)
    # _BIG_CHUNKS produces 2 batches; cap=-1 → both dispatched → 2 proposals
    proposals = run_pass1(_BIG_CHUNKS, MockAdapter(VALID_PROPOSAL), locked_schema_block="")
    assert len(proposals) == 2


# ---------------------------------------------------------------------------
# Batch selection persistence + incremental proposal shards + resume
# ---------------------------------------------------------------------------


def test_run_pass1_same_seed_reproducible_across_calls(monkeypatch):
    """Two separate run_pass1() calls with the same seed produce the same
    sampled batch selection — regression test for the module-level shared-RNG
    bug where a second call in the same process (e.g.
    --append-with-grow-schema) silently produced a different sample despite
    the same seed."""
    import mykg.config as cfg

    monkeypatch.setattr(cfg, "PASS1_MAX_SCHEMA_PROPOSALS", 1)
    proposals1 = run_pass1(_BIG_CHUNKS, MockAdapter(VALID_PROPOSAL), locked_schema_block="")
    proposals2 = run_pass1(_BIG_CHUNKS, MockAdapter(VALID_PROPOSAL), locked_schema_block="")
    assert proposals1 == proposals2


def test_run_pass1_writes_batch_selection_before_dispatch(tmp_path):
    """pass1_batch_selection.json is written with correct seed/indices before
    any LLM call — this is the reproducibility audit record."""
    import mykg.config as cfg

    seen_before_dispatch = {}

    class RecordingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            selection_path = tmp_path / "pass1_batch_selection.json"
            seen_before_dispatch["exists"] = selection_path.exists()
            return VALID_PROPOSAL

        def endpoint_label(self):
            return "recording"

    run_pass1(
        CHUNKS, RecordingAdapter(), locked_schema_block="", intermediate_dir=tmp_path
    )
    assert seen_before_dispatch["exists"] is True

    selection = json.loads((tmp_path / "pass1_batch_selection.json").read_text())
    assert selection["seed"] == cfg.PASS1_RANDOM_SEED
    assert selection["total_batches"] == 1
    assert selection["sampled_batch_count"] == 1
    assert selection["selected_batch_indices"] == [1]
    assert selection["batches"][0]["chunk_count"] == len(CHUNKS)
    assert selection["batches"][0]["source_files"] == ["a.md"]


def test_run_pass1_on_batch_done_fires_per_batch():
    """on_batch_done fires once per batch: status 'ok' for a valid proposal,
    'failed' (with an error message, no proposal) for one that never parses."""
    calls = []

    def on_batch_done(idx, proposal, error):
        calls.append((idx, proposal, error))

    proposals = run_pass1(
        _BIG_CHUNKS,
        SequenceAdapter([VALID_PROPOSAL, INVALID_JSON, INVALID_JSON]),
        locked_schema_block="",
        on_batch_done=on_batch_done,
    )
    assert len(proposals) == 1
    assert len(calls) == 2
    ok_calls = [c for c in calls if c[1] is not None]
    failed_calls = [c for c in calls if c[1] is None]
    assert len(ok_calls) == 1
    assert len(failed_calls) == 1
    assert failed_calls[0][2] is not None  # error message present


def test_run_pass1_resumes_from_matching_shards(tmp_path):
    """A second run_pass1() call over the IDENTICAL chunk set only
    dispatches LLM calls for batches whose shard is missing — batches whose
    shard already exists (and whose composition matches the recorded
    selection) are skipped."""
    call_count = {"n": 0}

    class CountingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            call_count["n"] += 1
            return VALID_PROPOSAL

        def endpoint_label(self):
            return "counting"

    def on_batch_done(idx, proposal, error):
        shard_dir = tmp_path / "pass1_batch_proposals"
        shard_dir.mkdir(exist_ok=True)
        entry = {"batch_index": idx, "status": "ok", "proposal": proposal}
        (shard_dir / f"{idx:04d}.json").write_text(json.dumps(entry))

    adapter = CountingAdapter()
    run_pass1(
        _BIG_CHUNKS,
        adapter,
        locked_schema_block="",
        intermediate_dir=tmp_path,
        on_batch_done=on_batch_done,
    )
    first_call_count = call_count["n"]
    assert first_call_count == 2  # _BIG_CHUNKS produces 2 batches

    # Second call, SAME chunks, same intermediate_dir — both batches should
    # already have a matching shard, so zero new LLM calls are made.
    call_count["n"] = 0
    proposals = run_pass1(
        _BIG_CHUNKS,
        adapter,
        locked_schema_block="",
        intermediate_dir=tmp_path,
        on_batch_done=on_batch_done,
    )
    assert call_count["n"] == 0
    assert len(proposals) == 2


def test_run_pass1_does_not_resume_when_chunks_differ(tmp_path):
    """A second run_pass1() call over a DIFFERENT chunk set (same
    intermediate_dir) must NOT reuse shards from the first call — this is
    the exact --append-with-grow-schema scenario (a second, locked Pass 1
    call over only the changed files) that the naive index-only resume
    check regressed."""
    call_count = {"n": 0}

    class CountingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            call_count["n"] += 1
            return VALID_PROPOSAL

        def endpoint_label(self):
            return "counting"

    def on_batch_done(idx, proposal, error):
        shard_dir = tmp_path / "pass1_batch_proposals"
        shard_dir.mkdir(exist_ok=True)
        entry = {"batch_index": idx, "status": "ok", "proposal": proposal}
        (shard_dir / f"{idx:04d}.json").write_text(json.dumps(entry))

    adapter = CountingAdapter()
    run_pass1(
        CHUNKS,
        adapter,
        locked_schema_block="",
        intermediate_dir=tmp_path,
        on_batch_done=on_batch_done,
    )
    assert call_count["n"] == 1  # CHUNKS produces 1 batch

    # Second call over a DIFFERENT single-chunk set — same intermediate_dir,
    # same batch index (1), but different content. Must be re-dispatched,
    # not silently reused from the first call's stale shard.
    different_chunks = [
        Chunk(
            source_file="different.md",
            chunk_index=0,
            text="Completely different content.",
            token_start=0,
            token_end=10,
        ),
    ]
    call_count["n"] = 0
    run_pass1(
        different_chunks,
        adapter,
        locked_schema_block="",
        intermediate_dir=tmp_path,
        on_batch_done=on_batch_done,
    )
    assert call_count["n"] == 1


def test_run_pass1_ignores_corrupted_selection_file(tmp_path):
    """A corrupted pass1_batch_selection.json is treated as if no prior
    selection exists — every batch is re-dispatched rather than crashing."""
    (tmp_path / "pass1_batch_selection.json").write_text("not valid json {")

    call_count = {"n": 0}

    class CountingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            call_count["n"] += 1
            return VALID_PROPOSAL

        def endpoint_label(self):
            return "counting"

    proposals = run_pass1(
        CHUNKS, CountingAdapter(), locked_schema_block="", intermediate_dir=tmp_path
    )
    assert call_count["n"] == 1
    assert len(proposals) == 1


def test_run_pass1_ignores_selection_with_different_batch_count(tmp_path):
    """A prior selection recording a different total batch count never
    matches — every batch is re-dispatched."""
    (tmp_path / "pass1_batch_selection.json").write_text(
        json.dumps(
            {
                "seed": 0,
                "total_batches": 5,
                "sampled_batch_count": 5,
                "selected_batch_indices": [1, 2, 3, 4, 5],
                "batches": [
                    {"index": i, "chunk_count": 1, "source_files": ["x.md"], "total_tokens": 10}
                    for i in range(1, 6)
                ],
            }
        )
    )
    call_count = {"n": 0}

    class CountingAdapter(LLMAdapter):
        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            call_count["n"] += 1
            return VALID_PROPOSAL

        def endpoint_label(self):
            return "counting"

    proposals = run_pass1(
        CHUNKS, CountingAdapter(), locked_schema_block="", intermediate_dir=tmp_path
    )
    assert call_count["n"] == 1
    assert len(proposals) == 1


def test_merge_proposals_from_step_reuses_shards_without_llm_dispatch(tmp_path):
    """--from-step merge_proposals: step_pass1_step with ctx.pass1_merge_only
    skips Pass 1 LLM dispatch entirely and reconstructs proposals from
    pass1_batch_proposals/ shards."""
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_pass1 import run_pass1_step

    shard_dir = tmp_path / "pass1_batch_proposals"
    shard_dir.mkdir(parents=True)
    (shard_dir / "0001.json").write_text(
        json.dumps({"batch_index": 1, "status": "ok", "proposal": json.loads(VALID_PROPOSAL)})
    )
    (shard_dir / "0002.json").write_text(
        json.dumps({"batch_index": 2, "status": "failed", "error": "simulated failure"})
    )

    class ExplodingAdapter(LLMAdapter):
        """Any LLM call is a bug in this test — merge_proposals mode must
        never dispatch Pass 1 batches."""

        def complete(self, system, user, context_label="", max_tokens=None, timeout=None):
            if "rdfs ontology expert" in system.lower() and "extract a schema" in system.lower():
                raise AssertionError("Pass 1 LLM dispatch must be skipped in merge_proposals mode")
            return "not json {"  # harmonize/quality-review fall back to unchanged schema

        def endpoint_label(self):
            return "exploding"

    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=ExplodingAdapter(),
        pass1_merge_only=True,
    )
    run_pass1_step(ctx)

    schema = json.loads((tmp_path / "schema.json").read_text())
    types = {c["type"] for c in schema["concepts"]}
    assert "Person" in types


def test_merge_proposals_from_step_propagates_locked_block(tmp_path):
    """--from-step merge_proposals with a locked base_schema must build the
    locked_block and pass it to the harmonize/quality-review cleanup prompts
    — this is the pass1_merge_only-specific code path that builds locked_block
    independently from the normal Pass 1 dispatch path."""
    from mykg.orchestrator import PipelineContext
    from mykg.schema_merge import _HARMONIZE_SYSTEM_PROMPT, _QUALITY_SYSTEM_PROMPT
    from mykg.steps.step_pass1 import run_pass1_step

    shard_dir = tmp_path / "pass1_batch_proposals"
    shard_dir.mkdir(parents=True)
    (shard_dir / "0001.json").write_text(
        json.dumps({"batch_index": 1, "status": "ok", "proposal": json.loads(VALID_PROPOSAL)})
    )

    response = "not json {"  # harmonize/quality-review fall back to unchanged schema
    adapter = SequenceAdapter([response, response])
    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=adapter,
        pass1_merge_only=True,
        base_schema={
            "locked_classes": {
                "Vehicle": {"type": "Vehicle", "parent": None, "attributes": ["name"]}
            },
            "locked_properties": {
                "owns": {"name": "owns", "domain": "Person", "range": "Vehicle", "attributes": []}
            },
        },
    )
    run_pass1_step(ctx)

    harmonize_systems = [s for s, _ in adapter.calls if s.startswith(_HARMONIZE_SYSTEM_PROMPT)]
    quality_systems = [s for s, _ in adapter.calls if s.startswith(_QUALITY_SYSTEM_PROMPT)]
    assert harmonize_systems and quality_systems
    for system in harmonize_systems + quality_systems:
        assert "Vehicle" in system
        assert "owns" in system
        assert "DO NOT RENAME, REMOVE, OR DUPLICATE" in system


def test_merge_proposals_from_step_errors_when_no_shards(tmp_path):
    """--from-step merge_proposals with no pass1_batch_proposals/ on disk
    raises a clear error rather than silently producing an empty schema."""
    import click
    import pytest

    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_pass1 import run_pass1_step

    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=MockAdapter(VALID_PROPOSAL),
        pass1_merge_only=True,
    )
    with pytest.raises(click.ClickException, match="pass1_batch_proposals"):
        run_pass1_step(ctx)


def test_merge_proposals_from_step_errors_when_all_batches_failed(tmp_path):
    """--from-step merge_proposals with a pass1_batch_proposals/ directory
    that exists but holds only "failed" shards (no successful proposal to
    merge) raises a clear error rather than silently producing an empty
    schema."""
    import click
    import pytest

    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_pass1 import run_pass1_step

    shard_dir = tmp_path / "pass1_batch_proposals"
    shard_dir.mkdir()
    (shard_dir / "0001.json").write_text(
        json.dumps({"batch_index": 1, "status": "failed", "error": "simulated failure"})
    )

    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=MockAdapter(VALID_PROPOSAL),
        pass1_merge_only=True,
    )
    with pytest.raises(click.ClickException, match="no successful batch proposals"):
        run_pass1_step(ctx)


def test_merge_proposals_from_step_skips_corrupted_shard(tmp_path):
    """A corrupted (non-JSON) shard file is skipped rather than crashing the
    whole merge_proposals reconstruction — the remaining valid shards are
    still used."""
    from mykg.orchestrator import PipelineContext
    from mykg.steps.step_pass1 import run_pass1_step

    shard_dir = tmp_path / "pass1_batch_proposals"
    shard_dir.mkdir()
    (shard_dir / "0001.json").write_text(
        json.dumps({"batch_index": 1, "status": "ok", "proposal": json.loads(VALID_PROPOSAL)})
    )
    (shard_dir / "0002.json").write_text("not valid json {")

    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=MockAdapter("not json {"),  # harmonize/quality-review fall back unchanged
        pass1_merge_only=True,
    )
    run_pass1_step(ctx)

    schema = json.loads((tmp_path / "schema.json").read_text())
    types = {c["type"] for c in schema["concepts"]}
    assert "Person" in types


# ---------------------------------------------------------------------------
# review_schema_quality tests
# ---------------------------------------------------------------------------

_BARE_SCHEMA = {
    "concepts": [
        {"type": "Location", "parent": None, "attributes": []},
        {"type": "Person", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {"name": "located_at", "domain": "Organization", "range": "Location", "attributes": []},
    ],
}

_IMPROVED_SCHEMA = {
    "concepts": [
        {"type": "Location", "parent": None, "attributes": ["name", "country", "region"]},
        {"type": "Person", "parent": None, "attributes": ["name"]},
    ],
    "properties": [
        {
            "name": "located_at",
            "domain": "Organization",
            "range": "Location",
            "attributes": ["base_type"],
        },
    ],
}


def test_review_schema_quality_returns_improved_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_IMPROVED_SCHEMA)
    result = review_schema_quality(_BARE_SCHEMA, adapter)
    assert result["concepts"][0]["attributes"] == ["name", "country", "region"]


def test_review_schema_quality_calls_llm_once():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_IMPROVED_SCHEMA)
    review_schema_quality(_BARE_SCHEMA, adapter)
    assert adapter.complete.call_count == 1


def test_review_schema_quality_prompt_contains_schema():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(_IMPROVED_SCHEMA)
    review_schema_quality(_BARE_SCHEMA, adapter)
    user_prompt = adapter.complete.call_args[0][1]
    assert "Location" in user_prompt and "located_at" in user_prompt


def test_review_schema_quality_falls_back_on_invalid_json():
    adapter = MagicMock()
    adapter.complete.return_value = "not json {"
    result = review_schema_quality(_BARE_SCHEMA, adapter)
    assert result == _BARE_SCHEMA


def test_review_schema_quality_falls_back_on_wrong_structure():
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps({"concepts": []})  # missing "properties"
    result = review_schema_quality(_BARE_SCHEMA, adapter)
    assert result == _BARE_SCHEMA


def test_pass1_system_prompt_forbids_bare_concepts():
    assert "empty attributes" in PASS1_SYSTEM_PROMPT or "at least" in PASS1_SYSTEM_PROMPT


def _make_step_ctx(tmp_path, adapter):
    ctx = PipelineContext(
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        intermediate_dir=tmp_path / "intermediate",
        adapter=adapter,
        base_schema=None,
        thesaurus=None,
        review=False,
    )
    ctx.intermediate_dir.mkdir(parents=True, exist_ok=True)
    ctx.output_dir.mkdir(parents=True, exist_ok=True)
    ctx.all_chunks = CHUNKS
    ctx.error_gate = None
    return ctx


def test_run_pass1_step_applies_quality_review(tmp_path):
    pass1_response = json.dumps(
        {
            "concepts": [{"type": "Location", "parent": None, "attributes": []}],
            "properties": [],
        }
    )
    quality_response = json.dumps(
        {
            "concepts": [{"type": "Location", "parent": None, "attributes": ["name", "country"]}],
            "properties": [],
        }
    )
    adapter = SequenceAdapter([pass1_response, quality_response])
    ctx = _make_step_ctx(tmp_path, adapter)
    run_pass1_step(ctx)
    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    assert schema["concepts"][0]["attributes"] == ["name", "country"]
    history_dir = ctx.intermediate_dir / "schema_history"
    triggers = [json.loads(f.read_text())["trigger"] for f in sorted(history_dir.glob("*.json"))]
    assert "pass1_merge" in triggers
    assert "schema_quality" in triggers


def test_run_pass1_step_propagates_locked_block_to_cleanup_prompts(tmp_path):
    """End-to-end wiring: with a base schema, run_pass1_step must inject the locked
    block into BOTH cleanup-pass system prompts (harmonize + quality review), not just
    the Pass 1 extraction prompt. Guards against someone dropping the locked_block
    argument from either call site — which the per-function unit tests cannot catch.
    """
    response = json.dumps(
        {
            "concepts": [{"type": "Vehicle", "parent": None, "attributes": ["name"]}],
            "properties": [],
        }
    )
    # SequenceAdapter records every (system, user) call: pass1 batch(es), then
    # harmonize, then quality review. With one batch that is 3 calls.
    adapter = SequenceAdapter([response, response, response])
    ctx = _make_step_ctx(tmp_path, adapter)
    ctx.base_schema = {
        "locked_classes": {"Vehicle": {"type": "Vehicle", "parent": None, "attributes": ["name"]}},
        "locked_properties": {
            "owns": {"name": "owns", "domain": "Person", "range": "Vehicle", "attributes": []}
        },
    }
    run_pass1_step(ctx)

    # The locked block lists the locked class/property names; assert both reach the
    # harmonize and quality system prompts. Identify each pass by its base prompt.
    from mykg.schema_merge import _HARMONIZE_SYSTEM_PROMPT, _QUALITY_SYSTEM_PROMPT

    harmonize_systems = [s for s, _ in adapter.calls if s.startswith(_HARMONIZE_SYSTEM_PROMPT)]
    quality_systems = [s for s, _ in adapter.calls if s.startswith(_QUALITY_SYSTEM_PROMPT)]
    assert harmonize_systems, "harmonize_schema was never called"
    assert quality_systems, "review_schema_quality was never called"
    for system in harmonize_systems + quality_systems:
        assert "Vehicle" in system, "locked class name missing from cleanup prompt"
        assert "owns" in system, "locked property name missing from cleanup prompt"
        assert "DO NOT RENAME, REMOVE, OR DUPLICATE" in system


# ---------------------------------------------------------------------------
# Unit 3 — --append-with-grow-schema scopes locked Pass 1 to changed files only (D52)
# ---------------------------------------------------------------------------


def test_grow_schema_pass1_uses_only_changed_files(tmp_path):
    """With grow_schema + append_new_files, locked Pass 1 must chunk ONLY the changed
    files from the manifest, never the unchanged old files."""
    response = json.dumps(
        {
            "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
            "properties": [],
        }
    )
    adapter = SequenceAdapter([response, response, response])
    ctx = _make_step_ctx(tmp_path, adapter)
    ctx.all_chunks = None  # append ingest does not chunk
    ctx.grow_schema = True
    ctx.append = True
    ctx.append_new_files = {"new.md"}

    manifest = {
        "old.md": {"content": "OLDFILEMARKER content about Acme.", "sha256": "x"},
        "new.md": {"content": "NEWFILEMARKER content about Bob.", "sha256": "y"},
    }
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest))

    run_pass1_step(ctx)

    all_user_text = "\n".join(user for _, user in adapter.calls)
    assert "NEWFILEMARKER" in all_user_text, "changed file content must reach Pass 1"
    assert "OLDFILEMARKER" not in all_user_text, "unchanged file must NOT reach locked Pass 1"


def test_grow_schema_pass1_ignores_changed_files_absent_from_manifest(tmp_path):
    """A changed-file name not present in the manifest is skipped (no crash)."""
    response = json.dumps(
        {"concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}], "properties": []}
    )
    adapter = SequenceAdapter([response, response, response])
    ctx = _make_step_ctx(tmp_path, adapter)
    ctx.all_chunks = None
    ctx.grow_schema = True
    ctx.append = True
    ctx.append_new_files = {"new.md", "ghost.md"}
    manifest = {"new.md": {"content": "NEWFILEMARKER text.", "sha256": "y"}}
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps(manifest))

    run_pass1_step(ctx)  # must not raise
    schema = json.loads((ctx.intermediate_dir / "schema.json").read_text())
    assert any(c["type"] == "Person" for c in schema["concepts"])


# ---------------------------------------------------------------------------
# List-type guard tests
# ---------------------------------------------------------------------------


def test_batch_skipped_when_concepts_not_list():
    """Batch where 'concepts' is null (not a list) is silently skipped → no valid proposals."""
    adapter = MockAdapter(json.dumps({"concepts": None, "properties": []}))
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert proposals == []


def test_batch_skipped_when_properties_not_list():
    """Batch where 'properties' is a dict (not a list) is silently skipped → no valid proposals."""
    adapter = MockAdapter(json.dumps({"concepts": [], "properties": {}}))
    proposals = run_pass1(CHUNKS, adapter, locked_schema_block="")
    assert proposals == []
