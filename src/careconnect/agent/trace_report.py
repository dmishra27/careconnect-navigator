"""Analyse agent traces stored in Unity Catalog with SQL.

  uv run python -m careconnect.agent.trace_report --env dev                  # all traces
  uv run python -m careconnect.agent.trace_report --env dev --eval-run mcp-20261017-101500
  uv run python -m careconnect.agent.trace_report --env dev --show-sql       # print the SQL
  uv run python -m careconnect.agent.trace_report --env dev --inspect        # span details

Reads `<catalog>.<schema>.<prefix>_trace_unified` (one row per trace, spans nested, tags as a
map) and prints five tables:
  runs     traces per evaluation run and backend: count, mean, median and 95th percentile time
  outcome  how runs ended: answer, urgent guard, no-grounding guard, step limit
  tools    per tool: calls, mean and 95th percentile time, errors, retries
  time_split  per run: model calls and tool calls, with their mean time (where time goes)
  slowest  the slowest test cases
  prompts  traces per prompt version and fingerprint, with share answered and mean time
           (traces from before the Prompt Registry show version "code")
"""

import argparse
import time

from careconnect.agent.tracing import trace_table
from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config

# Span attributes are a VARIANT whose values MLflow writes as JSON text ("\"TOOL\""), and a
# path lookup on a key with a dot (mlflow.spanType) returned nothing on 17 Oct. Matching the
# attributes' JSON text works whatever the quoting or nesting.
_ATTRS = "to_json(s.attributes)"
_IS_TOOL = f"{_ATTRS} RLIKE 'mlflow[.]spanType[^,}}]*TOOL'"
_RETRIED = f"{_ATTRS} RLIKE 'retried[^,}}]*true'"
# a model call is any span that is neither a tool nor the agent's own root span
_IS_MODEL = f"(NOT ({_IS_TOOL}) AND s.name <> 'careconnect_agent')"
_SPAN_MS = "(s.end_time_unix_nano - s.start_time_unix_nano) / 1e6"


def inspect_query(table: str) -> str:
    """What the spans look like: names, counts and a sample of raw attributes."""
    return f"""
SELECT s.name AS span,
       count(*) AS spans,
       left(first({_ATTRS}), 250) AS sample_attributes
FROM {table} t LATERAL VIEW explode(t.spans) x AS s
GROUP BY 1
ORDER BY spans DESC
LIMIT 20"""


def build_queries(table: str, eval_run: str | None = None) -> dict[str, str]:
    """The report's SQL. `eval_run` becomes the named parameter :eval_run (never pasted in)."""
    where = "WHERE t.tags['eval_run'] = :eval_run" if eval_run else ""
    and_where = "AND t.tags['eval_run'] = :eval_run" if eval_run else ""
    return {
        "runs": f"""
SELECT coalesce(t.tags['eval_run'], '(interactive)') AS eval_run,
       coalesce(t.tags['backend'], '?') AS backend,
       count(*) AS traces,
       round(avg(t.execution_duration_ms) / 1000, 2) AS mean_s,
       round(percentile_approx(t.execution_duration_ms, 0.5) / 1000, 2) AS p50_s,
       round(percentile_approx(t.execution_duration_ms, 0.95) / 1000, 2) AS p95_s,
       max(t.request_time) AS last_trace
FROM {table} t {where}
GROUP BY 1, 2
ORDER BY last_trace DESC
LIMIT 15""",
        "outcome": f"""
SELECT coalesce(t.tags['stopped'], '?') AS stopped,
       coalesce(t.tags['guard'], 'none') AS guard,
       count(*) AS traces,
       round(100 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM {table} t {where}
GROUP BY 1, 2
ORDER BY traces DESC""",
        "tools": f"""
SELECT s.name AS tool,
       count(*) AS calls,
       round(avg({_SPAN_MS})) AS mean_ms,
       round(percentile_approx({_SPAN_MS}, 0.95)) AS p95_ms,
       sum(CASE WHEN s.status.code LIKE '%ERROR%' THEN 1 ELSE 0 END) AS errors,
       sum(CASE WHEN {_RETRIED} THEN 1 ELSE 0 END) AS retried
FROM {table} t LATERAL VIEW explode(t.spans) x AS s
WHERE {_IS_TOOL} {and_where}
GROUP BY 1
ORDER BY calls DESC""",
        "time_split": f"""
SELECT coalesce(t.tags['eval_run'], '(interactive)') AS eval_run,
       sum(CASE WHEN {_IS_MODEL} THEN 1 ELSE 0 END) AS model_calls,
       round(avg(CASE WHEN {_IS_MODEL} THEN {_SPAN_MS} END)) AS model_mean_ms,
       sum(CASE WHEN {_IS_TOOL} THEN 1 ELSE 0 END) AS tool_calls,
       round(avg(CASE WHEN {_IS_TOOL} THEN {_SPAN_MS} END)) AS tool_mean_ms,
       max(t.request_time) AS last_trace
FROM {table} t LATERAL VIEW explode(t.spans) x AS s {where}
GROUP BY 1
ORDER BY last_trace DESC
LIMIT 15""",
        "slowest": f"""
SELECT t.tags['case_id'] AS case_id,
       t.tags['category'] AS category,
       count(*) AS runs,
       round(avg(t.execution_duration_ms) / 1000, 2) AS mean_s,
       round(max(t.execution_duration_ms) / 1000, 2) AS max_s
FROM {table} t
WHERE t.tags['case_id'] IS NOT NULL {and_where}
GROUP BY 1, 2
ORDER BY mean_s DESC
LIMIT 10""",
        "prompts": f"""
SELECT coalesce(t.tags['prompt_version'], 'code') AS prompt_version,
       coalesce(t.tags['prompt_hash'], '?') AS prompt_hash,
       count(*) AS traces,
       round(100 * avg(CASE WHEN t.tags['stopped'] = 'answer' THEN 1 ELSE 0 END), 1)
         AS answered_pct,
       round(avg(t.execution_duration_ms) / 1000, 2) AS mean_s,
       min(t.request_time) AS first_seen,
       max(t.request_time) AS last_seen
FROM {table} t {where}
GROUP BY 1, 2
ORDER BY last_seen DESC""",
    }


def run_sql(w, statement: str, params: dict[str, str], warehouse_id: str | None = None):
    """Execute on a SQL warehouse; returns (column names, rows)."""
    from databricks.sdk.service.sql import StatementParameterListItem, StatementState

    if warehouse_id is None:
        warehouses = list(w.warehouses.list())
        running = [x for x in warehouses if str(x.state).endswith("RUNNING")]
        warehouse_id = (running or warehouses)[0].id
    resp = w.statement_execution.execute_statement(
        statement=statement,
        warehouse_id=warehouse_id,
        parameters=[StatementParameterListItem(name=k, value=v) for k, v in params.items()],
        wait_timeout="50s",
    )
    while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
        time.sleep(2)
        resp = w.statement_execution.get_statement(resp.statement_id)
    if resp.status.state != StatementState.SUCCEEDED:
        raise RuntimeError(f"{resp.status.state}: {resp.status.error}")
    columns = [c.name for c in resp.manifest.schema.columns]
    return columns, (resp.result.data_array if resp.result else None) or []


def format_table(columns: list[str], rows: list[list]) -> str:
    """Plain fixed-width table for the terminal."""
    if not rows:
        return "   (no rows)"
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(c), *(len(r[i]) for r in cells)) for i, c in enumerate(columns)]
    lines = ["   " + "  ".join(c.ljust(widths[i]) for i, c in enumerate(columns))]
    lines += ["   " + "  ".join(v.ljust(widths[i]) for i, v in enumerate(r)) for r in cells]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    from databricks.sdk import WorkspaceClient

    parser = argparse.ArgumentParser(description="Analyse agent traces in Unity Catalog")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--eval-run", default=None, help="only this evaluation run")
    parser.add_argument("--show-sql", action="store_true")
    parser.add_argument("--inspect", action="store_true", help="also list span names, attributes")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    table = trace_table(cfg)
    params = {"eval_run": args.eval_run} if args.eval_run else {}
    w = WorkspaceClient()
    print(f"Traces: {table}" + (f"   eval_run: {args.eval_run}" if args.eval_run else ""))
    queries = build_queries(table, args.eval_run)
    if args.inspect:
        queries["spans (inspect)"] = inspect_query(table)
    for title, sql in queries.items():
        print(f"\n{title}")
        if args.show_sql:
            print(sql)
        try:
            used = params if ":eval_run" in sql else {}
            print(format_table(*run_sql(w, sql, used)))
        except Exception as exc:  # noqa: BLE001 - one failing query should not hide the rest
            print(f"   ERROR {str(exc)[:300]}")


if __name__ == "__main__":
    main()
