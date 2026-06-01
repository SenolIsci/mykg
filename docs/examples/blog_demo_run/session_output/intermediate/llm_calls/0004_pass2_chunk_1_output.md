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
        "founding_year": {"value": "2015", "confidence": 1.0}
      }
    },
    {
      "id": "person-alice-chen",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Alice Chen", "confidence": 1.0},
        "email": {"value": "alice.chen@acme.com", "confidence": 1.0},
        "education": {"value": "BSc in Computer Science from MIT", "confidence": 1.0},
        "join_date": {"value": "March 2021", "confidence": 1.0},
        "title": {"value": "Senior Software Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "person-bob-martinez",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Bob Martinez", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0},
        "join_date": {"value": "2018", "confidence": 1.0},
        "title": {"value": "Director of Engineering", "confidence": 1.0}
      }
    },
    {
      "id": "person-carol-okafor",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Carol Okafor", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0},
        "join_date": {"value": "January 2023", "confidence": 1.0},
        "title": {"value": "Site Reliability Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "person-sandra-kim",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Sandra Kim", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0},
        "join_date": {"value": null, "confidence": 0.0},
        "title": {"value": "CEO", "confidence": 1.0}
      }
    },
    {
      "id": "person-james-whitfield",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "James Whitfield", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": "PhD in Computer Science from Stanford", "confidence": 1.0},
        "join_date": {"value": null, "confidence": 0.0},
        "title": {"value": "CTO", "confidence": 1.0}
      }
    },
    {
      "id": "person-yuna-park",
      "type": "Employee",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Dr. Yuna Park", "confidence": 1.0},
        "email": {"value": null, "confidence": 0.0},
        "education": {"value": null, "confidence": 0.0},
        "join_date": {"value": null, "confidence": 0.0},
        "title": {"value": "Principal Researcher", "confidence": 1.0}
      }
    },
    {
      "id": "team-infrastructure-team",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "infrastructure team", "confidence": 1.0},
        "description": {"value": "responsible for cloud operations, CI/CD pipelines, and on-call rotations", "confidence": 1.0},
        "member_count": {"value": "5", "confidence": 1.0}
      }
    },
    {
      "id": "team-product-team",
      "type": "Team",
      "confidence": 0.9,
      "attributes": {
        "name": {"value": "product team", "confidence": 1.0},
        "description": {"value": null, "confidence": 0.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "team-platform-team",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Platform team", "confidence": 1.0},
        "description": {"value": null, "confidence": 0.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "team-ai-research-team",
      "type": "Team",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "AI Research team", "confidence": 1.0},
        "description": {"value": "current focus is on retrieval-augmented generation (RAG) and knowledge graph applications", "confidence": 1.0},
        "member_count": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "organization-google",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "Google", "confidence": 1.0},
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
        "industry": {"value": null, "confidence": 0.0},
        "founding_year": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "organization-novatech-inc",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "NovaTech Inc", "confidence": 1.0},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "industry": {"value": null, "confidence": 0.0},
        "founding_year": {"value": null, "confidence": 0.0}
      }
    },
    {
      "id": "organization-deepmind",
      "type": "Organization",
      "confidence": 1.0,
      "attributes": {
        "name": {"value": "DeepMind", "confidence": 1.0},
        "headquarters_location": {"value": null, "confidence": 0.0},
        "industry": {"value": null, "confidence": 0.0},
        "founding_year": {"value": null, "confidence": 0.0}
      }
    }
  ],
  "edges": [
    {
      "id": "edge-001",
      "type": "works_at",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": "March 2021", "confidence": 1.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "Senior Software Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "edge-002",
      "type": "works_at",
      "from": "person-bob-martinez",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": "2018", "confidence": 1.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "Director of Engineering", "confidence": 1.0}
      }
    },
    {
      "id": "edge-003",
      "type": "works_at",
      "from": "person-carol-okafor",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": "January 2023", "confidence": 1.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "Site Reliability Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "edge-004",
      "type": "works_at",
      "from": "person-sandra-kim",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "CEO", "confidence": 1.0}
      }
    },
    {
      "id": "edge-005",
      "type": "works_at",
      "from": "person-james-whitfield",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "CTO", "confidence": 1.0}
      }
    },
    {
      "id": "edge-006",
      "type": "works_at",
      "from": "person-yuna-park",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "Principal Researcher", "confidence": 1.0}
      }
    },
    {
      "id": "edge-007",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "team-infrastructure-team",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-008",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "team-product-team",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-009",
      "type": "member_of",
      "from": "person-carol-okafor",
      "to": "team-infrastructure-team",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-010",
      "type": "reports_to",
      "from": "person-bob-martinez",
      "to": "person-sandra-kim",
      "confidence": 1.0,
      "attributes": {}
    },
    {
      "id": "edge-011",
      "type": "co_founded",
      "from": "person-sandra-kim",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "year": {"value": "2015", "confidence": 1.0}
      }
    },
    {
      "id": "edge-012",
      "type": "co_founded",
      "from": "person-james-whitfield",
      "to": "organization-acme-corp",
      "confidence": 1.0,
      "attributes": {
        "year": {"value": "2015", "confidence": 1.0}
      }
    },
    {
      "id": "edge-013",
      "type": "works_at",
      "from": "person-bob-martinez",
      "to": "organization-google",
      "confidence": 0.9,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": "2018", "confidence": 0.8},
        "role": {"value": "Staff Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "edge-014",
      "type": "works_at",
      "from": "person-carol-okafor",
      "to": "organization-datasystems-inc",
      "confidence": 0.9,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": "January 2023", "confidence": 0.8},
        "role": {"value": "DevOps Engineer", "confidence": 1.0}
      }
    },
    {
      "id": "edge-015",
      "type": "works_at",
      "from": "person-sandra-kim",
      "to": "organization-novatech-inc",
      "confidence": 0.9,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": "VP Engineering", "confidence": 1.0}
      }
    },
    {
      "id": "edge-016",
      "type": "works_at",
      "from": "person-yuna-park",
      "to": "organization-deepmind",
      "confidence": 0.9,
      "attributes": {
        "start_date": {"value": null, "confidence": 0.0},
        "end_date": {"value": null, "confidence": 0.0},
        "role": {"value": null, "confidence": 0.0}
      }
    }
  ]
}
```
