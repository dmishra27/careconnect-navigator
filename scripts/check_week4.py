"""Week 4, Step 0: does this workspace support what "MLflow for GenAI" needs, on environment 6?

Each check prints what it did and adds one row to the summary table. Everything it creates
is named `careconnect_step0_*` (or `...-step0-*` for experiments) and removed at the end.

  uv run python scripts/check_week4.py

Checks:
  1. Local versions: MLflow 3.11 or newer (needed for traces in Unity Catalog), environment 6 pins
  2. Databricks Connect 19.1 against serverless compute
  3. Agent smoke test on the new MLflow: one question through the real agent and tools
  4. Prompt Registry: register, alias, load and delete a throwaway prompt in Unity Catalog
  5. Traces in Unity Catalog: an experiment with a table-prefix location, one trace, its tables
  6. Model registration in Unity Catalog: log, register and delete a tiny model
  7. GenAI evaluation: a code scorer and an LLM judge (default judge, then our endpoints)
  8. Model Serving: can endpoints be listed (custom endpoints are a Week 5 question)
"""

import time
import tomllib
import uuid
import warnings
from importlib.metadata import version
from pathlib import Path

import mlflow
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementState

from careconnect.config import ProjectConfig

warnings.filterwarnings("ignore", category=FutureWarning)
ROOT = Path(__file__).resolve().parents[1]
cfg = ProjectConfig.from_yaml(ROOT / "project_config.yml", env="dev")
w = WorkspaceClient()
me = w.current_user.me().user_name
mlflow.set_tracking_uri("databricks")
mlflow.set_registry_uri("databricks-uc")  # prompts and models live in Unity Catalog
CAT, SCH = cfg.catalog, cfg.schema_name
TAG = uuid.uuid4().hex[:6]  # keeps reruns from colliding with leftovers
summary: list[tuple[str, str, str]] = []  # (check, result, detail)
cleanup: list = []  # callables run at the end, newest first


def record(check: str, result: str, detail: str = "") -> None:
    print(f"   -> {result} {detail}")
    summary.append((check, result, detail[:110]))


def sql(statement: str) -> list[list]:
    """Run SQL on the first available warehouse and return the rows."""
    warehouses = list(w.warehouses.list())
    running = [x for x in warehouses if str(x.state).endswith("RUNNING")]
    wh = (running or warehouses)[0].id
    resp = w.statement_execution.execute_statement(
        statement=statement, warehouse_id=wh, wait_timeout="50s"
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{resp.status.state}: {resp.status.error}")
    return (resp.result.data_array if resp.result else None) or []


def experiment(name: str, **kwargs):
    exp = mlflow.set_experiment(f"/Users/{me}/{name}", **kwargs)
    cleanup.append(lambda: mlflow.delete_experiment(exp.experiment_id))
    return exp


# ---------------------------------------------------------------- 1. versions
print("\n1. Local versions")
try:
    pins = tomllib.loads((ROOT / "pyproject.toml").read_text())["tool"]["databricks"]
    env_version = pins["environment"]["environment_version"]
    mv = tuple(int(x) for x in mlflow.__version__.split(".")[:2])
    from mlflow.entities.trace_location import UnityCatalog  # noqa: F401 - 3.11+

    detail = (
        f"environment {env_version}, mlflow {mlflow.__version__}, "
        f"databricks-connect {version('databricks-connect')}, "
        f"databricks-sdk {version('databricks-sdk')}"
    )
    record("Local versions", "YES" if mv >= (3, 11) else "NO", detail)
except Exception as exc:  # noqa: BLE001 - report and carry on
    record("Local versions", "ERROR", str(exc))

# ---------------------------------------------------------------- 2. connect
print("\n2. Databricks Connect on serverless")
try:
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless(True).getOrCreate()
    n = spark.read.table(cfg.table("silver_chunks")).count()
    record("Databricks Connect 19.1", "YES", f"silver_chunks has {n} rows")
except Exception as exc:  # noqa: BLE001
    record("Databricks Connect 19.1", "ERROR", str(exc))

# ---------------------------------------------------------------- 3. agent smoke test
print("\n3. Agent on the new MLflow")
try:
    from careconnect.agent.main import build_agent

    experiment(f"careconnect-dev-step0-{TAG}")
    result = build_agent(cfg).run("How do I cancel my hospital appointment?")
    ok = "01632 960 100" in result.answer
    tools = ", ".join(c.name for c in result.tool_calls)
    detail = f"tools: {tools}; {result.answer[:60]}"
    record("Agent smoke test", "YES" if ok else "NO", detail)
except Exception as exc:  # noqa: BLE001
    record("Agent smoke test", "ERROR", str(exc))

# ---------------------------------------------------------------- 4. prompt registry
print("\n4. Prompt Registry")
prompt_name = f"{CAT}.{SCH}.careconnect_step0_prompt_{TAG}"
try:
    pv = mlflow.genai.register_prompt(
        name=prompt_name,
        template="Hello {{name}}, this is a Step 0 check.",
        commit_message="step 0",
    )
    cleanup.append(lambda: mlflow.MlflowClient().delete_prompt(prompt_name))
    cleanup.append(
        lambda: mlflow.MlflowClient().delete_prompt_version(prompt_name, str(pv.version))
    )
    mlflow.genai.set_prompt_alias(prompt_name, alias="step0", version=pv.version)
    loaded = mlflow.genai.load_prompt(f"prompts:/{prompt_name}@step0")
    text = loaded.format(name="CareConnect")
    record("Prompt Registry", "YES", f"version {pv.version}, alias step0 -> '{text}'")
except Exception as exc:  # noqa: BLE001
    record("Prompt Registry", "ERROR", str(exc))

# ---------------------------------------------------------------- 5. traces in UC
print("\n5. Traces in Unity Catalog (table-prefix location)")
prefix = f"careconnect_step0_{TAG}"
try:
    from mlflow.entities.trace_location import UnityCatalog

    experiment(
        f"careconnect-dev-step0-uc-traces-{TAG}",
        trace_location=UnityCatalog(catalog_name=CAT, schema_name=SCH, table_prefix=prefix),
    )
    cleanup.append(
        lambda: [
            sql(f"DROP TABLE IF EXISTS {CAT}.{SCH}.`{t[1]}`")
            for t in sql(f"SHOW TABLES IN {CAT}.{SCH} LIKE '{prefix}*'")
        ]  # fmt: skip
    )
    with mlflow.start_span(name="step0_ping") as span:
        span.set_inputs({"question": "ping"})
        span.set_outputs({"answer": "pong"})
    if hasattr(mlflow, "flush_trace_async_logging"):
        mlflow.flush_trace_async_logging()
    tables = [t[1] for t in sql(f"SHOW TABLES IN {CAT}.{SCH} LIKE '{prefix}*'")]
    rows = 0
    for _ in range(12):  # trace export is asynchronous: wait up to about 2 minutes
        try:
            rows = int(sql(f"SELECT count(*) FROM {CAT}.{SCH}.{prefix}_otel_spans")[0][0])
        except Exception:  # noqa: BLE001 - table may not exist yet
            rows = 0
        if rows:
            break
        time.sleep(10)
    result = "YES" if rows else ("PARTIAL" if tables else "NO")
    record("Traces in Unity Catalog", result, f"tables {tables}; spans stored: {rows}")
except Exception as exc:  # noqa: BLE001
    record("Traces in Unity Catalog", "ERROR", str(exc))

# ---------------------------------------------------------------- 6. model registration
print("\n6. Model registration in Unity Catalog")
model_name = f"{CAT}.{SCH}.careconnect_step0_model_{TAG}"
try:

    class Echo(mlflow.pyfunc.PythonModel):
        def predict(self, context, model_input, params=None):
            return model_input

    experiment(f"careconnect-dev-step0-model-{TAG}")
    with mlflow.start_run(run_name="step0-model"):
        info = mlflow.pyfunc.log_model(
            name="echo", python_model=Echo(), input_example={"question": ["ping"]}
        )
    mv = mlflow.register_model(info.model_uri, model_name)
    cleanup.append(lambda: mlflow.MlflowClient().delete_registered_model(model_name))
    record("Model registration in UC", "YES", f"{model_name} version {mv.version}")
except Exception as exc:  # noqa: BLE001
    record("Model registration in UC", "ERROR", str(exc))

# ---------------------------------------------------------------- 7. genai evaluation
print("\n7. GenAI evaluation (code scorer and LLM judge)")
try:
    from mlflow.genai.scorers import Guidelines, scorer

    @scorer
    def cites_a_source(outputs) -> bool:
        return "(" in str(outputs) and ")" in str(outputs)

    data = [
        {
            "inputs": {"question": "How do I complain?"},
            "outputs": "Phone the Complaints Team on 01632 960 180 "
            "(Making a complaint, How to complain).",
        }
    ]
    experiment(f"careconnect-dev-step0-eval-{TAG}")
    judges = [None, f"databricks:/{cfg.judge_endpoint}", f"databricks:/{cfg.llm_endpoint}"]
    working = []
    for model in judges:
        label = model or "default Databricks judge"
        try:
            judge = Guidelines(
                name="cites_source_judge",
                guidelines="The response names a source document in brackets.",
                **({"model": model} if model else {}),
            )
            res = mlflow.genai.evaluate(data=data, scorers=[cites_a_source, judge])
            metrics = {k: v for k, v in res.metrics.items() if "cites" in k}
            print(f"   {label}: {metrics}")
            if any("judge" in k for k in metrics):
                working.append(label)
        except Exception as exc:  # noqa: BLE001
            print(f"   {label}: ERROR {str(exc)[:150]}")
    detail = "judges working: " + (", ".join(working) or "none")
    record("GenAI evaluation", "YES" if working else "NO", detail)
except Exception as exc:  # noqa: BLE001
    record("GenAI evaluation", "ERROR", str(exc))

# ---------------------------------------------------------------- 8. model serving
print("\n8. Model Serving")
try:
    eps = list(w.serving_endpoints.list())
    custom = [e.name for e in eps if not (e.name or "").startswith("databricks-")]
    detail = f"{len(eps)} endpoints, custom: {custom or 'none'}"
    record("Model Serving listing", "YES", detail)
except Exception as exc:  # noqa: BLE001
    record("Model Serving listing", "ERROR", str(exc))

# ---------------------------------------------------------------- clean up
print("\nCleaning up Step 0 objects")
for undo in reversed(cleanup):
    try:
        undo()
    except Exception as exc:  # noqa: BLE001 - leftovers are named careconnect_step0_*
        print(f"   cleanup warning: {str(exc)[:120]}")

print("\nSummary")
print(f"{'check':<30}{'result':<10}detail")
for check, result, detail in summary:
    print(f"{check:<30}{result:<10}{detail}")
