---
confidence: 1.0
id: project-rag-pipeline
sources:
- partners.md
- projects.md
- technologies.md
type: Project
---

# RAG Pipeline

## Attributes
- **description**: document indexing; Internal RAG (Retrieval-Augmented Generation) pipeline to allow employees to query company's internal documentation using natural language (1.0)
- **status**: active; design phase (1.0)

## Relationships

### Outgoing
- [[Pinecone]] — uses_technology (1.0)
- [[Python]] — uses_technology (0.95)
- [[Qdrant]] — uses_technology (0.85)
- [[Weaviate]] — uses_technology (0.85)

### Incoming
- [[Acme Corp - DataSystems Inc Strategic Partnership]] — covers_project (1.0)
- [[Dr. Yuna Park]] — contributes_to (0.97)
- [[Alice Chen]] — contributes_to (1.0)
- [[DataSystems Inc - RAG Pipeline Partnership]] — covers_project (1.0)
- [[Acme Corp]] — owns (0.95)

## Source Files
- partners.md
- projects.md
- technologies.md
