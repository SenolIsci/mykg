graph [
  directed 1
  name "mykg knowledge graph"
  node [
    id 0
    label "organization-acme-corp"
    node_type "Organization"
    confidence 1.0
    source_files "team.md|projects.md|technologies.md"
    aliases ""
    attr_name_value "Acme Corp"
    attr_name_confidence 1.0
    attr_description_value "Organization undertaking database migration, RAG pipeline, and platform secrets service projects"
    attr_description_confidence 0.9
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Company"
    attr_type_confidence 0.9
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
    attr_title_value "Senior Software Engineer"
    attr_title_confidence 1.0
    attr_join_date_value "March 2021"
    attr_join_date_confidence 1.0
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
    attr_title_value "Director of Engineering"
    attr_title_confidence 1.0
    attr_join_date_value "2018"
    attr_join_date_confidence 1.0
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
    attr_title_value "Site Reliability Engineer"
    attr_title_confidence 1.0
    attr_join_date_value "January 2023"
    attr_join_date_confidence 1.0
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
    attr_title_value "CEO"
    attr_title_confidence 1.0
    attr_join_date_value "2015"
    attr_join_date_confidence 0.9
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
    attr_title_value "CTO"
    attr_title_confidence 1.0
    attr_join_date_value "2015"
    attr_join_date_confidence 0.9
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
    attr_title_value "Principal Researcher"
    attr_title_confidence 1.0
    attr_join_date_value ""
    attr_join_date_confidence 0.0
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
    attr_description_value "Responsible for cloud operations, CI/CD pipelines, and on-call rotations"
    attr_description_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Engineering Team"
    attr_type_confidence 0.9
    attr_focus_area_value "cloud operations, CI/CD pipelines, and on-call rotations; Infrastructure; Infrastructure and DevOps"
    attr_focus_area_confidence 1.0
    attr_member_count_value 5
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
    attr_name_confidence 0.9
    attr_description_value "Product development team managed by Bob Martinez"
    attr_description_confidence 0.8
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Product Team"
    attr_type_confidence 0.85
    attr_focus_area_value ""
    attr_focus_area_confidence 0.0
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 9
    label "team-platform-team"
    node_type "Team"
    confidence 1.0
    source_files "team.md|partners.md|projects.md"
    aliases "Platform team"
    attr_name_value "Platform Team"
    attr_name_confidence 1.0
    attr_description_value "Team building centralised secrets management service"
    attr_description_confidence 0.95
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Engineering Team"
    attr_type_confidence 0.85
    attr_focus_area_value "Platform Infrastructure"
    attr_focus_area_confidence 0.9
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
    attr_description_value "Research team focused on retrieval-augmented generation (RAG) and knowledge graph applications"
    attr_description_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Research Team"
    attr_type_confidence 0.95
    attr_focus_area_value "retrieval-augmented generation (RAG) and knowledge graph applications; AI Research; AI and ML"
    attr_focus_area_confidence 1.0
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 11
    label "team-backend-engineering-guild"
    node_type "Team"
    confidence 0.925
    source_files "team.md|technologies.md"
    aliases "backend guild"
    attr_name_value "Backend Engineering Guild"
    attr_name_confidence 1.0
    attr_description_value "Team standardising on Python (FastAPI) for services and Go for performance-critical components"
    attr_description_confidence 0.95
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Engineering Guild"
    attr_type_confidence 0.95
    attr_focus_area_value "Backend Engineering"
    attr_focus_area_confidence 1.0
    attr_member_count_value ""
    attr_member_count_confidence 0.0
  ]
  node [
    id 12
    label "organization-google"
    node_type "Organization"
    confidence 0.9
    source_files "team.md"
    aliases ""
    attr_name_value "Google"
    attr_name_confidence 0.9
    attr_description_value "Former employer of Bob Martinez"
    attr_description_confidence 0.7
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Technology Company"
    attr_type_confidence 0.8
  ]
  node [
    id 13
    label "organization-datasystems-inc"
    node_type "Organization"
    confidence 0.9
    source_files "team.md"
    aliases ""
    attr_name_value "DataSystems Inc"
    attr_name_confidence 0.9
    attr_description_value "Former employer of Carol Okafor"
    attr_description_confidence 0.7
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Technology Company"
    attr_type_confidence 0.75
  ]
  node [
    id 14
    label "organization-novatech-inc"
    node_type "Organization"
    confidence 0.9
    source_files "team.md"
    aliases ""
    attr_name_value "NovaTech Inc"
    attr_name_confidence 0.9
    attr_description_value "Former employer of Sandra Kim"
    attr_description_confidence 0.7
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Technology Company"
    attr_type_confidence 0.75
  ]
  node [
    id 15
    label "organization-deepmind"
    node_type "Organization"
    confidence 0.9
    source_files "team.md"
    aliases ""
    attr_name_value "DeepMind"
    attr_name_confidence 0.9
    attr_description_value "Former employer of Dr. Yuna Park"
    attr_description_confidence 0.7
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "AI Research Organization"
    attr_type_confidence 0.85
  ]
  node [
    id 16
    label "company-datasystems-inc"
    node_type "Company"
    confidence 1.0
    source_files "partners.md|projects.md|technologies.md"
    aliases ""
    attr_name_value "DataSystems Inc"
    attr_name_confidence 1.0
    attr_description_value "data infrastructure company"
    attr_description_confidence 1.0
    attr_headquarters_location_value "San Francisco"
    attr_headquarters_location_confidence 1.0
    attr_type_value "data infrastructure company"
    attr_type_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
    attr_annual_revenue_value ""
    attr_annual_revenue_confidence 0.0
  ]
  node [
    id 17
    label "company-acme-corp"
    node_type "Company"
    confidence 1.0
    source_files "partners.md|technologies.md"
    aliases ""
    attr_name_value "Acme Corp"
    attr_name_confidence 1.0
    attr_description_value "Company running technology infrastructure and AI/ML projects"
    attr_description_confidence 0.9
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "Technology Company"
    attr_type_confidence 0.8
    attr_founding_year_value "2015"
    attr_founding_year_confidence 1.0
    attr_annual_revenue_value ""
    attr_annual_revenue_confidence 0.0
  ]
  node [
    id 18
    label "partnership-acme-corp-datasystems-inc-strategic-partnership"
    node_type "Partnership"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Acme Corp - DataSystems Inc Strategic Partnership"
    attr_name_confidence 0.9
    attr_type_value "strategic partnership"
    attr_type_confidence 1.0
    attr_start_date_value "September 2025"
    attr_start_date_confidence 1.0
    attr_scope_value "co-develop document indexing and search infrastructure"
    attr_scope_confidence 1.0
  ]
  node [
    id 19
    label "person-carol-okafor"
    node_type "Person"
    confidence 1.0
    source_files "partners.md|projects.md"
    aliases ""
    attr_name_value "Carol Okafor"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value ""
    attr_education_confidence 0.0
  ]
  node [
    id 20
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
    id 21
    label "project-rag-pipeline"
    node_type "Project"
    confidence 1.0
    source_files "partners.md|projects.md|technologies.md"
    aliases "RAG Pipeline Project"
    attr_name_value "RAG Pipeline"
    attr_name_confidence 1.0
    attr_description_value "document indexing; Internal RAG (Retrieval-Augmented Generation) pipeline to allow employees to query company's internal documentation using natural language"
    attr_description_confidence 1.0
    attr_status_value "active; design phase"
    attr_status_confidence 1.0
    attr_budget_value ""
    attr_budget_confidence 0.0
  ]
  node [
    id 22
    label "project-db-migration"
    node_type "Project"
    confidence 0.975
    source_files "partners.md|partners.md|projects.md|technologies.md"
    aliases "DB Migration Project|DB Migration project|data lake migration"
    attr_name_value "DB Migration"
    attr_name_confidence 1.0
    attr_description_value "targets AWS Aurora; Database migration project to move Acme Corp's production PostgreSQL clusters from on-premise hardware to AWS Aurora; Moving PostgreSQL clusters to AWS Aurora"
    attr_description_confidence 1.0
    attr_status_value "planned; in progress"
    attr_status_confidence 1.0
    attr_budget_value "$120,000"
    attr_budget_confidence 1.0
  ]
  node [
    id 23
    label "company-novatech-inc"
    node_type "Company"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "NovaTech Inc"
    attr_name_confidence 1.0
    attr_description_value "SaaS company focused on developer tooling"
    attr_description_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "SaaS company"
    attr_type_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
    attr_annual_revenue_value ""
    attr_annual_revenue_confidence 0.0
  ]
  node [
    id 24
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
    id 25
    label "company-hashicorp"
    node_type "Company"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "HashiCorp"
    attr_name_confidence 1.0
    attr_description_value ""
    attr_description_confidence 0.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value ""
    attr_type_confidence 0.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
    attr_annual_revenue_value ""
    attr_annual_revenue_confidence 0.0
  ]
  node [
    id 26
    label "product-vault"
    node_type "Product"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Vault"
    attr_name_confidence 1.0
    attr_category_value ""
    attr_category_confidence 0.0
    attr_version_value ""
    attr_version_confidence 0.0
    attr_vendor_value "HashiCorp"
    attr_vendor_confidence 1.0
  ]
  node [
    id 27
    label "project-platform-secrets-service"
    node_type "Project"
    confidence 1.0
    source_files "partners.md|projects.md|technologies.md"
    aliases "Secrets Service project"
    attr_name_value "Platform Secrets Service"
    attr_name_confidence 1.0
    attr_description_value "Centralised secrets management service to replace ad-hoc use of environment variables; Adopting HashiCorp Vault for secrets management"
    attr_description_confidence 1.0
    attr_status_value "in progress"
    attr_status_confidence 0.8
    attr_budget_value ""
    attr_budget_confidence 0.0
  ]
  node [
    id 28
    label "contract-vault-enterprise-licence"
    node_type "Contract"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Vault enterprise licence"
    attr_name_confidence 1.0
    attr_type_value "enterprise licence"
    attr_type_confidence 1.0
    attr_signed_date_value "Q1 2026"
    attr_signed_date_confidence 1.0
    attr_value_value ""
    attr_value_confidence 0.0
  ]
  node [
    id 29
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
    id 30
    label "company-amazon-web-services"
    node_type "Company"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "Amazon Web Services"
    attr_name_confidence 1.0
    attr_description_value "cloud provider"
    attr_description_confidence 1.0
    attr_headquarters_location_value ""
    attr_headquarters_location_confidence 0.0
    attr_type_value "cloud provider"
    attr_type_confidence 1.0
    attr_founding_year_value ""
    attr_founding_year_confidence 0.0
    attr_annual_revenue_value ""
    attr_annual_revenue_confidence 0.0
  ]
  node [
    id 31
    label "product-aws-aurora"
    node_type "Product"
    confidence 1.0
    source_files "partners.md"
    aliases ""
    attr_name_value "AWS Aurora"
    attr_name_confidence 1.0
    attr_category_value ""
    attr_category_confidence 0.0
    attr_version_value ""
    attr_version_confidence 0.0
    attr_vendor_value "Amazon Web Services"
    attr_vendor_confidence 1.0
  ]
  node [
    id 32
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
    id 33
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
    id 34
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
    id 35
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
    id 36
    label "person-dr-yuna-park"
    node_type "Person"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Dr. Yuna Park"
    attr_name_confidence 1.0
    attr_email_value ""
    attr_email_confidence 0.0
    attr_education_value "Doctorate"
    attr_education_confidence 0.9
  ]
  node [
    id 37
    label "technology-postgresql"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "PostgreSQL"
    attr_name_confidence 1.0
    attr_category_value "Database"
    attr_category_confidence 1.0
    attr_version_value "15"
    attr_version_confidence 1.0
  ]
  node [
    id 38
    label "technology-aws-aurora"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "AWS Aurora"
    attr_name_confidence 1.0
    attr_category_value "Database"
    attr_category_confidence 1.0
    attr_version_value "PostgreSQL-compatible"
    attr_version_confidence 0.9
  ]
  node [
    id 39
    label "technology-pinecone"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "Pinecone"
    attr_name_confidence 1.0
    attr_category_value "Vector Database"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 40
    label "technology-hashicorp-vault"
    node_type "Technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    aliases ""
    attr_name_value "HashiCorp Vault"
    attr_name_confidence 1.0
    attr_category_value "Secrets Management"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 41
    label "partnership-datasystems-inc-rag-pipeline-partnership"
    node_type "Partnership"
    confidence 0.95
    source_files "projects.md"
    aliases ""
    attr_name_value "DataSystems Inc - RAG Pipeline Partnership"
    attr_name_confidence 0.9
    attr_type_value "Infrastructure Partnership"
    attr_type_confidence 0.8
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_scope_value "Document indexing infrastructure for RAG pipeline project"
    attr_scope_confidence 0.95
  ]
  node [
    id 42
    label "technology-weaviate"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Weaviate"
    attr_name_confidence 1.0
    attr_category_value "Vector Database"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 43
    label "technology-qdrant"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Qdrant"
    attr_name_confidence 1.0
    attr_category_value "Vector Database"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 44
    label "technology-aws"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "AWS"
    attr_name_confidence 1.0
    attr_category_value "Cloud Infrastructure"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 45
    label "technology-github-actions"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "GitHub Actions"
    attr_name_confidence 1.0
    attr_category_value "CI/CD"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 46
    label "technology-kubernetes"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Kubernetes"
    attr_name_confidence 1.0
    attr_category_value "Container Orchestration"
    attr_category_confidence 1.0
    attr_version_value "EKS"
    attr_version_confidence 0.9
  ]
  node [
    id 47
    label "technology-python"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Python"
    attr_name_confidence 1.0
    attr_category_value "Programming Language"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 48
    label "technology-pytorch"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "PyTorch"
    attr_name_confidence 1.0
    attr_category_value "ML Framework"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 49
    label "technology-hugging-face-transformers"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Hugging Face Transformers"
    attr_name_confidence 1.0
    attr_category_value "ML Library"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 50
    label "technology-aws-sagemaker"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "AWS SageMaker"
    attr_name_confidence 1.0
    attr_category_value "ML Platform"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 51
    label "product-document-processing-pipeline"
    node_type "Product"
    confidence 0.95
    source_files "technologies.md"
    aliases ""
    attr_name_value "Document Processing Pipeline"
    attr_name_confidence 0.95
    attr_category_value "Data Processing"
    attr_category_confidence 0.9
    attr_version_value ""
    attr_version_confidence 0.0
    attr_vendor_value "DataSystems Inc"
    attr_vendor_confidence 1.0
  ]
  node [
    id 52
    label "technology-fastapi"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "FastAPI"
    attr_name_confidence 1.0
    attr_category_value "Web Framework"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 53
    label "technology-go"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "Go"
    attr_name_confidence 1.0
    attr_category_value "Programming Language"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 54
    label "technology-react"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "React"
    attr_name_confidence 1.0
    attr_category_value "Frontend Framework"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  node [
    id 55
    label "technology-typescript"
    node_type "Technology"
    confidence 1.0
    source_files "technologies.md"
    aliases ""
    attr_name_value "TypeScript"
    attr_name_confidence 1.0
    attr_category_value "Programming Language"
    attr_category_confidence 1.0
    attr_version_value ""
    attr_version_confidence 0.0
  ]
  edge [
    source 0
    target 22
    label "edge-a0b90d"
    edge_type "owns"
    confidence 0.95
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 0
    target 21
    label "edge-7eb87c"
    edge_type "owns"
    confidence 0.95
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 0
    target 27
    label "edge-291e7d"
    edge_type "owns"
    confidence 0.95
    source_files "projects.md|technologies.md"
  ]
  edge [
    source 1
    target 0
    label "edge-88cb24"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 2
    target 0
    label "edge-2d3f24"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
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
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
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
    label "edge-49e18d"
    edge_type "leads"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 5
    target 0
    label "edge-c763a6"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 5
    target 9
    label "edge-0d344b"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 5
    target 10
    label "edge-cd3575"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 6
    target 0
    label "edge-7f50a8"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
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
    target 22
    label "edge-684e6a"
    edge_type "owns"
    confidence 1.0
    source_files "projects.md"
  ]
  edge [
    source 7
    target 44
    label "edge-a5fa0b"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Cloud infrastructure hosting"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 7
    target 45
    label "edge-250ef2"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "CI/CD pipeline"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 7
    target 46
    label "edge-a2c9f9"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Container orchestration"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 9
    target 26
    label "edge-4974af"
    edge_type "uses_technology"
    confidence 0.9
    source_files "partners.md"
    attr_purpose_value "Secrets Service project"
    attr_purpose_confidence 0.9
  ]
  edge [
    source 9
    target 27
    label "edge-32a3bc"
    edge_type "owns"
    confidence 1.0
    source_files "projects.md"
  ]
  edge [
    source 10
    target 47
    label "edge-7909c4"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Primary programming language for AI/ML research"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 10
    target 48
    label "edge-272682"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Machine learning framework"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 10
    target 49
    label "edge-0e75a3"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Transformer models and NLP"
    attr_purpose_confidence 0.95
  ]
  edge [
    source 10
    target 50
    label "edge-736b5e"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Running ML experiments"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 10
    target 43
    label "edge-2a9123"
    edge_type "uses_technology"
    confidence 0.75
    source_files "technologies.md"
    attr_purpose_value ""
    attr_purpose_confidence 0.0
  ]
  edge [
    source 10
    target 42
    label "edge-a9660b"
    edge_type "uses_technology"
    confidence 0.75
    source_files "technologies.md"
    attr_purpose_value ""
    attr_purpose_confidence 0.0
  ]
  edge [
    source 11
    target 47
    label "edge-5656a9"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Standard language for backend services"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 11
    target 52
    label "edge-79570f"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Framework for backend services"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 11
    target 53
    label "edge-8d0efc"
    edge_type "uses_technology"
    confidence 1.0
    source_files "technologies.md"
    attr_purpose_value "Performance-critical components"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 11
    target 54
    label "edge-0653e1"
    edge_type "uses_technology"
    confidence 0.9
    source_files "technologies.md"
    attr_purpose_value "Frontend framework"
    attr_purpose_confidence 0.9
  ]
  edge [
    source 11
    target 55
    label "edge-711bfe"
    edge_type "uses_technology"
    confidence 0.9
    source_files "technologies.md"
    attr_purpose_value "Frontend type system with React"
    attr_purpose_confidence 0.9
  ]
  edge [
    source 16
    target 51
    label "edge-591a21"
    edge_type "provides"
    confidence 1.0
    source_files "technologies.md"
  ]
  edge [
    source 17
    target 28
    label "edge-5cec91"
    edge_type "holds_contract"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 18
    target 17
    label "edge-34513c"
    edge_type "involves_organization"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "partner"
    attr_role_confidence 0.9
  ]
  edge [
    source 18
    target 16
    label "edge-9ff0cb"
    edge_type "involves_organization"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "partner"
    attr_role_confidence 0.9
  ]
  edge [
    source 18
    target 21
    label "edge-62ae21"
    edge_type "covers_project"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 18
    target 22
    label "edge-875834"
    edge_type "covers_project"
    confidence 0.9
    source_files "partners.md"
  ]
  edge [
    source 19
    target 0
    label "edge-079047"
    edge_type "works_at"
    confidence 1.0
    source_files "team.md"
    attr_role_value "Site Reliability Engineer"
    attr_role_confidence 1.0
    attr_start_date_value "January 2023"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 19
    target 7
    label "edge-5f6aa7"
    edge_type "member_of"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 19
    target 16
    label "edge-460858"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "DevOps Engineer"
    attr_role_confidence 1.0
    attr_start_date_value "2019"
    attr_start_date_confidence 1.0
    attr_end_date_value "2022"
    attr_end_date_confidence 1.0
  ]
  edge [
    source 19
    target 17
    label "edge-7fd27f"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value ""
    attr_role_confidence 0.0
    attr_start_date_value "2022"
    attr_start_date_confidence 0.8
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 19
    target 20
    label "edge-f92d5f"
    edge_type "reports_to"
    confidence 0.9
    source_files "partners.md"
  ]
  edge [
    source 19
    target 22
    label "edge-0e1aa2"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "Core Engineering Contributor"
    attr_role_confidence 1.0
    attr_contribution_type_value "Engineering"
    attr_contribution_type_confidence 1.0
  ]
  edge [
    source 20
    target 16
    label "edge-d9b19e"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "VP of Engineering"
    attr_role_confidence 1.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 21
    target 39
    label "edge-7c71e8"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_purpose_value "Vector database for retrieval-augmented generation; Vector database for embedding storage and similarity search"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 21
    target 47
    label "edge-459436"
    edge_type "uses_technology"
    confidence 0.95
    source_files "technologies.md"
    attr_purpose_value "Custom ingestion layer implementation"
    attr_purpose_confidence 0.95
  ]
  edge [
    source 21
    target 43
    label "edge-cfc8e2"
    edge_type "uses_technology"
    confidence 0.85
    source_files "technologies.md"
    attr_purpose_value ""
    attr_purpose_confidence 0.0
  ]
  edge [
    source 21
    target 42
    label "edge-10f2f3"
    edge_type "uses_technology"
    confidence 0.85
    source_files "technologies.md"
    attr_purpose_value ""
    attr_purpose_confidence 0.0
  ]
  edge [
    source 22
    target 27
    label "edge-ee4394"
    edge_type "depends_on"
    confidence 1.0
    source_files "projects.md"
  ]
  edge [
    source 22
    target 37
    label "edge-4a21fb"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_purpose_value "Source database system being migrated from"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 22
    target 38
    label "edge-4334dd"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_purpose_value "Target database system for migration"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 24
    target 0
    label "edge-d1a1b4"
    edge_type "leads"
    confidence 1.0
    source_files "team.md"
    attr_role_value "CEO"
    attr_role_confidence 1.0
    attr_start_date_value "2015"
    attr_start_date_confidence 0.9
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 24
    target 23
    label "edge-625cd5"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "VP Engineering"
    attr_role_confidence 1.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value "2015"
    attr_end_date_confidence 0.9
  ]
  edge [
    source 24
    target 17
    label "edge-a2d368"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "CEO"
    attr_role_confidence 1.0
    attr_start_date_value "2015"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 25
    target 26
    label "edge-bfb1eb"
    edge_type "provides"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 25
    target 29
    label "edge-ff6ca5"
    edge_type "has_contact"
    confidence 1.0
    source_files "partners.md"
    attr_contact_type_value "enterprise account manager"
    attr_contact_type_confidence 1.0
  ]
  edge [
    source 27
    target 40
    label "edge-bedee6"
    edge_type "uses_technology"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_purpose_value "Backend for secrets management service; Secrets management"
    attr_purpose_confidence 1.0
  ]
  edge [
    source 29
    target 25
    label "edge-abcc9e"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "enterprise account manager"
    attr_role_confidence 1.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 30
    target 31
    label "edge-e6a525"
    edge_type "provides"
    confidence 1.0
    source_files "partners.md"
  ]
  edge [
    source 30
    target 32
    label "edge-e272b2"
    edge_type "has_contact"
    confidence 1.0
    source_files "partners.md"
    attr_contact_type_value "account manager"
    attr_contact_type_confidence 1.0
  ]
  edge [
    source 32
    target 30
    label "edge-42d45c"
    edge_type "works_at"
    confidence 1.0
    source_files "partners.md"
    attr_role_value "account manager"
    attr_role_confidence 1.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 33
    target 0
    label "edge-ece6c4"
    edge_type "works_at"
    confidence 0.975
    source_files "team.md|technologies.md"
    attr_role_value "Director of Engineering"
    attr_role_confidence 1.0
    attr_start_date_value "2018"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 33
    target 7
    label "edge-8c3e84"
    edge_type "manages"
    confidence 1.0
    source_files "team.md|technologies.md"
  ]
  edge [
    source 33
    target 8
    label "edge-cff8ed"
    edge_type "manages"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 33
    target 24
    label "edge-9dc267"
    edge_type "reports_to"
    confidence 1.0
    source_files "team.md"
  ]
  edge [
    source 33
    target 22
    label "edge-825578"
    edge_type "contributes_to"
    confidence 0.95
    source_files "projects.md"
    attr_role_value "Initiator"
    attr_role_confidence 0.9
    attr_contribution_type_value "Project Initiation"
    attr_contribution_type_confidence 0.9
  ]
  edge [
    source 34
    target 0
    label "edge-0adce0"
    edge_type "works_at"
    confidence 0.975
    source_files "team.md|technologies.md"
    attr_role_value "Senior Software Engineer"
    attr_role_confidence 1.0
    attr_start_date_value "March 2021"
    attr_start_date_confidence 1.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 34
    target 11
    label "edge-df9a75"
    edge_type "leads"
    confidence 0.975
    source_files "team.md|technologies.md"
  ]
  edge [
    source 34
    target 22
    label "edge-8dbe79"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "Core Engineering Contributor"
    attr_role_confidence 1.0
    attr_contribution_type_value "Engineering"
    attr_contribution_type_confidence 1.0
  ]
  edge [
    source 34
    target 21
    label "edge-ea8712"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "Backend API Developer"
    attr_role_confidence 0.95
    attr_contribution_type_value "Backend Engineering"
    attr_contribution_type_confidence 1.0
  ]
  edge [
    source 35
    target 0
    label "edge-94a3a9"
    edge_type "works_at"
    confidence 0.975
    source_files "team.md|technologies.md"
    attr_role_value "CTO"
    attr_role_confidence 1.0
    attr_start_date_value "2015"
    attr_start_date_confidence 0.9
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 35
    target 9
    label "edge-5809d3"
    edge_type "leads"
    confidence 0.9
    source_files "projects.md"
  ]
  edge [
    source 35
    target 10
    label "edge-8f0036"
    edge_type "manages"
    confidence 0.95
    source_files "team.md"
  ]
  edge [
    source 35
    target 27
    label "edge-e68f52"
    edge_type "contributes_to"
    confidence 1.0
    source_files "projects.md|technologies.md"
    attr_role_value "Project Owner; Project lead"
    attr_role_confidence 1.0
    attr_contribution_type_value "Ownership; Leadership"
    attr_contribution_type_confidence 1.0
  ]
  edge [
    source 36
    target 0
    label "edge-f8fd44"
    edge_type "works_at"
    confidence 0.975
    source_files "team.md|technologies.md"
    attr_role_value "Principal Researcher"
    attr_role_confidence 1.0
    attr_start_date_value ""
    attr_start_date_confidence 0.0
    attr_end_date_value ""
    attr_end_date_confidence 0.0
  ]
  edge [
    source 36
    target 10
    label "edge-f4ef1d"
    edge_type "member_of"
    confidence 1.0
    source_files "team.md|projects.md"
  ]
  edge [
    source 36
    target 21
    label "edge-73bcce"
    edge_type "contributes_to"
    confidence 0.975
    source_files "projects.md|technologies.md"
    attr_role_value "Project Lead"
    attr_role_confidence 1.0
    attr_contribution_type_value "Leadership"
    attr_contribution_type_confidence 1.0
  ]
  edge [
    source 41
    target 16
    label "edge-6a0480"
    edge_type "involves_organization"
    confidence 1.0
    source_files "projects.md"
    attr_role_value "Document Indexing Infrastructure Provider"
    attr_role_confidence 0.95
  ]
  edge [
    source 41
    target 21
    label "edge-e0dfbf"
    edge_type "covers_project"
    confidence 1.0
    source_files "projects.md"
  ]
]
