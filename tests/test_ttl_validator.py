from mykg.ttl_validator import sanitize_abox_ttl, validate_knowledge_graph_ttl

VALID_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .
@prefix data: <http://mykg.local/data/> .

ex:Person       rdf:type rdfs:Class .
ex:Organization rdf:type rdfs:Class .

ex:name rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  rdfs:Literal .

ex:works_at rdf:type rdf:Property ;
    rdfs:domain ex:Person ;
    rdfs:range  ex:Organization .

data:alice   rdf:type ex:Person .
data:acme    rdf:type ex:Organization .
data:alice   ex:name "Alice" .
data:alice   ex:works_at data:acme .
"""

UNDECLARED_TYPE_TTL = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .
@prefix data: <http://mykg.local/data/> .

ex:Person rdf:type rdfs:Class .

data:alice rdf:type ex:Ghost .
"""


def test_valid_ttl_passes():
    result = validate_knowledge_graph_ttl(VALID_TTL)
    assert result["valid"] is True
    assert result["abox_checks"]["errors"] == []


def test_undeclared_type_fails():
    result = validate_knowledge_graph_ttl(UNDECLARED_TYPE_TTL)
    assert result["valid"] is False
    assert any("Ghost" in e["message"] for e in result["abox_checks"]["errors"])


def test_result_always_has_tbox_and_abox():
    result = validate_knowledge_graph_ttl(VALID_TTL)
    assert "tbox_checks" in result
    assert "abox_checks" in result
    assert "errors" in result["tbox_checks"]
    assert "errors" in result["abox_checks"]


def test_sanitize_abox_ttl_drops_undeclared_predicate_lines():
    """sanitize_abox_ttl drops object-property triples whose predicate is not declared (line 36)."""
    ttl = (
        "@prefix ex: <http://mykg.local/schema/> .\n"
        "@prefix data: <http://mykg.local/data/> .\n"
        "data:alice ex:works_at data:acme .\n"
        "data:alice ex:unknown_pred data:bob .\n"
    )
    schema = {"properties": [{"name": "works_at", "domain": "Person", "range": "Org"}]}
    cleaned = sanitize_abox_ttl(ttl, schema)
    assert "ex:works_at" in cleaned
    assert "ex:unknown_pred" not in cleaned


def test_validate_returns_syntax_error_on_bad_ttl():
    """Invalid Turtle returns a syntax_error tbox entry (lines 48-53)."""
    result = validate_knowledge_graph_ttl("this is %% not valid ttl")
    assert result["valid"] is False
    assert any(e["type"] == "syntax_error" for e in result["tbox_checks"]["errors"])


UNDEFINED_DOMAIN_AND_RANGE_TBOX = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Organization rdf:type rdfs:Class .

ex:works_at rdf:type rdf:Property ;
    rdfs:domain ex:NotAClass ;
    rdfs:range  ex:AnotherNotAClass .
"""


def test_validate_tbox_undefined_domain_and_range_errors():
    """Validator returns undefined_domain + undefined_range when class refs are undeclared (lines 63-70)."""
    result = validate_knowledge_graph_ttl(UNDEFINED_DOMAIN_AND_RANGE_TBOX)
    assert result["valid"] is False
    tbox = result["tbox_checks"]["errors"]
    assert any(e["type"] == "undefined_domain" for e in tbox)
    assert any(e["type"] == "undefined_range" for e in tbox)


UNDEFINED_PARENT_TBOX = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .

ex:Person rdf:type rdfs:Class .

ex:Engineer rdf:type rdfs:Class ;
    rdfs:subClassOf ex:UnknownParent .
"""


def test_validate_tbox_undefined_parent_error():
    """subClassOf parent that is not declared produces undefined_parent error (lines 71-75)."""
    result = validate_knowledge_graph_ttl(UNDEFINED_PARENT_TBOX)
    assert result["valid"] is False
    tbox = result["tbox_checks"]["errors"]
    assert any(e["type"] == "undefined_parent" for e in tbox)


UNDECLARED_PREDICATE_ABOX = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .
@prefix data: <http://mykg.local/data/> .

ex:Person rdf:type rdfs:Class .

data:alice rdf:type ex:Person .
data:alice ex:nope_predicate "value" .
"""


def test_validate_abox_undeclared_predicate_error():
    """ABox triples with an undeclared predicate are flagged (lines 98-104)."""
    result = validate_knowledge_graph_ttl(UNDECLARED_PREDICATE_ABOX)
    assert result["valid"] is False
    abox = result["abox_checks"]["errors"]
    assert any(e["type"] == "undeclared_predicate" for e in abox)


SKOS_EXEMPT_ABOX = """\
@prefix rdf:  <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix ex:   <http://mykg.local/schema/> .
@prefix data: <http://mykg.local/data/> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Person rdf:type rdfs:Class .

data:alice rdf:type ex:Person .
data:alice skos:altLabel "Allie" .
"""


def test_validate_abox_skos_predicate_is_exempt():
    """SKOS namespace predicates skip the undeclared_predicate check (lines 96-97)."""
    result = validate_knowledge_graph_ttl(SKOS_EXEMPT_ABOX)
    # SKOS predicate should NOT generate an undeclared_predicate error
    abox = result["abox_checks"]["errors"]
    assert not any(e["type"] == "undeclared_predicate" for e in abox)
