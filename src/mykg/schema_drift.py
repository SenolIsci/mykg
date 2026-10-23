"""schema_drift — detect declared-but-unused schema entries and prune them.

Schema drift is the gap between the induced vocabulary (``schema.json``) and the
graph that actually uses it: a concept with no instances, a property with no
edges. Everything here is deterministic and LLM-free. Nodes and edges are only
ever read; pruning rewrites ``schema.json`` (plus ``schema.ttl`` and a history
delta) and nothing else.

Classification of each declared entry (first match wins):
    used        — has instances / edges
    locked      — declared by the user-supplied base schema (D27); never pruned
    structural  — zero own instances but kept: an instantiated descendant, an
                  endpoint (domain/range) of a surviving property, or a
                  surviving child. There is no re-parenting, so a concept is
                  prunable only when its whole subtree is.
    prunable    — none of the above

A property survives when it is locked or has at least one edge; a zero-edge
unlocked property is prunable, which also covers the cascade from a removed
domain/range concept.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from mykg.logging import get
from mykg.schema_flattener import flatten_schema
from mykg.schema_history import TRIGGER_SCHEMA_PRUNE, write_schema
from mykg.utility.atomic_io import atomic_write_json, atomic_write_lines

log = get("mykg.schema_drift")

DRIFT_FILE = "schema_drift.json"
PLAN_FILE = "schema_prune_plan.json"
BACKUP_FILE = "schema.pre_prune.json"

Classification = Literal["used", "locked", "structural", "prunable"]
Kind = Literal["concept", "property"]


class SchemaDriftError(Exception):
    """Raised when a drift report, plan or apply cannot proceed safely."""


def _locked_names(entries: Any, key: str) -> set[str]:
    """Names from a parsed locked block: a name-keyed dict (as ``parse_base_schema``
    emits) or a list of names / entry dicts. Any other shape raises
    ``SchemaDriftError``."""
    if entries is None:
        return set()
    if isinstance(entries, dict):
        return {str(n) for n in entries}
    if not isinstance(entries, list):
        raise SchemaDriftError(
            "base_schema_parsed.json: locked block must be an object or list, "
            f"got {type(entries).__name__}"
        )
    names: set[str] = set()
    for e in entries:
        if isinstance(e, str):
            names.add(e)
        elif isinstance(e, dict) and isinstance(e.get(key), str):
            names.add(e[key])
        else:
            raise SchemaDriftError(
                f"base_schema_parsed.json: locked entry {e!r} must be a string or an "
                f"object with a string '{key}'"
            )
    return names


class LockedSchema(BaseModel):
    """Names locked by the base schema (D27)."""

    classes: set[str] = Field(default_factory=set)
    properties: set[str] = Field(default_factory=set)

    @classmethod
    def from_parsed(cls, parsed: dict | None) -> LockedSchema:
        """Build from ``base_schema_parsed.json`` content; None/empty -> no locks."""
        parsed = parsed or {}
        if not isinstance(parsed, dict):
            raise SchemaDriftError(
                f"base_schema_parsed.json must be a JSON object, got {type(parsed).__name__}"
            )
        return cls(
            classes=_locked_names(parsed.get("locked_classes"), "type"),
            properties=_locked_names(parsed.get("locked_properties"), "name"),
        )


class ConceptDrift(BaseModel):
    name: str
    parent: str | None = None
    instance_count: int = 0
    subtree_count: int = 0
    classification: Classification
    reason: str
    always_null_attributes: list[str] = Field(default_factory=list)


class PropertyDrift(BaseModel):
    name: str
    domain: str | None = None
    range: str | None = None
    edge_count: int = 0
    classification: Classification
    reason: str


class DriftReport(BaseModel):
    timestamp: str
    schema_fingerprint: str
    concepts: list[ConceptDrift]
    properties: list[PropertyDrift]
    undeclared_node_types: dict[str, int] = Field(default_factory=dict)
    undeclared_edge_types: dict[str, int] = Field(default_factory=dict)

    def unused_concepts(self) -> list[ConceptDrift]:
        return [c for c in self.concepts if c.classification != "used"]

    def unused_properties(self) -> list[PropertyDrift]:
        return [p for p in self.properties if p.classification != "used"]


class PlanEntry(BaseModel):
    kind: Kind
    name: str
    reason: str = ""


class PlanTotals(BaseModel):
    concepts: int
    properties: int


class PruneTotals(BaseModel):
    before: PlanTotals
    after: PlanTotals


class PrunePlan(BaseModel):
    schema_fingerprint: str
    created_at: str
    remove: list[PlanEntry] = Field(default_factory=list)
    keep: list[PlanEntry] = Field(default_factory=list)
    totals: PruneTotals


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stream_jsonl(path: Path) -> Iterator[dict]:
    """Yield one dict per non-blank JSONL line, streaming (Invariant 19).

    A missing or corrupt file, or a row that is not a JSON object, raises ``SchemaDriftError``: an absent export must
    not read as "zero instances", which would make every entry look prunable.
    """
    path = Path(path)
    if not path.exists():
        raise SchemaDriftError(f"{path} not found; run the pipeline to completion first")
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SchemaDriftError(f"{path}:{lineno} is not valid JSON: {exc}") from exc
            if not isinstance(row, dict):
                raise SchemaDriftError(
                    f"{path}:{lineno} must be a JSON object, got {type(row).__name__}"
                )
            yield row


def _is_null(attr: Any) -> bool:
    value = attr.get("value") if isinstance(attr, dict) else attr
    return value is None


def _fingerprint(
    schema: dict, node_counts: dict, edge_counts: dict, locked: LockedSchema | None = None
) -> str:
    """Digest of schema + per-type counts + the locked name sets, so a plan or
    record goes stale when the graph, the schema or the base-schema locks change."""
    locked = locked or LockedSchema()
    payload = {
        "schema": schema,
        "locked_classes": sorted(locked.classes),
        "locked_properties": sorted(locked.properties),
        "node_counts": {str(k): v for k, v in sorted(node_counts.items(), key=lambda x: str(x[0]))},
        "edge_counts": {str(k): v for k, v in sorted(edge_counts.items(), key=lambda x: str(x[0]))},
    }
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _ancestors(name: str, parents: dict[str, str | None]) -> list[str]:
    """Declared ancestors of ``name``, nearest first; stops at a parent cycle."""
    out: list[str] = []
    seen = {name}
    cur = parents.get(name)
    while cur is not None and cur in parents and cur not in seen:
        out.append(cur)
        seen.add(cur)
        cur = parents[cur]
    return out


def _check_schema_shape(schema: Any) -> None:
    """Raise ``SchemaDriftError`` unless ``schema`` has well-formed entries."""
    if not isinstance(schema, dict):
        raise SchemaDriftError(f"schema must be a JSON object, got {type(schema).__name__}")
    for key, name_key in (("concepts", "type"), ("properties", "name")):
        entries = schema.get(key, [])
        if not isinstance(entries, list):
            raise SchemaDriftError(f"schema '{key}' must be a list")
        for i, e in enumerate(entries):
            if not isinstance(e, dict) or not isinstance(e.get(name_key), str):
                raise SchemaDriftError(
                    f"schema {key}[{i}] must be an object with a string '{name_key}'"
                )
            if key == "concepts" and not isinstance(e.get("attributes", []), list):
                raise SchemaDriftError(
                    f"schema concept '{e[name_key]}': 'attributes' must be a list"
                )


def _row_type(row: dict, what: str) -> str | None:
    t = row.get("type")
    if t is not None and not isinstance(t, str):
        raise SchemaDriftError(f"{what} {row.get('id')!r}: 'type' must be a string")
    return t


def analyze_drift(
    schema: dict,
    nodes_iter: Iterable[dict],
    edges_iter: Iterable[dict],
    locked: LockedSchema | None,
) -> DriftReport:
    """Single streaming pass over nodes and edges; classify every schema entry."""
    locked = locked or LockedSchema()
    _check_schema_shape(schema)
    concepts = schema.get("concepts", [])
    properties = schema.get("properties", [])
    parents: dict[str, str | None] = {c["type"]: c.get("parent") for c in concepts}
    own_attrs = {c["type"]: list(c.get("attributes", [])) for c in concepts}

    node_counts: dict[str, int] = {}
    nonnull_attrs: dict[str, set[str]] = {}
    for node in nodes_iter:
        if not isinstance(node, dict):
            raise SchemaDriftError(f"node row must be a JSON object, got {type(node).__name__}")
        t = _row_type(node, "node")
        node_counts[t] = node_counts.get(t, 0) + 1
        seen = nonnull_attrs.setdefault(t, set())
        attrs = node.get("attributes") or {}
        if not isinstance(attrs, dict):
            raise SchemaDriftError(
                f"node {node.get('id')!r}: 'attributes' must be a JSON object, "
                f"got {type(attrs).__name__}"
            )
        for k, v in attrs.items():
            if not _is_null(v):
                seen.add(k)
    edge_counts: dict[str, int] = {}
    for edge in edges_iter:
        if not isinstance(edge, dict):
            raise SchemaDriftError(f"edge row must be a JSON object, got {type(edge).__name__}")
        t = _row_type(edge, "edge")
        edge_counts[t] = edge_counts.get(t, 0) + 1

    # An attribute counts as populated for a concept if any node of it or of a
    # descendant carries a value (subclass nodes carry inherited attributes).
    populated: dict[str, set[str]] = {n: set() for n in parents}
    for t, attrs in nonnull_attrs.items():
        if t in parents:
            for n in (t, *_ancestors(t, parents)):
                populated[n] |= attrs

    instance = {n: node_counts.get(n, 0) for n in parents}
    subtree = dict(instance)
    for n, cnt in instance.items():
        if cnt:
            for anc in _ancestors(n, parents):
                subtree[anc] += cnt

    surviving_props = [
        p for p in properties if p["name"] in locked.properties or edge_counts.get(p["name"], 0) > 0
    ]
    endpoints = {
        end for p in surviving_props for end in (p.get("domain"), p.get("range")) if end in parents
    }
    base_keep = {
        n
        for n in parents
        if instance[n] > 0 or n in locked.classes or subtree[n] > 0 or n in endpoints
    }
    # Parents of kept concepts must stay (no re-parenting).
    keep_parent = {a for n in base_keep for a in _ancestors(n, parents)}

    concept_rows: list[ConceptDrift] = []
    for c in concepts:
        n = c["type"]
        if instance[n] > 0:
            cls, reason = "used", f"{instance[n]} instance(s)"
        elif n in locked.classes:
            cls, reason = "locked", "locked by base schema"
        elif subtree[n] > 0:
            cls, reason = "structural", "has instantiated descendant"
        elif n in endpoints:
            cls, reason = "structural", "domain/range of a surviving property"
        elif n in keep_parent:
            cls, reason = "structural", "has surviving child"
        else:
            cls, reason = "prunable", "0 instances, 0 in subtree"
        nulls = sorted(a for a in own_attrs[n] if a not in populated[n])
        concept_rows.append(
            ConceptDrift(
                name=n,
                parent=c.get("parent"),
                instance_count=instance[n],
                subtree_count=subtree[n],
                classification=cls,
                reason=reason,
                always_null_attributes=nulls if instance[n] > 0 else [],
            )
        )
    removed = {r.name for r in concept_rows if r.classification == "prunable"}

    property_rows: list[PropertyDrift] = []
    for p in properties:
        n = p["name"]
        cnt = edge_counts.get(n, 0)
        if cnt > 0:
            cls, reason = "used", f"{cnt} edge(s)"
        elif n in locked.properties:
            cls, reason = "locked", "locked by base schema"
        else:
            cls = "prunable"
            gone = any(e in removed for e in (p.get("domain"), p.get("range")))
            reason = "0 edges; domain/range removed" if gone else "0 edges"
        property_rows.append(
            PropertyDrift(
                name=n,
                domain=p.get("domain"),
                range=p.get("range"),
                edge_count=cnt,
                classification=cls,
                reason=reason,
            )
        )

    declared_props = {p["name"] for p in properties}
    return DriftReport(
        timestamp=_now(),
        schema_fingerprint=_fingerprint(schema, node_counts, edge_counts, locked),
        concepts=concept_rows,
        properties=property_rows,
        undeclared_node_types={
            str(t): c
            for t, c in sorted(node_counts.items(), key=lambda x: str(x[0]))
            if t not in parents
        },
        undeclared_edge_types={
            str(t): c
            for t, c in sorted(edge_counts.items(), key=lambda x: str(x[0]))
            if t not in declared_props
        },
    )


def record_drift(report: DriftReport, intermediate_dir: Path) -> Path:
    """Atomically write ``intermediate/schema_drift.json``."""
    path = Path(intermediate_dir) / DRIFT_FILE
    atomic_write_json(path, report.model_dump())
    return path


def _derive_keep_totals(
    report: DriftReport, remove: list[PlanEntry]
) -> tuple[list[PlanEntry], PruneTotals]:
    """``keep`` (unused entries not being removed) and ``totals``, both derived from
    ``remove`` and the report; never read from a stored plan."""
    removed = {(e.kind, e.name) for e in remove}
    keep: list[PlanEntry] = []
    for kind, rows in (("concept", report.concepts), ("property", report.properties)):
        for r in rows:
            if r.classification != "used" and (kind, r.name) not in removed:
                keep.append(
                    PlanEntry(kind=kind, name=r.name, reason=f"{r.classification}: {r.reason}")
                )
    n_c, n_p = len(report.concepts), len(report.properties)
    r_c = sum(1 for k, _ in removed if k == "concept")
    r_p = len(removed) - r_c
    totals = PruneTotals(
        before=PlanTotals(concepts=n_c, properties=n_p),
        after=PlanTotals(concepts=n_c - r_c, properties=n_p - r_p),
    )
    return keep, totals


def plan_prune(report: DriftReport) -> PrunePlan:
    """Plan removing every ``prunable`` entry; other unused entries go to ``keep``."""
    remove = [
        PlanEntry(kind=kind, name=r.name, reason=r.reason)
        for kind, rows in (("concept", report.concepts), ("property", report.properties))
        for r in rows
        if r.classification == "prunable"
    ]
    keep, totals = _derive_keep_totals(report, remove)
    return PrunePlan(
        schema_fingerprint=report.schema_fingerprint,
        created_at=_now(),
        remove=remove,
        keep=keep,
        totals=totals,
    )


def write_plan(plan: PrunePlan, intermediate_dir: Path) -> Path:
    """Atomically write ``intermediate/schema_prune_plan.json``."""
    path = Path(intermediate_dir) / PLAN_FILE
    atomic_write_json(path, plan.model_dump())
    return path


def load_plan(path: Path) -> PrunePlan:
    """Parse and validate a (possibly hand-edited) plan file."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SchemaDriftError(f"Cannot read plan {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SchemaDriftError(f"Plan {path} is not valid JSON: {exc}") from exc
    try:
        return PrunePlan.model_validate(raw)
    except ValidationError as exc:
        raise SchemaDriftError(f"Plan {path} is malformed: {exc}") from exc


def _check_dangling(
    concepts: list[dict], properties: list[dict], rm_c: set[str], rm_p: set[str]
) -> None:
    """Reject removing a concept that a kept property or kept child still references."""
    for p in properties:
        if p["name"] in rm_p:
            continue
        for end in (p.get("domain"), p.get("range")):
            if end in rm_c:
                raise SchemaDriftError(
                    f"Cannot remove concept '{end}': kept property '{p['name']}' "
                    "uses it as domain/range"
                )
    for c in concepts:
        if c["type"] not in rm_c and c.get("parent") in rm_c:
            raise SchemaDriftError(
                f"Cannot remove concept '{c['parent']}': kept concept '{c['type']}' "
                "has it as parent"
            )


def validate_plan(plan: PrunePlan, report: DriftReport) -> None:
    """Check ``plan`` against a freshly computed ``report``; raise on any problem."""
    if plan.schema_fingerprint != report.schema_fingerprint:
        raise SchemaDriftError(
            "Plan is stale or belongs to another session (schema/instance fingerprint "
            "mismatch); re-run the preview"
        )
    rows: dict[str, dict[str, Any]] = {
        "concept": {r.name: r for r in report.concepts},
        "property": {r.name: r for r in report.properties},
    }
    rm_c: set[str] = set()
    rm_p: set[str] = set()
    for e in plan.remove:
        row = rows[e.kind].get(e.name)
        if row is None:
            raise SchemaDriftError(f"{e.kind} '{e.name}' is not in the schema")
        if row.classification != "prunable":
            raise SchemaDriftError(
                f"{e.kind} '{e.name}' cannot be pruned: it is {row.classification} ({row.reason})"
            )
        (rm_c if e.kind == "concept" else rm_p).add(e.name)
    _check_dangling(
        [{"type": r.name, "parent": r.parent} for r in report.concepts],
        [{"name": r.name, "domain": r.domain, "range": r.range} for r in report.properties],
        rm_c,
        rm_p,
    )


def recompute_plan(plan: PrunePlan, report: DriftReport) -> PrunePlan:
    """Validate ``plan`` against ``report``; return a copy whose ``keep`` and
    ``totals`` are recomputed from the validated ``remove`` list (duplicates
    dropped). The stored values of a loaded, possibly hand-edited plan are
    informational and ignored."""
    validate_plan(plan, report)
    seen: set[tuple[str, str]] = set()
    remove: list[PlanEntry] = []
    reasons = {
        "concept": {r.name: r.reason for r in report.concepts},
        "property": {r.name: r.reason for r in report.properties},
    }
    for e in plan.remove:
        if (e.kind, e.name) not in seen:
            seen.add((e.kind, e.name))
            # Reasons come from the report: the plan's own text is informational.
            remove.append(e.model_copy(update={"reason": reasons[e.kind][e.name]}))
    keep, totals = _derive_keep_totals(report, remove)
    return plan.model_copy(update={"remove": remove, "keep": keep, "totals": totals})


def apply_prune(plan: PrunePlan, intermediate_dir: Path, report: DriftReport) -> dict:
    """Apply ``plan`` to ``schema.json``; returns the pruned schema.

    ``report`` (freshly computed from the current graph) is required: the plan is
    always run through ``validate_plan`` first (fingerprint, locked / structural /
    used checks), so a stale or hand-edited plan can never remove an entry the
    graph uses. An empty ``plan.remove`` returns the unchanged schema immediately:
    no backup, no history entry, no write.

    The backup ``schema.pre_prune.json`` holds the schema as it was before the
    most recent prune (a second prune overwrites it). The pruned schema is
    validated in memory first; any problem aborts with nothing written. Only
    schema.json / schema.ttl / flattened_schema.json / history / the backup are
    touched; nodes, edges and shards never are.

    ``flattened_schema.json`` is regenerated from the pruned schema only if it
    already exists (a session that never flattened has nothing stale; the
    ``schema_flatten`` step creates it later).

    Crash window: the writes are not one transaction. They are ordered so a re-run
    is idempotent: backup, then the derived files (``schema.ttl``,
    ``flattened_schema.json``; each written atomically), then ``schema.json`` plus
    its history delta last. A crash before ``schema.json`` lands leaves the old
    schema authoritative; re-running the prune (preview + apply) redoes it all and
    rewrites the derived files identically. A crash after ``schema.json`` but
    before the history delta only loses that audit record, and
    ``mykg approve-schema`` regenerates ``schema.ttl`` if it is ever stale.
    Concurrent writers are not serialized (the CLI refuses to run while a step is
    running).
    """
    from mykg.exporter import export_ttl
    from mykg.schema_validator import validate_schema_ttl

    plan = recompute_plan(plan, report)
    intermediate_dir = Path(intermediate_dir)
    schema_path = intermediate_dir / "schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaDriftError(f"Cannot read {schema_path}: {exc}") from exc
    _check_schema_shape(schema)
    if {c["type"] for c in schema.get("concepts", [])} != {r.name for r in report.concepts} or {
        p["name"] for p in schema.get("properties", [])
    } != {r.name for r in report.properties}:
        raise SchemaDriftError(
            "schema.json changed since the drift report was computed; re-run the preview"
        )

    if not plan.remove:
        log.info("schema_drift — nothing to prune")
        return schema

    declared_c = {c["type"] for c in schema.get("concepts", [])}
    declared_p = {p["name"] for p in schema.get("properties", [])}
    rm_c = {e.name for e in plan.remove if e.kind == "concept"}
    rm_p = {e.name for e in plan.remove if e.kind == "property"}
    for kind, names, declared in (("concept", rm_c, declared_c), ("property", rm_p, declared_p)):
        missing = sorted(names - declared)
        if missing:
            raise SchemaDriftError(f"{kind} '{missing[0]}' is not in the schema")
    _check_dangling(schema.get("concepts", []), schema.get("properties", []), rm_c, rm_p)

    pruned = dict(schema)
    pruned["concepts"] = [c for c in schema.get("concepts", []) if c["type"] not in rm_c]
    pruned["properties"] = [p for p in schema.get("properties", []) if p["name"] not in rm_p]

    ttl = export_ttl(pruned, [], {})
    result = validate_schema_ttl(ttl)
    if not result.valid:
        raise SchemaDriftError(f"Pruned schema failed validation: {result.errors}")
    flat = flatten_schema(pruned)

    shutil.copy2(schema_path, intermediate_dir / BACKUP_FILE)
    atomic_write_lines(intermediate_dir / "schema.ttl", ttl.rstrip("\n").split("\n"))
    flat_path = intermediate_dir / "flattened_schema.json"
    if flat_path.exists():
        atomic_write_json(flat_path, flat)
    write_schema(
        pruned,
        intermediate_dir,
        TRIGGER_SCHEMA_PRUNE,
        extra={
            "pruned": [{"kind": e.kind, "name": e.name, "reason": e.reason} for e in plan.remove]
        },
    )
    log.info("schema_drift — pruned %d concept(s), %d property(ies)", len(rm_c), len(rm_p))
    return pruned
