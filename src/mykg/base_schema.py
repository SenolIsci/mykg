from __future__ import annotations

from rdflib import OWL, RDF, RDFS, Graph


class BaseSchemaError(Exception):
    pass


def _local(uri) -> str:
    return str(uri).split("/")[-1].split("#")[-1]


def _extract_class(s, g, locked_classes: dict[str, dict]) -> None:
    name = _local(s)
    if name in locked_classes:
        return
    parent_node = g.value(s, RDFS.subClassOf)
    parent = _local(parent_node) if parent_node else None
    locked_classes[name] = {"type": name, "parent": parent, "attributes": []}


def _extract_datatype_property(s, g, locked_classes: dict[str, dict], seen: set[str]) -> None:
    name = _local(s)
    if name in seen:
        return
    seen.add(name)
    domain_nodes = list(g.objects(s, RDFS.domain))
    for domain_node in domain_nodes:
        domain = _local(domain_node)
        if domain in locked_classes:
            locked_classes[domain]["attributes"].append(name)


def _extract_object_property(s, g, locked_properties: dict[str, dict]) -> None:
    name = _local(s)
    if name in locked_properties:
        return
    domain_nodes = list(g.objects(s, RDFS.domain))
    range_node = g.value(s, RDFS.range)
    range_ = _local(range_node) if range_node and range_node != RDFS.Literal else None
    domain_node = domain_nodes[0] if domain_nodes else None
    domain = _local(domain_node) if domain_node else None
    locked_properties[name] = {
        "name": name,
        "domain": domain,
        "range": range_,
        "attributes": [],
    }


def parse_base_schema(ttl_content: str) -> dict:
    g = Graph()
    try:
        g.parse(data=ttl_content, format="turtle")
    except Exception as exc:
        raise BaseSchemaError(f"Failed to parse base schema TTL: {exc}") from exc

    locked_classes: dict[str, dict] = {}
    locked_properties: dict[str, dict] = {}
    seen_datatype: set[str] = set()

    # RDFS classes, then OWL classes (skip duplicates)
    for s, _, _ in g.triples((None, RDF.type, RDFS.Class)):
        _extract_class(s, g, locked_classes)
    for s, _, _ in g.triples((None, RDF.type, OWL.Class)):
        _extract_class(s, g, locked_classes)

    # RDFS properties (heuristic: range == rdfs:Literal → datatype, else object)
    for s, _, _ in g.triples((None, RDF.type, RDF.Property)):
        name = _local(s)
        if name in locked_properties or name in seen_datatype:
            continue
        range_node = g.value(s, RDFS.range)
        if range_node == RDFS.Literal:
            _extract_datatype_property(s, g, locked_classes, seen_datatype)
        else:
            _extract_object_property(s, g, locked_properties)

    # OWL properties (type declaration is definitive, no range heuristic needed)
    for s, _, _ in g.triples((None, RDF.type, OWL.ObjectProperty)):
        _extract_object_property(s, g, locked_properties)
    for s, _, _ in g.triples((None, RDF.type, OWL.DatatypeProperty)):
        _extract_datatype_property(s, g, locked_classes, seen_datatype)

    return {"locked_classes": locked_classes, "locked_properties": locked_properties}
