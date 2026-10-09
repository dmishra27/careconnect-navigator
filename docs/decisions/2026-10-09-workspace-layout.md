# Workspace layout on Free Edition: one schema per environment

- Date: 2026-10-09
- Status: accepted

## Context

Databricks Free Edition gives one workspace with a `workspace` catalog and serverless
compute only. The project needs separate dev and prod environments, raw and cleaned data
layers, and names that match `project_config.yml` exactly.

## Decision

1. **One catalog, one schema per environment.** Everything lives in catalog `workspace`:
   schema `careconnect_dev` for the `dev` bundle target and `careconnect_prod` for
   `prod`. Both schemas and the managed `landing` Volume are defined in the bundle
   (`resources/schemas.yml`), not created by hand.
2. **Medallion layers are table-name prefixes, not schemas.** `bronze_`, `silver_`,
   `gold_` for data, and `ops_` for operational tables (quarantine, rejects,
   data-quality results). For example `bronze_documents`, `silver_chunks`,
   `silver_phs_ongoing_waits`, `ops_dq_results`.
3. **No development-mode prefix on schemas.** `experimental.skip_name_prefix_for_schema:
   true` in `databricks.yml` stops development mode renaming the schema to
   `dev_<user>_careconnect_dev`. Jobs still get the `[dev <user>]` prefix, and their
   schedules stay paused in dev.

## Why

- Three layers times two environments would mean six schemas for a handful of tables.
  Prefixes keep the layer visible in every table name with half the moving parts.
- Code reads names from `ProjectConfig` (`cfg.table("silver_chunks")`), so the
  environment switch is one setting.
- Matching names between the bundle and `project_config.yml` removes a class of
  "table not found" errors when the same code runs from a laptop and from a job.

## Consequences

- Unity Catalog permissions are granted per schema, so dev and prod can be separated, but
  bronze and silver in the same environment cannot be. That is acceptable here: all data
  is synthetic or public aggregate statistics.
- `skip_name_prefix_for_schema` is an experimental bundle setting. If it is removed,
  the fallback is to set the schema per target explicitly and accept the dev prefix in
  `project_config.yml`.
- On a paid workspace this maps cleanly to one catalog per environment with schemas
  `bronze`, `silver`, `gold`, without changing pipeline code beyond `ProjectConfig`.
