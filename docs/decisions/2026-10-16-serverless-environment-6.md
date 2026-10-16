# Move to serverless environment version 6

- Date: 2026-10-16
- Status: accepted (16 October: all 8 checks in `scripts/check_week4.py` passed, `ingest_job` succeeded on environment 6, agent evaluation 28 of 28)

## Context

Week 4 ("MLflow for GenAI") needs agent traces stored in Unity Catalog. In Week 3 the workspace
refused the schema-based trace location ("Creation of UC schema trace locations is disabled.
Please use UC table prefix locations instead."). The table-prefix location is the class
`mlflow.entities.trace_location.UnityCatalog`, checked in the published wheels:

| MLflow | Table-prefix trace location |
|--------|-----------------------------|
| 3.8.1 (serverless environment 5, our pin) | no |
| 3.9.0, 3.10.1 | no |
| 3.11.1, 3.12.0 and later | yes |

Since Week 1 the laptop has been pinned to the packages serverless ships (`[tool.uv]
constraint-dependencies` plus `environment_version` in the jobs), so code that passes locally
behaves the same in a job. Upgrading MLflow on the laptop alone would break that.

Serverless environment version 6 ships Python 3.12.3, `mlflow-skinny` 3.12.0,
`databricks-connect` 19.1, `databricks-sdk` 0.122.0 and `databricks-agents` 1.11.0.

## Decision

Move the whole project to environment 6:

- `[tool.databricks.environment] environment_version = "6"` and the `constraint-dependencies`
  block rebuilt from the environment 6 standard base package list (pip, setuptools, wheel and
  databricks-connect excluded, as before);
- `databricks-connect~=19.1.0` in the dev group;
- `environment_version: "6"` in `ingest_job` and `phs_job`.

`uv lock` resolves MLflow 3.12.0 and all 176 unit tests pass on it.

## Consequences

- Traces in Unity Catalog, the Prompt Registry and `mlflow.genai.evaluate` with the current
  built-in judges become available locally and in jobs.
- The constraints were rebuilt from the published release notes rather than by the VS Code
  extension. Re-running the extension's environment setup should produce the same block; any
  difference is taken as correct and committed.
- If Free Edition does not offer environment 6, the fallback is to upgrade MLflow for laptop
  evaluation runs only, which gives up the laptop-matches-jobs rule; that would be recorded
  as a new decision.

## Evidence (16 October)

| Check | Result |
|-------|--------|
| Local versions | environment 6, MLflow 3.12.0, databricks-connect 19.1, databricks-sdk 0.122.0 |
| Databricks Connect 19.1 on serverless | read `silver_chunks` (353 rows) |
| Agent on MLflow 3.12 | correct answer with `search_guidance` |
| Prompt Registry | register, alias and load a prompt in Unity Catalog |
| Traces in Unity Catalog | table-prefix location created 6 tables (`_otel_spans`, `_otel_logs`, `_otel_metrics`, `_otel_annotations`, `_trace_metadata`, `_trace_unified`); 1 span stored |
| Model registration in Unity Catalog | logged, registered (version 1) and deleted |
| GenAI evaluation | code scorer and LLM judges ran; the Llama 3.1 8B judge failed an answer that plainly cites its source, so it is not used as a judge |
| Model Serving | endpoints listed; no custom endpoints yet (Week 5) |
| Jobs on environment 6 | `ingest_job` TERMINATED SUCCESS (with index sync); `phs_job` reached RUNNING, result to be confirmed (the CLI lost its connection while polling) |
| Agent evaluation | 28 of 28, mean 4.3 s per question |
