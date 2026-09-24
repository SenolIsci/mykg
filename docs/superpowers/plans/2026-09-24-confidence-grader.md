# Confidence Grader (TypeSafe AI / Jev) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an independent confidence-grading pass to the mykg pipeline that re-scores every Pass 2 extracted attribute value against its source chunk text using TypeSafe AI's Jev model, replacing the extractor's self-reported confidence before the graph is assembled.

**Architecture:** A new opt-in `grader:` config block selects the TypeSafe backend; a small `TypeSafeGrader` class (not an `LLMAdapter`) wraps `typesafe_sdk.TypeSafeClient` and issues one `Noul` question per extracted attribute (plus one per entity for overall confidence), batched into one `system_one` call per chunk. A new pipeline step `grade_confidence` runs between `pass2` and `normalize_names`, mirrors Pass 2's per-file shard/resume machinery, and writes `intermediate/confidence_grades.json`. `step_assemble` overwrites self-reported confidence with graded values immediately after loading raw extractions, before any dedup logic runs.

**Primitive choice confirmed:** `Score` (TypeSafe's ordered N-tier rubric primitive, e.g. `criteria = ["not supported", "weakly supported", ...]`) was reconsidered against `Noul` per a direct request for "a score between 0 and 1, whatever is suitable." `Score.score` is the winning tier's *index* (not a 0–1 value) and its own `.confidence` field is a distribution-spread statistic unrelated to correctness — using it would require designing a tier rubric and manually deriving `score / (len(criteria)-1)` to reach 0–1. `Noul.noul` returns a 0–1 probability directly, with no rubric to design and no derivation step, so it remains the chosen primitive throughout this plan.

**Tech Stack:** Python 3.11+, `typesafe-sdk` (new dependency, Python ≥3.10 — compatible), Pydantic `BaseModel` for config/context fields, `ThreadPoolExecutor` for per-file parallelism (Invariant 12), `pytest` + `monkeypatch` for tests (no live API calls in unit tests).

**Spec:** `docs/superpowers/specs/2026-09-24-confidence-grader-design.md` — the plan argues from this spec; read both. In particular read the spec's "Grader backend: TypeSafe AI (Jev)" section (`Noul` primitive selection, adapter shape, exception hierarchy) before Task 1.

## Global Constraints

- `enabled: false` is the shipped default for `grader:` in every profile of both `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml` — grading must be fully opt-in; the pipeline's existing self-reported-confidence behavior is unchanged unless a user turns it on (spec "Config block, revised").
- `typesafe-sdk` is an **optional** dependency, imported lazily only inside grader code paths — must not be imported at module load time anywhere reachable when `grader.enabled` is false, so users who never enable grading never need it installed (spec "Adapter shape" bullet 5).
- `TypeSafeGrader` is **not** a subclass of `LLMAdapter` and is **not** registered in `llm/config.py:load_adapter()`'s provider dispatch (spec "Adapter shape").
- Every attribute's self-reported confidence must be preserved as `attr["self_reported_confidence"]`, never dropped, when a grade overwrites `attr["confidence"]` (spec "Consumption at assemble time" — mirrors D9's "never silently drop" pattern).
- No changes to `assembler.py`'s dedup/aggregation logic — it must keep reading whatever sits in `confidence` fields unmodified (spec "Consumption at assemble time").
- Config keys read via `config.py`'s `_get()`/`_get_opt()` come from the `pipeline:` YAML block; the `grader:` block is a **profile-level sibling of `llm:`**, read from `RAW` directly (matching how `load_adapter()` reads `RAW["llm"]`) — NOT wired through `config.py`'s pipeline-only constant mechanism. `_apply_profile()` in `src/mykg/config.py` promotes only an explicit allowlist of profile keys (`provider`, `pipeline`, `llm`, `llm_retry`, `agent`, `mcp`) — `grader` must be added to that allowlist or it is silently dropped for every profile (verified in Task 1).
- Any new key added under `preprocess:`, `pipeline:`, or any other YAML block must be added to **both** `mykg_config.yaml` and `src/mykg/data/mykg_config.yaml` (Invariant 17) — the `grader:` block, being a sibling of `llm:` rather than under `pipeline:`, is technically outside Invariant 17's literal wording, but this plan applies the same both-files discipline to it for consistency (one shipped block should not differ between the runtime and packaging copies).
- All file I/O uses `encoding="utf-8"` explicitly and `json.dumps(..., ensure_ascii=False)` where content may be non-ASCII (Invariant 20).
- `grade_confidence` participates in the existing per-file `ThreadPoolExecutor` parallelism convention (Invariant 12) — no serial loop over files/chunks.

## Review Focus

- **`grader.enabled: false` (the default) must be a true no-op.** A user who never touches `grader:` config should see byte-identical pipeline output to before this feature existed — no new files with unexpected content, no attempted `typesafe_sdk` import, no behavior change in `step_assemble`. Task 4's tests pin this explicitly.
- **Missing `TYPESAFE_API_KEY` with `grader.enabled: true` must fail fast with a clear message**, not a bare `KeyError`/`AttributeError` deep in the SDK — mirrors `openai_adapter.py`'s `ValueError` pattern. Covered in Task 3.
- **A chunk whose grader call raises must not abort the pipeline or lose other chunks' grades.** `run_grade_confidence` must catch grading failures per-chunk (the spec's "graceful degradation" contract) the same breadth `run_pass2._process_file`'s `except Exception` already uses — one bad chunk must not prevent `confidence_grades.json` from being written with every other chunk's grades intact. Covered in Task 4.
- **An entity/attribute with no grade entry must fall through to its self-reported confidence unchanged**, not `None`/`0.0`/a KeyError — this is the graceful-degradation contract at the consumption boundary (Task 8), and it's the one path most likely to silently corrupt confidence values if `_apply_grades` assumes every attribute was graded.
- **Re-running `--from-step pass2` (or earlier) after grading has already happened must not leave stale grades for content that gets re-extracted differently.** This is easy to get wrong because `grade_confidence` sits *after* pass2 in step order, so the existing `idx <= pass2_idx` shard-clearing condition in `cli.py` is the wrong boundary — a separate `idx <= grade_confidence_idx` condition is needed (a superset of the pass2 one). Covered in Task 7.

---

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Declare `typesafe-sdk` as an optional dependency group |
| `mykg_config.yaml` | Modify | Add `grader:` block to every profile |
| `src/mykg/data/mykg_config.yaml` | Modify | Same, packaging copy (Invariant 17 discipline) |
| `src/mykg/config.py` | Modify | Add `"grader"` to `_apply_profile()`'s promoted-keys allowlist |
| `src/mykg/llm/typesafe_grader.py` | Create | `TypeSafeGrader` class — wraps `typesafe_sdk.TypeSafeClient`, builds `Noul` questions, returns flat confidence map |
| `tests/test_typesafe_grader.py` | Create | Unit tests for `TypeSafeGrader` against a mocked SDK client |
| `src/mykg/steps/step_grade_confidence.py` | Create | `run_grade_confidence` pipeline step — per-file/per-chunk orchestration, shard read/write, `.done` sentinel |
| `tests/test_step_grade_confidence.py` | Create | Unit tests for the step against a mocked `TypeSafeGrader` |
| `src/mykg/pipeline.py` | Modify | Register `grade_confidence` Step between `pass2` and `normalize_names` |
| `src/mykg/orchestrator.py` | Modify | Add `grader: Any = None` field to `PipelineContext`; add `"grade_confidence"` to `_SCHEMA_RESTART_INVALIDATE` and `_APPEND_INVALIDATE` |
| `src/mykg/cli.py` | Modify | Construct `ctx.grader` alongside `ctx.adapter`; extend `_delete_from_step`'s shard-clearing block to cover `grade_confidence` |
| `src/mykg/steps/step_assemble.py` | Modify | Load `confidence_grades.json` and apply grades before `assign_stable_ids` |
| `tests/test_assembler.py` or new `tests/test_step_assemble_grading.py` | Modify/Create | Tests for the grade-application hook |
| `CLAUDE.md` | Modify | D16 table: two new rows for `confidence_grades.json` / `confidence_grades_shards/` |

---

### Task 1: Config plumbing — `grader:` block + `_apply_profile` allowlist fix

**Files:**
- Modify: `src/mykg/config.py:78-88` (`_apply_profile` promoted-keys list)
- Modify: `mykg_config.yaml` (every profile — add `grader:` block as a sibling of `llm:`)
- Modify: `src/mykg/data/mykg_config.yaml` (same, packaging copy)
- Test: `tests/test_config_grader_profile.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is the foundation task).
- Produces: `mykg.config.RAW["grader"]` resolves to the active profile's `grader:` block after `_apply_profile()` runs (or is absent if the profile has no `grader:` key). Later tasks read `RAW.get("grader", {})` directly — not a new `config.py` constant, per the Global Constraints note on why this isn't a `pipeline:`-nested key.

**Context:** `src/mykg/config.py:57-96` (`_apply_profile`) currently promotes only `provider`, `pipeline`, `llm`, `llm_retry`, `agent`, `mcp` from the active profile onto the top-level `RAW` dict. Any other profile-level key (including a new `grader:` block) is silently dropped when a profile is activated — confirmed by reading the function body directly. This must be fixed first or every later task building on `RAW["grader"]` will silently see nothing.

- [ ] **Step 1: Write the failing test — `_apply_profile` promotes `grader`**

```python
"""Tests confirming mykg_config.yaml's per-profile `grader:` block survives
profile resolution the same way `llm:` does."""
from __future__ import annotations

from mykg.config import _apply_profile


def test_apply_profile_promotes_grader_block():
    raw = {
        "profile": "test-profile",
        "profiles": {
            "test-profile": {
                "provider": "openai",
                "llm": {"model": "gpt-5"},
                "grader": {"enabled": True, "backend": "typesafe"},
            }
        },
    }
    result = _apply_profile(raw)
    assert result["grader"] == {"enabled": True, "backend": "typesafe"}


def test_apply_profile_grader_absent_when_profile_omits_it():
    raw = {
        "profile": "test-profile",
        "profiles": {
            "test-profile": {
                "provider": "openai",
                "llm": {"model": "gpt-5"},
            }
        },
    }
    result = _apply_profile(raw)
    assert "grader" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config_grader_profile.py -v`
Expected: FAIL on `test_apply_profile_promotes_grader_block` — `KeyError: 'grader'` (the block was silently dropped).

- [ ] **Step 3: Fix `_apply_profile` to promote `grader`**

In `src/mykg/config.py`, in `_apply_profile`, immediately after the existing `if "mcp" in profile:` block (around line 88):

```python
    if "mcp" in profile:
        result["mcp"] = profile["mcp"]
    if "grader" in profile:
        result["grader"] = profile["grader"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config_grader_profile.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Add the `grader:` block to every profile in `mykg_config.yaml`**

For each of the 7 profiles (`ollama-local`, `anthropic-claude`, `openai`, `gemini`, `openrouter-free`, `claude-cli`, `agent-claude-code`), add a `grader:` block as a sibling of the existing `llm:` block (same indentation level — both are direct children of the profile key). Use this exact shape (values may differ per profile only in comments, not in the default `enabled: false`):

```yaml
    grader:
      # Optional independent confidence re-scoring pass (TypeSafe AI / Jev) — see
      # docs/superpowers/specs/2026-09-24-confidence-grader-design.md. Disabled by
      # default; the pipeline's self-reported confidence is unchanged unless enabled.
      # Requires TYPESAFE_API_KEY in .env.mykg when enabled.
      enabled: false
      backend: typesafe          # only backend for now
      max_questions_per_call: 50 # self-imposed cap; no documented server-side limit
      timeout: 600
      retry_max: 2
      max_workers: 4
```

Place it immediately after the `llm:` block and before `pipeline:` in each profile, matching the existing `provider:` / `llm_retry:` / `llm:` / `pipeline:` ordering convention already visible in the file.

- [ ] **Step 6: Mirror the same 7 `grader:` blocks into `src/mykg/data/mykg_config.yaml`**

This is the packaging copy shipped inside the wheel (Invariant 17's both-files discipline). Apply the identical `grader:` block to each of that file's 7 profiles, same placement.

- [ ] **Step 7: Verify both YAML files still parse and every profile has the block**

Run:
```bash
python -c "
import yaml
for path in ('mykg_config.yaml', 'src/mykg/data/mykg_config.yaml'):
    data = yaml.safe_load(open(path, encoding='utf-8'))
    profiles = data['profiles']
    missing = [name for name, p in profiles.items() if 'grader' not in p]
    assert not missing, f'{path}: profiles missing grader: {missing}'
    print(f'{path}: OK, {len(profiles)} profiles all have grader:')
"
```
Expected: both files print `OK, 7 profiles all have grader:` with no assertion error.

- [ ] **Step 8: Commit**

```bash
git add src/mykg/config.py mykg_config.yaml src/mykg/data/mykg_config.yaml tests/test_config_grader_profile.py
git commit -m "feat(config): add grader: block to every profile, fix _apply_profile allowlist

_apply_profile() only promoted an explicit key allowlist (provider,
pipeline, llm, llm_retry, agent, mcp) from the active profile onto RAW.
A profile-level grader: block would have been silently dropped without
this fix. Adds grader: to every profile in both mykg_config.yaml and
the packaging copy, disabled by default."
```

---

### Task 2: `typesafe-sdk` optional dependency

**Files:**
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: nothing.
- Produces: `pip install mykg[grader]` installs `typesafe-sdk`; `pip install mykg` (default) does not.

**Context:** `pyproject.toml` currently has no `[project.optional-dependencies]` table — every dependency including `anthropic`/`openai`/`google-genai` is a hard core dependency (verified by reading the file). This is a new pattern for this project, matching the spec's explicit choice to keep `typesafe-sdk` optional so users who never enable grading don't need it installed.

- [ ] **Step 1: Add the optional-dependencies table**

In `pyproject.toml`, immediately after the closing `]` of the existing `dependencies = [...]` list (before `[project.scripts]`):

```toml

[project.optional-dependencies]
grader = [
    "typesafe-sdk>=0.1",
]
```

- [ ] **Step 2: Verify the project still installs cleanly without the extra**

Run: `uv pip install -e . --dry-run` (or `pip install -e . --dry-run` if `uv` is unavailable)
Expected: succeeds with no mention of `typesafe-sdk` (it is not pulled in by the base install).

- [ ] **Step 3: Verify the extra installs `typesafe-sdk`**

Run: `uv pip install -e ".[grader]" --dry-run`
Expected: `typesafe-sdk` appears in the resolved dependency list.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "feat(deps): add typesafe-sdk as an optional [grader] extra

Not a core dependency — only needed when grader.enabled is true.
Install via 'pip install mykg[grader]'."
```

---

### Task 3: `TypeSafeGrader` class

**Files:**
- Create: `src/mykg/llm/typesafe_grader.py`
- Test: `tests/test_typesafe_grader.py`

**Interfaces:**
- Consumes: `mykg.config.RAW.get("grader", {})` (from Task 1) for its config values; `TYPESAFE_API_KEY` from `os.environ` (sourced via the existing `load_dotenv(".env.mykg")` call already in `cli.py` — no change needed there, `os.environ.get` reads whatever dotenv already populated).
- Produces:
  - `class TypeSafeGrader` with constructor `TypeSafeGrader(api_key: str | None = None, timeout: float = 600, retry_max: int = 2, max_questions_per_call: int = 50)`.
  - `TypeSafeGrader.grade_chunk(chunk_text: str, entities: list[EntityAttrs]) -> dict[str, dict[str, float]]` where `EntityAttrs` is a small `dict`-shaped record `{"id": str, "type": str, "attributes": dict[str, Any]}` (node or edge — same shape either way, the grader doesn't need to distinguish). Returns `{stable_id: {attr_name: confidence_float, "__self__": confidence_float}}` — exactly the flat map shape `step_grade_confidence.py` (Task 4) expects to write into shards.
  - `build_grader(raw_config: dict | None = None) -> TypeSafeGrader | None` factory function: returns `None` when `grader.enabled` is falsy or absent; otherwise constructs and returns a `TypeSafeGrader`. This is what `cli.py` (Task 6) calls to populate `ctx.grader`.

**Context:** Per the spec's "Adapter shape" section — this is a new, small, purpose-built class, **not** an `LLMAdapter` subclass, **not** registered in `llm/config.py:load_adapter()`. `typesafe_sdk` is imported lazily inside this module's functions (not at module top level) so importing `mykg.llm.typesafe_grader` itself doesn't require the package to be installed — only calling `build_grader()` with `enabled: true` does. Mirror `openai_adapter.py:60-66`'s fail-fast `ValueError` pattern for a missing API key. One `TypeSafeClient` instance is constructed **per `TypeSafeGrader` instance** (the constructor builds it), so callers construct one `TypeSafeGrader` per worker thread (Task 4) rather than sharing one across threads — sidesteps the SDK's undocumented thread-safety question entirely (spec's "Adapter shape" section).

For the `Noul` question shape, follow the spec exactly:

```python
Noul(
    instructions={
        "field": {"name": attr_name, "type": "string", "description": attr_name},
        "extracted_value": value,
        "entity_type": entity_type,
        "question": "Is `extracted_value` correct for `field`, given the source text in `state`?",
    }
)
```

plus one additional `Noul` per entity keyed `f"{entity_id}::__self__"` with instructions `{"entity_type": entity_type, "question": "Is this {entity_type} entity, as a whole, correctly identified in the source text?"}`.

Question keys use `f"{entity_id}::{attr_name}"` (and `f"{entity_id}::__self__"` for the entity-level question) — the `::` separator was chosen because it cannot appear in a stable ID (`ids.py`'s `stable_id()` uses hyphens/lowercase only) or a schema attribute name, so splitting `key.rsplit("::", 1)` to recover `(entity_id, attr_name)` on the response side is unambiguous.

- [ ] **Step 1: Write the failing test — question-building and response-parsing, no real SDK call**

```python
"""Tests for mykg.llm.typesafe_grader.TypeSafeGrader — mocks the SDK client so
no real TypeSafe API call is made."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mykg.llm.typesafe_grader import TypeSafeGrader, build_grader


def _mock_noul_result(value: float) -> MagicMock:
    result = MagicMock()
    result.noul = value
    return result


def test_grade_chunk_builds_one_noul_per_attribute_plus_self(monkeypatch):
    grader = TypeSafeGrader(api_key="fake-key")

    captured_questions = {}

    def fake_system_one(state, questions, **kwargs):
        captured_questions.update(questions)
        response = MagicMock()
        response.nouls = {
            "person-alice::name": _mock_noul_result(0.95),
            "person-alice::__self__": _mock_noul_result(0.9),
        }
        return response

    grader._client.system_one = fake_system_one

    entities = [{"id": "person-alice", "type": "Person", "attributes": {"name": "Alice"}}]
    result = grader.grade_chunk("Alice works here.", entities)

    assert set(captured_questions.keys()) == {"person-alice::name", "person-alice::__self__"}
    assert result == {"person-alice": {"name": 0.95, "__self__": 0.9}}


def test_grade_chunk_skips_entities_with_no_attributes():
    grader = TypeSafeGrader(api_key="fake-key")

    def fake_system_one(state, questions, **kwargs):
        response = MagicMock()
        response.nouls = {k: _mock_noul_result(1.0) for k in questions}
        return response

    grader._client.system_one = fake_system_one

    result = grader.grade_chunk("text", [{"id": "x", "type": "Person", "attributes": {}}])
    # Still gets a __self__ question even with zero attributes.
    assert result == {"x": {"__self__": 1.0}}


def test_missing_api_key_raises_value_error(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY"):
        TypeSafeGrader(api_key=None)


def test_build_grader_returns_none_when_disabled():
    assert build_grader({"enabled": False}) is None
    assert build_grader({}) is None
    assert build_grader(None) is None


def test_build_grader_returns_grader_when_enabled(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    grader = build_grader({"enabled": True, "backend": "typesafe", "timeout": 300})
    assert isinstance(grader, TypeSafeGrader)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_typesafe_grader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mykg.llm.typesafe_grader'`.

- [ ] **Step 3: Implement `TypeSafeGrader`**

```python
"""TypeSafeGrader — wraps typesafe_sdk.TypeSafeClient to re-score confidence
for Pass 2 extracted attributes using TypeSafe AI's Jev model (Noul primitive).

NOT an LLMAdapter subclass and NOT registered in llm/config.py:load_adapter() —
Jev's typed system_one(state, questions) call has no free-text completion
equivalent, so it is kept as its own small interface. See
docs/superpowers/specs/2026-09-24-confidence-grader-design.md ("Adapter shape").

typesafe_sdk is imported lazily inside functions, not at module load time, so
importing this module never requires the optional dependency to be installed —
only actually building/using a TypeSafeGrader does.
"""

from __future__ import annotations

import os
from typing import Any, TypedDict

from mykg.logging import get

log = get("mykg.llm.typesafe_grader")

_SEPARATOR = "::"
_SELF_KEY = "__self__"


class EntityAttrs(TypedDict):
    id: str
    type: str
    attributes: dict[str, Any]


class TypeSafeGrader:
    """Grades extracted attribute values against source chunk text via Jev's
    Noul primitive. One instance owns one typesafe_sdk.TypeSafeClient — callers
    construct one TypeSafeGrader per worker thread rather than sharing an
    instance across threads (the SDK does not document thread-safety for
    concurrent reuse of one client)."""

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 600,
        retry_max: int = 2,
        max_questions_per_call: int = 50,
    ) -> None:
        if api_key is None:
            api_key = os.environ.get("TYPESAFE_API_KEY")
        if not api_key:
            raise ValueError(
                "TYPESAFE_API_KEY is required — set TYPESAFE_API_KEY in your "
                "environment (e.g. .env.mykg) to use the TypeSafe grader, or "
                "set grader.enabled: false in mykg_config.yaml."
            )

        from typesafe_sdk import RetryPolicy, TypeSafeClient

        self._max_questions_per_call = max_questions_per_call
        self._client = TypeSafeClient(
            api_key=api_key,
            timeout=timeout,
            retry=RetryPolicy(max_retries=retry_max),
        )

    def grade_chunk(
        self, chunk_text: str, entities: list[EntityAttrs]
    ) -> dict[str, dict[str, float]]:
        """Return {entity_id: {attr_name: confidence, "__self__": confidence}}.

        Builds one Noul question per (entity, attribute) pair plus one Noul
        question per entity for its own overall confidence, batches them into
        one or more system_one calls (split at max_questions_per_call), and
        flattens the response back into a per-entity map. Entities/attributes
        whose question fails to come back in the response are simply absent
        from the result — callers (step_grade_confidence) treat an absent
        entry as "not graded" and fall back to self-reported confidence.
        """
        from typesafe_sdk import Noul

        questions: dict[str, Any] = {}
        for entity in entities:
            eid = entity["id"]
            etype = entity["type"]
            for attr_name, value in entity.get("attributes", {}).items():
                key = f"{eid}{_SEPARATOR}{attr_name}"
                questions[key] = Noul(
                    instructions={
                        "field": {"name": attr_name, "type": "string", "description": attr_name},
                        "extracted_value": value,
                        "entity_type": etype,
                        "question": (
                            "Is `extracted_value` correct for `field`, given the "
                            "source text in `state`?"
                        ),
                    }
                )
            self_key = f"{eid}{_SEPARATOR}{_SELF_KEY}"
            questions[self_key] = Noul(
                instructions={
                    "entity_type": etype,
                    "question": (
                        f"Is this {etype} entity, as a whole, correctly identified "
                        "in the source text in `state`?"
                    ),
                }
            )

        result: dict[str, dict[str, float]] = {}
        items = list(questions.items())
        for start in range(0, len(items), self._max_questions_per_call):
            batch = dict(items[start : start + self._max_questions_per_call])
            response = self._client.system_one(state=chunk_text, questions=batch)
            for key, noul_result in response.nouls.items():
                eid, _, attr_or_self = key.rpartition(_SEPARATOR)
                result.setdefault(eid, {})[attr_or_self] = noul_result.noul

        return result


def build_grader(raw_config: dict | None) -> TypeSafeGrader | None:
    """Construct a TypeSafeGrader from a `grader:` config block, or None when
    disabled/absent. This is the factory cli.py calls to populate ctx.grader."""
    cfg = raw_config or {}
    if not cfg.get("enabled"):
        return None
    return TypeSafeGrader(
        timeout=cfg.get("timeout", 600),
        retry_max=cfg.get("retry_max", 2),
        max_questions_per_call=cfg.get("max_questions_per_call", 50),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_typesafe_grader.py -v`
Expected: PASS (all 5 tests). Note: `test_grade_chunk_builds_one_noul_per_attribute_plus_self` and `test_grade_chunk_skips_entities_with_no_attributes` construct a real `TypeSafeGrader(api_key="fake-key")`, which calls the real `TypeSafeClient(...)` constructor — this does not make a network call (constructing a client is not a request), only `system_one` does, and that's replaced with `fake_system_one` before it's ever called. If `typesafe-sdk` is not installed in the test environment, install it first: `uv pip install -e ".[grader]"`.

- [ ] **Step 5: Commit**

```bash
git add src/mykg/llm/typesafe_grader.py tests/test_typesafe_grader.py
git commit -m "feat(grader): add TypeSafeGrader — Noul-based per-attribute confidence scoring

New parallel interface, not an LLMAdapter subclass. One Noul question
per extracted attribute plus one per entity for overall confidence,
batched into system_one calls capped at max_questions_per_call.
typesafe_sdk is imported lazily so it stays an optional dependency."
```

---

### Task 4: `grade_confidence` pipeline step

**Files:**
- Create: `src/mykg/steps/step_grade_confidence.py`
- Test: `tests/test_step_grade_confidence.py`

**Interfaces:**
- Consumes: `TypeSafeGrader.grade_chunk(chunk_text, entities) -> dict[str, dict[str, float]]` (Task 3); `ctx.grader: TypeSafeGrader | None` (Task 6 adds this field, but this task can write against a plain `PipelineContext` attribute access — Task 6 is what makes it a real declared field); `chunker.chunk_file(source_file, content) -> list[Chunk]` (existing, `src/mykg/chunker.py:49`); `raw_extractions.json` / `raw_extractions_shards/` (existing pass2 outputs); `chunk_node_index.json` (existing pass2 output, format `{filename: {chunk_idx_str: [stable_id, ...]}}`).
- Produces: `run_grade_confidence(ctx: PipelineContext) -> None` — the step function registered in `pipeline.py` (Task 5). Writes `intermediate/confidence_grades_shards/<slug>.json` (shape `{"_fname": fname, "data": {stable_id: {attr: confidence, "__self__": confidence}}}`, mirrors `raw_extractions_shards/`'s shape exactly) and the merged `intermediate/confidence_grades.json` (`{stable_id: {attr: confidence, "__self__": confidence}}` across all files) plus `intermediate/confidence_grades.done`.

**Context:** Mirrors `run_pass2`'s structure (`src/mykg/pass2.py:416-601`) at a smaller scale: per-file `ThreadPoolExecutor`, per-file shard flush inside the `as_completed` loop (D57 incremental-flush pattern — not the "submit everything, finalize once at the end" anti-pattern D57 documents as a bug). Reuses `_fname_slug` naming (mirror `step_pass2.py:18-19`'s `_fname_slug` helper — either import it or duplicate the one-liner; duplicating is fine here since it's a trivial pure function and importing from `step_pass2` would create an odd cross-step dependency).

When `ctx.grader is None` (disabled), write `confidence_grades.json` as `{}` and the `.done` sentinel, return immediately — no `ThreadPoolExecutor`, no file iteration.

When enabled: for each file in `raw_extractions.json`, re-derive its chunks via `chunk_file(fname, content)` (content from `file_manifest.json`/`ctx.file_contents`, same loader pattern `step_pass2.py:_load_manifest` already uses), then for each chunk look up `chunk_node_index[fname][str(chunk_idx_1based)]` → the list of stable IDs extracted from that chunk, pull each one's current `type`+`attributes` from that file's raw nodes/edges (search both `nodes` and `edges` lists by `id`), call `ctx.grader.grade_chunk(chunk.text, entities)`, and merge the per-chunk result into that file's accumulated grades dict. A `TypeSafeError` (or any exception) from `grade_chunk` for one chunk is caught, logged as a warning, and that chunk's entities simply contribute nothing to the file's grades — matches `run_pass2._process_file`'s exception breadth.

- [ ] **Step 1: Write the failing test — disabled grader is a no-op**

```python
"""Tests for mykg.steps.step_grade_confidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mykg.orchestrator import PipelineContext
from mykg.steps.step_grade_confidence import run_grade_confidence


class FakeAdapter:
    def complete(self, *a, **k):
        raise NotImplementedError

    def endpoint_label(self):
        return "fake"


def _make_ctx(tmp_path: Path, grader=None) -> PipelineContext:
    out = tmp_path / "output"
    inter = tmp_path / "intermediate"
    inp = tmp_path / "input"
    for p in (out, inter, inp):
        p.mkdir(parents=True)
    ctx = PipelineContext(
        input_dir=inp,
        output_dir=out,
        intermediate_dir=inter,
        adapter=FakeAdapter(),
    )
    ctx.grader = grader
    return ctx


def test_disabled_grader_writes_empty_grades_and_done(tmp_path):
    ctx = _make_ctx(tmp_path, grader=None)
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps({}))
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(json.dumps({}))

    run_grade_confidence(ctx)

    grades_path = ctx.intermediate_dir / "confidence_grades.json"
    done_path = ctx.intermediate_dir / "confidence_grades.done"
    assert grades_path.exists()
    assert json.loads(grades_path.read_text()) == {}
    assert done_path.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_step_grade_confidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mykg.steps.step_grade_confidence'`. (Also note: `PipelineContext` has no `grader` field yet — `ctx.grader = grader` on a Pydantic model without that field declared will raise at assignment. This test will only fully pass once Task 6 adds the field; write it now, but expect it to need Task 6 before it's green — see Step 4 note below.)

- [ ] **Step 3: Implement the step (disabled path first, minimal)**

```python
"""grade_confidence pipeline step — re-scores Pass 2 extracted attribute
confidence using an independent grader (TypeSafeGrader) against source chunk
text. Mirrors pass2's per-file shard/resume pattern (D57) at a smaller scale.
See docs/superpowers/specs/2026-09-24-confidence-grader-design.md.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from mykg import config as _cfg
from mykg.chunker import chunk_file
from mykg.logging import get
from mykg.orchestrator import PipelineContext
from mykg.utility.atomic_io import atomic_write_json

log = get("mykg.steps.grade_confidence")


def _fname_slug(fname: str) -> str:
    return fname.replace("/", "_").replace("\\", "_").replace(" ", "_")


def _content_from_entry(entry: str | dict) -> str:
    return entry["content"] if isinstance(entry, dict) else entry


def _index_entities(file_data: dict) -> dict[str, dict]:
    """Map stable_id -> {"id", "type", "attributes"} for every node/edge in a
    file's raw extraction, so a chunk's stable-id list can be resolved to full
    entity records for grading."""
    by_id: dict[str, dict] = {}
    for node in file_data.get("nodes", []):
        if node and node.get("id"):
            attrs = {
                k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (node.get("attributes") or {}).items()
            }
            by_id[node["id"]] = {"id": node["id"], "type": node.get("type", ""), "attributes": attrs}
    for edge in file_data.get("edges", []):
        if edge and edge.get("from") and edge.get("to"):
            eid = f"{edge['type']}::{edge['from']}::{edge['to']}"
            attrs = {
                k: (v.get("value") if isinstance(v, dict) else v)
                for k, v in (edge.get("attributes") or {}).items()
            }
            by_id[eid] = {"id": eid, "type": edge.get("type", ""), "attributes": attrs}
    return by_id


def _grade_file(
    fname: str,
    content: str,
    file_data: dict,
    chunk_index: dict[str, list[str]],
    grader,
) -> dict[str, dict[str, float]]:
    """Grade every chunk of one file, returning the merged per-entity grades
    for that file. A single chunk's grading failure is caught and logged —
    other chunks in the same file still contribute their grades."""
    entities_by_id = _index_entities(file_data)
    chunks = chunk_file(fname, content)
    file_grades: dict[str, dict[str, float]] = {}

    for i, chunk in enumerate(chunks, 1):
        stable_ids = chunk_index.get(str(i), [])
        entities = [entities_by_id[sid] for sid in stable_ids if sid in entities_by_id]
        if not entities:
            continue
        try:
            chunk_grades = grader.grade_chunk(chunk.text, entities)
        except Exception as exc:  # noqa: BLE001 — graceful degradation, mirrors run_pass2._process_file
            log.warning("  %s chunk %d — grading failed: %s — leaving self-reported confidence", fname, i, exc)
            continue
        for eid, attrs in chunk_grades.items():
            file_grades.setdefault(eid, {}).update(attrs)

    return file_grades


def run_grade_confidence(ctx: PipelineContext) -> None:
    grades_path = ctx.intermediate_dir / "confidence_grades.json"
    done_path = ctx.intermediate_dir / "confidence_grades.done"

    if ctx.grader is None:
        atomic_write_json(grades_path, {})
        done_path.write_text("", encoding="utf-8")
        log.info("Step — grading disabled (grader.enabled: false); confidence_grades.json is empty")
        return

    raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text(encoding="utf-8"))
    chunk_node_index = json.loads(
        (ctx.intermediate_dir / "chunk_node_index.json").read_text(encoding="utf-8")
    )
    manifest_path = ctx.intermediate_dir / "file_manifest.json"
    manifest = ctx.file_contents
    if manifest is None:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}

    shard_dir = ctx.intermediate_dir / "confidence_grades_shards"
    shard_dir.mkdir(exist_ok=True)

    all_grades: dict[str, dict[str, float]] = {}
    grader = ctx.grader

    def _process(fname: str) -> tuple[str, dict[str, dict[str, float]]]:
        content = _content_from_entry(manifest.get(fname, ""))
        file_data = raw.get(fname, {})
        chunk_index = chunk_node_index.get(fname, {})
        return fname, _grade_file(fname, content, file_data, chunk_index, grader)

    max_workers = _cfg.RAW.get("grader", {}).get("max_workers", 4)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process, fname): fname for fname in raw}
        for future in as_completed(futures):
            fname = futures[future]
            try:
                fname, file_grades = future.result()
            except Exception as exc:  # noqa: BLE001 — one file's failure must not lose others
                log.error("Step — grading file %s failed entirely: %s", fname, exc)
                continue
            all_grades.update(file_grades)
            slug = _fname_slug(fname)
            atomic_write_json(shard_dir / f"{slug}.json", {"_fname": fname, "data": file_grades})

    atomic_write_json(grades_path, all_grades)
    done_path.write_text("", encoding="utf-8")
    log.info("Step — graded %d entit(y/ies) across %d file(s)", len(all_grades), len(raw))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_step_grade_confidence.py -v`
Expected: FAIL at `ctx.grader = grader` with a Pydantic validation error (`PipelineContext` has no `grader` field yet). This is expected — leave it failing and proceed to Task 6, which adds the field, then return here.

**Do not skip ahead without completing this loop** — after Task 6 lands, re-run this exact command and confirm PASS before moving to Task 5's own tests. Note this dependency explicitly in the task tracker.

- [ ] **Step 5: Add the enabled-path test (also blocked on Task 6 — write now, verify after)**

```python
def test_enabled_grader_grades_and_writes_shard(tmp_path):
    class FakeGrader:
        def grade_chunk(self, chunk_text, entities):
            return {e["id"]: {**{a: 0.8 for a in e["attributes"]}, "__self__": 0.9} for e in entities}

    ctx = _make_ctx(tmp_path, grader=FakeGrader())
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "attributes": {"name": {"value": "Alice", "confidence": 0.5}},
                }
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps({"doc.md": {"1": ["person-alice"]}})
    )
    (ctx.intermediate_dir / "file_manifest.json").write_text(
        json.dumps({"doc.md": "Alice is a person."})
    )

    run_grade_confidence(ctx)

    grades = json.loads((ctx.intermediate_dir / "confidence_grades.json").read_text())
    assert grades == {"person-alice": {"name": 0.8, "__self__": 0.9}}
    shard_path = ctx.intermediate_dir / "confidence_grades_shards" / "doc.md.json"
    assert shard_path.exists()
    shard = json.loads(shard_path.read_text())
    assert shard["_fname"] == "doc.md"


def test_chunk_grading_failure_does_not_lose_other_chunks(tmp_path):
    class FlakyGrader:
        def grade_chunk(self, chunk_text, entities):
            if "bob" in entities[0]["id"]:
                raise RuntimeError("simulated grader failure")
            return {e["id"]: {"__self__": 0.7} for e in entities}

    ctx = _make_ctx(tmp_path, grader=FlakyGrader())
    raw = {
        "doc.md": {
            "nodes": [
                {"id": "person-alice", "type": "Person", "attributes": {}},
                {"id": "person-bob", "type": "Person", "attributes": {}},
            ],
            "edges": [],
        }
    }
    (ctx.intermediate_dir / "raw_extractions.json").write_text(json.dumps(raw))
    # Two chunks so alice and bob are graded in separate grade_chunk calls.
    (ctx.intermediate_dir / "chunk_node_index.json").write_text(
        json.dumps({"doc.md": {"1": ["person-alice"], "2": ["person-bob"]}})
    )
    long_text = ("Alice is here. " * 500) + ("Bob is here. " * 500)
    (ctx.intermediate_dir / "file_manifest.json").write_text(json.dumps({"doc.md": long_text}))

    run_grade_confidence(ctx)

    grades = json.loads((ctx.intermediate_dir / "confidence_grades.json").read_text())
    assert grades.get("person-alice") == {"__self__": 0.7}
    assert "person-bob" not in grades
```

- [ ] **Step 6: After Task 6 lands, run all step_grade_confidence tests and verify pass**

Run: `pytest tests/test_step_grade_confidence.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 7: Commit**

```bash
git add src/mykg/steps/step_grade_confidence.py tests/test_step_grade_confidence.py
git commit -m "feat(pipeline): add grade_confidence step

Per-file ThreadPoolExecutor mirroring pass2's shard/resume pattern.
Disabled grader (ctx.grader is None) writes an empty confidence_grades.json
and .done sentinel as a no-op passthrough. A chunk's grading failure is
caught and logged; other chunks and files still contribute their grades."
```

---

### Task 5: Register the step in `pipeline.py`

**Files:**
- Modify: `src/mykg/pipeline.py:1-93`
- Test: `tests/test_pipeline_step_order.py`

**Interfaces:**
- Consumes: `run_grade_confidence` from `mykg.steps.step_grade_confidence` (Task 4).
- Produces: `STEPS` list (and its `PIPELINE` alias) includes a `Step(name="grade_confidence", ...)` entry positioned between `"pass2"` and `"normalize_names"`.

- [ ] **Step 1: Write the failing test**

```python
"""Confirms grade_confidence is registered between pass2 and normalize_names."""
from __future__ import annotations

from mykg.pipeline import STEPS


def test_grade_confidence_step_registered_between_pass2_and_normalize():
    names = [s.name for s in STEPS]
    assert "grade_confidence" in names
    assert names.index("pass2") < names.index("grade_confidence") < names.index("normalize_names")


def test_grade_confidence_step_is_llm_step_and_declares_outputs():
    step = next(s for s in STEPS if s.name == "grade_confidence")
    assert step.is_llm_step is True
    assert set(step.outputs) == {"confidence_grades.json", "confidence_grades.done"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_step_order.py -v`
Expected: FAIL — `"grade_confidence" in names` is False.

- [ ] **Step 3: Register the step**

In `src/mykg/pipeline.py`, add the import:

```python
from mykg.steps.step_grade_confidence import run_grade_confidence
```

(alongside the other `from mykg.steps.step_*` imports, alphabetically — after `step_assemble`, before `step_ingest`, matching the existing alphabetical-by-module ordering already visible in the file... actually check current order: `step_assemble, step_ingest, step_normalize, step_orphan_connect, step_orphan_score, step_pass1, step_pass2, step_preprocess, step_schema, step_validate_graph` — insert `from mykg.steps.step_grade_confidence import run_grade_confidence` after the `step_assemble` import, keeping alphabetical order: `step_assemble`, `step_grade_confidence`, `step_ingest`, ...).

Then insert the new `Step(...)` entry into `STEPS`, between the existing `pass2` Step (currently lines 44-54) and the `normalize_names` Step (currently lines 55-60):

```python
    Step(
        name="grade_confidence",
        fn=run_grade_confidence,
        outputs=["confidence_grades.json", "confidence_grades.done"],
        is_llm_step=True,
    ),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_step_order.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full existing pipeline test suite to check for regressions**

Run: `pytest tests/ -k "pipeline or orchestrator" -v`
Expected: PASS — no existing test hardcodes the exact step count/order in a way that breaks (if one does, e.g. a test asserting `len(STEPS) == 12`, update that count to 13 as part of this task).

- [ ] **Step 6: Commit**

```bash
git add src/mykg/pipeline.py tests/test_pipeline_step_order.py
git commit -m "feat(pipeline): register grade_confidence step between pass2 and normalize_names"
```

---

### Task 6: `PipelineContext.grader` field + `cli.py` wiring

**Files:**
- Modify: `src/mykg/orchestrator.py:47-108` (`PipelineContext`)
- Modify: `src/mykg/cli.py` (adapter/ctx construction, around the existing `adapter = load_adapter(...)` call and `PipelineContext(...)` construction — see spec's "Config" section for exact intent)
- Test: `tests/test_cli_grader_wiring.py`

**Interfaces:**
- Consumes: `mykg.llm.typesafe_grader.build_grader(raw_config: dict | None) -> TypeSafeGrader | None` (Task 3).
- Produces: `PipelineContext.grader: Any = None` field exists and is populated by `cli.py`'s `extract_graph` command (or wherever `adapter = load_adapter(...)` and `ctx = PipelineContext(...)` currently live) from `_cfg.RAW.get("grader", {})`.

**Context:** This task is what makes Task 4's step 4/5 tests (which do `ctx.grader = grader`) actually pass — `PipelineContext` is a Pydantic `BaseModel` with `model_config = ConfigDict(arbitrary_types_allowed=True)`, so an undeclared attribute assignment raises a validation error, not a silent dynamic attribute set. `Any` (not `TypeSafeGrader | None`) is used for the same reason `adapter: Any` and `error_gate: Any = None` already are — avoiding a circular import between `orchestrator.py` and `llm/typesafe_grader.py`.

- [ ] **Step 1: Write the failing test — field exists and defaults to None**

```python
"""Confirms PipelineContext has a grader field, defaulting to None, and that
cli.py's extract-graph command populates it from the grader: config block."""
from __future__ import annotations

from pathlib import Path

from mykg.orchestrator import PipelineContext


def test_pipeline_context_grader_defaults_to_none(tmp_path):
    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=object(),
    )
    assert ctx.grader is None


def test_pipeline_context_accepts_explicit_grader(tmp_path):
    sentinel = object()
    ctx = PipelineContext(
        input_dir=tmp_path,
        output_dir=tmp_path,
        intermediate_dir=tmp_path,
        adapter=object(),
        grader=sentinel,
    )
    assert ctx.grader is sentinel
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_grader_wiring.py -v`
Expected: FAIL — Pydantic raises `ValidationError` on the unexpected `grader` kwarg / `ctx.grader` raises `AttributeError`.

- [ ] **Step 3: Add the field to `PipelineContext`**

In `src/mykg/orchestrator.py`, inside the `PipelineContext` class body, immediately after the existing `error_gate: Any = None` line:

```python
    error_gate: Any = None  # ErrorGate | None — Any to avoid circular import
    grader: Any = None  # TypeSafeGrader | None — Any to avoid circular import with llm/typesafe_grader.py
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_grader_wiring.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Go back and re-run Task 4's tests now that the field exists**

Run: `pytest tests/test_step_grade_confidence.py -v`
Expected: PASS (all 4 tests — this closes the loop noted in Task 4 Step 4).

- [ ] **Step 6: Wire `ctx.grader` construction into `cli.py`**

Find the existing adapter-construction block in `src/mykg/cli.py` (the line reading `adapter = load_adapter(error_gate=error_gate, intermediate_dir=intermediate_dir)`, followed shortly by `ctx = PipelineContext(...)`). Add, immediately after the `adapter = load_adapter(...)` line:

```python
    from mykg.llm.typesafe_grader import build_grader

    grader = build_grader(_cfg().RAW.get("grader"))
    if grader is not None:
        logging.getLogger(__name__).info("Grader: TypeSafe AI (Jev) — confidence re-scoring enabled")
```

(Match whatever the existing local `_cfg()` accessor pattern is in that function — `cli.py` already calls `_cfg()` for other config reads nearby, e.g. `_cfg().ERROR_GATE_THRESHOLD`/`_cfg().OUTPUT_DIR`; use the same accessor rather than importing `mykg.config` fresh, to pick up any active `--profile` override already applied earlier in the function.)

Then add `grader=grader,` to the `PipelineContext(...)` constructor call, alongside the existing `adapter=adapter,` line.

- [ ] **Step 7: Write an integration-style test confirming end-to-end wiring**

```python
def test_extract_graph_wires_grader_when_enabled(tmp_path, monkeypatch):
    """Smoke test: with grader.enabled true and TYPESAFE_API_KEY set, the
    constructed PipelineContext has a non-None grader. Does not run the full
    pipeline — just checks the wiring path builds a grader instance."""
    import mykg.config as cfg

    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-key")
    monkeypatch.setitem(cfg.RAW, "grader", {"enabled": True, "backend": "typesafe"})

    from mykg.llm.typesafe_grader import build_grader

    grader = build_grader(cfg.RAW.get("grader"))
    assert grader is not None


def test_extract_graph_grader_none_when_disabled(monkeypatch):
    import mykg.config as cfg

    monkeypatch.setitem(cfg.RAW, "grader", {"enabled": False})

    from mykg.llm.typesafe_grader import build_grader

    assert build_grader(cfg.RAW.get("grader")) is None
```

Add these to `tests/test_cli_grader_wiring.py`.

- [ ] **Step 8: Run the full test file**

Run: `pytest tests/test_cli_grader_wiring.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 9: Run the broader CLI test suite to check for regressions**

Run: `pytest tests/test_cli_commands.py tests/test_cli_profile_model.py -v`
Expected: PASS — no existing test should be affected by an additive field/construction change.

- [ ] **Step 10: Commit**

```bash
git add src/mykg/orchestrator.py src/mykg/cli.py tests/test_cli_grader_wiring.py
git commit -m "feat(pipeline): wire ctx.grader from grader: config in cli.py

PipelineContext.grader defaults to None (Any type to avoid a circular
import with llm/typesafe_grader.py, matching the existing adapter/
error_gate fields). cli.py builds it via build_grader() alongside the
existing adapter construction."
```

---

### Task 7: Re-entry / invalidation wiring

**Files:**
- Modify: `src/mykg/orchestrator.py:260-269` (`_SCHEMA_RESTART_INVALIDATE`), `:273-280` (`_APPEND_INVALIDATE`)
- Modify: `src/mykg/cli.py:2032-2049` (shard-clearing block in `_delete_from_step`)
- Test: `tests/test_delete_from_step_grade_confidence.py`

**Interfaces:**
- Consumes: nothing new — modifies existing orchestrator sets and the existing `_delete_from_step` function.
- Produces: a schema-gap restart, `--append` detecting changes, or `--from-step grade_confidence`/`pass2`/earlier all correctly clear stale grading state.

**Context — the Review Focus item on step ordering.** `grade_confidence` sits **after** `pass2` in `STEPS` order (Task 5). The existing shard-clearing block in `cli.py` (`src/mykg/cli.py:2032`) is keyed on `idx <= pass2_idx` — that condition is checking "is the target step at or before pass2." Since `grade_confidence` comes *after* pass2, a `--from-step grade_confidence` run has `idx == grade_confidence_idx > pass2_idx`, so the existing `idx <= pass2_idx` check would be `False` and the pass2 shard-clearing block would correctly NOT fire (pass2's own shards should indeed survive a `--from-step grade_confidence` re-entry — only grading, not extraction, needs to redo). But **grading's own shard directory** needs an equivalent clearing block, keyed on a **new** `grade_confidence_idx`, using `idx <= grade_confidence_idx` — a condition that is `True` for `--from-step grade_confidence` itself AND for any earlier step (`pass2`, `pass1`, etc.), matching the existing pattern's own semantics one level later in the pipeline.

- [ ] **Step 1: Write the failing test — schema-restart and append invalidation sets include grade_confidence**

```python
"""Confirms grade_confidence participates in the existing re-entry
invalidation sets and _delete_from_step's shard-clearing logic."""
from __future__ import annotations

from mykg.orchestrator import _APPEND_INVALIDATE, _SCHEMA_RESTART_INVALIDATE


def test_grade_confidence_in_schema_restart_invalidate():
    assert "grade_confidence" in _SCHEMA_RESTART_INVALIDATE


def test_grade_confidence_in_append_invalidate():
    assert "grade_confidence" in _APPEND_INVALIDATE
```

```python
def test_delete_from_step_pass2_clears_confidence_grades_shards(tmp_path):
    """--from-step pass2 (or earlier) must also clear confidence_grades_shards/
    and confidence_grades.json, since grade_confidence sits after pass2 and its
    output depends on pass2's — stale grades would otherwise survive a
    pass2 re-extraction and silently attach to different content."""
    from mykg.cli import _delete_from_step

    intermediate_dir = tmp_path / "intermediate"
    output_dir = tmp_path / "output"
    intermediate_dir.mkdir()
    output_dir.mkdir()

    shard_dir = intermediate_dir / "confidence_grades_shards"
    shard_dir.mkdir()
    (shard_dir / "doc.md.json").write_text("{}")
    (intermediate_dir / "confidence_grades.json").write_text("{}")
    (intermediate_dir / "confidence_grades.done").write_text("")

    _delete_from_step("pass2", intermediate_dir, output_dir)

    assert not shard_dir.exists()
    assert not (intermediate_dir / "confidence_grades.json").exists()


def test_delete_from_step_grade_confidence_clears_its_own_shards(tmp_path):
    """--from-step grade_confidence must clear its own shards but must NOT
    touch pass2's raw_extractions_shards/ (pass2 output should survive)."""
    from mykg.cli import _delete_from_step

    intermediate_dir = tmp_path / "intermediate"
    output_dir = tmp_path / "output"
    intermediate_dir.mkdir()
    output_dir.mkdir()

    grade_shard_dir = intermediate_dir / "confidence_grades_shards"
    grade_shard_dir.mkdir()
    (grade_shard_dir / "doc.md.json").write_text("{}")

    raw_shard_dir = intermediate_dir / "raw_extractions_shards"
    raw_shard_dir.mkdir()
    (raw_shard_dir / "doc.md.json").write_text("{}")

    _delete_from_step("grade_confidence", intermediate_dir, output_dir)

    assert not grade_shard_dir.exists()
    assert raw_shard_dir.exists()  # pass2's shards must survive
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delete_from_step_grade_confidence.py -v`
Expected: FAIL — `"grade_confidence" in _SCHEMA_RESTART_INVALIDATE` is False; the shard-clearing tests fail because `confidence_grades_shards/` still exists after `_delete_from_step` runs (no clearing logic for it exists yet).

- [ ] **Step 3: Add `grade_confidence` to both invalidation sets**

In `src/mykg/orchestrator.py`:

```python
_SCHEMA_RESTART_INVALIDATE = {
    "schema_validate",
    "schema_flatten",
    "pass2",
    "grade_confidence",
    "normalize_names",
    "assemble",
    "orphan_score",
    "orphan_connect",
    "validate_graph",
}
```

```python
_APPEND_INVALIDATE = {
    "pass2",
    "grade_confidence",
    "normalize_names",
    "assemble",
    "orphan_score",
    "orphan_connect",
    "validate_graph",
}
```

- [ ] **Step 4: Add the `grade_confidence` shard-clearing block in `cli.py`**

In `src/mykg/cli.py`, immediately after the existing pass2 shard-clearing block (right after the `pass2_concat_map.json`/`pass2_batch_map.json` loop, before the `pass1_batch_selection.json` block), add:

```python
    # confidence_grades_shards/ + confidence_grades.json are not listed in
    # Step.outputs' pass2 entry and grade_confidence sits AFTER pass2 in STEPS —
    # so this is a separate condition from the pass2_idx check above, using
    # idx <= grade_confidence_idx (a superset of idx <= pass2_idx, since
    # grade_confidence comes later). A --from-step pass2-or-earlier run must
    # also invalidate grading, since re-extracted content needs re-grading;
    # a --from-step grade_confidence run must clear ONLY its own shards,
    # leaving pass2's raw_extractions_shards/ untouched.
    grade_confidence_idx = (
        step_names.index("grade_confidence") if "grade_confidence" in step_names else -1
    )
    if grade_confidence_idx >= 0 and idx <= grade_confidence_idx:
        grade_shard_path = intermediate_dir / "confidence_grades_shards"
        if grade_shard_path.exists():
            shutil.rmtree(grade_shard_path)
            click.echo(f"Deleted {grade_shard_path}")
        grades_path = intermediate_dir / "confidence_grades.json"
        if grades_path.exists():
            grades_path.unlink()
            click.echo(f"Deleted {grades_path}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_delete_from_step_grade_confidence.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 6: Run the broader re-entry test suite to check for regressions**

Run: `pytest tests/test_append.py tests/test_append_modified_e2e.py tests/test_append_deleted_e2e.py tests/test_grow_schema_e2e.py -v`
Expected: PASS — these exercise `_delete_from_step`/`_APPEND_INVALIDATE` paths already; confirm the additive `grade_confidence` entries don't break any existing assertion about exactly which files get deleted.

- [ ] **Step 7: Commit**

```bash
git add src/mykg/orchestrator.py src/mykg/cli.py tests/test_delete_from_step_grade_confidence.py
git commit -m "feat(pipeline): wire grade_confidence into re-entry invalidation

Adds grade_confidence to _SCHEMA_RESTART_INVALIDATE and _APPEND_INVALIDATE
so schema-gap restarts and --append re-grade re-extracted chunks. Adds a
separate confidence_grades_shards/ clearing block in cli.py keyed on
grade_confidence_idx (a superset of the existing pass2_idx check, since
grade_confidence sits after pass2 in step order) — --from-step pass2 or
earlier clears grading too; --from-step grade_confidence clears only its
own shards, leaving pass2's raw_extractions_shards/ untouched."
```

---

### Task 8: Assemble-time confidence overwrite

**Files:**
- Modify: `src/mykg/steps/step_assemble.py`
- Test: `tests/test_step_assemble_grading.py`

**Interfaces:**
- Consumes: `intermediate/confidence_grades.json` (Task 4's output format: `{stable_id: {attr_name: confidence_float, "__self__": confidence_float}}`).
- Produces: `_apply_grades(raw: dict, grades: dict) -> None` — new helper in `step_assemble.py`, mutates `raw` in place. Called from `run_assemble` immediately after loading `raw_extractions.json`, before `assign_stable_ids(raw)` is called.

**Context — the Review Focus item on graceful degradation.** For every node/edge whose ID appears in `grades`: for each attribute present in that grade entry, set `attr["self_reported_confidence"] = attr["confidence"]` (preserve, never drop — per D9's spirit and the spec's explicit contract) then `attr["confidence"] = graded_value`. If `"__self__"` is present in the grade entry, do the same preserve-then-overwrite for the entity's own top-level `confidence` field. An entity absent from `grades` entirely, or present but missing a specific attribute's key, is left completely untouched for that attribute — no `self_reported_confidence` field is added where no grade exists (since nothing was overwritten, there's nothing to record as "prior").

Note the raw extraction shape (from reading `pass2.py`'s `_backfill_extraction`): `node["attributes"][attr_name]` is always `{"value": ..., "confidence": ...}` by the time it reaches `raw_extractions.json` (backfilled by pass2 for every schema-declared attribute) — so `_apply_grades` can assume that shape for any attribute key it looks up, but must still guard against an attribute name in the grade map that doesn't exist on the node (e.g. grading ran against a stale/different extraction) by skipping it rather than raising.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for step_assemble's confidence-grade application (_apply_grades)."""
from __future__ import annotations

import json
from pathlib import Path

from mykg.orchestrator import PipelineContext
from mykg.steps.step_assemble import _apply_grades, run_assemble


def test_apply_grades_overwrites_confidence_and_preserves_self_reported():
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-alice",
                    "type": "Person",
                    "confidence": 0.6,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.5}},
                }
            ],
            "edges": [],
        }
    }
    grades = {"person-alice": {"name": 0.95, "__self__": 0.99}}

    _apply_grades(raw, grades)

    node = raw["doc.md"]["nodes"][0]
    assert node["attributes"]["name"]["confidence"] == 0.95
    assert node["attributes"]["name"]["self_reported_confidence"] == 0.5
    assert node["confidence"] == 0.99


def test_apply_grades_leaves_ungraded_entities_untouched():
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-bob",
                    "type": "Person",
                    "confidence": 0.6,
                    "attributes": {"name": {"value": "Bob", "confidence": 0.5}},
                }
            ],
            "edges": [],
        }
    }
    _apply_grades(raw, grades={})

    node = raw["doc.md"]["nodes"][0]
    assert node["attributes"]["name"] == {"value": "Bob", "confidence": 0.5}
    assert "self_reported_confidence" not in node["attributes"]["name"]
    assert node["confidence"] == 0.6


def test_apply_grades_skips_attribute_not_present_on_node():
    """A grade for an attribute name the node doesn't actually have (stale
    grading run) must be skipped, not raise."""
    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "person-carol",
                    "type": "Person",
                    "confidence": 0.6,
                    "attributes": {"name": {"value": "Carol", "confidence": 0.5}},
                }
            ],
            "edges": [],
        }
    }
    grades = {"person-carol": {"nonexistent_attr": 0.9}}

    _apply_grades(raw, grades)  # must not raise

    node = raw["doc.md"]["nodes"][0]
    assert node["attributes"]["name"]["confidence"] == 0.5  # untouched


def test_apply_grades_covers_edges_too():
    raw = {
        "doc.md": {
            "nodes": [],
            "edges": [
                {
                    "id": "edge-1",
                    "type": "works_at",
                    "from": "person-alice",
                    "to": "org-acme",
                    "confidence": 0.7,
                    "attributes": {"role": {"value": "engineer", "confidence": 0.6}},
                }
            ],
        }
    }
    grades = {"edge-1": {"role": 0.85, "__self__": 0.9}}

    _apply_grades(raw, grades)

    edge = raw["doc.md"]["edges"][0]
    assert edge["attributes"]["role"]["confidence"] == 0.85
    assert edge["attributes"]["role"]["self_reported_confidence"] == 0.6
    assert edge["confidence"] == 0.9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_step_assemble_grading.py -v`
Expected: FAIL — `ImportError: cannot import name '_apply_grades'`.

- [ ] **Step 3: Implement `_apply_grades` and wire it into `run_assemble`**

In `src/mykg/steps/step_assemble.py`, add the helper (near the top, after `_annotate_aliases`):

```python
def _apply_grades(raw: dict, grades: dict) -> None:
    """Overwrite self-reported confidence with independently-graded confidence
    (from confidence_grades.json) where a grade exists. Mutates raw in place.

    Preserves the prior value as attr["self_reported_confidence"] — never
    dropped, per D9's "never silently discard a confidence signal" spirit.
    An entity absent from grades, or a graded attribute name absent on the
    node/edge (e.g. a stale grading run against different content), is left
    completely untouched.
    """
    for file_data in raw.values():
        for entity_list in (file_data.get("nodes", []), file_data.get("edges", [])):
            for entity in entity_list:
                if not entity or not entity.get("id"):
                    continue
                entity_grades = grades.get(entity["id"])
                if not entity_grades:
                    continue
                attrs = entity.get("attributes", {})
                for attr_name, graded_conf in entity_grades.items():
                    if attr_name == "__self__":
                        continue
                    attr = attrs.get(attr_name)
                    if not isinstance(attr, dict):
                        continue
                    attr["self_reported_confidence"] = attr.get("confidence")
                    attr["confidence"] = graded_conf
                if "__self__" in entity_grades:
                    entity["self_reported_confidence"] = entity.get("confidence")
                    entity["confidence"] = entity_grades["__self__"]
```

Then modify `run_assemble` — immediately after the existing `raw = json.loads((ctx.intermediate_dir / "raw_extractions.json").read_text(encoding="utf-8"))` line and before `raw_with_ids = assign_stable_ids(raw)`:

```python
    grades_path = ctx.intermediate_dir / "confidence_grades.json"
    if grades_path.exists():
        grades = json.loads(grades_path.read_text(encoding="utf-8"))
        if grades:
            _apply_grades(raw, grades)
            log.debug("Steps 7–9 — applied %d graded confidence entr(y/ies)", len(grades))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_step_assemble_grading.py -v`
Expected: PASS (all 4 tests).

- [ ] **Step 5: Run the full assemble test suite to check for regressions**

Run: `pytest tests/test_assembler.py -v`
Expected: PASS — confirms `deduplicate_nodes`/`deduplicate_edges` behavior is completely unaffected (this task never touches `assembler.py`).

- [ ] **Step 6: Write an end-to-end-style test through `run_assemble` itself (not just the helper)**

```python
def test_run_assemble_applies_grades_before_dedup(tmp_path):
    from mykg.llm.adapter import LLMAdapter

    class MockAdapter(LLMAdapter):
        def complete(self, *a, **k):
            return "{}"

        def endpoint_label(self):
            return "mock"

    out = tmp_path / "output"
    inter = tmp_path / "intermediate"
    inp = tmp_path / "input"
    for p in (out, inter, inp):
        p.mkdir(parents=True)
    ctx = PipelineContext(input_dir=inp, output_dir=out, intermediate_dir=inter, adapter=MockAdapter())

    raw = {
        "doc.md": {
            "nodes": [
                {
                    "id": "raw-id-ignored",
                    "type": "Person",
                    "confidence": 0.5,
                    "attributes": {"name": {"value": "Alice", "confidence": 0.5}},
                }
            ],
            "edges": [],
        }
    }
    (inter / "raw_extractions.json").write_text(json.dumps(raw))
    # Grade keyed by the STABLE id assign_stable_ids will assign (person-alice),
    # not the raw pre-assembly id — grading runs against pass2's own stable-id
    # scheme (Task 4 built entities from raw_extractions.json's node["id"],
    # which pass2 already assigns via _name_slug/stable_id before this step runs).
    grades = {"person-alice": {"name": 0.97}}
    (inter / "confidence_grades.json").write_text(json.dumps(grades))

    run_assemble(ctx)

    nodes = json.loads((inter / "nodes.json").read_text())
    alice = next(n for n in nodes if n["id"] == "person-alice")
    assert alice["attributes"]["name"]["confidence"] == 0.97
    assert alice["attributes"]["name"]["self_reported_confidence"] == 0.5
```

Add this to `tests/test_step_assemble_grading.py`. Run: `pytest tests/test_step_assemble_grading.py -v` — Expected: PASS (5 tests total now).

- [ ] **Step 7: Commit**

```bash
git add src/mykg/steps/step_assemble.py tests/test_step_assemble_grading.py
git commit -m "feat(assemble): apply graded confidence before dedup

_apply_grades overwrites self-reported confidence with confidence_grades.json
values where a grade exists, preserving the prior value as
self_reported_confidence. Entities/attributes with no grade are untouched.
assembler.py's dedup logic is unchanged — it only reads whatever confidence
value is already on the attribute dict by the time it runs."
```

---

### Task 9: Documentation — CLAUDE.md D16 table + README/config comments

**Files:**
- Modify: `CLAUDE.md` (D16 intermediate-files table)

**Interfaces:**
- Consumes: nothing.
- Produces: documentation reflecting the new intermediate files, matching every other D16 row's format exactly.

- [ ] **Step 1: Add two rows to the D16 table**

In `CLAUDE.md`, immediately after the existing `| \`intermediate/failed_chunks.json\` | ... |` row (the row documenting pass2's output), add:

```markdown
| `intermediate/confidence_grades.json` | After `grade_confidence` (always) | Independently-graded per-attribute confidence, keyed by stable ID: `{stable_id: {attr_name: confidence_float, "__self__": confidence_float}}`. Empty `{}` when `grader.enabled` is false (default). Merged into node/edge confidence by `step_assemble` before dedup |
| `intermediate/confidence_grades_shards/` | During `grade_confidence` (per-file, when enabled) | Per-file confidence-grade shards — one `<slug>.json` per source file containing `{_fname, data}`; mirrors `raw_extractions_shards/`'s shape. Absent entirely when grading is disabled |
```

- [ ] **Step 2: Verify the table still renders as valid Markdown**

Run: `grep -c '^|' CLAUDE.md` before and after to confirm two more `|`-prefixed lines were added and nothing else broke (a quick sanity check, not a real Markdown linter — this repo has no Markdown CI step to run).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add confidence_grades.json / confidence_grades_shards/ to D16 table"
```

---

## Final Integration Check

After all 9 tasks are committed, run the complete relevant test suite once more, in order, before opening a PR or declaring the branch done:

```bash
pytest tests/test_config_grader_profile.py tests/test_typesafe_grader.py \
       tests/test_step_grade_confidence.py tests/test_pipeline_step_order.py \
       tests/test_cli_grader_wiring.py tests/test_delete_from_step_grade_confidence.py \
       tests/test_step_assemble_grading.py -v
```
Expected: all PASS.

Then run the full existing suite to catch anything unrelated broken along the way:

```bash
pytest tests/ -x -q
```
Expected: PASS (or only pre-existing, unrelated failures — verify with `git stash` + re-run if anything looks suspicious).

Finally, confirm the no-op contract holds for a real (non-mocked) default run: with `grader.enabled: false` (the shipped default, untouched), running any existing end-to-end test that exercises the full `STEPS` list (e.g. `tests/test_live_pipeline.py` if it runs without live API calls, or whichever existing test drives `orchestrator.run()` through `validate_graph`) must produce `confidence_grades.json` as `{}` and otherwise identical output to a pre-this-branch run.
