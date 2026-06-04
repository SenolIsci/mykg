# Neo4j LOAD CSV exporter

Turns a finished mykg session into a self-contained import bundle: plain-header CSVs plus paste-and-run Cypher scripts you execute against any Neo4j 5+ instance. No optional Python dependency, no plugins, no live driver.

Requires Neo4j 5.x or newer. The generated Cypher uses `CREATE CONSTRAINT … IF NOT EXISTS`, `IN TRANSACTIONS OF`, and the modern `REQUIRE` syntax — none of which exist in 4.x.

## How to enable

**Canonical entry point — pipeline integration.** Set the toggle in `mykg_config.yaml`:

```yaml
profiles:
  <your-profile>:
    pipeline:
      export:
        neo4j_csv_enabled: true     # default false
        neo4j_csv_dir: neo4j_csv    # subdirectory under output/
```

The bundle is then written to `<session>/output/neo4j_csv/` by `step_validate_graph` alongside `nodes.jsonl`, `knowledge_graph.ttl`, and the NetworkX outputs. Pass `--neo4j-csv` to `mykg extract-graph` to override the YAML for a single run.

**Standalone fallback.** When the toggle was off at extraction time and you want to produce a bundle from an existing session without re-running the pipeline:

```bash
python -m mykg.exporters.neo4j.emit_load_csv \
  --session 2026-06-03T10-00-00 \
  --out neo4j_load_csv/
```

Produces:
- One `nodes_<Label>.csv` per concept type, with plain headers (`id,name,name_confidence,...`).
- One `relationships_<TYPE>.csv` per relationship type.
- `import_browser.cypher` — paste into Neo4j Browser. Uses relative `file:/<name>.csv` URIs that resolve against the DBMS's `import/` directory; copy the CSVs there first.
- `import_shell.cypher` — for `cypher-shell -f`. Uses absolute `file:///` URIs; requires `dbms.security.allow_csv_import_from_file_urls=true` in `neo4j.conf`.
- `README.md` — quick-reference for the bundle.

The script:
1. Creates `CONSTRAINT _mykgnode_id_unique` on `(n:_MykgNode) REQUIRE n.id IS UNIQUE`.
2. For each label, runs `:auto LOAD CSV WITH HEADERS FROM '...' AS row CALL { ... MERGE (n:_MykgNode {id: row.id}) SET n:<Label> SET n.<attr> = ... } IN TRANSACTIONS OF 1000 ROWS`.
3. For each rel-type, runs the equivalent edge MERGE.

Idempotent — re-running over the same DB updates in place. No plugin required.

## Data model

Each node carries:
- Its leaf concept type as its single domain label (e.g. `:SoftwareEngineer`), sanitized to PascalCase.
- A shared `:_MykgNode` label which owns the `id` uniqueness constraint.
- Properties: `id`, `<attr>` and `<attr>_confidence` for every non-null attribute, `_node_confidence`, `_parents` (list walked from `schema.json`), `_aliases` (list, omitted when source has no `aliases` field), `_source_files`.

Each edge carries:
- A relationship type = the sanitized property name (`works_at` → `:WORKS_AT`).
- Properties: `confidence`, `<attr>` and `<attr>_confidence` for every non-null attribute, `method`, `source_files`.

## Example Cypher queries

```cypher
-- Find every Person and their employer
MATCH (p)-[r:WORKS_AT]->(o) WHERE p:Person OR "Person" IN p._parents
RETURN p.name, o.name, r.role, r.confidence ORDER BY r.confidence DESC;

-- Find every node with a confidence under 0.5
MATCH (n:_MykgNode) WHERE n._node_confidence < 0.5 RETURN n;
```

## Troubleshooting

- `Neo4jPlugin not found` for any plugin — this path doesn't require plugins (no APOC, no n10s).
- `URL not allowed` from `cypher-shell` — set `dbms.security.allow_csv_import_from_file_urls=true` in `neo4j.conf` and restart, or use the browser variant instead.
- `unique constraint violation` on re-import — should not happen; the script uses `MERGE`. If it does, check that you didn't manually create a different constraint with the same name.
