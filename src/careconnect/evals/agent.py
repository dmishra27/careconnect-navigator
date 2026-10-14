"""Agent evaluation: run labelled questions through the agent and score each answer.

Checks are deterministic (no LLM judge yet), so a run is cheap, repeatable and explainable:
  tools    the expected tools were called ([] = none at all, as for urgent questions)
  guard    urgent questions trigger the right safety guard; others never do
  include  every required fact is in the answer ("a|b" = either)
  exclude  no forbidden text (outdated leaflet details, wrong claims, medical advice)

  uv run python -m careconnect.evals.agent --env dev                 # default tool backend
  uv run python -m careconnect.evals.agent --env dev --tools direct  # compare backends
  uv run python -m careconnect.evals.agent --env dev --uc-traces     # traces in Unity Catalog

Results go to MLflow (experiment <experiment_name>-agent, runs agent-eval-*) with a
per-question table; every agent call is also traced there.
"""

import argparse
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from careconnect.agent.guardrails import EMERGENCY, MENTAL_HEALTH
from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config

URGENT_GUARDS = {EMERGENCY, MENTAL_HEALTH}


@dataclass
class Case:
    id: str
    category: str
    question: str
    tools: list[str] | None = None
    guard: str | None = None
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


def load_cases(path: str | Path) -> list[Case]:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return [Case(**c) for c in raw["cases"]]


def _contains(answer: str, alternatives: str) -> bool:
    text = answer.lower()
    return any(alt.strip().lower() in text for alt in alternatives.split("|"))


def score_case(case: Case, answer: str, tools_called: list[str], guard: str | None) -> dict:
    """One row of results: which checks passed and why any failed."""
    failures = []
    if case.tools is not None:
        if case.tools == []:
            tools_ok = not tools_called
        else:
            tools_ok = set(case.tools) <= set(tools_called)
        if not tools_ok:
            failures.append(
                f"tools: expected {case.tools or 'none'}, called {tools_called or 'none'}"
            )
    else:
        tools_ok = None
    urgent = guard if guard in URGENT_GUARDS else None
    guard_ok = urgent == case.guard
    if not guard_ok:
        failures.append(
            f"guard: expected {case.guard or 'not urgent'}, got {urgent or 'not urgent'}"
        )
    missing = [f for f in case.include if not _contains(answer, f)]
    present = [f for f in case.exclude if _contains(answer, f)]
    failures += [f"missing: {m}" for m in missing]
    failures += [f"forbidden: {p}" for p in present]
    return {
        "id": case.id,
        "category": case.category,
        "question": case.question,
        "passed": not failures,
        "tools_ok": tools_ok,
        "guard_ok": guard_ok,
        "facts_found": len(case.include) - len(missing),
        "facts_expected": len(case.include),
        "violations": len(present),
        "failures": "; ".join(failures),
        "tools_called": ", ".join(tools_called),
        "guard": guard or "",
        "answer": answer,
    }


def summarise(rows: list[dict]) -> dict:
    n = len(rows) or 1
    tool_rows = [r for r in rows if r["tools_ok"] is not None]
    urgent = [r for r in rows if r["category"] == "safety_urgent"]
    not_urgent = [r for r in rows if r["category"] != "safety_urgent"]
    facts_expected = sum(r["facts_expected"] for r in rows) or 1
    metrics = {
        "pass_rate": sum(r["passed"] for r in rows) / n,
        "tool_accuracy": sum(r["tools_ok"] for r in tool_rows) / (len(tool_rows) or 1),
        "fact_recall": sum(r["facts_found"] for r in rows) / facts_expected,
        "violation_rate": sum(r["violations"] > 0 for r in rows) / n,
        "urgent_recall": sum(r["guard_ok"] for r in urgent) / (len(urgent) or 1),
        "false_alarm_rate": sum(not r["guard_ok"] for r in not_urgent) / (len(not_urgent) or 1),
        "n_cases": len(rows),
    }
    if rows and "seconds" in rows[0]:
        metrics["mean_seconds"] = sum(r["seconds"] for r in rows) / n
        metrics["mean_steps"] = sum(r["steps"] for r in rows) / n
    by_cat = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r["passed"])
    for cat, passes in by_cat.items():
        metrics[f"pass_rate_{cat}"] = sum(passes) / len(passes)
    return metrics


def run_cases(agent, cases: list[Case]) -> list[dict]:
    rows = []
    for case in cases:
        start = time.perf_counter()
        result = agent.run(case.question)
        row = score_case(case, result.answer, [c.name for c in result.tool_calls], result.guard)
        row.update(seconds=round(time.perf_counter() - start, 2), steps=result.steps)
        rows.append(row)
        print(f"  {case.id:<4} {'PASS' if row['passed'] else 'FAIL'}  {row['failures']}")
    return rows


def _setup_uc_traces(cfg: ProjectConfig, experiment: str) -> str:
    """Point the experiment's traces at Unity Catalog; fall back quietly if not allowed."""
    import mlflow
    from mlflow.entities import UCSchemaLocation

    try:
        from mlflow.tracing import set_experiment_trace_location

        exp = mlflow.set_experiment(experiment)
        set_experiment_trace_location(
            UCSchemaLocation(cfg.catalog, cfg.schema_name), experiment_id=exp.experiment_id
        )
        return f"traces stored in Unity Catalog schema {cfg.catalog}.{cfg.schema_name}"
    except Exception as exc:  # noqa: BLE001 - preview feature; keep evaluating without it
        return f"Unity Catalog trace storage not available ({type(exc).__name__}: {exc})"


def main(argv: list[str] | None = None) -> None:
    import mlflow
    import pandas as pd
    from databricks.sdk import WorkspaceClient

    from careconnect.agent.main import build_agent

    parser = argparse.ArgumentParser(description="Evaluate the CareConnect agent")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--tools", default=None, help="tool backend (default: config)")
    parser.add_argument("--model", default=None)
    parser.add_argument("--cases", default=None)
    parser.add_argument("--only", default=None, help="comma-separated case ids")
    parser.add_argument("--uc-traces", action="store_true", help="store traces in Unity Catalog")
    parser.add_argument("--no-mlflow", action="store_true")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    cases = load_cases(
        args.cases or _find_config().parent / "data" / "eval" / "agent_questions.yml"
    )
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c.id in wanted]
    backend = args.tools or cfg.agent_tool_backend

    w = WorkspaceClient()
    mlflow.set_tracking_uri("databricks")
    name = cfg.agent_experiment_name + ("-uc" if args.uc_traces else "")
    experiment = f"/Users/{w.current_user.me().user_name}/{name}"
    if args.uc_traces:
        print(_setup_uc_traces(cfg, experiment))
    mlflow.set_experiment(experiment)
    mlflow.openai.autolog()

    agent = build_agent(cfg, args.model, backend)
    print(f"model: {agent.model}   backend: {backend}   cases: {len(cases)}")
    rows = run_cases(agent, cases)
    metrics = summarise(rows)

    print("\nSummary")
    for key, value in metrics.items():
        print(f"  {key:<28}{value:.3f}" if isinstance(value, float) else f"  {key:<28}{value}")

    if not args.no_mlflow:
        with mlflow.start_run(run_name=f"agent-eval-{backend}"):
            mlflow.set_tag("stage", "week3-agent-eval")
            mlflow.log_params({"backend": backend, "model": agent.model, "cases": len(cases)})
            mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
            mlflow.log_table(pd.DataFrame(rows), artifact_file="per_question.json")
        print(f"\nLogged to MLflow experiment {name} (run agent-eval-{backend})")


if __name__ == "__main__":
    main()
