# MLflow trace storage: experiment storage for now, Unity Catalog with the agent

- Date: 2026-10-09
- Status: accepted (revisit when the agent is served)

## Context

MLflow traces from the project currently go to experiment storage in
`/Users/<you>/careconnect-dev`. Databricks suggests storing traces in Unity Catalog
instead. Experiment storage caps each experiment at 100,000 traces; Unity Catalog storage
removes that cap and makes traces queryable from SQL and dashboards.

Constraints from the Databricks documentation:

- An experiment can only be bound to a Unity Catalog trace location **when the
  experiment is created**. `careconnect-dev` already exists, so it cannot be moved.
- Writing traces to Unity Catalog needs a SQL warehouse (Free Edition has one 2X-Small
  warehouse) and explicit `MODIFY` and `SELECT` grants on the target schema.

## Decision

- **Weeks 1 and 2:** keep experiment storage. The only traces so far come from the Week 1
  test call; the Week 2 retrieval evaluation logs runs and tables, not traces.
- **When the agent is built and served:** create a new experiment for agent traces
  (for example `careconnect-dev-agent`) bound at creation to
  `workspace.careconnect_dev` with table prefix `traces_`, and the same for prod. The
  existing experiment keeps retrieval-evaluation runs.

## Why

- The 100,000 cap only matters once a served agent logs every request. Before that,
  Unity Catalog storage adds a warehouse dependency and grants for no gain.
- Binding happens at creation, so the right moment is when the agent experiment is
  first created, not by retrofitting the current one.

## Consequences

- Traces from early experiments stay in experiment storage; Databricks documents a
  migration path if they are ever needed in Unity Catalog.
- Trace tables will follow the workspace-layout convention (`traces_` prefix in the
  environment schema).
