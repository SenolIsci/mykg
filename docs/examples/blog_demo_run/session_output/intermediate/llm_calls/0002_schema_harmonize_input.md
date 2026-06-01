## System

You are an RDFS ontology expert. Your job is to harmonize a knowledge graph schema that was produced by merging independent batch proposals. The algorithmic merge does exact and normalized string matching, but it cannot detect semantic near-duplicates — concepts or properties with different names that represent the same real-world category. Fix this silently. Do not explain changes.

You are given:
1. MERGED SCHEMA — the result of algorithmically unioning all batch proposals.
2. RAW PROPOSALS — the individual batch outputs before merging.

Your task: produce a single harmonized schema.

WHAT TO DO
==========
A. COLLAPSE NEAR-DUPLICATE CONCEPTS
   Identify concept types that represent the same real-world category but have slightly
   different names (e.g. "MilitaryUnit" / "ArmyUnit" / "MilitaryFormation"). Keep the
   most general or most frequently used name; merge their attributes (union, deduplicate,
   max 4 per class). Update domain/range in all properties that reference the removed names.

B. COLLAPSE NEAR-DUPLICATE PROPERTIES
   Identify properties with different names but the same semantic meaning
   (e.g. "commands" / "led_by" / "is_commanded_by"). Keep the clearest name; merge
   their attributes. Flip domain/range if needed to make the kept direction consistent.
   IMPORTANT: two properties with identical domain AND identical range are almost always
   duplicates regardless of name difference (e.g. "member_of" and "belongs_to" both
   Person→Organization). Collapse them — keep the more general or more common name.

C. LIFT MISCLASSIFIED INSTANCES TO PROPER TYPES
   If a concept looks like a named entity rather than a reusable category (e.g. "FourthAirForce"),
   remove it and ensure a general parent type exists (e.g. "MilitaryUnit").

D. UNIFY ATTRIBUTE NAMING
   Across all concepts and properties, standardize attribute names for the same field:
   prefer "date" over "incident_date", "name" over "title" when both appear at the same
   level of the hierarchy.

STRICT RULES
============
- Return ONLY valid JSON with keys "concepts" and "properties". No markdown. No explanation.
- "domain" and "range" must be class names that appear in the returned concepts[].
- Root classes have "parent": null. Every non-root class must name a parent in concepts[].
- "attributes" is always a JSON array of strings, never null, never empty for concepts
  (every concept must have at least "name").
- Do NOT add a "Relationship" class.
- Do NOT invent new concepts or properties not derivable from the input.
- Max 4 attributes per concept, max 4 attributes per property.

## User

MERGED SCHEMA:
{
  "concepts": [
    {
      "type": "Organization",
      "parent": null,
      "attributes": [
        "name",
        "description",
        "headquarters_location",
        "type"
      ]
    },
    {
      "type": "Company",
      "parent": "Organization",
      "attributes": [
        "founding_year",
        "annual_revenue"
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
        "title",
        "join_date"
      ]
    },
    {
      "type": "Team",
      "parent": "Organization",
      "attributes": [
        "name",
        "focus_area",
        "member_count"
      ]
    },
    {
      "type": "Project",
      "parent": null,
      "attributes": [
        "name",
        "description",
        "status",
        "budget",
        "target_date"
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
      "type": "Product",
      "parent": "Technology",
      "attributes": [
        "vendor"
      ]
    },
    {
      "type": "Partnership",
      "parent": null,
      "attributes": [
        "name",
        "type",
        "start_date",
        "scope"
      ]
    },
    {
      "type": "Contract",
      "parent": null,
      "attributes": [
        "name",
        "type",
        "signed_date",
        "value"
      ]
    }
  ],
  "properties": [
    {
      "name": "works_at",
      "domain": "Employee",
      "range": "Company",
      "attributes": [
        "role",
        "start_date",
        "end_date"
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
      "name": "contributes_to",
      "domain": "Employee",
      "range": "Project",
      "attributes": [
        "role",
        "contribution_type"
      ]
    },
    {
      "name": "owns",
      "domain": "Employee",
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
      "attributes": [
        "purpose"
      ]
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
      "attributes": [
        "role"
      ]
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
      "attributes": [
        "contact_type"
      ]
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

RAW PROPOSALS:
[
  {
    "concepts": [
      {
        "type": "Organization",
        "parent": null,
        "attributes": [
          "name",
          "description",
          "headquarters_location",
          "type"
        ]
      },
      {
        "type": "Company",
        "parent": "Organization",
        "attributes": [
          "founding_year",
          "annual_revenue"
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
          "title",
          "join_date"
        ]
      },
      {
        "type": "Team",
        "parent": "Organization",
        "attributes": [
          "name",
          "focus_area",
          "member_count"
        ]
      },
      {
        "type": "Project",
        "parent": null,
        "attributes": [
          "name",
          "description",
          "status",
          "budget",
          "target_date"
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
        "type": "Product",
        "parent": "Technology",
        "attributes": [
          "vendor"
        ]
      },
      {
        "type": "Partnership",
        "parent": null,
        "attributes": [
          "name",
          "type",
          "start_date",
          "scope"
        ]
      },
      {
        "type": "Contract",
        "parent": null,
        "attributes": [
          "name",
          "type",
          "signed_date",
          "value"
        ]
      }
    ],
    "properties": [
      {
        "name": "works_at",
        "domain": "Employee",
        "range": "Company",
        "attributes": [
          "role",
          "start_date",
          "end_date"
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
        "name": "contributes_to",
        "domain": "Employee",
        "range": "Project",
        "attributes": [
          "role",
          "contribution_type"
        ]
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
        "attributes": [
          "purpose"
        ]
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
        "attributes": [
          "role"
        ]
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
        "attributes": [
          "contact_type"
        ]
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
]
