## Response

```json
{
  "concepts": [
    {
      "type": "Organization",
      "parent": null,
      "attributes": ["name", "description", "headquarters_location", "type"]
    },
    {
      "type": "Company",
      "parent": "Organization",
      "attributes": ["founding_year", "annual_revenue"]
    },
    {
      "type": "Person",
      "parent": null,
      "attributes": ["name", "email", "education"]
    },
    {
      "type": "Employee",
      "parent": "Person",
      "attributes": ["title", "join_date"]
    },
    {
      "type": "Team",
      "parent": "Organization",
      "attributes": ["name", "focus_area", "member_count"]
    },
    {
      "type": "Project",
      "parent": null,
      "attributes": ["name", "description", "status", "budget", "target_date"]
    },
    {
      "type": "Technology",
      "parent": null,
      "attributes": ["name", "category", "version"]
    },
    {
      "type": "Product",
      "parent": "Technology",
      "attributes": ["vendor"]
    },
    {
      "type": "Partnership",
      "parent": null,
      "attributes": ["name", "type", "start_date", "scope"]
    },
    {
      "type": "Contract",
      "parent": null,
      "attributes": ["name", "type", "signed_date", "value"]
    }
  ],
  "properties": [
    {
      "name": "works_at",
      "domain": "Employee",
      "range": "Company",
      "attributes": ["role", "start_date", "end_date"]
    },
    {
      "name": "manages",
      "domain": "Employee",
      "range": "Team",
      "attributes": []
    },
    {
      "name": "member_of",
      "domain": "Employee",
      "range": "Team",
      "attributes": []
    },
    {
      "name": "reports_to",
      "domain": "Employee",
      "range": "Employee",
      "attributes": []
    },
    {
      "name": "contributes_to",
      "domain": "Employee",
      "range": "Project",
      "attributes": ["role", "contribution_type"]
    },
    {
      "name": "owns",
      "domain": "Employee",
      "range": "Project",
      "attributes": []
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
      "attributes": ["purpose"]
    },
    {
      "name": "uses",
      "domain": "Team",
      "range": "Technology",
      "attributes": []
    },
    {
      "name": "provides",
      "domain": "Company",
      "range": "Product",
      "attributes": []
    },
    {
      "name": "partners_with",
      "domain": "Company",
      "range": "Company",
      "attributes": []
    },
    {
      "name": "governed_by",
      "domain": "Partnership",
      "range": "Contract",
      "attributes": []
    },
    {
      "name": "involves",
      "domain": "Partnership",
      "range": "Company",
      "attributes": ["role"]
    },
    {
      "name": "covers",
      "domain": "Partnership",
      "range": "Project",
      "attributes": []
    },
    {
      "name": "has_contact",
      "domain": "Company",
      "range": "Employee",
      "attributes": ["contact_type"]
    },
    {
      "name": "holds_contract",
      "domain": "Company",
      "range": "Contract",
      "attributes": []
    },
    {
      "name": "leads",
      "domain": "Employee",
      "range": "Organization",
      "attributes": []
    }
  ]
}
```
