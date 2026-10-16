"""Agent evaluation: run labelled questions through the agent and score each answer.

Checks are deterministic (no LLM judge yet), so a run is cheap, repeatable and explainable:
  tools    the expected tools were called ([] = none at all, as for urgent questions)
  guard    urgent questions trigger the right safety guard; others never do
  include  every required fact is in the answer ("a|b" = either)
  exclude  no forbidden text (outdated leaflet details, wrong claims, medical advice)

  uv run python -m careconnect.evals.agent --env dev                 # default tool backend
  uv run python -m careconnect.evals.agent --env dev --tools direct  # compare backends
  uv run python -m careconnect.evals.agent --env dev --experiment-traces  # old trace storage

Results go to MLflow (experiment <experiment_name>-agent-uc, runs agent-eval-*) with a
per-question table. Every agent call is traced to Unity Catalog tables and tagged with
case_id, category and eval_run, so trace_report.py can analyse a run with SQL.
"""

import argparse
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from careconnect.agent.guardrails import EMERGENCY, MENTAL_HEALTH
from careconnect.agent.tracing import setup_agent_experiment, trace_table
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


def run_cases(agent, cases: list[Case], eval_run: str | None = None) -> list[dict]:
    rows = []
    for case in cases:
        start = time.perf_counter()
        tags = {"case_id": case.id, "category": case.category, "eval_run": eval_run}
        result = agent.run(case.question, tags=tags)
        row = score_case(case, result.answer, [c.name for c in result.tool_calls], result.guard)
        row.update(seconds=round(time.perf_counter() - start, 2), steps=result.steps)
        rows.append(row)
        print(f"  {case.id:<4} {'PASS' if row['passed'] else 'FAIL'}  {row['failures']}")
        if not row["passed"]:  # show the answer so a reviewer can tell agent from label errors
            print("        answer: " + " ".join(result.answer.split())[:400])
    return rows


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
    parser.add_argument(
        "--experiment-traces",
        action="store_true",
        help="store traces in the MLflow experiment instead of Unity Catalog",
    )
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
    experiment = setup_agent_experiment(
        cfg, w.current_user.me().user_name, uc=not args.experiment_traces
    )
    name = experiment.rsplit("/", 1)[-1]
    mlflow.openai.autolog()

    agent = build_agent(cfg, args.model, backend)
    # one label per evaluation run, on every trace and on the MLflow run, so SQL can join them
    eval_run = f"{backend}-{time.strftime('%Y%m%d-%H%M%S')}"
    print(f"model: {agent.model}   backend: {backend}   cases: {len(cases)}   eval_run: {eval_run}")
    rows = run_cases(agent, cases, eval_run)
    metrics = summarise(rows)

    print("\nSummary")
    for key, value in metrics.items():
        print(f"  {key:<28}{value:.3f}" if isinstance(value, float) else f"  {key:<28}{value}")

    if not args.no_mlflow:
        with mlflow.start_run(run_name=f"agent-eval-{backend}"):
            mlflow.set_tags({"stage": "week4-agent-eval", "eval_run": eval_run})
            mlflow.log_params(
                {
                    "backend": backend,
                    "model": agent.model,
                    "cases": len(cases),
                    "prompt_hash": agent.trace_tags["prompt_hash"],
                    "eval_run": eval_run,
                }
            )
            mlflow.log_metrics({k: float(v) for k, v in metrics.items()})
            mlflow.log_table(pd.DataFrame(rows), artifact_file="per_question.json")
        print(f"\nLogged to MLflow experiment {name} (run agent-eval-{backend})")
    if not args.experiment_traces:
        print(f"Traces in Unity Catalog: {trace_table(cfg)} (tag eval_run = {eval_run})")


if __name__ == "__main__":
    main()
