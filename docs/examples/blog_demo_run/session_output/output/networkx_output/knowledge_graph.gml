graph [
  directed 1
  name "mykg knowledge graph"
  node [
    id 0
    label "organization-acme-corp"
    node_type "Organization"
    confidence 1.0
    source_files "team.md|projects.md|partners.md|technologies.md"
    aliases ""
    attr_name_value "Acme Corp"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value ""
    attr_industry_confidence 0.0
    attr_founding_year_value "2015"
    attr_founding_year_confidence 1.0
  ]
  node [
    id 1
    label "employee-alice-chen"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Alice Chen"
    attr_name_confidence 1.0
    attr_email_value "alice.chen@acme.com"
    attr_email_confidence 1.0
    attr_education_value "BSc in Computer Science from MIT"
    attr_education_confidence 1.0
    attr_join_date_value "March 2021"
    attr_join_date_confidence 1.0
    attr_title_value "Senior Software Engineer"
    attr_title_confidence 1.0
  ]
  node [
    id 2
    label "employee-bob-martinez"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Bob Martinez"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
    attr_join_date_value "2018"
    attr_join_date_confidence 1.0
    attr_title_value "Director of Engineering"
    attr_title_confidence 1.0
  ]
  node [
    id 3
    label "employee-carol-okafor"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Carol Okafor"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
    attr_join_date_value "January 2023"
    attr_join_date_confidence 1.0
    attr_title_value "Site Reliability Engineer"
    attr_title_confidence 1.0
  ]
  node [
    id 4
    label "employee-sandra-kim"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Sandra Kim"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
    attr_join_date_value ""
    attr_join_date_confidence 0.0
    attr_title_value "CEO"
    attr_title_confidence 1.0
  ]
  node [
    id 5
    label "employee-james-whitfield"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "James Whitfield"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value "PhD in Computer Science from Stanford"
    attr_education_confidence 1.0
    attr_join_date_value ""
    attr_join_date_confidence 0.0
    attr_title_value "CTO"
    attr_title_confidence 1.0
  ]
  node [
    id 6
    label "employee-dr-yuna-park"
    node_type "Employee"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Dr. Yuna Park"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
    attr_join_date_value ""
    attr_join_date_confidence 0.0
    attr_title_value "Principal Researcher"
    attr_title_confidence 1.0
  ]
  node [
    id 7
    label "team-infrastructure-team"
    node_type "Team"
    confidence 1.0
    source_files "team.md|projects.md|technologies.md"
    aliases "infrastructure team"
    attr_name_value "Infrastructure Team"
    attr_name_confidence 1.0
    attr_description_value "responsible for cloud operations, CI/CD pipelines, and on-call rotations"
    attr_description_confidence 1.0
    attr_member_count_value "5"
    attr_member_count_confidence 1.0
  ]
  node [
    id 8
    label "team-product-team"
    node_type "Team"
    confidence 0.9
    source_files "team.md"
    aliases ""
    attr_name_value "product team"
    attr_name_confidence 1.0
    attr_description_value ""
    attr_description_confidence 0.0
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 9
    label "team-platform-team"
    node_type "Team"
    confidence 1.0
    source_files "team.md|projects.md|partners.md"
    aliases "Platform team"
    attr_name_value "Platform Team"
    attr_name_confidence 1.0
    attr_description_value "team building platform services including secrets management"
    attr_description_confidence 0.85
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 10
    label "team-ai-research-team"
    node_type "Team"
    confidence 1.0
    source_files "team.md|projects.md|technologies.md"
    aliases "AI Research team"
    attr_name_value "AI Research Team"
    attr_name_confidence 1.0
    attr_description_value "current focus is on retrieval-augmented generation (RAG) and knowledge graph applications"
    attr_description_confidence 1.0
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 11
    label "organization-google"
    node_type "Organization"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "Google"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value ""
    attr_industry_confidence 0.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 12
    label "organization-datasystems-inc"
    node_type "Organization"
    confidence 1.0
    source_files "team.md|projects.md|partners.md|technologies.md"
    aliases ""
    attr_name_value "DataSystems Inc"
    attr_name_confidence 1.0
    attr_headquarters_location_value "San Francisco"
    attr_headquarters_location_confidence 1.0
    attr_industry_value "data infrastructure"
    attr_industry_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 13
    label "organization-novatech-inc"
    node_type "Organization"
    confidence 1.0
    source_files "team.md|partners.md"
    aliases ""
    attr_name_value "NovaTech Inc"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value "SaaS"
    attr_industry_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 14
    label "organization-deepmind"
    node_type "Organization"
    confidence 1.0
    source_files "team.md"
    aliases ""
    attr_name_value "DeepMind"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value ""
    attr_industry_confidence 0.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 15
    label "person-bob-martinez"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Bob Martinez"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 16
    label "person-alice-chen"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Alice Chen"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 17
    label "person-carol-okafor"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|partners.md"
    aliases ""
    attr_name_value "Carol Okafor"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 18
    label "person-james-whitfield"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "James Whitfield"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 19
    label "person-dr-yuna-park"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Dr. Yuna Park"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value "doctorate"
    attr_education_confidence 0.7
  ]
  node [
    id 20
    label "project-db-migration-project"
    node_type "Project"
    confidence 0.975
    source_files "projects.md|partners.md|partners.md|technologies.md"
    aliases "DB Migration|DB Migration project|data lake migration"
    attr_name_value "DB Migration Project"
    attr_name_confidence 1.0
    attr_status_value "in progress"
    attr_status_confidence 1.0
    attr_target_completion_date_value "end of Q3 2026"
    attr_target_completion_date_confidence 1.0
    attr_budget_value "$120,000"
    attr_budget_confidence 1.0
  ]
  node [
    id 21
    label "project-rag-pipeline-project"
    node_type "Project"
    confidence 1.0
    source_files "projects.md|partners.md|technologies.md"
    aliases "RAG Pipeline"
    attr_name_value "RAG Pipeline Project"
    attr_name_confidence 1.0
    attr_status_value "design phase"
    attr_status_confidence 1.0
    attr_target_completion_date_value "Q4 2026"
    attr_target_completion_date_confidence 1.0
    attr_budget_value ""
    attr_budget_confidence 0.0
  ]
  node [
    id 22
    label "project-platform-secrets-service"
    node_type "Project"
    confidence 1.0
    source_files "projects.md|partners.md|technologies.md"
    aliases "Secrets Service"
    attr_name_value "Platform Secrets Service"
    attr_name_confidence 1.0
    attr_status_value "in progress"
    attr_status_confidence 0.8
    attr_target_completion_date_value "August 2026"
    attr_target_completion_date_confidence 1.0
    attr_budget_value ""
    attr_budget_confidence 0.0
  ]
  node [
    id 23
    label "technology-postgresql"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "PostgreSQL"
    attr_name_confidence 1.0
    attr_type_value "database"
    attr_type_confidence 0.95
    attr_version_value "15"
    attr_version_confidence 1.0
  ]
  node [
    id 24
    label "technology-aws-aurora"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|partners.md|technologies.md"
    aliases ""
    attr_name_value "AWS Aurora"
    attr_name_confidence 1.0
    attr_type_value "cloud database"
    attr_type_confidence 0.95
    attr_version_value "PostgreSQL-compatible"
    attr_version_confidence 0.8
  ]
  node [
    id 25
    label "technology-pinecone"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Pinecone"
    attr_name_confidence 1.0
    attr_type_value "vector database"
    attr_type_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 26
    label "technology-hashicorp-vault"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "HashiCorp Vault"
    attr_name_confidence 1.0
    attr_type_value "secrets management"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 27
    label "person-dr-priya-nair"
    node_type "Person"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Dr. Priya Nair"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 28
    label "person-sandra-kim"
    node_type "Person"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Sandra Kim"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 29
    label "organization-hashicorp"
    node_type "Organization"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "HashiCorp"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value ""
    attr_industry_confidence 0.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 30
    label "product-vault"
    node_type "Product"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Vault"
    attr_name_confidence 1.0
    attr_type_value ""
    attr_type_confidence 0.0
    attr_version_value ""
    attr_version_confidence 0.0
    attr_description_value ""
    attr_description_confidence 0.0
  ]
  node [
    id 31
    label "agreement-vault-enterprise-licence"
    node_type "Agreement"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Vault enterprise licence"
    attr_name_confidence 1.0
    attr_type_value "enterprise licence"
    attr_type_confidence 1.0
    attr_start_date_value "Q1 2026"
    attr_start_date_confidence 0.9
  ]
  node [
    id 32
    label "person-marcus-tan"
    node_type "Person"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Marcus Tan"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 33
    label "organization-amazon-web-services"
    node_type "Organization"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Amazon Web Services"
    attr_name_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_industry_value "cloud provider"
    attr_industry_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
  ]
  node [
    id 34
    label "person-lisa-huang"
    node_type "Person"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Lisa Huang"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 35
    label "technology-weaviate"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Weaviate"
    attr_name_confidence 1.0
    attr_type_value "Vector Database"
    attr_type_confidence 0.9
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 36
    label "technology-qdrant"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Qdrant"
    attr_name_confidence 1.0
    attr_type_value "Vector Database"
    attr_type_confidence 0.9
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 37
    label "technology-aws"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "AWS"
    attr_name_confidence 1.0
    attr_type_value "Cloud Platform"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 38
    label "technology-github-actions"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "GitHub Actions"
    attr_name_confidence 1.0
    attr_type_value "CI/CD"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 39
    label "technology-kubernetes"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Kubernetes"
    attr_name_confidence 1.0
    attr_type_value "Container Orchestration"
    attr_type_confidence 0.95
    attr_version_value "EKS"
    attr_version_confidence 0.8
  ]
  node [
    id 40
    label "technology-python"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Python"
    attr_name_confidence 1.0
    attr_type_value "Programming Language"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 41
    label "technology-pytorch"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "PyTorch"
    attr_name_confidence 1.0
    attr_type_value "ML Framework"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 42
    label "technology-hugging-face-transformers"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Hugging Face Transformers"
    attr_name_confidence 1.0
    attr_type_value "ML Library"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 43
    label "technology-aws-sagemaker"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "AWS SageMaker"
    attr_name_confidence 1.0
    attr_type_value "ML Platform"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 44
    label "product-document-processing-pipeline"
    node_type "Product"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Document Processing Pipeline"
    attr_name_confidence 1.0
    attr_type_value "Data Processing"
    attr_type_confidence 0.85
    attr_version_value ""
    attr_version_confidence 0.0
    attr_description_value "Feeds the RAG pipeline ingestion layer"
    attr_description_confidence 0.8
  ]
  node [
    id 45
    label "team-backend-engineering-guild"
    node_type "Team"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Backend Engineering Guild"
    attr_name_confidence 1.0
    attr_description_value "Standardizes backend technologies at Acme Corp"
    attr_description_confidence 0.85
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 46
    label "technology-fastapi"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "FastAPI"
    attr_name_confidence 1.0
    attr_type_value "Web Framework"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 47
    label "technology-go"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Go"
    attr_name_confidence 1.0
    attr_type_value "Programming Language"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 48
    label "technology-react"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "React"
    attr_name_confidence 1.0
    attr_type_value "Frontend Framework"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 49
    label "technology-typescript"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "TypeScript"
    attr_name_confidence 1.0
    attr_type_value "Programming Language"
    attr_type_confidence 0.95
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  edge [
    source 0
    target 12
    label "edge-d7c9a1"
    edge_type "has_partnership"
    confidence 1.0
    source_files "projects.md|partners.md"
    attr_type_value "strategic partnership"
    attr_type_confidence 1.0
    attr_start_date_value "September 2025"
    attr_start_date_confidence 1.0
  ]
  edge [
    source 0
    target 13
    label "edge-b5eb28"
    edge_type "has_partnership"
    confidence 0.8
    source_files "partners.md"
    attr_type_value "informal advisory relationship"
    attr_type_confidence 0.8
    attr_start_date_value ""
    attr_start_date_confidence 0.0
  ]
  edge [
    source 0
    target 31
    label "edge-1b377e"
    edge_type "has_agreement"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 1
    target 0
    label "edge-88cb24"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
  ]
  edge [
    source 2
    target 0
    label "edge-2d3f24"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
  ]
  edge [
    source 2
    target 7
    label "edge-c64595"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 2
    target 8
    label "edge-d91709"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 2
    target 4
    label "edge-dd4d62"
    edge_type "reports_to"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 3
    target 0
    label "edge-91d97c"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
  ]
  edge [
    source 3
    target 7
    label "edge-e59ad9"
    edge_type "member_of"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 4
    target 0
    label "edge-f6784c"
    edge_type "co_founded"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
    attr_year_value ""
    attr_year_confidence 0.0
  ]
  edge [
    source 5
    target 0
    label "edge-2f8749"
    edge_type "co_founded"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
    attr_year_value ""
    attr_year_confidence 0.0
  ]
  edge [
    source 5
    target 9
    label "edge-0d344b"
    edge_type "manages"
    confidence 0.9
    source_files "team.md"
  ]
  edge [
    source 5
    target 10
    label "edge-cd3575"
    edge_type "manages"
    confidence 0.9
    source_files "team.md"
  ]
  edge [
    source 6
    target 0
    label "edge-7f50a8"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
  ]
  edge [
    source 6
    target 10
    label "edge-abfe59"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 7
    target 20
    label "edge-6fa176"
    edge_type "owns"
    confidence 1.0
    source_files "projects.md"
  ]
  edge [
    source 9
    target 22
    label "edge-32a3bc"
    edge_type "owns"
    confidence 0.95
    source_files "projects.md|partners.md"
  ]
  edge [
    source 12
    target 44
    label "edge-651787"
    edge_type "provides"
    confidence 1.0
    source_files "technologies.md"
  ]
  edge [
    source 12
    target 0
    label "edge-c9ccdc"
    edge_type "vendor_for"
    confidence 0.85
    source_files "technologies.md"
  ]
  edge [
    source 15
    target 0
    label "edge-ece6c4"
    edge_type "works_at"
    confidence 0.9666666666666667
    source_files "team.md|projects.md|technologies.md"
    attr_start_date_value "2018"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "Director of Engineering"
    attr_role_confidence 1.0
  ]
  edge [
    source 15
    target 7
    label "edge-8c3e84"
    edge_type "manages"
    confidence 1.0
    source_files "team.md|technologies.md"
  ]
  edge [
    source 15
    target 8
    label "edge-cff8ed"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 15
    target 28
    label "edge-9dc267"
    edge_type "reports_to"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 15
    target 11
    label "edge-083f4a"
    edge_type "works_at"
    confidence 0.9
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value "2018"
    attr_end_date_confidence 0.8
    attr_role_value "Staff Engineer"
    attr_role_confidence 1.0
  ]
  edge [
    source 15
    target 20
    label "edge-b6585c"
    edge_type "leads"
    confidence 0.9
    source_files "projects.md"
    attr_role_value "initiator"
    attr_role_confidence 0.85
  ]
  edge [
    source 16
    target 0
    label "edge-0adce0"
    edge_type "works_at"
    confidence 0.9666666666666667
    source_files "team.md|projects.md|technologies.md"
    attr_start_date_value "March 2021"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "Senior Software Engineer"
    attr_role_confidence 1.0
  ]
  edge [
    source 16
    target 20
    label "edge-f77976"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "core engineering contributor"
    attr_role_confidence 1.0
  ]
  edge [
    source 16
    target 21
    label "edge-9ca93e"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "backend API work"
    attr_role_confidence 1.0
  ]
  edge [
    source 16
    target 45
    label "edge-770457"
    edge_type "manages"
    confidence 1.0
    source_files "technologies.md"
  ]
  edge [
    source 17
    target 0
    label "edge-079047"
    edge_type "works_at"
    confidence 0.9833333333333334
    source_files "team.md|projects.md|partners.md"
    attr_start_date_value "January 2023"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "Site Reliability Engineer"
    attr_role_confidence 1.0
  ]
  edge [
    source 17
    target 7
    label "edge-5f6aa7"
    edge_type "member_of"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 17
    target 12
    label "edge-f1b25e"
    edge_type "works_at"
    confidence 0.95
    source_files "team.md|partners.md"
    attr_start_date_value "2019"
    attr_start_date_confidence 1.0
    attr_end_date_value "2022"
    attr_end_date_confidence 1.0
    attr_role_value "DevOps Engineer"
    attr_role_confidence 1.0
  ]
  edge [
    source 17
    target 20
    label "edge-1bb309"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "core engineering contributor"
    attr_role_confidence 1.0
  ]
  edge [
    source 17
    target 27
    label "edge-f92d5f"
    edge_type "reports_to"
    confidence 0.9
    source_files "partners.md"
  ]
  edge [
    source 18
    target 0
    label "edge-550da7"
    edge_type "co_founded"
    confidence 1.0
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "CTO"
    attr_role_confidence 1.0
    attr_year_value "2015"
    attr_year_confidence 1.0
  ]
  edge [
    source 18
    target 22
    label "edge-5d8c88"
    edge_type "leads"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_role_value "project owner"
    attr_role_confidence 1.0
  ]
  edge [
    source 18
    target 9
    label "edge-73ec0d"
    edge_type "manages"
    confidence 0.85
    source_files "projects.md"
  ]
  edge [
    source 19
    target 0
    label "edge-f8fd44"
    edge_type "works_at"
    confidence 0.9666666666666667
    source_files "team.md|projects.md|technologies.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "Principal Researcher"
    attr_role_confidence 1.0
  ]
  edge [
    source 19
    target 14
    label "edge-283b79"
    edge_type "works_at"
    confidence 0.9
    source_files "team.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value ""
    attr_role_confidence 0.0
  ]
  edge [
    source 19
    target 21
    label "edge-2433f1"
    edge_type "contributes_to"
    confidence 0.85
    source_files "technologies.md"
    attr_role_value "Technology evaluator"
    attr_role_confidence 0.8
  ]
  edge [
    source 19
    target 10
    label "edge-439f54"
    edge_type "manages"
    confidence 1.0
    source_files "technologies.md"
  ]
  edge [
    source 20
    target 22
    label "edge-629b4f"
    edge_type "depends_on"
    confidence 1.0
    source_files "projects.md"
  ]
  edge [
    source 20
    target 23
    label "edge-f50b01"
    edge_type "uses_technology"
    confidence 0.95
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 20
    target 24
    label "edge-554618"
    edge_type "uses_technology"
    confidence 0.9833333333333334
    source_files "projects.md|partners.md|technologies.md"
  ]
  edge [
    source 20
    target 37
    label "edge-e1f59d"
    edge_type "uses_technology"
    confidence 0.85
    source_files "technologies.md"
  ]
  edge [
    source 20
    target 39
    label "edge-97d81a"
    edge_type "uses_technology"
    confidence 0.65
    source_files "technologies.md"
  ]
  edge [
    source 21
    target 25
    label "edge-025633"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 21
    target 40
    label "edge-ae6127"
    edge_type "uses_technology"
    confidence 0.9
    source_files "technologies.md"
  ]
  edge [
    source 21
    target 41
    label "edge-576c0d"
    edge_type "uses_technology"
    confidence 0.75
    source_files "technologies.md"
  ]
  edge [
    source 21
    target 42
    label "edge-a61fe5"
    edge_type "uses_technology"
    confidence 0.75
    source_files "technologies.md"
  ]
  edge [
    source 21
    target 43
    label "edge-b7af5c"
    edge_type "uses_technology"
    confidence 0.7
    source_files "technologies.md"
  ]
  edge [
    source 21
    target 37
    label "edge-51d314"
    edge_type "uses_technology"
    confidence 0.75
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 26
    label "edge-bedee6"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 22
    target 30
    label "edge-e2f3fb"
    edge_type "uses_technology"
    confidence 0.9
    source_files "partners.md"
  ]
  edge [
    source 22
    target 39
    label "edge-37e61e"
    edge_type "uses_technology"
    confidence 0.7
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 35
    label "edge-bde869"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 36
    label "edge-31e6a2"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 46
    label "edge-522413"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 38
    label "edge-b6c74c"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 47
    label "edge-62bba2"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 48
    label "edge-60a3ee"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 22
    target 49
    label "edge-33b559"
    edge_type "uses_technology"
    confidence 0.0
    source_files "technologies.md"
  ]
  edge [
    source 27
    target 12
    label "edge-8adddb"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "VP of Engineering"
    attr_role_confidence 1.0
  ]
  edge [
    source 28
    target 0
    label "edge-178bbc"
    edge_type "co_founded"
    confidence 1.0
    source_files "team.md|partners.md"
    attr_start_date_value "2015"
    attr_start_date_confidence 0.9
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "CEO"
    attr_role_confidence 1.0
    attr_year_value "2015"
    attr_year_confidence 1.0
  ]
  edge [
    source 28
    target 13
    label "edge-f5f9c8"
    edge_type "works_at"
    confidence 0.95
    source_files "team.md|partners.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value "2015"
    attr_end_date_confidence 0.8
    attr_role_value "VP Engineering"
    attr_role_confidence 1.0
  ]
  edge [
    source 29
    target 30
    label "edge-eace28"
    edge_type "provides"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 29
    target 0
    label "edge-30eedf"
    edge_type "vendor_for"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 32
    target 29
    label "edge-c27b40"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "enterprise account manager"
    attr_role_confidence 1.0
  ]
  edge [
    source 32
    target 0
    label "edge-c6dadc"
    edge_type "account_manager_for"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 33
    target 0
    label "edge-1e5aed"
    edge_type "vendor_for"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 34
    target 33
    label "edge-13584e"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
    attr_role_value "account manager"
    attr_role_confidence 1.0
  ]
  edge [
    source 34
    target 0
    label "edge-1b099b"
    edge_type "account_manager_for"
    confidence 1.0
    source_files "partners.md"
  ]
]
