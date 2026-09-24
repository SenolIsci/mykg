import json

from mykg.chunker import Chunk
from mykg.llm.adapter import LLMAdapter
from mykg.pass1 import run_pass1

VALID_PROPOSAL = json.dumps(
    {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name"]},
        ],
        "properties": [],
    }
)

CHUNKS = [
    Chunk(
        source_file="a.md", chunk_index=0, text="Alice works at Acme.", token_start=0, token_end=10
    ),
]


class _MockAdapter(LLMAdapter):
    def __init__(self, response: str):
        self._response = response

    def complete(
        self,
        system: str,
        user: str,
        context_label: str = "",
        max_tokens: int | None = None,
        timeout: int | None = None,
        temperature: float | None = None,
    ) -> str:
        return self._response

    def endpoint_label(self) -> str:
        return "mock"


def test_pass1_process_batch_creates_span(span_exporter):
    adapter = _MockAdapter(VALID_PROPOSAL)
    run_pass1(CHUNKS, adapter, locked_schema_block="")

    spans = span_exporter.get_finished_spans()
    batch_spans = [s for s in spans if s.name == "mykg.pass1.batch"]
    assert len(batch_spans) == 1
    assert batch_spans[0].attributes["mykg.batch.index"] == 1
    assert batch_spans[0].attributes["mykg.batch.chunk_count"] == 1


def test_pass1_process_batch_span_records_error_on_bad_json(span_exporter):
    adapter = _MockAdapter("not json {")
    run_pass1(CHUNKS, adapter, locked_schema_block="")

    spans = span_exporter.get_finished_spans()
    batch_spans = [s for s in spans if s.name == "mykg.pass1.batch"]
    assert len(batch_spans) == 1
    from opentelemetry.trace import StatusCode

    assert batch_spans[0].status.status_code == StatusCode.ERROR


def test_pass2_process_file_creates_span(span_exporter):
    from mykg.pass2 import run_pass2

    schema = {
        "concepts": [{"type": "Person", "parent": None, "attributes": ["name"]}],
        "properties": [],
    }
    flat_schema = {"Person": ["name"]}
    extraction = {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.9,
                "attributes": {"name": {"value": "Alice", "confidence": 0.9}},
            }
        ],
        "edges": [],
    }
    adapter = _MockAdapter(json.dumps(extraction))
    files = {"team.md": "Alice works at Acme."}

    run_pass2(files, schema, flat_schema, adapter)

    spans = span_exporter.get_finished_spans()
    file_spans = [s for s in spans if s.name == "mykg.pass2.file"]
    assert len(file_spans) == 1
    assert file_spans[0].attributes["mykg.file.name"] == "team.md"


def test_orphan_confirm_one_creates_span(span_exporter):
    from unittest.mock import MagicMock

    from mykg.orphan_connector import OrphanCandidate, confirm_orphan_edges

    schema = {
        "concepts": [
            {"type": "Person", "attributes": ["name"], "parent": None},
            {"type": "Organization", "attributes": ["name"], "parent": None},
        ],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
        ],
    }
    candidate = OrphanCandidate(
        orphan_id="person-bob",
        orphan_type="Person",
        orphan_name="Bob",
        candidate_id="org-acme",
        candidate_type="Organization",
        candidate_name="Acme",
        cooccurrence_count=3,
        heuristic_score=0.6,
        shared_chunks=["f.md::1"],
    )
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        {"connected": True, "type": "works_at", "confidence": 0.85, "rationale": "r"}
    )

    confirm_orphan_edges([candidate], schema, adapter, max_workers=1)

    spans = span_exporter.get_finished_spans()
    confirm_spans = [s for s in spans if s.name == "mykg.orphan.confirm"]
    assert len(confirm_spans) == 1
    assert confirm_spans[0].attributes["mykg.orphan.orphan_id"] == "person-bob"
    assert confirm_spans[0].attributes["mykg.orphan.candidate_id"] == "org-acme"


def test_pass2_validation_error_recorded_as_span_event(span_exporter):
    """A chunk that fails schema validation records a
    pass2.chunk.validation_errors event on the enclosing batch/file span,
    not just a log line."""
    from mykg.pass2 import run_pass2

    schema = {
        "concepts": [
            {"type": "Person", "parent": None, "attributes": ["name", "email"]},
            {"type": "Organization", "parent": None, "attributes": ["name"]},
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
    flat_schema = {"Person": ["name", "email"], "Organization": ["name"]}

    valid_extraction = {
        "nodes": [
            {
                "id": "person-alice",
                "type": "Person",
                "confidence": 0.97,
                "attributes": {
                    "name": {"value": "Alice", "confidence": 0.99},
                    "email": {"value": "alice@acme.com", "confidence": 0.97},
                },
            },
            {
                "id": "org-acme",
                "type": "Organization",
                "confidence": 0.99,
                "attributes": {"name": {"value": "Acme", "confidence": 0.99}},
            },
        ],
        "edges": [
            {
                "id": "edge-001",
                "type": "works_at",
                "from": "person-alice",
                "to": "org-acme",
                "confidence": 0.96,
                "attributes": {"role": {"value": "engineer", "confidence": 0.91}},
            }
        ],
    }
    bad_extraction = {
        "nodes": valid_extraction["nodes"],
        "edges": [
            {
                "id": "edge-001",
                "type": "INVALID_TYPE",
                "from": "person-alice",
                "to": "org-acme",
                "confidence": 0.8,
                "attributes": {"role": {"value": "eng", "confidence": 0.8}},
            }
        ],
    }

    calls = []

    class _RetryAdapter(LLMAdapter):
        def complete(
            self,
            system,
            user,
            context_label="",
            max_tokens=None,
            timeout=None,
            temperature=None,
        ):
            calls.append(1)
            if len(calls) == 1:
                return json.dumps(bad_extraction)
            return json.dumps(valid_extraction)

        def endpoint_label(self) -> str:
            return "mock-retry"

    run_pass2({"test.md": "content"}, schema, flat_schema, _RetryAdapter())

    spans = span_exporter.get_finished_spans()
    file_spans = [s for s in spans if s.name == "mykg.pass2.file"]
    assert len(file_spans) == 1
    events = file_spans[0].events
    validation_events = [e for e in events if e.name == "pass2.chunk.validation_errors"]
    assert len(validation_events) == 1
    assert validation_events[0].attributes["mykg.chunk_index"] == 1
    assert any("INVALID_TYPE" in e for e in validation_events[0].attributes["mykg.errors"])


def test_orphan_process_group_creates_span(span_exporter):
    from unittest.mock import MagicMock

    from mykg.orphan_connector import OrphanChunkGroup, confirm_orphan_chunk_groups

    schema = {
        "concepts": [
            {"type": "Person", "attributes": ["name"], "parent": None},
            {"type": "Organization", "attributes": ["name"], "parent": None},
        ],
        "properties": [
            {"name": "works_at", "domain": "Person", "range": "Organization", "attributes": []}
        ],
    }
    group = OrphanChunkGroup(
        chunk_key="input.md::1",
        filename="input.md",
        chunk_idx=1,
        is_blank_response=False,
        orphan_ids=["person-bob"],
        connected_ids=["org-acme"],
    )
    nodes = [
        {
            "id": "person-bob",
            "type": "Person",
            "confidence": 0.9,
            "attributes": {"name": {"value": "Bob", "confidence": 0.9}},
            "source_files": ["input.md"],
        },
        {
            "id": "org-acme",
            "type": "Organization",
            "confidence": 0.9,
            "attributes": {"name": {"value": "Acme", "confidence": 0.9}},
            "source_files": ["input.md"],
        },
    ]
    chunk_texts = {"input.md::1": "Bob works at Acme Corp."}
    adapter = MagicMock()
    adapter.complete.return_value = json.dumps(
        [
            {
                "type": "works_at",
                "from": "person-bob",
                "to": "org-acme",
                "confidence": 0.9,
                "rationale": "Bob works at Acme Corp.",
            }
        ]
    )

    confirm_orphan_chunk_groups([group], nodes, schema, adapter, chunk_texts=chunk_texts)

    spans = span_exporter.get_finished_spans()
    group_spans = [s for s in spans if s.name == "mykg.orphan.group"]
    assert len(group_spans) == 1
    assert group_spans[0].attributes["mykg.orphan.chunk_key"] == "input.md::1"
    assert group_spans[0].attributes["mykg.orphan.count"] == 1
