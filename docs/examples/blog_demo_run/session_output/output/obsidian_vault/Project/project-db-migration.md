---
confidence: 0.975
id: project-db-migration
sources:
- partners.md
- partners.md
- projects.md
- technologies.md
type: Project
---

# DB Migration

## Attributes
- **description**: targets AWS Aurora; Database migration project to move Acme Corp's production PostgreSQL clusters from on-premise hardware to AWS Aurora; Moving PostgreSQL clusters to AWS Aurora (1.0)
- **status**: planned; in progress (1.0)
- **budget**: $120,000 (1.0)

## Relationships

### Outgoing
- [[Platform Secrets Service]] — depends_on (1.0)
- [[PostgreSQL]] — uses_technology (1.0)
- [[AWS Aurora]] — uses_technology (1.0)

### Incoming
- [[Acme Corp - DataSystems Inc Strategic Partnership]] — covers_project (0.9)
- [[Infrastructure Team]] — owns (1.0)
- [[Bob Martinez]] — contributes_to (0.95)
- [[Alice Chen]] — contributes_to (1.0)
- [[Carol Okafor]] — contributes_to (1.0)
- [[Acme Corp]] — owns (0.95)

## Source Files
- partners.md
- partners.md
- projects.md
- technologies.md
