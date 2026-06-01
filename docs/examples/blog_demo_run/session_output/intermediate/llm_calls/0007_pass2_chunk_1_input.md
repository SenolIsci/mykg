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
  - Organization: attributes = ['name', 'headquarters_location', 'industry', 'founding_year']
    Outgoing edges: provides → Product, has_partnership → Organization, vendor_for → Organization, has_agreement → Agreement
    Incoming edges: Person → works_at, Organization → has_partnership, Organization → vendor_for, Person → account_manager_for, Person → co_founded
  - Company: attributes = ['name', 'headquarters_location', 'industry', 'founding_year', 'annual_spend']
  - Person: attributes = ['name', 'email', 'education']
    Outgoing edges: works_at → Organization, manages → Team, member_of → Team, reports_to → Person, leads → Project, contributes_to → Project, account_manager_for → Organization, co_founded → Organization
    Incoming edges: Person → reports_to
  - Employee: attributes = ['name', 'email', 'education', 'join_date', 'title']
  - Team: attributes = ['name', 'description', 'member_count']
    Outgoing edges: owns → Project
    Incoming edges: Person → manages, Person → member_of
  - Project: attributes = ['name', 'status', 'target_completion_date', 'budget']
    Outgoing edges: depends_on → Project, uses_technology → Technology
    Incoming edges: Person → leads, Person → contributes_to, Team → owns, Project → depends_on, Agreement → supports
  - Technology: attributes = ['name', 'type', 'version']
    Incoming edges: Project → uses_technology
  - Product: attributes = ['name', 'type', 'version', 'description']
    Incoming edges: Organization → provides
  - Agreement: attributes = ['name', 'type', 'start_date']
    Outgoing edges: supports → Project
    Incoming edges: Organization → has_agreement

Relationship types:
  - works_at (Person → Organization): edge attributes = ['start_date', 'end_date', 'role']
  - manages (Person → Team): edge attributes = []
  - member_of (Person → Team): edge attributes = []
  - reports_to (Person → Person): edge attributes = []
  - leads (Person → Project): edge attributes = ['role']
  - contributes_to (Person → Project): edge attributes = ['role']
  - owns (Team → Project): edge attributes = []
  - depends_on (Project → Project): edge attributes = []
  - uses_technology (Project → Technology): edge attributes = []
  - provides (Organization → Product): edge attributes = []
  - has_partnership (Organization → Organization): edge attributes = ['type', 'start_date']
  - vendor_for (Organization → Organization): edge attributes = []
  - has_agreement (Organization → Agreement): edge attributes = []
  - account_manager_for (Person → Organization): edge attributes = []
  - co_founded (Person → Organization): edge attributes = ['year']
  - supports (Agreement → Project): edge attributes = []

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

