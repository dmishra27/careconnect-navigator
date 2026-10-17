"""Where agent traces go, and the tags that make them queryable.

From Week 4 agent traces are stored in Unity Catalog: the experiment is linked to a
table-prefix location, so every trace lands in governed tables such as
`workspace.careconnect_dev.careconnect_agent_trace_unified` and can be analysed with SQL
(see trace_report.py). `--experiment-traces` keeps the old experiment storage as a fallback.

Each trace is tagged (all values are strings) so questions like "how slow is get_waiting_times
for prompt version X on the MCP backend?" become one SQL query:
  backend, model, prompt_hash          set by the agent
  stopped, guard, steps, tool_calls,
  retries                              outcome of the run
  case_id, category, eval_run          set by the evaluation
"""

import hashlib

import mlflow

from careconnect.config import ProjectConfig


def prompt_hash(prompt: str) -> str:
    """Short, stable fingerprint of a prompt, so traces show which wording produced them."""
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12]


def setup_agent_experiment(cfg: ProjectConfig, user_name: str, uc: bool = True) -> str:
    """Make the agent experiment active; with uc=True its traces are stored in Unity Catalog.

    Linking is idempotent: an experiment already linked to the same prefix is reused.
    """
    mlflow.set_tracking_uri("databricks")
    if not uc:
        name = f"/Users/{user_name}/{cfg.agent_experiment_name}"
        mlflow.set_experiment(name)
        return name
    from mlflow.entities.trace_location import UnityCatalog

    name = f"/Users/{user_name}/{cfg.agent_uc_experiment_name}"
    location = UnityCatalog(
        catalog_name=cfg.catalog,
        schema_name=cfg.schema_name,
        table_prefix=cfg.agent_trace_prefix,
    )
    try:
        mlflow.set_experiment(name, trace_location=location)
    except Exception as exc:
        if "already contains traces" in str(exc):
            raise RuntimeError(
                f"Experiment {name} already holds traces stored outside Unity Catalog, and "
                "Databricks only links an experiment with no traces. Delete or rename it in "
                "the MLflow UI, or change agent_uc_experiment_name; run with "
                "--experiment-traces to keep working meanwhile."
            ) from exc
        raise
    return name


def trace_table(cfg: ProjectConfig, suffix: str = "trace_unified") -> str:
    """Fully qualified name of one of the Unity Catalog trace tables."""
    return f"{cfg.catalog}.{cfg.schema_name}.{cfg.agent_trace_prefix}_{suffix}"


def tag_current_trace(tags: dict) -> None:
    """Add string tags to the active trace; never let tracing break an answer."""
    clean = {str(k): str(v) for k, v in tags.items() if v is not None}
    try:
        mlflow.update_current_trace(tags=clean)
    except Exception:  # noqa: BLE001 - tracing may be disabled (tests) or unavailable
        pass
