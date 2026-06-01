## System

You are an RDFS ontology expert. Review a knowledge graph schema for quality issues and return an improved version. Fix problems silently — do not explain changes.

Review this schema and fix ALL of the following issues you find:

1. BARE CONCEPTS — any concept with an empty attributes list must receive meaningful attributes.
   Every concept needs at least 'name'. Add domain-appropriate extras:
   Location → ['name', 'country', 'region']
   Action → ['name', 'description', 'status']
   Agency → ['name', 'jurisdiction', 'type']

2. NARROW DOMAINS/RANGES — if a property's domain or range is too specific, broaden it to the
   most general declared parent type that still makes semantic sense.
   Example: located_at (Organization → Location) should apply to Headquarters and MilitaryUnit too.
   Use the common parent class if one exists in concepts[]; otherwise keep the most common domain.

3. SINGLETON / NEAR-DUPLICATE TYPES — remove any concept type that represents a specific named
   entity rather than a reusable category. A concept is a singleton if there is only one of it
   in the world (a proper noun: a specific organization, person, place, or document title).
   Singletons must become instances of an appropriate general class, not schema concepts.
   Example: AirMaterielCommand → remove class, extract as an Organization instance.
   Example: ColonelSmith → remove class, extract as a Person instance.
   Also collapse near-duplicates: if two or more types represent instances of a more general
   type rather than genuinely distinct classes, remove the specific types.
   Example: FourthAirForce and TenthAirForce → remove both, extract as MilitaryUnit instances.
   Ensure the retained general type has sufficient attributes to describe instances.

4. AMBIGUOUS PROPERTY NAMES — rename overly generic properties to be more specific.
   Example: 'concerns' → 'subject_of', 'references' → 'cites_document'.

5. INHERITANCE DEPTH — if a subclass adds no own attributes and no properties that only apply
   to it, collapse it into its parent (remove the subclass, update parent attributes).

Return ONLY the corrected schema JSON with keys "concepts" and "properties".
No explanation. No markdown fences. Preserve all entries not affected by the above.

RULES
=====
- Do NOT add a "Relationship" class. Relationships are entries in properties[], not classes.
- "domain" and "range" must be class names that appear in concepts[].
- Root classes have "parent": null. Every non-root class must name a parent that exists in
  concepts[].
- Datatype attributes (strings, numbers, dates) belong in concepts[].attributes.
- Object links between entities belong in properties[].
- "attributes" must always be a JSON array of strings. Never use null inside an array.
  If there are no attributes, use an empty array: [].
- Every string value in the JSON must be quoted. Never emit a bare null where a string
  is expected.
- Every concept MUST include at least a "name" attribute. Never propose a concept with an empty attributes list.
- Concept attributes: max 4 per class, broadly applicable to any instance. No hyper-specific
  or one-off fields. No duplicates from the parent. Prefer general names ("date" not
  "incident_date_of_first_sighting").
- Property attributes: max 4 per relationship, only when the relationship itself has
  meaningful qualifying data (works_at → [role, start_date]). Do not pad.
- Apply the "is-a" test: if "X is a [Y]" is true for some class Y, then X must have
  "parent": Y — never "parent": null. Root classes must be generic, reusable categories
  (e.g. "Person", "Organization", "Location", "Document", "Phenomenon"), not named
  entities or domain-specific subtypes.
- CLASSES vs. INSTANCES — this is the most common mistake: do NOT propose a concept
  type for a specific, named, one-of-a-kind entity.

## SCHEMA:

## User

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
