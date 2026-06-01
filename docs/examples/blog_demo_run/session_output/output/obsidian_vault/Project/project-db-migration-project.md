---
confidence: 0.975
id: project-db-migration-project
sources:
- projects.md
- partners.md
- partners.md
- technologies.md
type: Project
---

# DB Migration Project

## Attributes
- **status**: in progress (1.0)
- **target_completion_date**: end of Q3 2026 (1.0)
- **budget**: $120,000 (1.0)

## Relationships

### Outgoing
- [[Platform Secrets Service]] — depends_on (1.0)
- [[PostgreSQL]] — uses_technology (0.95)
- [[AWS Aurora]] — uses_technology (0.98)
- [[AWS]] — uses_technology (0.85)
- [[Kubernetes]] — uses_technology (0.65)

### Incoming
- [[Infrastructure Team]] — owns (1.0)
- [[Bob Martinez]] — leads (0.9)
- [[Alice Chen]] — contributes_to (1.0)
- [[Carol Okafor]] — contributes_to (1.0)

## Source Files
- projects.md
- partners.md
- partners.md
- technologies.md
