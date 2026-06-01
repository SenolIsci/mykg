## System

You are an RDFS ontology expert. Extract a schema of concept types and relationship properties from the provided source text.

OUTPUT FORMAT
=============
Return a single JSON object with exactly two keys: "concepts" and "properties".
Do NOT return any other keys (no "relations", no "edges", no "graph").

"concepts" — RDFS classes. Each entry has:
  - "type": PascalCase class name (e.g. "Person", "Organization")
  - "parent": name of the parent class, or null for root classes
  - "attributes": list of snake_case datatype attribute names OWN to this class
    (do NOT repeat attributes from parent classes here)

"properties" — RDFS object properties that LINK two classes. Each entry has:
  - "name": snake_case predicate (e.g. "works_at", "depends_on")
  - "domain": the subject class name (must appear in concepts[])
  - "range": the object class name (must appear in concepts[])
  - "attributes": edge-level metadata fields to capture per relationship instance

RULES
=====
- Do NOT add a "Relationship" class. Relationships are entries in properties[], not classes.
- "domain" and "range" must be class names that appear in concepts[].
- Root classes have "parent": null. Every non-root class must name a parent that exists in
  concepts[].
- Datatype attributes (strings, numbers, dates) belong in concepts[].attributes.
- Object links between entities belong in properties[].
- "attributes" must always be a JSON array of strings. Never use null inside an array.
  If there are no attributes, use an empty array: [].
- Every string value in the JSON must be quoted. Never emit a bare null where a string
  is expected.
- Every concept MUST include at least a "name" attribute. Never propose a concept with an empty attributes list.
- Concept attributes: 0–4 per class, broadly applicable to any instance. No hyper-specific
  or one-off fields. No duplicates from the parent. Prefer general names ("date" not
  "incident_date_of_first_sighting").
- Property attributes: 0–4 per relationship, only when the relationship itself has
  meaningful qualifying data (works_at → [role, start_date]). Do not pad.
- Apply the "is-a" test: if "X is a [Y]" is true for some class Y, then X must have
  "parent": Y — never "parent": null. Root classes must be generic, reusable categories
  (e.g. "Person", "Organization", "Location", "Document", "Phenomenon"), not named
  entities or domain-specific subtypes.
- CLASSES vs. INSTANCES — this is the most common mistake: do NOT propose a concept
  type for a specific, named, one-of-a-kind entity.

## SOURCE TEXT

## User

# Partner and Vendor Notes

## DataSystems Inc

DataSystems Inc is a data infrastructure company headquartered in San Francisco. Acme Corp signed a strategic partnership with DataSystems in September 2025 to co-develop document indexing and search infrastructure.

Carol Okafor previously worked at DataSystems Inc as a DevOps Engineer from 2019 to 2022, before joining Acme Corp. Her former manager at DataSystems was Dr. Priya Nair, who is now VP of Engineering at DataSystems.

The partnership covers two active workstreams: the RAG Pipeline Project (document indexing) and a planned data lake migration.

## NovaTech Inc

NovaTech Inc is a SaaS company focused on developer tooling. Sandra Kim, Acme Corp's CEO, was VP Engineering at NovaTech before co-founding Acme Corp in 2015.

Acme Corp has an informal advisory relationship with NovaTech. No active commercial contract exists.

## HashiCorp

HashiCorp provides the Vault product used by Acme Corp's Platform team in the Secrets Service project. Acme Corp holds an enterprise licence for Vault signed in Q1 2026. The vendor contact is Marcus Tan, an enterprise account manager at HashiCorp.

## AWS

Amazon Web Services (AWS) is Acme Corp's primary cloud provider. The DB Migration project targets AWS Aurora. Acme Corp's annual AWS spend is approximately $800,000. The account manager is Lisa Huang at AWS.


# Active Projects — Q2/Q3 2026

## DB Migration Project

The database migration project aims to move Acme Corp's production PostgreSQL clusters from on-premise hardware to AWS Aurora. The project is owned by the infrastructure team and was initiated by Bob Martinez following a reliability incident in January 2026.

Alice Chen and Carol Okafor are the core engineering contributors. The target completion date is end of Q3 2026. The project has a dependency on the Platform team's new secrets management service, which is being built by James Whitfield's team.

Current status: in progress. Risk: medium. Budget: $120,000.

## RAG Pipeline Project

Acme Corp is building an internal RAG (Retrieval-Augmented Generation) pipeline to allow employees to query the company's internal documentation using natural language. The project is led by Dr. Yuna Park from the AI Research team.

Alice Chen is contributing backend API work. The project uses a vector database (Pinecone) and integrates with the internal knowledge base. A partnership with DataSystems Inc provides the document indexing infrastructure for this project.

Target delivery: Q4 2026. Current status: design phase.

## Platform Secrets Service

The Platform team is building a centralised secrets management service to replace ad-hoc use of environment variables. James Whitfield is the project owner. The service will use HashiCorp Vault as its backend.

Alice Chen requested this project after identifying credential hygiene issues during a security audit in February 2026. Expected completion: August 2026.


# Team Notes — Acme Corp

## Engineering

Alice Chen is a Senior Software Engineer at Acme Corp. She joined the company in March 2021 and holds a BSc in Computer Science from MIT. Alice specialises in distributed systems and currently leads the backend guild. Her email is alice.chen@acme.com.

Bob Martinez is the Director of Engineering at Acme Corp. He has been with the company since 2018 and previously worked at Google as a Staff Engineer. Bob manages both the infrastructure team and the product team. He reports directly to the CEO, Sandra Kim.

Carol Okafor joined Acme Corp in January 2023 as a Site Reliability Engineer. Before Acme, Carol worked at DataSystems Inc for four years as a DevOps Engineer. She is a member of the infrastructure team led by Bob.

## Leadership

Sandra Kim is the CEO of Acme Corp. She co-founded the company in 2015 with James Whitfield, who now serves as CTO. Sandra previously held the role of VP Engineering at NovaTech Inc.

James Whitfield is the CTO of Acme Corp. He has a PhD in Computer Science from Stanford. James oversees the Platform team and the AI Research team.

## Teams

The infrastructure team is responsible for cloud operations, CI/CD pipelines, and on-call rotations. It is managed by Bob Martinez and currently has five members including Carol Okafor.

The AI Research team is led by Dr. Yuna Park, a Principal Researcher who joined from DeepMind. The team's current focus is on retrieval-augmented generation (RAG) and knowledge graph applications.


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

