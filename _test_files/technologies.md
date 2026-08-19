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
