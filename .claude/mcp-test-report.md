# mykg MCP Server — Full Test Report

- **Session:** 2026-06-25T19-16-18
- **Date:** 2026-06-27 21:43:06
- **Endpoint:** http://localhost:3100/mcp
- **Tools:** 13

## 1. Discovery Queries

### Q01: List entity types
**Tool:** `mykg_list_node_types`  
**Args:** `{}`  

```json
[
  {
    "type": "Technology",
    "count": 18,
    "sample_ids": [
      "technology-vault",
      "technology-aws-aurora",
      "technology-pinecone"
    ]
  },
  {
    "type": "Person",
    "count": 14,
    "sample_ids": [
      "person-carol-okafor",
      "person-dr-priya-nair",
      "person-sandra-kim"
    ]
  },
  {
    "type": "Organization",
    "count": 9,
    "sample_ids": [
      "organization-datasystems-inc",
      "organization-acme-corp",
      "organization-novatech-inc"
    ]
  },
  {
    "type": "Project",
    "count": 3,
    "sample_ids": [
      "project-db-migration-project",
      "project-rag-pipeline-project",
      "project-platform-secrets-service"
    ]
  }
]
```
**Result: PASS**

### Q02: Graph statistics
**Tool:** `mykg_get_stats`  
**Args:** `{}`  

```json
{
  "session_name": "2026-06-25T19-16-18",
  "node_count": 44,
  "edge_count": 70,
  "type_distribution": {
    "Technology": 18,
    "Person": 14,
    "Organization": 9,
    "Project": 3
  },
  "density": 0.036998,
  "weakly_connected_components": 5,
  "avg_degree": 3.18,
  "source_file_count": 5
}
```
**Result: PASS**

### Q03: Available sessions
**Tool:** `mykg_list_sessions`  
**Args:** `{}`  

```json
[
  {
    "name": "2026-06-25T19-20-43",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-25T19-16-18",
    "is_current": true,
    "status": "complete",
    "node_count": 44,
    "edge_count": 89,
    "has_vault": true
  },
  {
    "name": "2026-06-25T19-13-43",
    "is_current": false,
    "status": "complete",
    "node_count": 39,
    "edge_count": 66,
    "has_vault": true
  },
  {
    "name": "2026-06-25T19-09-46",
    "is_current": false,
    "status": "complete",
    "node_count": 38,
    "edge_count": 66,
    "has_vault": true
  },
  {
    "name": "2026-06-25T19-07-14",
    "is_current": false,
    "status": "complete",
    "node_count": 39,
    "edge_count": 62,
    "has_vault": true
  },
  {
    "name": "2026-06-25T18-51-57",
    "is_current": false,
    "status": "complete",
    "node_count": 45,
    "edge_count": 78,
    "has_vault": true
  },
  {
    "name": "2026-06-25T18-18-11",
    "is_current": false,
    "status": "complete",
    "node_count": 36,
    "edge_count": 29,
    "has_vault": true
  },
  {
    "name": "2026-06-25T18-10-06",
    "is_current": false,
    "status": "complete",
    "node_count": 45,
    "edge_count": 74,
    "has_vault": true
  },
  {
    "name": "2026-06-25T17-55-36",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T11-41-27",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-42-32",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-42-31",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-40-52",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-38-55",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-37-58",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-37-19",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-21-46",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-17-27",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T07-12-57",
    "is_current": false,
    "status": "complete",
    "node_count": 54,
    "edge_count": 103,
    "has_vault": true
  },
  {
    "name": "2026-06-22T07-12-35",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  },
  {
    "name": "2026-06-22T06-52-04",
    "is_current": false,
    "status": "incomplete",
    "node_count": 0,
    "edge_count": 0,
    "has_vault": false
  }
]
```
**Result: PASS**

### Q04: Schema structure
**Tool:** `mykg_get_schema`  
**Args:** `{}`  

```json
{
  "concepts": [
    {
      "type": "Organization",
      "parent": null,
      "attributes": [
        "name",
        "description",
        "headquarters"
      ]
    },
    {
      "type": "Person",
      "parent": null,
      "attributes": [
        "name",
        "title",
        "email",
        "start_date"
      ]
    },
    {
      "type": "Team",
      "parent": null,
      "attributes": [
        "name",
        "focus",
        "member_count"
      ]
    },
    {
      "type": "Project",
      "parent": null,
      "attributes": [
        "name",
        "status",
        "priority",
        "budget"
      ]
    },
    {
      "type": "Technology",
      "parent": null,
      "attributes": [
        "name",
        "category",
        "version"
      ]
    },
    {
      "type": "Location",
      "parent": null,
      "attributes": [
        "name",
        "country",
        "region"
      ]
    },
    {
      "type": "Document",
      "parent": null,
      "attributes": [
        "name",
        "description"
      ]
    },
    {
      "type": "Role",
      "parent": null,
      "attributes": [
        "name",
        "start_date",
        "end_date"
      ]
    }
  ],
  "properties": [
    {
      "name": "employs",
      "domain": "Organization",
      "range": "Person",
      "attributes": []
    },
    {
      "name": "manages",
      "domain": "Person",
      "range": "Team",
      "attributes": []
    },
    {
      "name": "reports_to",
      "domain": "Person",
      "range": "Person",
      "attributes": []
    },
    {
      "name": "member_of",
      "domain": "Person",
      "range": "Team",
      "attributes": []
    },
    {
      "name": "leads",
      "domain": "Person",
      "range": "Team",
      "attributes": []
    },
    {
      "name": "works_on",
      "domain": "Person",
      "range": "Project",
      "attributes": [
        "role",
        "start_date",
        "end_date"
      ]
    },
    {
      "name": "owns",
      "domain": "Team",
      "range": "Project",
      "attributes": []
    },
    {
      "name": "depends_on",
      "domain": "Project",
      "range": "Project",
      "attributes": []
    },
    {
      "name": "uses",
      "domain": "Project",
      "range": "Technology",
      "attributes": []
    },
    {
      "name": "located_in",
      "domain": "Organization",
      "range": "Location",
      "attributes": []
    },
    {
      "name": "partnered_with",
      "domain": "Organization",
      "range": "Organization",
      "attributes": [
        "relationship_type",
        "start_date",
        "end_date"
      ]
    },
    {
      "name": "advises",
      "domain": "Organization",
      "range": "Organization",
      "attributes": [
        "relationship_type"
      ]
    },
    {
      "name": "signed_with",
      "domain": "Organization",
      "range": "Organization",
      "attributes": [
        "contract_type",
        "start_date",
        "end_date"
      ]
    },
    {
      "name": "provides",
      "domain": "Organization",
      "range": "Project",
      "attributes": []
    },
    {
      "name": "authored",
      "domain": "Person",
      "range": "Document",
      "attributes": []
    },
    {
      "name": "contains",
      "domain": "Document",
      "range": "Project",
      "attributes": []
    },
    {
      "name": "related_to",
      "domain": "Technology",
      "range": "Technology",
      "attributes": []
    },
    {
      "name": "reports_about",
      "domain": "Document",
      "range": "Organization",
      "attributes": []
    }
  ]
}
```
**Result: PASS**

## 2. Search Queries

### Q05: Find people named Alice
**Tool:** `mykg_search_nodes`  
**Args:** `{"query":"Alice","type":"Person"}`  

```json
[
  {
    "id": "person-alice-chen",
    "type": "Person",
    "name": "Alice Chen",
    "confidence": 0.99,
    "match_field": "prefix: Alice Chen"
  }
]
```
**Result: PASS**

### Q06: Search for database tech
**Tool:** `mykg_search_nodes`  
**Args:** `{"query":"database","limit":5}`  

```json
[
  {
    "id": "technology-pinecone",
    "type": "Technology",
    "name": "Pinecone",
    "confidence": 0.945,
    "match_field": "substring: vector database"
  },
  {
    "id": "technology-aws-aurora",
    "type": "Technology",
    "name": "AWS Aurora",
    "confidence": 0.99,
    "match_field": "attr:category=database"
  },
  {
    "id": "technology-weaviate",
    "type": "Technology",
    "name": "Weaviate",
    "confidence": 0.9800000000000001,
    "match_field": "attr:category=vector database"
  },
  {
    "id": "technology-qdrant",
    "type": "Technology",
    "name": "Qdrant",
    "confidence": 0.9800000000000001,
    "match_field": "attr:category=vector database"
  },
  {
    "id": "technology-postgresql-15",
    "type": "Technology",
    "name": "PostgreSQL 15",
    "confidence": 0.99,
    "match_field": "attr:category=database"
  }
]
```
**Result: PASS**

### Q07: Non-existent entity
**Tool:** `mykg_search_nodes`  
**Args:** `{"query":"xyznonexistent"}`  

```json
No nodes found matching 'xyznonexistent'. Use mykg_list_node_types to see available types.
```
**Result: PASS**

### Q08: Search across attributes
**Tool:** `mykg_search_nodes`  
**Args:** `{"query":"acme","limit":10}`  

```json
[
  {
    "id": "organization-acme-corp",
    "type": "Organization",
    "name": "Acme Corp",
    "confidence": 0.99,
    "match_field": "prefix: Acme Corp"
  },
  {
    "id": "person-alice-chen",
    "type": "Person",
    "name": "Alice Chen",
    "confidence": 0.99,
    "match_field": "attr:email=alice.chen@acme.com"
  }
]
```
**Result: PASS**

## 3. Node Detail Queries

### Q09: Full details of Acme Corp
**Tool:** `mykg_get_node`  
**Args:** `{"node_id":"organization-acme-corp"}`  

```json
{
  "id": "organization-acme-corp",
  "type": "Organization",
  "confidence": 0.99,
  "attributes": {
    "name": {
      "value": "Acme Corp",
      "confidence": 0.99
    },
    "description": {
      "value": "company",
      "confidence": 0.7
    },
    "headquarters": {
      "value": null,
      "confidence": 0.0
    }
  },
  "source_files": [
    "input.md",
    "partners.md",
    "projects.md",
    "team.md",
    "technologies.md"
  ]
}
```
**Result: PASS**

### Q10: Non-existent node
**Tool:** `mykg_get_node`  
**Args:** `{"node_id":"person-nobody"}`  

```json
Error: Node 'person-nobody' not found. Use mykg_search_nodes to find valid IDs.
```
**Result: PASS**

### Q11: Vault note for Acme Corp
**Tool:** `mykg_read_note`  
**Args:** `{"node_id":"organization-acme-corp"}`  

```json
---
confidence: 0.99
id: organization-acme-corp
sources:
- input.md
- partners.md
- projects.md
- team.md
- technologies.md
type: Organization
---

# Acme Corp

## Attributes
- **description**: company (0.7)

## Relationships

### Outgoing
- [[DataSystems Inc]] — partnered_with (0.98)
- [[NovaTech Inc]] — advises (0.78)
- [[HashiCorp]] — signed_with (0.95)
- [[Carol Okafor]] — employs (0.98)
- [[Sandra Kim]] — employs (0.95)
- [[Marcus Tan]] — employs (0.7)
- [[Lisa Huang]] — employs (0.7)
- [[Bob Martinez]] — employs (0.98)
- [[Alice Chen]] — employs (0.99)
- [[James Whitfield]] — employs (0.99)
- [[Dr. Yuna Park]] — employs (0.98)
- [[DataSystems Inc]] — signed_with (0.98)
- [[NovaTech Inc]] — partnered_with (0.58)

### Incoming
- [[Bob Martinez]] — manages (0.0)
- [[Alice Chen]] — leads (0.0)
- [[Dr. Yuna Park]] — leads (0.0)
- [[Princess Leia]] — authored (0.0)
- [[DataSystems Inc]] — reports_about (0.0)
- [[Amazon Web Services (AWS)]] — reports_about (0.0)
- [[HashiCorp]] — reports_about (0.0)
- [[NovaTech Inc]] — reports_about (0.0)
- [[Google]] — reports_about (0.0)
- [[DeepMind]] — reports_about (0.0)

## Source Files
- input.md
- partners.md
- projects.md
- team.md
- technologies.md
```
**Result: PASS**

### Q12: Vault note for orphan
**Tool:** `mykg_read_note`  
**Args:** `{"node_id":"person-luke-skywalker"}`  

```json
---
confidence: 0.98
id: person-luke-skywalker
sources:
- input.md
- partners.md
- projects.md
- team.md
- technologies.md
type: Person
---

# Luke Skywalker

## Source Files
- input.md
- partners.md
- projects.md
- team.md
- technologies.md
```
**Result: PASS**

## 4. Relationship Queries

### Q13: Incoming edges to Acme
**Tool:** `mykg_get_neighbors`  
**Args:** `{"node_id":"organization-acme-corp","direction":"incoming","limit":5}`  

```json
{
  "node_id": "organization-acme-corp",
  "direction": "incoming",
  "edge_count": 5,
  "edges": [
    {
      "id": "edge-573d44",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-931711",
      "type": "leads",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "input.md",
        "partners.md",
        "partners.md",
        "projects.md",
        "projects.md",
        "team.md",
        "team.md",
        "technologies.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-df144f",
      "type": "leads",
      "from": "person-dr-yuna-park",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-73597c",
      "type": "authored",
      "from": "person-princess-leia",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-492301",
      "type": "reports_about",
      "from": "organization-datasystems-inc",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    }
  ],
  "neighbors": [
    {
      "id": "person-alice-chen",
      "type": "Person",
      "name": "Alice Chen",
      "confidence": 0.99
    },
    {
      "id": "person-dr-yuna-park",
      "type": "Person",
      "name": "Dr. Yuna Park",
      "confidence": 0.99
    },
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "name": "DataSystems Inc",
      "confidence": 0.99
    },
    {
      "id": "person-princess-leia",
      "type": "Person",
      "name": "Princess Leia",
      "confidence": 0.9800000000000001
    },
    {
      "id": "person-bob-martinez",
      "type": "Person",
      "name": "Bob Martinez",
      "confidence": 0.99
    }
  ]
}
```
**Result: PASS**

### Q14: Outgoing edges from Acme
**Tool:** `mykg_get_neighbors`  
**Args:** `{"node_id":"organization-acme-corp","direction":"outgoing","limit":5}`  

```json
{
  "node_id": "organization-acme-corp",
  "direction": "outgoing",
  "edge_count": 5,
  "edges": [
    {
      "id": "edge-cb9bf5",
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.9800000000000001,
      "attributes": {
        "relationship_type": {
          "value": "strategic partnership",
          "confidence": 0.97
        },
        "start_date": {
          "value": "2025-09",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-5fc27b",
      "type": "advises",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.78,
      "attributes": {
        "relationship_type": {
          "value": "informal advisory relationship",
          "confidence": 0.92
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f7a018",
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-hashicorp",
      "confidence": 0.95,
      "attributes": {
        "contract_type": {
          "value": "enterprise licence",
          "confidence": 0.96
        },
        "start_date": {
          "value": "2026-Q1",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-1b3995",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-carol-okafor",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-c2585f",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-sandra-kim",
      "confidence": 0.95,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    }
  ],
  "neighbors": [
    {
      "id": "organization-novatech-inc",
      "type": "Organization",
      "name": "NovaTech Inc",
      "confidence": 0.99
    },
    {
      "id": "person-carol-okafor",
      "type": "Person",
      "name": "Carol Okafor",
      "confidence": 0.99
    },
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "name": "DataSystems Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-hashicorp",
      "type": "Organization",
      "name": "HashiCorp",
      "confidence": 0.99
    },
    {
      "id": "person-sandra-kim",
      "type": "Person",
      "name": "Sandra Kim",
      "confidence": 0.99
    }
  ]
}
```
**Result: PASS**

### Q15: Both directions
**Tool:** `mykg_get_neighbors`  
**Args:** `{"node_id":"organization-acme-corp","direction":"both","limit":5}`  

```json
{
  "node_id": "organization-acme-corp",
  "direction": "both",
  "edge_count": 5,
  "edges": [
    {
      "id": "edge-cb9bf5",
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.9800000000000001,
      "attributes": {
        "relationship_type": {
          "value": "strategic partnership",
          "confidence": 0.97
        },
        "start_date": {
          "value": "2025-09",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-5fc27b",
      "type": "advises",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.78,
      "attributes": {
        "relationship_type": {
          "value": "informal advisory relationship",
          "confidence": 0.92
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f7a018",
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-hashicorp",
      "confidence": 0.95,
      "attributes": {
        "contract_type": {
          "value": "enterprise licence",
          "confidence": 0.96
        },
        "start_date": {
          "value": "2026-Q1",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-1b3995",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-carol-okafor",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-c2585f",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-sandra-kim",
      "confidence": 0.95,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    }
  ],
  "neighbors": [
    {
      "id": "organization-novatech-inc",
      "type": "Organization",
      "name": "NovaTech Inc",
      "confidence": 0.99
    },
    {
      "id": "person-carol-okafor",
      "type": "Person",
      "name": "Carol Okafor",
      "confidence": 0.99
    },
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "name": "DataSystems Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-hashicorp",
      "type": "Organization",
      "name": "HashiCorp",
      "confidence": 0.99
    },
    {
      "id": "person-sandra-kim",
      "type": "Person",
      "name": "Sandra Kim",
      "confidence": 0.99
    }
  ]
}
```
**Result: PASS**

### Q16: Filter by edge type
**Tool:** `mykg_get_neighbors`  
**Args:** `{"node_id":"organization-acme-corp","edge_type":"partners_with"}`  

```json
{
  "node_id": "organization-acme-corp",
  "direction": "both",
  "edge_count": 0,
  "edges": [],
  "neighbors": []
}
```
**Result: PASS**

### Q17: Orphan node neighbors
**Tool:** `mykg_get_neighbors`  
**Args:** `{"node_id":"person-luke-skywalker"}`  

```json
{
  "node_id": "person-luke-skywalker",
  "direction": "both",
  "edge_count": 0,
  "edges": [],
  "neighbors": []
}
```
**Result: PASS**

## 5. Path Queries

### Q18: Alice Chen → Acme Corp
**Tool:** `mykg_find_path`  
**Args:** `{"from_id":"person-alice-chen","to_id":"organization-acme-corp"}`  

```json
{
  "path": [
    {
      "id": "person-alice-chen",
      "type": "Person",
      "name": "Alice Chen",
      "confidence": 0.99
    },
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "name": "Acme Corp",
      "confidence": 0.99
    }
  ],
  "hops": [
    {
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "edge": {
        "type": "employs",
        "confidence": 0.99
      }
    }
  ],
  "length": 1
}
```
**Result: PASS**

### Q19: Max hops = 1
**Tool:** `mykg_find_path`  
**Args:** `{"from_id":"person-alice-chen","to_id":"organization-acme-corp","max_hops":1}`  

```json
{
  "path": [
    {
      "id": "person-alice-chen",
      "type": "Person",
      "name": "Alice Chen",
      "confidence": 0.99
    },
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "name": "Acme Corp",
      "confidence": 0.99
    }
  ],
  "hops": [
    {
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "edge": {
        "type": "employs",
        "confidence": 0.99
      }
    }
  ],
  "length": 1
}
```
**Result: PASS**

### Q20: Path from orphan (no path)
**Tool:** `mykg_find_path`  
**Args:** `{"from_id":"person-luke-skywalker","to_id":"organization-acme-corp"}`  

```json
No path found between 'person-luke-skywalker' and 'organization-acme-corp'.
```
**Result: PASS**

### Q21: Invalid node ID
**Tool:** `mykg_find_path`  
**Args:** `{"from_id":"nonexistent","to_id":"organization-acme-corp"}`  

```json
Error: Node 'nonexistent' not found. Use mykg_search_nodes to find valid IDs.
```
**Result: PASS**

## 6. Graph Analysis Queries

### Q22: Top 5 hub nodes
**Tool:** `mykg_hub_nodes`  
**Args:** `{"top_n":5}`  

```json
[
  {
    "id": "organization-acme-corp",
    "type": "Organization",
    "name": "Acme Corp",
    "confidence": 0.99,
    "degree": 21,
    "in_degree": 10,
    "out_degree": 11
  },
  {
    "id": "project-rag-pipeline-project",
    "type": "Project",
    "name": "RAG Pipeline Project",
    "confidence": 0.945,
    "degree": 17,
    "in_degree": 5,
    "out_degree": 12
  },
  {
    "id": "project-db-migration-project",
    "type": "Project",
    "name": "DB Migration Project",
    "confidence": 0.99,
    "degree": 12,
    "in_degree": 4,
    "out_degree": 8
  },
  {
    "id": "organization-datasystems-inc",
    "type": "Organization",
    "name": "DataSystems Inc",
    "confidence": 0.99,
    "degree": 6,
    "in_degree": 1,
    "out_degree": 5
  },
  {
    "id": "project-platform-secrets-service",
    "type": "Project",
    "name": "Platform Secrets Service",
    "confidence": 0.96,
    "degree": 6,
    "in_degree": 4,
    "out_degree": 2
  }
]
```
**Result: PASS**

### Q23: Orphan/isolated nodes
**Tool:** `mykg_orphan_nodes`  
**Args:** `{}`  

```json
{
  "orphan_count": 3,
  "total_nodes": 44,
  "orphans": [
    {
      "id": "person-luke-skywalker",
      "type": "Person",
      "name": "Luke Skywalker",
      "confidence": 0.9800000000000001
    },
    {
      "id": "person-darth-vader",
      "type": "Person",
      "name": "Darth Vader",
      "confidence": 0.9800000000000001
    },
    {
      "id": "person-beru",
      "type": "Person",
      "name": "Beru",
      "confidence": 0.95
    }
  ]
}
```
**Result: PASS**

### Q24: Subgraph: Organizations
**Tool:** `mykg_query_subgraph`  
**Args:** `{"types":["Organization"]}`  

```json
{
  "nodes": [
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "name": "DataSystems Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "name": "Acme Corp",
      "confidence": 0.99
    },
    {
      "id": "organization-novatech-inc",
      "type": "Organization",
      "name": "NovaTech Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-hashicorp",
      "type": "Organization",
      "name": "HashiCorp",
      "confidence": 0.99
    },
    {
      "id": "organization-amazon-web-services-aws",
      "type": "Organization",
      "name": "Amazon Web Services (AWS)",
      "confidence": 0.99
    },
    {
      "id": "organization-google",
      "type": "Organization",
      "name": "Google",
      "confidence": 0.95
    },
    {
      "id": "organization-deepmind",
      "type": "Organization",
      "name": "DeepMind",
      "confidence": 0.95
    },
    {
      "id": "organization-mit",
      "type": "Organization",
      "name": "MIT",
      "confidence": 0.9
    },
    {
      "id": "organization-stanford",
      "type": "Organization",
      "name": "Stanford",
      "confidence": 0.9
    }
  ],
  "edges": [
    {
      "id": "edge-cb9bf5",
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.9800000000000001,
      "attributes": {
        "relationship_type": {
          "value": "strategic partnership",
          "confidence": 0.97
        },
        "start_date": {
          "value": "2025-09",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-5fc27b",
      "type": "advises",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.78,
      "attributes": {
        "relationship_type": {
          "value": "informal advisory relationship",
          "confidence": 0.92
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f7a018",
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-hashicorp",
      "confidence": 0.95,
      "attributes": {
        "contract_type": {
          "value": "enterprise licence",
          "confidence": 0.96
        },
        "start_date": {
          "value": "2026-Q1",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-e661af",
      "type": "located_in",
      "from": "organization-datasystems-inc",
      "to": "organization-mit",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-492301",
      "type": "reports_about",
      "from": "organization-datasystems-inc",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-15e4a9",
      "type": "reports_about",
      "from": "organization-amazon-web-services-aws",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-e84e78",
      "type": "reports_about",
      "from": "organization-hashicorp",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-bddcc8",
      "type": "reports_about",
      "from": "organization-novatech-inc",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-22d8e5",
      "type": "reports_about",
      "from": "organization-google",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f3be1d",
      "type": "reports_about",
      "from": "organization-deepmind",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.98,
      "method": "orphan_inferred",
      "attributes": {
        "contract_type": {
          "value": null,
          "confidence": 0.0
        },
        "start_date": {
          "value": null,
          "confidence": 0.0
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "source_files": [
        "partners.md"
      ],
      "id": "edge-9a5236"
    },
    {
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.58,
      "method": "orphan_inferred",
      "attributes": {
        "relationship_type": {
          "value": null,
          "confidence": 0.0
        },
        "start_date": {
          "value": null,
          "confidence": 0.0
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "source_files": [
        "partners.md"
      ],
      "id": "edge-27a74f"
    }
  ],
  "stats": {
    "node_count": 9,
    "edge_count": 12
  }
}
```
**Result: PASS**

### Q25: Subgraph: confidence ≥ 0.98
**Tool:** `mykg_query_subgraph`  
**Args:** `{"min_confidence":0.98}`  

```json
{
  "nodes": [
    {
      "id": "organization-datasystems-inc",
      "type": "Organization",
      "name": "DataSystems Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "name": "Acme Corp",
      "confidence": 0.99
    },
    {
      "id": "organization-novatech-inc",
      "type": "Organization",
      "name": "NovaTech Inc",
      "confidence": 0.99
    },
    {
      "id": "organization-hashicorp",
      "type": "Organization",
      "name": "HashiCorp",
      "confidence": 0.99
    },
    {
      "id": "organization-amazon-web-services-aws",
      "type": "Organization",
      "name": "Amazon Web Services (AWS)",
      "confidence": 0.99
    },
    {
      "id": "person-carol-okafor",
      "type": "Person",
      "name": "Carol Okafor",
      "confidence": 0.99
    },
    {
      "id": "person-sandra-kim",
      "type": "Person",
      "name": "Sandra Kim",
      "confidence": 0.99
    },
    {
      "id": "person-bob-martinez",
      "type": "Person",
      "name": "Bob Martinez",
      "confidence": 0.99
    },
    {
      "id": "person-alice-chen",
      "type": "Person",
      "name": "Alice Chen",
      "confidence": 0.99
    },
    {
      "id": "person-james-whitfield",
      "type": "Person",
      "name": "James Whitfield",
      "confidence": 0.99
    },
    {
      "id": "person-dr-yuna-park",
      "type": "Person",
      "name": "Dr. Yuna Park",
      "confidence": 0.99
    },
    {
      "id": "person-luke-skywalker",
      "type": "Person",
      "name": "Luke Skywalker",
      "confidence": 0.9800000000000001
    },
    {
      "id": "person-princess-leia",
      "type": "Person",
      "name": "Princess Leia",
      "confidence": 0.9800000000000001
    },
    {
      "id": "person-darth-vader",
      "type": "Person",
      "name": "Darth Vader",
      "confidence": 0.9800000000000001
    },
    {
      "id": "project-db-migration-project",
      "type": "Project",
      "name": "DB Migration Project",
      "confidence": 0.99
    },
    {
      "id": "technology-vault",
      "type": "Technology",
      "name": "Vault",
      "confidence": 0.99
    },
    {
      "id": "technology-aws-aurora",
      "type": "Technology",
      "name": "AWS Aurora",
      "confidence": 0.99
    },
    {
      "id": "technology-weaviate",
      "type": "Technology",
      "name": "Weaviate",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-qdrant",
      "type": "Technology",
      "name": "Qdrant",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-postgresql-15",
      "type": "Technology",
      "name": "PostgreSQL 15",
      "confidence": 0.99
    },
    {
      "id": "technology-github-actions",
      "type": "Technology",
      "name": "GitHub Actions",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-kubernetes-eks",
      "type": "Technology",
      "name": "Kubernetes (EKS)",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-aws",
      "type": "Technology",
      "name": "AWS",
      "confidence": 0.99
    },
    {
      "id": "technology-python",
      "type": "Technology",
      "name": "Python",
      "confidence": 0.99
    },
    {
      "id": "technology-pytorch",
      "type": "Technology",
      "name": "PyTorch",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-hugging-face-transformers",
      "type": "Technology",
      "name": "Hugging Face Transformers",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-fastapi",
      "type": "Technology",
      "name": "FastAPI",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-go",
      "type": "Technology",
      "name": "Go",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-react",
      "type": "Technology",
      "name": "React",
      "confidence": 0.9800000000000001
    },
    {
      "id": "technology-typescript",
      "type": "Technology",
      "name": "TypeScript",
      "confidence": 0.9800000000000001
    }
  ],
  "edges": [
    {
      "id": "edge-cb9bf5",
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.9800000000000001,
      "attributes": {
        "relationship_type": {
          "value": "strategic partnership",
          "confidence": 0.97
        },
        "start_date": {
          "value": "2025-09",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-5fc27b",
      "type": "advises",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.78,
      "attributes": {
        "relationship_type": {
          "value": "informal advisory relationship",
          "confidence": 0.92
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f7a018",
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-hashicorp",
      "confidence": 0.95,
      "attributes": {
        "contract_type": {
          "value": "enterprise licence",
          "confidence": 0.96
        },
        "start_date": {
          "value": "2026-Q1",
          "confidence": 0.9
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-444bc3",
      "type": "provides",
      "from": "organization-amazon-web-services-aws",
      "to": "project-db-migration-project",
      "confidence": 0.72,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-d96a3f",
      "type": "employs",
      "from": "organization-datasystems-inc",
      "to": "person-carol-okafor",
      "confidence": 0.96,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-1b3995",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-carol-okafor",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-c2585f",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-sandra-kim",
      "confidence": 0.95,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-26c0a5",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-bob-martinez",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-aa4d31",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-alice-chen",
      "confidence": 0.99,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-eea0c7",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-james-whitfield",
      "confidence": 0.99,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-969545",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-dr-yuna-park",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-9dc267",
      "type": "reports_to",
      "from": "person-bob-martinez",
      "to": "person-sandra-kim",
      "confidence": 0.9800000000000001,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-a245ab",
      "type": "works_on",
      "from": "person-carol-okafor",
      "to": "project-db-migration-project",
      "confidence": 0.95,
      "attributes": {
        "role": {
          "value": "core engineering contributor",
          "confidence": 0.92
        },
        "start_date": {
          "value": "2026",
          "confidence": 0.6
        },
        "end_date": {
          "value": "2026",
          "confidence": 0.6
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-ee69eb",
      "type": "works_on",
      "from": "person-alice-chen",
      "to": "project-db-migration-project",
      "confidence": 0.95,
      "attributes": {
        "role": {
          "value": "core engineering contributor",
          "confidence": 0.95
        },
        "start_date": {
          "value": null,
          "confidence": 0.0
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-f4962b",
      "type": "works_on",
      "from": "person-bob-martinez",
      "to": "project-db-migration-project",
      "confidence": 0.8,
      "attributes": {
        "role": {
          "value": "initiator",
          "confidence": 0.9
        },
        "start_date": {
          "value": "2026-01",
          "confidence": 0.8
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-573d44",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-b2228e",
      "type": "manages",
      "from": "person-bob-martinez",
      "to": "project-db-migration-project",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-307cb6",
      "type": "member_of",
      "from": "person-carol-okafor",
      "to": "project-db-migration-project",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-602ea5",
      "type": "member_of",
      "from": "person-alice-chen",
      "to": "project-db-migration-project",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-338936",
      "type": "member_of",
      "from": "person-bob-martinez",
      "to": "project-db-migration-project",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-931711",
      "type": "leads",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "input.md",
        "partners.md",
        "partners.md",
        "projects.md",
        "projects.md",
        "team.md",
        "team.md",
        "technologies.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-df144f",
      "type": "leads",
      "from": "person-dr-yuna-park",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-73597c",
      "type": "authored",
      "from": "person-princess-leia",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-537766",
      "type": "depends_on",
      "from": "project-db-migration-project",
      "to": "technology-aws-aurora",
      "confidence": 0.97,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-1d4536",
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "technology-aws-aurora",
      "confidence": 0.95,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-8e949f",
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "technology-postgresql-15",
      "confidence": 0.95,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-2c607e",
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "technology-aws",
      "confidence": 0.9,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-537a3f",
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "technology-github-actions",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-078fa0",
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "technology-kubernetes-eks",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-992b80",
      "type": "contains",
      "from": "project-db-migration-project",
      "to": "technology-aws-aurora",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-df9fc9",
      "type": "related_to",
      "from": "technology-postgresql-15",
      "to": "technology-aws-aurora",
      "confidence": 0.6,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-99129f",
      "type": "related_to",
      "from": "technology-fastapi",
      "to": "technology-python",
      "confidence": 0.4,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-c4b4f2",
      "type": "related_to",
      "from": "technology-react",
      "to": "technology-typescript",
      "confidence": 0.4,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-492301",
      "type": "reports_about",
      "from": "organization-datasystems-inc",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-15e4a9",
      "type": "reports_about",
      "from": "organization-amazon-web-services-aws",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-e84e78",
      "type": "reports_about",
      "from": "organization-hashicorp",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-bddcc8",
      "type": "reports_about",
      "from": "organization-novatech-inc",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "type": "signed_with",
      "from": "organization-acme-corp",
      "to": "organization-datasystems-inc",
      "confidence": 0.98,
      "method": "orphan_inferred",
      "attributes": {
        "contract_type": {
          "value": null,
          "confidence": 0.0
        },
        "start_date": {
          "value": null,
          "confidence": 0.0
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "source_files": [
        "partners.md"
      ],
      "id": "edge-9a5236"
    },
    {
      "type": "reports_to",
      "from": "person-sandra-kim",
      "to": "person-james-whitfield",
      "confidence": 0.72,
      "method": "orphan_inferred",
      "attributes": {},
      "source_files": [
        "partners.md"
      ],
      "id": "edge-eb413f"
    },
    {
      "type": "uses",
      "from": "project-db-migration-project",
      "to": "organization-amazon-web-services-aws",
      "confidence": 0.95,
      "method": "orphan_inferred",
      "attributes": {},
      "source_files": [
        "partners.md"
      ],
      "id": "edge-e6dd42"
    },
    {
      "type": "partnered_with",
      "from": "organization-acme-corp",
      "to": "organization-novatech-inc",
      "confidence": 0.58,
      "method": "orphan_inferred",
      "attributes": {
        "relationship_type": {
          "value": null,
          "confidence": 0.0
        },
        "start_date": {
          "value": null,
          "confidence": 0.0
        },
        "end_date": {
          "value": null,
          "confidence": 0.0
        }
      },
      "source_files": [
        "partners.md"
      ],
      "id": "edge-27a74f"
    }
  ],
  "stats": {
    "node_count": 30,
    "edge_count": 41
  }
}
```
**Result: PASS**

### Q26: Subgraph: specific nodes
**Tool:** `mykg_query_subgraph`  
**Args:** `{"node_ids":["organization-acme-corp","person-alice-chen"]}`  

```json
{
  "nodes": [
    {
      "id": "organization-acme-corp",
      "type": "Organization",
      "name": "Acme Corp",
      "confidence": 0.99
    },
    {
      "id": "person-alice-chen",
      "type": "Person",
      "name": "Alice Chen",
      "confidence": 0.99
    }
  ],
  "edges": [
    {
      "id": "edge-aa4d31",
      "type": "employs",
      "from": "organization-acme-corp",
      "to": "person-alice-chen",
      "confidence": 0.99,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "partners.md",
        "projects.md",
        "team.md",
        "technologies.md"
      ]
    },
    {
      "id": "edge-931711",
      "type": "leads",
      "from": "person-alice-chen",
      "to": "organization-acme-corp",
      "confidence": 0.0,
      "attributes": {},
      "method": "llm_extraction",
      "source_files": [
        "input.md",
        "input.md",
        "partners.md",
        "partners.md",
        "projects.md",
        "projects.md",
        "team.md",
        "team.md",
        "technologies.md",
        "technologies.md"
      ]
    }
  ],
  "stats": {
    "node_count": 2,
    "edge_count": 2
  }
}
```
**Result: PASS**

## 7. Traversal Queries

### Q27: BFS from Acme depth=1
**Tool:** `mykg_query_graph`  
**Args:** `{"question":"Acme Corp","mode":"bfs","depth":1}`  

```json
# Knowledge Graph Context: Acme Corp
Seeds: organization-acme-corp | Mode: bfs | Depth: 1
Nodes visited: 16 | Edges found: 15

## Nodes
- [Organization] NovaTech Inc (organization-novatech-inc) conf=0.99 (description=SaaS company focused on developer tooling)
- [Person] Alice Chen (person-alice-chen) conf=0.99 (title=Senior Software Engineer, email=alice.chen@acme.com, start_date=2021-03)
- [Person] James Whitfield (person-james-whitfield) conf=0.99 (title=CTO)
- [Organization] Acme Corp (organization-acme-corp) conf=0.99 (description=company)
- [Person] Carol Okafor (person-carol-okafor) conf=0.99 (title=DevOps Engineer / Site Reliability Engineer, start_date=2019)
- [Person] Marcus Tan (person-marcus-tan) conf=0.95 (title=enterprise account manager)
- [Organization] Google (organization-google) conf=0.95 (description=employer of Bob Martinez)
- [Person] Lisa Huang (person-lisa-huang) conf=0.95 (title=account manager)
- [Person] Dr. Yuna Park (person-dr-yuna-park) conf=0.99 (title=Principal Researcher)
- [Organization] DataSystems Inc (organization-datasystems-inc) conf=0.99 (description=data infrastructure company, headquarters=San Francisco)
- [Organization] HashiCorp (organization-hashicorp) conf=0.99 (description=vendor providing Vault)
- [Person] Princess Leia (person-princess-leia) conf=0.98 (title=member of the Imperial Senate)
- [Person] Bob Martinez (person-bob-martinez) conf=0.99 (title=Director of Engineering, start_date=2018)
- [Person] Sandra Kim (person-sandra-kim) conf=0.99 (title=CEO / VP Engineering, start_date=2015)
- [Organization] DeepMind (organization-deepmind) conf=0.95 (description=former employer of Dr. Yuna Park)
- [Organization] Amazon Web Services (AWS) (organization-amazon-web-services-aws) conf=0.99 (description=primary cloud provider)

## Relationships
- organization-acme-corp --[partnered_with]--> organization-datasystems-inc (conf=0.98)
- organization-acme-corp --[advises]--> organization-novatech-inc (conf=0.78)
- organization-acme-corp --[signed_with]--> organization-hashicorp (conf=0.95)
- organization-acme-corp --[employs]--> person-carol-okafor (conf=0.98)
- organization-acme-corp --[employs]--> person-sandra-kim (conf=0.95)
- organization-acme-corp --[employs]--> person-marcus-tan (conf=0.70)
- organization-acme-corp --[employs]--> person-lisa-huang (conf=0.70)
- organization-acme-corp --[employs]--> person-bob-martinez (conf=0.98)
- organization-acme-corp --[employs]--> person-alice-chen (conf=0.99)
- organization-acme-corp --[employs]--> person-james-whitfield (conf=0.99)
- organization-acme-corp --[employs]--> person-dr-yuna-park (conf=0.98)
- organization-amazon-web-services-aws --[reports_about]--> organization-acme-corp (conf=0.00)
- person-princess-leia --[authored]--> organization-acme-corp (conf=0.00)
- organization-google --[reports_about]--> organization-acme-corp (conf=0.00)
- organization-deepmind --[reports_about]--> organization-acme-corp (conf=0.00)
```
**Result: PASS**

### Q28: DFS from Acme depth=2
**Tool:** `mykg_query_graph`  
**Args:** `{"question":"Acme Corp","mode":"dfs","depth":2}`  

```json
# Knowledge Graph Context: Acme Corp
Seeds: organization-acme-corp | Mode: dfs | Depth: 2
Nodes visited: 21 | Edges found: 20

## Nodes
- [Organization] NovaTech Inc (organization-novatech-inc) conf=0.99 (description=SaaS company focused on developer tooling)
- [Person] Lisa Huang (person-lisa-huang) conf=0.95 (title=account manager)
- [Project] Platform Secrets Service (project-platform-secrets-service) conf=0.96
- [Person] Dr. Priya Nair (person-dr-priya-nair) conf=0.96 (title=VP of Engineering)
- [Person] James Whitfield (person-james-whitfield) conf=0.99 (title=CTO)
- [Project] RAG Pipeline Project (project-rag-pipeline-project) conf=0.94 (status=design phase)
- [Person] Marcus Tan (person-marcus-tan) conf=0.95 (title=enterprise account manager)
- [Organization] HashiCorp (organization-hashicorp) conf=0.99 (description=vendor providing Vault)
- [Organization] MIT (organization-mit) conf=0.90 (description=institution awarding Alice Chen's BSc)
- [Organization] Google (organization-google) conf=0.95 (description=employer of Bob Martinez)
- [Person] Dr. Yuna Park (person-dr-yuna-park) conf=0.99 (title=Principal Researcher)
- [Organization] DataSystems Inc (organization-datasystems-inc) conf=0.99 (description=data infrastructure company, headquarters=San Francisco)
- [Organization] DeepMind (organization-deepmind) conf=0.95 (description=former employer of Dr. Yuna Park)
- [Person] Alice Chen (person-alice-chen) conf=0.99 (title=Senior Software Engineer, email=alice.chen@acme.com, start_date=2021-03)
- [Project] DB Migration Project (project-db-migration-project) conf=0.99 (status=in progress, priority=medium, budget=120000)
- [Organization] Acme Corp (organization-acme-corp) conf=0.99 (description=company)
- [Person] Carol Okafor (person-carol-okafor) conf=0.99 (title=DevOps Engineer / Site Reliability Engineer, start_date=2019)
- [Person] Princess Leia (person-princess-leia) conf=0.98 (title=member of the Imperial Senate)
- [Person] Bob Martinez (person-bob-martinez) conf=0.99 (title=Director of Engineering, start_date=2018)
- [Person] Sandra Kim (person-sandra-kim) conf=0.99 (title=CEO / VP Engineering, start_date=2015)
- [Organization] Amazon Web Services (AWS) (organization-amazon-web-services-aws) conf=0.99 (description=primary cloud provider)

## Relationships
- organization-acme-corp --[partnered_with]--> organization-datasystems-inc (conf=0.98)
- organization-datasystems-inc --[provides]--> project-rag-pipeline-project (conf=0.90)
- organization-datasystems-inc --[employs]--> person-carol-okafor (conf=0.96)
- organization-datasystems-inc --[employs]--> person-dr-priya-nair (conf=0.95)
- organization-datasystems-inc --[located_in]--> organization-mit (conf=0.00)
- organization-acme-corp --[advises]--> organization-novatech-inc (conf=0.78)
- organization-acme-corp --[signed_with]--> organization-hashicorp (conf=0.95)
- organization-hashicorp --[provides]--> project-platform-secrets-service (conf=0.93)
- organization-acme-corp --[employs]--> person-sandra-kim (conf=0.95)
- person-sandra-kim --[reports_to]--> person-james-whitfield (conf=0.72)
- person-bob-martinez --[reports_to]--> person-sandra-kim (conf=0.98)
- organization-acme-corp --[employs]--> person-marcus-tan (conf=0.70)
- organization-acme-corp --[employs]--> person-lisa-huang (conf=0.70)
- organization-acme-corp --[employs]--> person-alice-chen (conf=0.99)
- person-alice-chen --[works_on]--> project-db-migration-project (conf=0.95)
- organization-acme-corp --[employs]--> person-dr-yuna-park (conf=0.98)
- organization-deepmind --[employs]--> person-dr-yuna-park (conf=0.90)
- organization-amazon-web-services-aws --[reports_about]--> organization-acme-corp (conf=0.00)
- person-princess-leia --[authored]--> organization-acme-corp (conf=0.00)
- organization-google --[reports_about]--> organization-acme-corp (conf=0.00)
```
**Result: PASS**

### Q29: BFS: database migration
**Tool:** `mykg_query_graph`  
**Args:** `{"question":"database migration","mode":"bfs","depth":2}`  

```json
No nodes found matching 'database migration'. Try mykg_search_nodes for more flexible search.
```
**Result: PASS**

### Q30: No matching seeds
**Tool:** `mykg_query_graph`  
**Args:** `{"question":"xyznonexistent"}`  

```json
No nodes found matching 'xyznonexistent'. Try mykg_search_nodes for more flexible search.
```
**Result: PASS**

## Summary

| Metric | Value |
|--------|-------|
| Total  | 30 |
| Passed | 30 |
| Failed | 0 |
