## Response

```json
{
  "concepts": [
    {
      "type": "Organization",
      "parent": null,
      "attributes": [
        "name",
        "headquarters_location",
        "industry",
        "founding_year"
      ]
    },
    {
      "type": "Company",
      "parent": "Organization",
      "attributes": [
        "annual_spend"
      ]
    },
    {
      "type": "Person",
      "parent": null,
      "attributes": [
        "name",
        "email",
        "education"
      ]
    },
    {
      "type": "Employee",
      "parent": "Person",
      "attributes": [
        "join_date",
        "title"
      ]
    },
    {
      "type": "Team",
      "parent": null,
      "attributes": [
        "name",
        "description",
        "member_count"
      ]
    },
    {
      "type": "Project",
      "parent": null,
      "attributes": [
        "name",
        "status",
        "target_completion_date",
        "budget"
      ]
    },
    {
      "type": "Technology",
      "parent": null,
      "attributes": [
        "name",
        "type",
        "version"
      ]
    },
    {
      "type": "Product",
      "parent": "Technology",
      "attributes": [
        "name"
      ]
    },
    {
      "type": "Partnership",
      "parent": null,
      "attributes": [
        "name",
        "type",
        "start_date"
      ]
    },
    {
      "type": "Contract",
      "parent": null,
      "attributes": [
        "name",
        "type",
        "signed_date"
      ]
    }
  ],
  "properties": [
    {
      "name": "works_at",
      "domain": "Employee",
      "range": "Company",
      "attributes": [
        "start_date",
        "end_date",
        "role"
      ]
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
      "name": "leads",
      "domain": "Employee",
      "range": "Project",
      "attributes": [
        "role"
      ]
    },
    {
      "name": "contributes_to",
      "domain": "Employee",
      "range": "Project",
      "attributes": [
        "role"
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
      "name": "provides",
      "domain": "Company",
      "range": "Product",
      "attributes": []
    },
    {
      "name": "has_partnership",
      "domain": "Company",
      "range": "Company",
      "attributes": [
        "type",
        "start_date"
      ]
    },
    {
      "name": "vendor_for",
      "domain": "Company",
      "range": "Company",
      "attributes": []
    },
    {
      "name": "has_contract",
      "domain": "Company",
      "range": "Contract",
      "attributes": []
    },
    {
      "name": "account_manager_for",
      "domain": "Employee",
      "range": "Company",
      "attributes": []
    },
    {
      "name": "co_founded",
      "domain": "Person",
      "range": "Company",
      "attributes": [
        "year"
      ]
    },
    {
      "name": "supports",
      "domain": "Partnership",
      "range": "Project",
      "attributes": []
    }
  ]
}
```
