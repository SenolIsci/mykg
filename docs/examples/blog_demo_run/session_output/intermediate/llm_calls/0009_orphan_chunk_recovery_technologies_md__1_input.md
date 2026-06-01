## System

You are a knowledge graph expert. You are given  a list of orphan nodes (nodes with no edges in the knowledge graph), a list of already-connected graph nodes, a schema of allowed relationship types, and a chunk of source text.

Find all relationships between the orphan nodes and any other node listed (orphan or connected) from the chunk of source text. Use only property types listed in SCHEMA PROPERTIES.

OUTPUT FORMAT
=============
Return a JSON array of edge objects. Each object must have exactly these keys:
  "type": the exact property name from the schema
  "from": the stable node ID of the source node
  "to": the stable node ID of the target node
  "confidence": float 0.0-1.0
  "rationale": one sentence citing evidence from the source text

Return an empty array [] if no relationships are found.
Return ONLY the JSON array — no markdown, no extra keys.

## User

ORPHAN NODES (find relationships for these)
============================================
  - id: technology-qdrant, type: Technology, name: Qdrant
  - id: technology-weaviate, type: Technology, name: Weaviate

ALREADY-CONNECTED GRAPH NODES (cross-reference targets)
=========================================================
  - id: team-backend-engineering-guild, type: Team, name: Backend Engineering Guild
  - id: project-platform-secrets-service, type: Project, name: Platform Secrets Service
  - id: team-infrastructure-team, type: Team, name: Infrastructure Team
  - id: team-ai-research-team, type: Team, name: AI Research Team
  - id: project-rag-pipeline, type: Project, name: RAG Pipeline
  - id: project-db-migration, type: Project, name: DB Migration

SCHEMA PROPERTIES
=================
  - works_at (Person → Organization)
  - manages (Person → Organization)
  - member_of (Person → Team)
  - reports_to (Person → Person)
  - contributes_to (Person → Project)
  - owns (Organization → Project)
  - depends_on (Project → Project)
  - uses_technology (Project → Technology)
  - uses_technology (Team → Technology)
  - provides (Company → Product)
  - partners_with (Company → Company)
  - governed_by (Partnership → Contract)
  - involves_organization (Partnership → Company)
  - covers_project (Partnership → Project)
  - has_contact (Company → Person)
  - holds_contract (Company → Contract)
  - leads (Person → Organization)

CHUNK SOURCE TEXT
=================
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

