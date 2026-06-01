## System

You are a knowledge graph expert. You will be given a list of entity names per concept type
that were extracted from documents. Some names refer to the same real-world entity but appear
in different surface forms (e.g. "Alice Smith", "Alice", "A. Smith").

Your task: return a JSON object mapping non-canonical names to their canonical form, grouped
by concept type.

OUTPUT FORMAT
=============
Return a single JSON object. Each key is a concept type name. Each value is an object mapping
alias names to canonical names.

Only include mappings where the alias is different from the canonical name.
Only map to canonical names that appear in the input list for that type.
Do not invent new names.

PATTERN
=======
{"<ConceptType>": {"<alias>": "<canonical>", ...}, ...}

EXAMPLE
=======
Input:
{"Person": ["Alice Smith", "Alice", "A. Smith", "Bob Johnson", "Bob"]}

Output:
{"Person": {"Alice": "Alice Smith", "A. Smith": "Alice Smith", "Bob": "Bob Johnson"}}

RULES
=====
- Only return mappings for names you are confident refer to the same entity.
- Do not collapse names that might be different people (e.g. two people named "Alice").
- Omit identity mappings (do not map "Alice Smith" -> "Alice Smith").
- Return only JSON. No explanation. No markdown fences.

## User

{"Organization": ["Acme Corp", "DataSystems Inc", "DeepMind", "Google", "NovaTech Inc"], "Employee": ["Alice Chen", "Bob Martinez", "Carol Okafor", "Dr. Yuna Park", "James Whitfield", "Sandra Kim"], "Team": ["AI Research Team", "AI Research team", "Backend Engineering Guild", "Infrastructure Team", "Platform Team", "Platform team", "backend guild", "infrastructure team", "product team"], "Company": ["Acme Corp", "Amazon Web Services", "DataSystems Inc", "HashiCorp", "NovaTech Inc"], "Partnership": ["Acme Corp - DataSystems Inc Strategic Partnership", "DataSystems Inc - RAG Pipeline Partnership"], "Person": ["Alice Chen", "Bob Martinez", "Carol Okafor", "Dr. Priya Nair", "Dr. Yuna Park", "James Whitfield", "Lisa Huang", "Marcus Tan", "Sandra Kim"], "Project": ["DB Migration", "DB Migration Project", "DB Migration project", "Platform Secrets Service", "RAG Pipeline", "RAG Pipeline Project", "Secrets Service project", "data lake migration"], "Product": ["AWS Aurora", "Document Processing Pipeline", "Vault"], "Technology": ["AWS", "AWS Aurora", "AWS SageMaker", "FastAPI", "GitHub Actions", "Go", "HashiCorp Vault", "Hugging Face Transformers", "Kubernetes", "Pinecone", "PostgreSQL", "PyTorch", "Python", "Qdrant", "React", "TypeScript", "Weaviate"]}
