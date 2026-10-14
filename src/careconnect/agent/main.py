"""Ask the agent a question from the command line. Each question is one MLflow trace.

  uv run agent "Where can I get a blood test in Larbank?"
  uv run agent --demo                 # five questions covering every tool
  uv run agent --model databricks-qwen3-next-80b-a3b-instruct "..."
  uv run agent --demo --tools mcp         # UC tools through Databricks' MCP server
  uv run agent --demo --tools mcp-search  # search through the Vector Search MCP too
  uv run agent --list-tools --tools mcp   # show exactly what the model is given

Tool backends:
  direct      our search + UC functions run through the SQL warehouse (default)
  mcp         our search + UC functions discovered and called over MCP
  mcp-search  everything over MCP, including Databricks' Vector Search MCP for search
              (note: that server cannot apply our "current documents only" filter)

Traces go to the MLflow experiment <experiment_name>-agent (e.g. careconnect-dev-agent).
"""

import argparse
import json
import time
import warnings

import mlflow
from databricks.sdk import WorkspaceClient

from careconnect.agent.loop import Agent
from careconnect.agent.mcp import McpClient, mcp_tools, uc_functions_url, vector_search_url
from careconnect.agent.tools import SqlRunner, Toolbox, make_search_tool, make_uc_tools
from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config
from careconnect.search.retriever import Retriever
from careconnect.tools import sql as uc

BACKENDS = ("direct", "mcp", "mcp-search")

DEMO_QUESTIONS = [
    "Can I change my hospital appointment more than once?",
    "Where can I get a blood test in Larbank, and when is it open?",
    "How long are people waiting for a first orthopaedics appointment in Scotland?",
    "How long is the wait for ENT outpatients in NHS Lothian?",
    "I have been waiting 4 months for my knee operation. How long should I wait, and how do "
    "I complain?",
]


def build_tools(cfg: ProjectConfig, w, backend: str = "direct") -> list:
    if backend == "direct":
        return [make_search_tool(Retriever(cfg, w)), *make_uc_tools(cfg, SqlRunner(w))]
    uc_mcp = McpClient(uc_functions_url(cfg, w.config.host), w)
    tools = mcp_tools(uc_mcp, include=set(uc.FUNCTIONS))
    if backend == "mcp":
        return [make_search_tool(Retriever(cfg, w)), *tools]
    vs_mcp = McpClient(vector_search_url(cfg, w.config.host), w)
    index = cfg.chunks_index.split(".")[-1]
    return [*mcp_tools(vs_mcp, include={index}, rename={index: "search_guidance"}), *tools]


def build_agent(cfg: ProjectConfig, model: str | None = None, backend: str = "direct") -> Agent:
    w = WorkspaceClient()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client = w.serving_endpoints.get_open_ai_client()
    return Agent(client, model or cfg.llm_endpoint, Toolbox(build_tools(cfg, w, backend)))


def _short(text: str, n: int = 110) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 3] + "..."


def _rows(data) -> list[dict] | None:
    """Rows as dicts, from our tools ({"rows": [{...}]}) or the UC MCP server
    ({"columns": [...], "rows": [[...]]})."""
    if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
        return None
    rows, cols = data["rows"], data.get("columns")
    if cols and rows and isinstance(rows[0], list):
        names = [c.get("name") if isinstance(c, dict) else c for c in cols]
        return [dict(zip(names, r, strict=False)) for r in rows]
    return [r for r in rows if isinstance(r, dict)]


def _preview(result: str) -> str:
    """Show what a tool returned: for waiting times, which board and specialty each row is.

    Display only: never let a format we did not expect stop the demo.
    """
    try:
        data = json.loads(result)
    except (json.JSONDecodeError, TypeError):
        return _short(str(result), 80)
    try:
        rows = _rows(data)
        if rows is not None and rows and "specialty" in rows[0]:
            labels = [
                f"{r.get('board')} / {r.get('specialty')} / {r.get('patient_type')}" for r in rows
            ]
            return f"{len(rows)} row(s): " + "; ".join(labels)
        if rows is not None:
            return f"{len(rows)} row(s): " + _short(json.dumps(rows), 80)
        if isinstance(data, list):
            return f"{len(data)} result(s): " + _short(json.dumps(data), 80)
    except Exception:  # noqa: BLE001 - display only
        pass
    return _short(result, 80)


def ask(agent: Agent, question: str) -> None:
    print(f"\nQ: {question}")
    start = time.perf_counter()
    result = agent.run(question)
    elapsed = time.perf_counter() - start
    for i, call in enumerate(result.tool_calls, 1):
        args = json.loads(call.arguments or "{}")
        print(f"   tool {i}: {call.name}({json.dumps(args)}) -> {_preview(call.result)}")
    print(f"   steps: {result.steps} ({result.stopped}), {elapsed:.1f}s")
    print(f"A: {result.answer}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ask CareConnect Navigator")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--model", default=None, help="serving endpoint (default: config)")
    parser.add_argument("--demo", action="store_true", help="run the five demo questions")
    parser.add_argument("--tools", choices=BACKENDS, default="direct", help="tool backend")
    parser.add_argument("--list-tools", action="store_true", help="print the tools and exit")
    args = parser.parse_args(argv)
    if not (args.question or args.demo or args.list_tools):
        parser.error("give a question, --demo or --list-tools")

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    w = WorkspaceClient()
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(f"/Users/{w.current_user.me().user_name}/{cfg.agent_experiment_name}")
    mlflow.openai.autolog()

    agent = build_agent(cfg, args.model, args.tools)
    print(f"model: {agent.model}   backend: {args.tools}   tools: {', '.join(agent.toolbox.tools)}")
    if args.list_tools:
        for tool in agent.toolbox.tools.values():
            params = ", ".join(tool.parameters.get("properties", {})) or "none"
            print(f"\n{tool.name}({params})\n   {_short(tool.description, 300)}")
        return
    for q in DEMO_QUESTIONS if args.demo else [args.question]:
        ask(agent, q)
    print(f"\nTraces: MLflow experiment {cfg.agent_experiment_name}")


if __name__ == "__main__":
    main()
