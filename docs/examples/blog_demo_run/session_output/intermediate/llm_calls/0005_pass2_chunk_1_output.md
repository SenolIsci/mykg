## Response

```json
{
  "nodes": [
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Acme Corp", "confidence": 1.0},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "industry": {"value": null, "confidence": 0.0},
        "founding_year": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "DataSystems Inc", "confidence": 1.0},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "industry": {"value": "document indexing infrastructure", "confidence": 0.8},
        "founding_year": {"value": null, "confidence": 0.0}
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
      "id": "person-carol-okafor",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Carol Okafor", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0}
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
      "id": "person-yuna-park",
      "type": "Person",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Dr. Yuna Park", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": "doctorate", "confidence": 0.7}
      }
    },
    {
      "id": "team-infrastructure",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Infrastructure Team", "confidence": 1.0},
        "description": {"value": "team responsible for infrastructure projects including database migration", "confidence": 0.8},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "team-platform",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Platform Team", "confidence": 1.0},
        "description": {"value": "team building platform services including secrets management", "confidence": 0.85},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "team-ai-research",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AI Research Team", "confidence": 1.0},
        "description": {"value": "team focused on AI research and development", "confidence": 0.8},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "project-db-migration",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "DB Migration Project", "confidence": 1.0},
        "status": {"value": "in progress", "confidence": 1.0},
        "target_completion_date": {"value": "end of Q3 2026", "confidence": 1.0},
        "budget": {"value": "$120,000", "confidence": 1.0}
      }
    },
    {
      "id": "project-rag-pipeline",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "RAG Pipeline Project", "confidence": 1.0},
        "status": {"value": "design phase", "confidence": 1.0},
        "target_completion_date": {"value": "Q4 2026", "confidence": 1.0},
        "budget": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "project-platform-secrets-service",
      "type": "Project",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Platform Secrets Service", "confidence": 1.0},
        "status": {"value": "in progress", "confidence": 0.8},
        "target_completion_date": {"value": "August 2026", "confidence": 1.0},
        "budget": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-postgresql",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "PostgreSQL", "confidence": 1.0},
        "type": {"value": "database", "confidence": 0.95},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-aws-aurora",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AWS Aurora", "confidence": 1.0},
        "type": {"value": "cloud database", "confidence": 0.95},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-pinecone",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Pinecone", "confidence": 1.0},
        "type": {"value": "vector database", "confidence": 1.0},
        "version": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "technology-hashicorp-vault",
      "type": "Technology",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "HashiCorp Vault", "confidence": 1.0},
        "type": {"value": "secrets management", "confidence": 0.95},
        "version": {"value": null, "confidence": 0.0}
      }
    }
  ],
  "edges": [
    {
      "id": "edge-001",
      "type": "owns",
      "from": "team-infrastructure",
      "to": "project-db-migration",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-002",
      "type": "leads",
      "from": "person-bob-martinez",
      "to": "project-db-migration",
      "confidence": 0.9,
      "attributes": {
        "role": {"value": "initiator", "confidence": 0.85}
      }
    },
    {
      "id": "edge-003",
      "type": "contributes_to",
      "from": "person-alice-chen",
      "to": "project-db-migration",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "core engineering contributor", "confidence": 1.0}
      }
    },
    {
      "id": "edge-004",
      "type": "contributes_to",
      "from": "person-carol-okafor",
      "to": "project-db-migration",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "core engineering contributor", "confidence": 1.0}
      }
    },
    {
      "id": "edge-005",
      "type": "depends_on",
      "from": "project-db-migration",
      "to": "project-platform-secrets-service",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-006",
      "type": "uses_technology",
      "from": "project-db-migration",
      "to": "technology-postgresql",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-007",
      "type": "uses_technology",
      "from": "project-db-migration",
      "to": "technology-aws-aurora",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-008",
      "type": "leads",
      "from": "person-yuna-park",
      "to": "project-rag-pipeline",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "project lead", "confidence": 1.0}
      }
    },
    {
      "id": "edge-009",
      "type": "contributes_to",
      "from": "person-alice-chen",
      "to": "project-rag-pipeline",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "backend API work", "confidence": 1.0}
      }
    },
    {
      "id": "edge-010",
      "type": "uses_technology",
      "from": "project-rag-pipeline",
      "to": "technology-pinecone",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-011",
      "type": "has_partnership",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 1.0,
      "attributes": {
        "type": {"value": "document indexing infrastructure provider", "confidence": 0.9},
        "start_date": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "edge-012",
      "type": "owns",
      "from": "team-platform",
      "to": "project-platform-secrets-service",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-013",
      "type": "leads",
      "from": "person-james-whitfield",
      "to": "project-platform-secrets-service",
      "confidence": 1.0,
      "attributes": {
        "role": {"value": "project owner", "confidence": 1.0}
      }
    },
    {
      "id": "edge-014",
      "type": "uses_technology",
      "from": "project-platform-secrets-service",
      "to": "technology-hashicorp-vault",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-015",
      "type": "member_of",
      "from": "person-yuna-park",
      "to": "team-ai-research",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-016",
      "type": "manages",
      "from": "person-james-whitfield",
      "to": "team-platform",
      "confidence": 0.85,
      "attributes": {}
    },
    {
      "id": "edge-017",
      "type": "works_at",
      "from": "person-bob-martinez",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "edge-018",
      "type": "works_at",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "engineer", "confidence": 0.8}
      }
    },
    {
      "id": "edge-019",
      "type": "works_at",
      "from": "person-carol-okafor",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "engineer", "confidence": 0.8}
      }
    },
    {
      "id": "edge-020",
      "type": "works_at",
      "from": "person-james-whitfield",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "team lead", "confidence": 0.8}
      }
    },
    {
      "id": "edge-021",
      "type": "works_at",
      "from": "person-yuna-park",
      "to": "organization-acme-corp",
      "confidence": 0.95,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "researcher", "confidence": 0.8}
      }
    }
  ]
}
```
