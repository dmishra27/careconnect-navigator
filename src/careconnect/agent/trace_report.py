"""Analyse agent traces stored in Unity Catalog with SQL.

  uv run python -m careconnect.agent.trace_report --env dev                  # all traces
  uv run python -m careconnect.agent.trace_report --env dev --eval-run mcp-20261017-101500
  uv run python -m careconnect.agent.trace_report --env dev --show-sql       # print the SQL

Reads `<catalog>.<schema>.<prefix>_trace_unified` (one row per trace, spans nested, tags as a
map) and prints five tables:
  runs     traces per evaluation run and backend: count, mean, median and 95th percentile time
  outcome  how runs ended: answer, urgent guard, no-grounding guard, step limit
  tools    per tool: calls, mean and 95th percentile time, errors, retries
  slowest  the slowest test cases
  prompts  traces per prompt fingerprint (prompt_hash), so prompt versions can be compared
"""

import argparse
import time

from careconnect.agent.tracing import trace_table
from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config

# MLflow stores span attributes as JSON text, so a span type reads as "TOOL" with quotes
_SPAN_TYPE = "replace(s.attributes:`mlflow.spanType`::string, '\"', '')"
_SPAN_MS = "(s.end_time_unix_nano - s.start_time_unix_nano) / 1e6"


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
       sum(CASE WHEN lower(s.attributes:retried::string) LIKE '%true%' THEN 1 ELSE 0 END)
         AS retried
FROM {table} t LATERAL VIEW explode(t.spans) x AS s
WHERE {_SPAN_TYPE} = 'TOOL' {and_where}
GROUP BY 1
ORDER BY calls DESC""",
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
SELECT coalesce(t.tags['prompt_hash'], '?') AS prompt_hash,
       count(*) AS traces,
       min(t.request_time) AS first_seen,
       max(t.request_time) AS last_seen
FROM {table} t {where}
GROUP BY 1
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
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    table = trace_table(cfg)
    params = {"eval_run": args.eval_run} if args.eval_run else {}
    w = WorkspaceClient()
    print(f"Traces: {table}" + (f"   eval_run: {args.eval_run}" if args.eval_run else ""))
    for title, sql in build_queries(table, args.eval_run).items():
        print(f"\n{title}")
        if args.show_sql:
            print(sql)
        try:
            print(format_table(*run_sql(w, sql, params)))
        except Exception as exc:  # noqa: BLE001 - one failing query should not hide the rest
            print(f"   ERROR {str(exc)[:300]}")


if __name__ == "__main__":
    main()
