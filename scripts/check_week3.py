"""Week 3, Step 0: what does this workspace support for tools, MCP and agents?

Runs five read-mostly checks and prints a summary table. The only thing it creates is a
throwaway Unity Catalog function (`careconnect_step0_ping`), which it drops at the end.

  uv run python scripts/check_week3.py

Checks:
  1. Chat model endpoints available in the workspace
  2. Tool calling: does each candidate model return a structured tool call?
  3. Unity Catalog functions: can we create and call SQL and Python functions?
  4. Databricks managed MCP servers: do the endpoints answer, and what tools do they list?
  5. Databricks Apps: can apps be listed (needed to host our own MCP server later)?
"""

import json
from pathlib import Path

import requests
from databricks.sdk import WorkspaceClient

from careconnect.config import ProjectConfig

ROOT = Path(__file__).resolve().parents[1]
cfg = ProjectConfig.from_yaml(ROOT / "project_config.yml", env="dev")
w = WorkspaceClient()
host = w.config.host.rstrip("/")
summary: list[tuple[str, str, str]] = []  # (check, result, detail)

# ---------------------------------------------------------------- 1. chat endpoints
print("\n1. Chat model endpoints")
chat_endpoints = []
try:
    for ep in w.serving_endpoints.list():
        if (ep.task or "") == "llm/v1/chat":
            chat_endpoints.append(ep.name)
    for name in sorted(chat_endpoints):
        print(f"   {name}")
    summary.append(("Chat endpoints", f"{len(chat_endpoints)} found", ""))
except Exception as exc:  # noqa: BLE001 - report and carry on
    summary.append(("Chat endpoints", "ERROR", str(exc)[:120]))

# ---------------------------------------------------------------- 2. tool calling
print("\n2. Tool calling")
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_waiting_times",
            "description": "Latest published waiting times for a hospital specialty in Scotland.",
            "parameters": {
                "type": "object",
                "properties": {
                    "specialty": {"type": "string", "description": "e.g. Orthopaedics"},
                    "patient_type": {"type": "string", "enum": ["New Outpatient", "Inpatient"]},
                },
                "required": ["specialty"],
            },
        },
    }
]
QUESTION = "How long is the wait for a first orthopaedics outpatient appointment in Scotland?"
candidates = [cfg.llm_endpoint, cfg.judge_endpoint] + [
    n for n in chat_endpoints if "qwen" in n and n not in (cfg.llm_endpoint, cfg.judge_endpoint)
]
client = w.serving_endpoints.get_open_ai_client()
for model in candidates:
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": QUESTION}],
            tools=TOOLS,
            max_tokens=200,
        )
        msg = resp.choices[0].message
        if msg.tool_calls:
            call = msg.tool_calls[0].function
            print(f"   {model}: tool call {call.name}({call.arguments})")
            summary.append((f"Tool calling: {model}", "YES", f"{call.name}({call.arguments})"))
        else:
            text = (msg.content or "").replace("\n", " ")[:100]
            print(f"   {model}: answered in text, no tool call: {text}")
            summary.append((f"Tool calling: {model}", "NO", "answered in text"))
    except Exception as exc:  # noqa: BLE001
        print(f"   {model}: ERROR {exc}")
        summary.append((f"Tool calling: {model}", "ERROR", str(exc)[:120]))

# ---------------------------------------------------------------- 3. UC functions
print("\n3. Unity Catalog functions")
fn = f"{cfg.catalog}.{cfg.schema_name}.careconnect_step0_ping"
spark = None
try:
    from databricks.connect import DatabricksSession

    spark = DatabricksSession.builder.serverless(True).getOrCreate()
    spark.sql(
        f"CREATE OR REPLACE FUNCTION {fn}(name STRING) RETURNS STRING "
        "COMMENT 'Week 3 step 0 test function; safe to drop' "
        "RETURN concat('hello ', name)"
    )
    out = spark.sql(f"SELECT {fn}('sql') AS r").collect()[0]["r"]
    print(f"   SQL function: {out}")
    summary.append(("UC SQL function", "YES", out))
except Exception as exc:  # noqa: BLE001
    print(f"   SQL function: ERROR {exc}")
    summary.append(("UC SQL function", "ERROR", str(exc)[:120]))

fn_py = fn + "_py"
if spark is not None:
    try:
        spark.sql(
            f"CREATE OR REPLACE FUNCTION {fn_py}(name STRING) RETURNS STRING "
            "LANGUAGE PYTHON COMMENT 'Week 3 step 0 test function; safe to drop' "
            "AS $$ return 'hello ' + name $$"
        )
        out = spark.sql(f"SELECT {fn_py}('python') AS r").collect()[0]["r"]
        print(f"   Python function: {out}")
        summary.append(("UC Python function", "YES", out))
    except Exception as exc:  # noqa: BLE001
        print(f"   Python function: ERROR {exc}")
        summary.append(("UC Python function", "ERROR", str(exc)[:120]))

# ---------------------------------------------------------------- 4. managed MCP
print("\n4. Databricks managed MCP servers")
MCP_URLS = {
    "UC functions MCP": f"{host}/api/2.0/mcp/functions/{cfg.catalog}/{cfg.schema_name}",
    "Vector Search MCP": f"{host}/api/2.0/mcp/vector-search/{cfg.catalog}/{cfg.schema_name}",
    "system.ai dbsql MCP": f"{host}/ai-gateway/mcp-services/dbsql",
}
INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "careconnect-step0", "version": "0.1"},
    },
}


def _rpc_json(resp: requests.Response) -> dict:
    """MCP over HTTP may answer as plain JSON or as a server-sent event stream."""
    if "text/event-stream" in resp.headers.get("Content-Type", ""):
        for line in resp.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:])
        return {}
    return resp.json()


for label, url in MCP_URLS.items():
    headers = {
        **w.config.authenticate(),
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    try:
        r = requests.post(url, headers=headers, json=INIT, timeout=60)
        if r.status_code != 200:
            detail = r.text.replace("\n", " ")[:120]
            print(f"   {label}: HTTP {r.status_code} {detail}")
            summary.append((label, f"HTTP {r.status_code}", detail))
            continue
        session = r.headers.get("Mcp-Session-Id")
        if session:
            headers["Mcp-Session-Id"] = session
        requests.post(
            url,
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
            timeout=60,
        )
        r2 = requests.post(
            url,
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            timeout=60,
        )
        tools = [t["name"] for t in _rpc_json(r2).get("result", {}).get("tools", [])]
        print(f"   {label}: available, tools = {tools}")
        summary.append((label, "YES", ", ".join(tools) or "no tools listed"))
    except Exception as exc:  # noqa: BLE001
        print(f"   {label}: ERROR {exc}")
        summary.append((label, "ERROR", str(exc)[:120]))

# ---------------------------------------------------------------- 5. apps
print("\n5. Databricks Apps")
try:
    names = [a.name for a in w.apps.list()]
    print(f"   apps listed: {names}")
    summary.append(("Databricks Apps", "YES", f"{len(names)} existing"))
except Exception as exc:  # noqa: BLE001
    print(f"   ERROR {exc}")
    summary.append(("Databricks Apps", "ERROR", str(exc)[:120]))

# ---------------------------------------------------------------- clean up
if spark is not None:
    for name in (fn, fn_py):
        try:
            spark.sql(f"DROP FUNCTION IF EXISTS {name}")
        except Exception:  # noqa: BLE001
            pass

print("\nSummary")
print(f"{'check':<52}{'result':<12}detail")
for check, result, detail in summary:
    print(f"{check:<52}{result:<12}{detail}")
