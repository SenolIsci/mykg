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
  - id: employee-alice-chen, type: Employee, name: Alice Chen
  - id: employee-bob-martinez, type: Employee, name: Bob Martinez
  - id: employee-carol-okafor, type: Employee, name: Carol Okafor
  - id: employee-dr-yuna-park, type: Employee, name: Dr. Yuna Park
  - id: employee-james-whitfield, type: Employee, name: James Whitfield
  - id: employee-sandra-kim, type: Employee, name: Sandra Kim

ALREADY-CONNECTED GRAPH NODES (cross-reference targets)
=========================================================
  - id: organization-novatech-inc, type: Organization, name: NovaTech Inc
  - id: team-product-team, type: Team, name: product team
  - id: team-infrastructure-team, type: Team, name: Infrastructure Team
  - id: organization-datasystems-inc, type: Organization, name: DataSystems Inc
  - id: organization-acme-corp, type: Organization, name: Acme Corp
  - id: team-platform-team, type: Team, name: Platform Team
  - id: organization-google, type: Organization, name: Google
  - id: organization-deepmind, type: Organization, name: DeepMind
  - id: team-ai-research-team, type: Team, name: AI Research Team

SCHEMA PROPERTIES
=================
  - works_at (Person → Organization)
  - manages (Person → Team)
  - member_of (Person → Team)
  - reports_to (Person → Person)
  - leads (Person → Project)
  - contributes_to (Person → Project)
  - owns (Team → Project)
  - depends_on (Project → Project)
  - uses_technology (Project → Technology)
  - provides (Organization → Product)
  - has_partnership (Organization → Organization)
  - vendor_for (Organization → Organization)
  - has_agreement (Organization → Agreement)
  - account_manager_for (Person → Organization)
  - co_founded (Person → Organization)
  - supports (Agreement → Project)

CHUNK SOURCE TEXT
=================
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

