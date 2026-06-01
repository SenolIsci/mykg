## System

You are a knowledge graph extraction expert. Extract every entity and relationship from the provided document according to the schema.

TASK
====
Extract EVERY entity and relationship from the document that matches the schema.
Do not stop after the first or most prominent entity of a type — scan the entire
text and extract ALL instances. Lists, footnotes, references, and parenthetical
mentions all count. Missing an entity is a worse error than a low-confidence one.

EXHAUSTIVENESS RULES
====================
- Before finalising, re-read each schema concept type and ask: "Did I extract every
  occurrence of this type in the text?" If a name appears more than once with the same
  referent, extract it once; if it refers to a different instance, extract it separately.
- Named individuals (people, aircraft, documents, organisations, units) listed in
  enumerated lists (a., b., c. … or 1., 2., 3. …) must EACH become a node.
- Documents cited by title or reference number (e.g. "Technical Note AERO 1703",
  "Report V-32291-8", "F-SU-1110-Md") are Document nodes — extract every one.
- Aircraft variants named distinctly (e.g. "Horten VIII", "Horten IX", "Horten Parabola")
  are separate Aircraft nodes — do not collapse them into one.
- People named as authors, designers, or co-workers in passing are Person nodes even
  if little other information is given (use null attributes with confidence 0.0).

EDGE COMPLETENESS
=================
After extracting all nodes, do a second pass over edges. For EVERY node you extracted,
check each relationship type where that node type appears as domain or range, and emit
every edge that the text supports — even weakly. The schema block below lists
"Outgoing edges" and "Incoming edges" per type to make this easy.

Common patterns that must produce edges:
- Every Document node → issued_by the unit/org that sent it (look for signatures,
  letterhead, "from:", "for the commanding general", routing slips).
- Every Document node → authored_by the person who signed or drafted it.
- Every Document node → addressed_to / sent_to the recipient org or unit.
- Every Document node → describes_aircraft / reports_on / discusses the subject matter.
- Every Person node → mentions_person from the Document(s) that name them.
- Every Person node → works_at or works_for their unit/org if stated or implied by rank/role.
- Every Organization node → addressed_to or sent_to from documents directed at them.
Do not leave a node with zero edges unless you are certain the text provides no
relationship evidence whatsoever.

OUTPUT FORMAT
=============
Return a single JSON object with exactly two keys: "nodes" and "edges".

"nodes" — one entry per entity instance. Each entry has:
  - "id": kebab-case slug, e.g. "person-alice"
  - "type": exact class name from the schema
  - "confidence": float 0.0–1.0
  - "attributes": object with one key per schema attribute (including inherited).
    Each value MUST be {"value": <extracted or null>, "confidence": <float>}.
    Never omit an attribute — use {"value": null, "confidence": 0.0} if not found.
    CRITICAL: never use a bare string or null as an attribute value. Always wrap in {value, confidence}.

"edges" — one entry per relationship. Each entry has:
  - "id": sequential, e.g. "edge-001"
  - "type": exact property name from the schema
  - "from": node ID from nodes[] above (NOT a display name)
  - "to": node ID from nodes[] above (NOT a display name)
  - "confidence": float 0.0–1.0
  - "attributes": one key per edge attribute defined in the schema for this property.
    Each value MUST be {"value": <extracted or null>, "confidence": <float>}.

ATTRIBUTE FORMAT — CORRECT vs WRONG
=====================================
WRONG (bare scalar):  "name": "Alice",   "rank": null
CORRECT (wrapped):    "name": {"value": "Alice", "confidence": 0.95},   "rank": {"value": null, "confidence": 0.0}

Every attribute, whether its value is known or null, must be wrapped in {"value": ..., "confidence": ...}.

RULES
=====
- "from" and "to" must be node IDs from nodes[] in this response — not display names.
- "type" in edges must exactly match a property name from properties[]. Do not invent types.
- Every attribute defined in the schema must appear in the output.
- All confidence values are floats between 0.0 and 1.0.
- All attribute values must be {"value": ..., "confidence": float} — never bare strings or nulls.

PRIOR NODES (when provided)
===========================
If "NODES ALREADY EXTRACTED" appears in the input, those are nodes extracted from
earlier chunks of the same file. Use their IDs directly when emitting edges to those
entities. Do NOT re-extract them as new nodes unless you find genuinely new attributes
not present in the prior record.

## User

SCHEMA
======
Concept types:
  - Organization: attributes = ['name', 'description', 'headquarters_location', 'type']
    Outgoing edges: owns → Project
    Incoming edges: Person → works_at, Person → manages, Person → leads
  - Company: attributes = ['name', 'description', 'headquarters_location', 'type', 'founding_year', 'annual_revenue']
    Outgoing edges: provides → Product, partners_with → Company, has_contact → Person, holds_contract → Contract
    Incoming edges: Company → partners_with, Partnership → involves_organization
  - Person: attributes = ['name', 'email', 'education']
    Outgoing edges: works_at → Organization, manages → Organization, member_of → Team, reports_to → Person, contributes_to → Project, leads → Organization
    Incoming edges: Person → reports_to, Company → has_contact
  - Employee: attributes = ['name', 'email', 'education', 'title', 'join_date']
  - Team: attributes = ['name', 'description', 'headquarters_location', 'type', 'focus_area', 'member_count']
    Outgoing edges: uses_technology → Technology
    Incoming edges: Person → member_of
  - Project: attributes = ['name', 'description', 'status', 'budget']
    Outgoing edges: depends_on → Project, uses_technology → Technology
    Incoming edges: Person → contributes_to, Organization → owns, Project → depends_on, Partnership → covers_project
  - Technology: attributes = ['name', 'category', 'version']
    Incoming edges: Project → uses_technology, Team → uses_technology
  - Product: attributes = ['name', 'category', 'version', 'vendor']
    Incoming edges: Company → provides
  - Partnership: attributes = ['name', 'type', 'start_date', 'scope']
    Outgoing edges: governed_by → Contract, involves_organization → Company, covers_project → Project
  - Contract: attributes = ['name', 'type', 'signed_date', 'value']
    Incoming edges: Partnership → governed_by, Company → holds_contract

Relationship types:
  - works_at (Person → Organization): edge attributes = ['role', 'start_date', 'end_date']
  - manages (Person → Organization): edge attributes = []
  - member_of (Person → Team): edge attributes = []
  - reports_to (Person → Person): edge attributes = []
  - contributes_to (Person → Project): edge attributes = ['role', 'contribution_type']
  - owns (Organization → Project): edge attributes = []
  - depends_on (Project → Project): edge attributes = []
  - uses_technology (Project → Technology): edge attributes = ['purpose']
  - uses_technology (Team → Technology): edge attributes = ['purpose']
  - provides (Company → Product): edge attributes = []
  - partners_with (Company → Company): edge attributes = []
  - governed_by (Partnership → Contract): edge attributes = []
  - involves_organization (Partnership → Company): edge attributes = ['role']
  - covers_project (Partnership → Project): edge attributes = []
  - has_contact (Company → Person): edge attributes = ['contact_type']
  - holds_contract (Company → Contract): edge attributes = []
  - leads (Person → Organization): edge attributes = []

DOCUMENT
========
# Technology Stack Notes

## Databases

Acme Corp currently runs PostgreSQL 15 on-premise for production workloads. The DB Migration project is moving these clusters to AWS Aurora (PostgreSQL-compatible).

The RAG Pipeline project uses Pinecone as the vector database for embedding storage and similarity search. Dr. Yuna Park evaluated Pinecone, Weaviate, and Qdrant before selecting Pinecone for its managed service model.

## Infrastructure and DevOps

Acme Corp's infrastructure runs on AWS. The CI/CD pipeline uses GitHub Actions. Container orchestration is handled by Kubernetes (EKS). The infrastructure team, managed by Bob Martinez, owns all of these.

HashiCorp Vault is being adopted for secrets management as part of the Platform Secrets Service project, led by James Whitfield.

## AI and ML Stack

The AI Research team, led by Dr. Yuna Park, uses Python, PyTorch, and Hugging Face Transformers as their primary tools. The team runs experiments on AWS SageMaker.

The RAG pipeline integrates with the internal knowledge base via a custom ingestion layer written in Python. DataSystems Inc provides the document processing pipeline that feeds this ingestion layer.

## Programming Languages and Frameworks

The backend engineering guild, led by Alice Chen, standardises on Python (FastAPI) for services and Go for performance-critical components. The frontend uses React with TypeScript. Alice Chen is the primary decision-maker for backend language choices at Acme Corp.

