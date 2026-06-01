## Response

```json
{
  "nodes": [
    {
      "id": "company-acme-corp",
      "type": "Company",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Acme Corp", "confidence": 1.0},
        "description": {"value": "Company running technology infrastructure and AI/ML projects", "confidence": 0.9},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Technology Company", "confidence": 0.8},
        "founding_year": {"value": null, "confidence": 0.0},
        "annual_revenue": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-postgresql-15",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "PostgreSQL", "confidence": 1.0},
        "category": {"value": "Database", "confidence": 1.0},
        "version": {"value": "15", "confidence": 1.0}
      }
    },
    {
      "id": "project-db-migration",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "DB Migration", "confidence": 1.0},
        "description": {"value": "Moving PostgreSQL clusters to AWS Aurora", "confidence": 1.0},
        "status": {"value": "In Progress", "confidence": 0.7},
        "budget": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-aws-aurora",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AWS Aurora", "confidence": 1.0},
        "category": {"value": "Database", "confidence": 1.0},
        "version": {"value": "PostgreSQL-compatible", "confidence": 0.9}
      }
    },
    {
      "id": "project-rag-pipeline",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "RAG Pipeline", "confidence": 1.0},
        "description": {"value": "Vector database system for embedding storage and similarity search, integrating with internal knowledge base", "confidence": 0.95},
        "status": {"value": null, "confidence": 0.0},
        "budget": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-pinecone",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Pinecone", "confidence": 1.0},
        "category": {"value": "Vector Database", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "person-yuna-park",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Dr. Yuna Park", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": "Doctorate", "confidence": 0.9}
      }
    },
    {
      "id": "technology-weaviate",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Weaviate", "confidence": 1.0},
        "category": {"value": "Vector Database", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-qdrant",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Qdrant", "confidence": 1.0},
        "category": {"value": "Vector Database", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-aws",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AWS", "confidence": 1.0},
        "category": {"value": "Cloud Infrastructure", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-github-actions",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "GitHub Actions", "confidence": 1.0},
        "category": {"value": "CI/CD", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-kubernetes",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Kubernetes", "confidence": 1.0},
        "category": {"value": "Container Orchestration", "confidence": 1.0},
        "version": {"value": "EKS", "confidence": 0.9}
      }
    },
    {
      "id": "team-infrastructure",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Infrastructure Team", "confidence": 1.0},
        "description": {"value": "Team managing AWS infrastructure, CI/CD pipeline, and container orchestration", "confidence": 0.95},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Engineering Team", "confidence": 0.9},
        "focus_area": {"value": "Infrastructure and DevOps", "confidence": 1.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "person-bob-martinez",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Bob Martinez", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-hashicorp-vault",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "HashiCorp Vault", "confidence": 1.0},
        "category": {"value": "Secrets Management", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "project-platform-secrets-service",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Platform Secrets Service", "confidence": 1.0},
        "description": {"value": "Adopting HashiCorp Vault for secrets management", "confidence": 1.0},
        "status": {"value": "In Progress", "confidence": 0.7},
        "budget": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "person-james-whitfield",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "James Whitfield", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "team-ai-research",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AI Research Team", "confidence": 1.0},
        "description": {"value": "Team conducting AI and ML research using Python, PyTorch, and Hugging Face Transformers", "confidence": 0.95},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Research Team", "confidence": 0.95},
        "focus_area": {"value": "AI and ML", "confidence": 1.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-python",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Python", "confidence": 1.0},
        "category": {"value": "Programming Language", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-pytorch",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "PyTorch", "confidence": 1.0},
        "category": {"value": "ML Framework", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-hugging-face-transformers",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Hugging Face Transformers", "confidence": 1.0},
        "category": {"value": "ML Library", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-aws-sagemaker",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AWS SageMaker", "confidence": 1.0},
        "category": {"value": "ML Platform", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "company-datasystems-inc",
      "type": "Company",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "DataSystems Inc", "confidence": 1.0},
        "description": {"value": "Provider of document processing pipeline", "confidence": 0.95},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Technology Services Provider", "confidence": 0.85},
        "founding_year": {"value": null, "confidence": 0.0},
        "annual_revenue": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "product-document-processing-pipeline",
      "type": "Product",
      "confidence": 0.95,
      "attributes": {
        "name": {"value": "Document Processing Pipeline", "confidence": 0.95},
        "category": {"value": "Data Processing", "confidence": 0.9},
        "version": {"value": null, "confidence": 0.0},
        "vendor": {"value": "DataSystems Inc", "confidence": 1.0}
      }
    },
    {
      "id": "team-backend-engineering-guild",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Backend Engineering Guild", "confidence": 1.0},
        "description": {"value": "Team standardising on Python (FastAPI) for services and Go for performance-critical components", "confidence": 0.95},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Engineering Guild", "confidence": 0.95},
        "focus_area": {"value": "Backend Engineering", "confidence": 1.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "person-alice-chen",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Alice Chen", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-fastapi",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "FastAPI", "confidence": 1.0},
        "category": {"value": "Web Framework", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-go",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Go", "confidence": 1.0},
        "category": {"value": "Programming Language", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-react",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "React", "confidence": 1.0},
        "category": {"value": "Frontend Framework", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-typescript",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "TypeScript", "confidence": 1.0},
        "category": {"value": "Programming Language", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Acme Corp", "confidence": 1.0},
        "description": {"value": "Organization managing technology projects and infrastructure", "confidence": 0.9},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "type": {"value": "Corporation", "confidence": 0.9}
      }
    }
  ],
  "edges": [
    {
      "id": "edge-001",
      "type": "uses_technology",
      "from": "project-db-migration",
      "to": "technology-postgresql-15",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Source database for migration", "confidence": 0.9}
      }
    },
    {
      "id": "edge-002",
      "type": "uses_technology",
      "from": "project-db-migration",
      "to": "technology-aws-aurora",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Target database for migration", "confidence": 0.95}
      }
    },
    {
      "id": "edge-003",
      "type": "uses_technology",
      "from": "project-rag-pipeline",
      "to": "technology-pinecone",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Vector database for embedding storage and similarity search", "confidence": 1.0}
      }
    },
    {
      "id": "edge-004",
      "type": "contributes_to",
      "from": "person-yuna-park",
      "to": "project-rag-pipeline",
      "confidence": 0.95,
      "attributes": {
        "role": {"value": "Technology evaluator and selector", "confidence": 0.95},
        "contribution_type": {"value": "Technology evaluation", "confidence": 0.95}
      }
    },
    {
      "id": "edge-005",
      "type": "leads",
      "from": "person-yuna-park",
      "to": "team-ai-research",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-006",
      "type": "uses_technology",
      "from": "team-infrastructure",
      "to": "technology-aws",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Cloud infrastructure hosting", "confidence": 1.0}
      }
    },
    {
      "id": "edge-007",
      "type": "uses_technology",
      "from": "team-infrastructure",
      "to": "technology-github-actions",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "CI/CD pipeline", "confidence": 1.0}
      }
    },
    {
      "id": "edge-008",
      "type": "uses_technology",
      "from": "team-infrastructure",
      "to": "technology-kubernetes",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Container orchestration", "confidence": 1.0}
      }
    },
    {
      "id": "edge-009",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "team-infrastructure",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-010",
      "type": "uses_technology",
      "from": "project-platform-secrets-service",
      "to": "technology-hashicorp-vault",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Secrets management", "confidence": 1.0}
      }
    },
    {
      "id": "edge-011",
      "type": "contributes_to",
      "from": "person-james-whitfield",
      "to": "project-platform-secrets-service",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "Project lead", "confidence": 1.0},
        "contribution_type": {"value": "Leadership", "confidence": 1.0}
      }
    },
    {
      "id": "edge-012",
      "type": "uses_technology",
      "from": "team-ai-research",
      "to": "technology-python",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Primary programming language for AI/ML research", "confidence": 1.0}
      }
    },
    {
      "id": "edge-013",
      "type": "uses_technology",
      "from": "team-ai-research",
      "to": "technology-pytorch",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Machine learning framework", "confidence": 1.0}
      }
    },
    {
      "id": "edge-014",
      "type": "uses_technology",
      "from": "team-ai-research",
      "to": "technology-hugging-face-transformers",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Transformer models and NLP", "confidence": 0.95}
      }
    },
    {
      "id": "edge-015",
      "type": "uses_technology",
      "from": "team-ai-research",
      "to": "technology-aws-sagemaker",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Running ML experiments", "confidence": 1.0}
      }
    },
    {
      "id": "edge-016",
      "type": "provides",
      "from": "company-datasystems-inc",
      "to": "product-document-processing-pipeline",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-017",
      "type": "uses_technology",
      "from": "project-rag-pipeline",
      "to": "technology-python",
      "confidence": 0.95,
      "attributes": {
        "purpose": {"value": "Custom ingestion layer implementation", "confidence": 0.95}
      }
    },
    {
      "id": "edge-018",
      "type": "leads",
      "from": "person-alice-chen",
      "to": "team-backend-engineering-guild",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-019",
      "type": "uses_technology",
      "from": "team-backend-engineering-guild",
      "to": "technology-python",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Standard language for backend services", "confidence": 1.0}
      }
    },
    {
      "id": "edge-020",
      "type": "uses_technology",
      "from": "team-backend-engineering-guild",
      "to": "technology-fastapi",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Framework for backend services", "confidence": 1.0}
      }
    },
    {
      "id": "edge-021",
      "type": "uses_technology",
      "from": "team-backend-engineering-guild",
      "to": "technology-go",
      "confidence": 1.0,
      "attributes": {
        "purpose": {"value": "Performance-critical components", "confidence": 1.0}
      }
    },
    {
      "id": "edge-022",
      "type": "uses_technology",
      "from": "team-backend-engineering-guild",
      "to": "technology-react",
      "confidence": 0.9,
      "attributes": {
        "purpose": {"value": "Frontend framework", "confidence": 0.9}
      }
    },
    {
      "id": "edge-023",
      "type": "uses_technology",
      "from": "team-backend-engineering-guild",
      "to": "technology-typescript",
      "confidence": 0.9,
      "attributes": {
        "purpose": {"value": "Frontend type system with React", "confidence": 0.9}
      }
    },
    {
      "id": "edge-024",
      "type": "owns",
      "from": "organization-acme-corp",
      "to": "project-db-migration",
      "confidence": 0.95,
      "attributes": {}
    },
    {
      "id": "edge-025",
      "type": "owns",
      "from": "organization-acme-corp",
      "to": "project-rag-pipeline",
      "confidence": 0.95,
      "attributes": {}
    },
    {
      "id": "edge-026",
      "type": "owns",
      "from": "organization-acme-corp",
      "to": "project-platform-secrets-service",
      "confidence": 0.95,
      "attributes": {}
    },
    {
      "id": "edge-027",
      "type": "works_at",
      "from": "person-bob-martinez",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "role": {"value": "Infrastructure Manager", "confidence": 0.9},
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "edge-028",
      "type": "works_at",
      "from": "person-yuna-park",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "role": {"value": "AI Research Lead", "confidence": 0.9},
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "edge-029",
      "type": "works_at",
      "from": "person-james-whitfield",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "role": {"value": "Project Lead", "confidence": 0.85},
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "edge-030",
      "type": "works_at",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "role": {"value": "Backend Engineering Lead", "confidence": 0.9},
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0}
      }
    }
  ]
}
```
