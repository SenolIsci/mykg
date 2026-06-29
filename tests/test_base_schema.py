import pytest

from mykg.base_schema import BaseSchemaError, parse_base_schema

VALID_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Vehicle    rdf:type rdfs:Class .
ex:ElectricCar rdf:type rdfs:Class .
ex:ElectricCar rdfs:subClassOf ex:Vehicle .

ex:name rdf:type rdf:Property ;
    rdfs:domain ex:Vehicle ;
    rdfs:range  rdfs:Literal .

ex:manufactured_by rdf:type rdf:Property ;
    rdfs:domain ex:Vehicle ;
    rdfs:range  ex:Manufacturer .

ex:Manufacturer rdf:type rdfs:Class .
"""

INVALID_TTL = "not turtle at all %%"


def test_parse_valid_ttl_returns_classes():
    result = parse_base_schema(VALID_TTL)
    assert "Vehicle" in result["locked_classes"]
    assert "ElectricCar" in result["locked_classes"]
    assert "Manufacturer" in result["locked_classes"]


def test_parse_valid_ttl_class_parent():
    result = parse_base_schema(VALID_TTL)
    assert result["locked_classes"]["ElectricCar"]["parent"] == "Vehicle"
    assert result["locked_classes"]["Vehicle"]["parent"] is None


def test_parse_valid_ttl_class_attributes():
    result = parse_base_schema(VALID_TTL)
    assert "name" in result["locked_classes"]["Vehicle"]["attributes"]


def test_parse_valid_ttl_object_property():
    result = parse_base_schema(VALID_TTL)
    assert "manufactured_by" in result["locked_properties"]
    prop = result["locked_properties"]["manufactured_by"]
    assert prop["domain"] == "Vehicle"
    assert prop["range"] == "Manufacturer"


def test_parse_invalid_ttl_raises():
    with pytest.raises(BaseSchemaError):
        parse_base_schema(INVALID_TTL)


# ---------------------------------------------------------------------------
# OWL ontology support (D54)
# ---------------------------------------------------------------------------

OWL_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person       a owl:Class .
ex:Organization a owl:Class .
ex:Employee     a owl:Class ; rdfs:subClassOf ex:Person .

ex:name a owl:DatatypeProperty ;
    rdfs:domain ex:Person ;
    rdfs:range  rdfs:Literal .

ex:works_at a owl:ObjectProperty ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organization .
"""


def test_parse_owl_class():
    result = parse_base_schema(OWL_TTL)
    assert "Person" in result["locked_classes"]
    assert "Organization" in result["locked_classes"]
    assert "Employee" in result["locked_classes"]
    assert result["locked_classes"]["Employee"]["parent"] == "Person"
    assert result["locked_classes"]["Person"]["parent"] is None


def test_parse_owl_object_property():
    result = parse_base_schema(OWL_TTL)
    assert "works_at" in result["locked_properties"]
    prop = result["locked_properties"]["works_at"]
    assert prop["domain"] == "Person"
    assert prop["range"] == "Organization"


def test_parse_owl_datatype_property():
    result = parse_base_schema(OWL_TTL)
    assert "name" in result["locked_classes"]["Person"]["attributes"]
    assert "name" not in result["locked_properties"]


def test_parse_mixed_rdfs_owl():
    mixed = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person a rdfs:Class .
ex:Organization a owl:Class .
ex:Person a owl:Class .

ex:name a rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  rdfs:Literal .

ex:works_at a owl:ObjectProperty ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organization .
"""
    result = parse_base_schema(mixed)
    assert "Person" in result["locked_classes"]
    assert "Organization" in result["locked_classes"]
    assert len([k for k in result["locked_classes"] if k == "Person"]) == 1
    assert "name" in result["locked_classes"]["Person"]["attributes"]
    assert "works_at" in result["locked_properties"]
