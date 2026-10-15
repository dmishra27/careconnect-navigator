"""The agent's tools: JSON schemas the model sees, and the Python that runs each call.

Two kinds of tool:
* search_guidance runs our own retriever (AUTO query type, current documents only), so
  superseded leaflets can never reach the model.
* find_clinic, get_waiting_times and list_waiting_time_specialties run the Unity Catalog
  functions registered by `uv run tools`, here through the SQL Statement Execution API on a
  SQL warehouse. (Step 4 adds an MCP backend for the same functions.)
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass

import mlflow

from careconnect.config import ProjectConfig
from careconnect.tools import sql as uc

MAX_ROWS = 20
MAX_PASSAGE_CHARS = 1200


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    run: Callable[..., object]

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def _string(description: str) -> dict:
    return {"type": "string", "description": description}


# ------------------------------------------------------------------ search


def make_search_tool(retriever, k: int = 5) -> Tool:
    def search_guidance(query: str, source_type: str | None = None) -> list[dict]:
        filters = {"source_type": source_type} if source_type in ("leaflet", "policy") else None
        hits = retriever.search(query, k, filters)
        return [
            {
                "title": h.title,
                "section": h.section_path.split(" > ", 1)[-1],
                "page": h.page,
                "source_type": h.source_type,
                "text": h.text.split("\n\n", 1)[-1][:MAX_PASSAGE_CHARS],
            }
            for h in hits
        ]

    return Tool(
        name="search_guidance",
        description=(
            "Search Firth Valley Health Board leaflets and national NHS Scotland policy "
            "documents. Returns the most relevant passages with title, section and page."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": _string("What to look for, in plain words"),
                "source_type": {
                    "type": "string",
                    "enum": ["leaflet", "policy"],
                    "description": "Optional: only local leaflets, or only national policy",
                },
            },
            "required": ["query"],
        },
        run=search_guidance,
    )


# ------------------------------------------------------------------ UC functions via SQL


class SqlRunner:
    """Runs `SELECT * FROM fn(:a, :b)` on a SQL warehouse with named parameters."""

    def __init__(self, w, warehouse_id: str | None = None, timeout_s: int = 180):
        self.w, self.timeout_s = w, timeout_s
        self.warehouse_id = warehouse_id or self._pick_warehouse()

    def _pick_warehouse(self) -> str:
        warehouses = list(self.w.warehouses.list())
        if not warehouses:
            raise RuntimeError("No SQL warehouse found; create one or set warehouse_id")
        running = [wh for wh in warehouses if str(wh.state).endswith("RUNNING")]
        return (running or warehouses)[0].id

    def call(self, function: str, args: dict[str, str | None]) -> list[dict]:
        from databricks.sdk.service.sql import StatementParameterListItem, StatementState

        names = list(args)
        statement = f"SELECT * FROM {function}({', '.join(':' + n for n in names)})"
        params = [
            StatementParameterListItem(name=n, value=args[n], type="STRING")
            if args[n] not in (None, "")
            else StatementParameterListItem(name=n, type="STRING")  # no value = NULL
            for n in names
        ]
        resp = self.w.statement_execution.execute_statement(
            statement=statement,
            warehouse_id=self.warehouse_id,
            parameters=params,
            wait_timeout="30s",
            row_limit=MAX_ROWS,
        )
        deadline = time.monotonic() + self.timeout_s
        while resp.status.state in (StatementState.PENDING, StatementState.RUNNING):
            if time.monotonic() > deadline:
                raise TimeoutError(f"{function} did not finish in {self.timeout_s}s")
            time.sleep(2)
            resp = self.w.statement_execution.get_statement(resp.statement_id)
        if resp.status.state != StatementState.SUCCEEDED:
            raise RuntimeError(f"{function} failed: {resp.status.error}")
        cols = [c.name for c in resp.manifest.schema.columns]
        rows = (resp.result.data_array if resp.result else None) or []
        return [dict(zip(cols, r, strict=False)) for r in rows]


def make_uc_tools(cfg: ProjectConfig, runner) -> list[Tool]:
    def find_clinic(service: str | None = None, town: str | None = None):
        return runner.call(cfg.table(uc.FIND_CLINIC), {"service": service, "town": town})

    def get_waiting_times(
        specialty: str | None = None, patient_type: str | None = None, board: str | None = None
    ):
        rows = runner.call(
            cfg.table(uc.GET_WAITING_TIMES),
            {"specialty": specialty, "patient_type": patient_type, "board": board},
        )
        # the source label is the same on every row: say it once
        source = rows[0].pop("source", None) if rows else None
        for r in rows[1:]:
            r.pop("source", None)
        return {"source": source or uc.PHS_SOURCE_LABEL, "rows": rows}

    def list_waiting_time_specialties():
        return [r["specialty"] for r in runner.call(cfg.table(uc.LIST_SPECIALTIES), {})]

    return [
        Tool(
            name=uc.FIND_CLINIC,
            description=(
                "Find Firth Valley Health Board hospitals and community clinics by service "
                "and/or town. Returns name, address, phone, opening hours and services."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "service": _string('e.g. "blood tests", "podiatry", "x-ray", "contraception"'),
                    "town": _string("Larbank, Grangeford, Inverbrae, Kilbrannan or Muirhead"),
                },
            },
            run=find_clinic,
        ),
        Tool(
            name=uc.GET_WAITING_TIMES,
            description=(
                "Latest NHS Scotland waiting times (patients still waiting) from Public Health "
                "Scotland, for Scotland or a named real health board. Not Firth Valley figures."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "specialty": _string('e.g. "Orthopaedics", "Ophthalmology"; empty = all'),
                    "patient_type": {"type": "string", "enum": ["New Outpatient", "Inpatient"]},
                    "board": _string('A real board, e.g. "NHS Lothian"; empty = Scotland'),
                },
            },
            run=get_waiting_times,
        ),
        Tool(
            name=uc.LIST_SPECIALTIES,
            description="List the specialty names get_waiting_times recognises.",
            parameters={"type": "object", "properties": {}},
            run=list_waiting_time_specialties,
        ),
    ]


# ------------------------------------------------------------------ dispatch


class Toolbox:
    def __init__(self, tools: list[Tool], attempts: int = 2, retry_delay: float = 1.0):
        self.tools = {t.name: t for t in tools}
        self.attempts, self.retry_delay = attempts, retry_delay

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.tools.values()]

    def _run_with_retry(self, name: str, args: dict, span) -> object:
        """Tools only read data, so a failed call (timeout, busy warehouse) is retried once."""
        for attempt in range(1, self.attempts + 1):
            try:
                return self.tools[name].run(**args)
            except (TypeError, ValueError):  # wrong arguments: retrying cannot help
                raise
            except Exception:
                if attempt == self.attempts:
                    raise
                span.set_attribute("retried", True)
                time.sleep(self.retry_delay)
        raise AssertionError("unreachable")

    def run(self, name: str, arguments: str | dict) -> str:
        """Run one tool call and return JSON for the model. Errors go back to the model too."""
        with mlflow.start_span(name=name, span_type="TOOL") as span:
            try:
                args = json.loads(arguments or "{}") if isinstance(arguments, str) else arguments
                span.set_inputs(args)
                if name not in self.tools:
                    raise KeyError(f"unknown tool {name}")
                args = {k: v for k, v in (args or {}).items() if v not in (None, "")}
                result = self._run_with_retry(name, args, span)
            except Exception as exc:  # noqa: BLE001 - the model can recover from a tool error
                result = {"error": f"{type(exc).__name__}: {exc}"}
            span.set_outputs(result)
        # MCP tools already return text; our own tools return Python objects
        return result if isinstance(result, str) else json.dumps(result, default=str)
