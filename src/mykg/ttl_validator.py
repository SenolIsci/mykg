from __future__ import annotations

import re

from rdflib import RDF, RDFS, Graph, Namespace

from mykg import config as _cfg


def _data_namespace() -> Namespace:
    return Namespace(_cfg.TTL_NAMESPACE_DATA)


def _local(uri) -> str:
    return str(uri).split("/")[-1].split("#")[-1]


def sanitize_abox_ttl(ttl: str, schema: dict) -> str:
    """Remove ABox triples whose predicate is not declared in the schema.

    Strips any line of the form ``data:<id> ex:<pred> data:<id> .`` where
    ``<pred>`` is not in ``schema["properties"][*]["name"]``. TBox lines and
    all other triples are left untouched.
    """
    ex = _cfg.TTL_SCHEMA_PREFIX_LABEL
    data = _cfg.TTL_DATA_PREFIX_LABEL
    declared = {p["name"] for p in schema.get("properties", [])}
    # Match object-property triple lines: data:X ex:PRED data:Y .
    pattern = re.compile(
        rf"^{re.escape(data)}:\S+\s+{re.escape(ex)}:(\S+)\s+{re.escape(data)}:\S+\s+\.$"
    )
    kept = []
    for line in ttl.splitlines():
        m = pattern.match(line.strip())
        if m and m.group(1) not in declared:
            continue
        kept.append(line)
    return "\n".join(kept)


def validate_knowledge_graph_ttl(ttl_content: str) -> dict:
    tbox_errors: list[dict] = []
    abox_errors: list[dict] = []

    g = Graph()
    try:
        g.parse(data=ttl_content, format="turtle")
    except Exception as exc:
        return {
            "valid": False,
            "tbox_checks": {"errors": [{"type": "syntax_error", "message": str(exc)}]},
            "abox_checks": {"errors": []},
        }

    DATA = _data_namespace()
    declared_classes = {s for s, _, _ in g.triples((None, RDF.type, RDFS.Class))}
    declared_properties = {s for s, _, _ in g.triples((None, RDF.type, RDF.Property))}

    # TBox checks
    for s, _, _ in g.triples((None, RDF.type, RDF.Property)):
        domain_node = g.value(s, RDFS.domain)
        range_node = g.value(s, RDFS.range)
        if domain_node and domain_node not in declared_classes:
            tbox_errors.append(
                {"type": "undefined_domain", "message": f"domain {_local(domain_node)} undeclared"}
            )
        if range_node and range_node != RDFS.Literal and range_node not in declared_classes:
            tbox_errors.append(
                {"type": "undefined_range", "message": f"range {_local(range_node)} undeclared"}
            )
    for child, _, parent in g.triples((None, RDFS.subClassOf, None)):
        if parent not in declared_classes:
            tbox_errors.append(
                {"type": "undefined_parent", "message": f"parent {_local(parent)} undeclared"}
            )

    # ABox checks
    for s, _, o in g.triples((None, RDF.type, None)):
        if str(s).startswith(str(DATA)) and o not in declared_classes:
            abox_errors.append(
                {
                    "type": "undeclared_type",
                    "message": f"rdf:type {_local(o)} is not a declared rdfs:Class",
                }
            )

    # External well-known namespaces whose predicates are exempt from undeclared_predicate check.
    # Sourced from config so new external vocabularies can be added without code changes.
    _external_ns = {_cfg.TTL_NAMESPACE_SKOS}

    for s, p, o in g:
        if p in (RDF.type, RDFS.subClassOf, RDFS.domain, RDFS.range):
            continue
        if str(s).startswith(str(DATA)):
            p_str = str(p)
            if any(p_str.startswith(ns) for ns in _external_ns):
                continue
            if p not in declared_properties:
                abox_errors.append(
                    {
                        "type": "undeclared_predicate",
                        "message": f"predicate {_local(p)} is not a declared rdf:Property",
                    }
                )

    all_errors = tbox_errors + abox_errors
    return {
        "valid": len(all_errors) == 0,
        "tbox_checks": {"errors": tbox_errors},
        "abox_checks": {"errors": abox_errors},
    }
