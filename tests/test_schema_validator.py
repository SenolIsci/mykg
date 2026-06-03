from mykg.schema_validator import validate_schema_ttl

VALID_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person       rdf:type rdfs:Class .
ex:Organization rdf:type rdfs:Class .

ex:name rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  rdfs:Literal .

ex:works_at rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organization .
"""

UNDEFINED_RANGE_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person rdf:type rdfs:Class .

ex:works_at rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organisation .
"""

BAD_SYNTAX_TTL = "not turtle %%"


def test_valid_ttl_is_valid():
    result = validate_schema_ttl(VALID_TTL)
    assert result.valid is True
    assert result.errors == []


def test_undefined_range_detected():
    result = validate_schema_ttl(UNDEFINED_RANGE_TTL)
    assert result.valid is False
    assert any("Organisation" in e["message"] for e in result.errors)


def test_syntax_error_detected():
    result = validate_schema_ttl(BAD_SYNTAX_TTL)
    assert result.valid is False
    assert any(e["type"] == "syntax_error" for e in result.errors)


def test_result_has_error_fields():
    result = validate_schema_ttl(UNDEFINED_RANGE_TTL)
    err = result.errors[0]
    assert "type" in err
    assert "message" in err


UNDEFINED_DOMAIN_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Organization rdf:type rdfs:Class .

ex:works_at rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organization .
"""

UNDEFINED_PARENT_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person rdf:type rdfs:Class .

ex:SoftwareEngineer rdf:type rdfs:Class ;
    rdfs:subClassOf ex:Worker .
"""


def test_undefined_domain_detected():
    """domain that refers to an undeclared class generates an undefined_domain error (line 32-38)."""
    result = validate_schema_ttl(UNDEFINED_DOMAIN_TTL)
    assert result.valid is False
    assert any(e["type"] == "undefined_domain" for e in result.errors)
    assert any("Person" in e["message"] for e in result.errors)


def test_undefined_parent_detected():
    """subClassOf parent that is not declared generates an undefined_parent error (lines 50-59)."""
    result = validate_schema_ttl(UNDEFINED_PARENT_TTL)
    assert result.valid is False
    assert any(e["type"] == "undefined_parent" for e in result.errors)
    assert any("Worker" in e["message"] for e in result.errors)
