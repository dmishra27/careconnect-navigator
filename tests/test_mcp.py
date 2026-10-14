import json
from types import SimpleNamespace as NS

import mlflow
import pytest

from careconnect.agent.mcp import McpClient, McpError, mcp_tools, short_name, uc_functions_url
from careconnect.agent.tools import Toolbox
from careconnect.config import ProjectConfig

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")  # MLflow file store

CFG = ProjectConfig(
    env="dev",
    catalog="workspace",
    schema_name="careconnect_dev",
    experiment_name="careconnect-dev",
    llm_endpoint="databricks-llm",
    judge_endpoint="databricks-judge",
    embedding_endpoint="databricks-gte-large-en",
)
W = NS(config=NS(authenticate=lambda: {"Authorization": "Bearer t"}, host="https://h"))
TOOLS = [
    {
        "name": "workspace__careconnect_dev__find_clinic",
        "description": "Find clinics",
        "inputSchema": {"type": "object", "properties": {"service": {"type": "string"}}},
    },
    {"name": "workspace__careconnect_dev__careconnect_step0_ping", "description": "test"},
]


@pytest.fixture(autouse=True)
def no_tracing(tmp_path, monkeypatch):
    monkeypatch.setenv("MLFLOW_TRACKING_URI", tmp_path.as_uri())
    mlflow.set_tracking_uri(tmp_path.as_uri())
    mlflow.tracing.disable()
    yield
    mlflow.tracing.enable()


class FakeServer:
    """Speaks just enough MCP over HTTP; answers the first call as an SSE stream."""

    def __init__(self, call_result=None):
        self.requests = []
        self.call_result = call_result or {"content": [{"type": "text", "text": "Larbank"}]}

    def post(self, url, headers, json, timeout):  # noqa: A002 - mirrors requests.post
        self.requests.append((json.get("method"), headers.get("Mcp-Session-Id"), json))
        method = json.get("method")
        if method == "initialize":
            body = {"jsonrpc": "2.0", "id": json["id"], "result": {"protocolVersion": "x"}}
            text = "event: message\ndata: " + _dumps(body)
            sse = {"Content-Type": "text/event-stream", "Mcp-Session-Id": "s1"}
            return NS(status_code=200, text=text, headers=sse)
        if method == "notifications/initialized":
            return NS(status_code=202, text="", headers={})
        result = {"tools": TOOLS} if method == "tools/list" else self.call_result
        body = {"jsonrpc": "2.0", "id": json["id"], "result": result}
        return NS(status_code=200, text=_dumps(body), headers={"Content-Type": "application/json"},
                  json=lambda: body)  # fmt: skip


def _dumps(obj):
    return json.dumps(obj)


def test_client_initialises_once_and_reuses_the_session():
    server = FakeServer()
    client = McpClient("https://h/mcp", W, session=server)
    client.list_tools()
    client.call_tool("workspace__careconnect_dev__find_clinic", {"service": "x"})
    methods = [m for m, _, _ in server.requests]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert [sid for _, sid, _ in server.requests][2:] == ["s1", "s1"]  # session id sent back


def test_tool_call_returns_the_text_content():
    client = McpClient("https://h/mcp", W, session=FakeServer())
    assert client.call_tool("t", {}) == "Larbank"


def test_tool_errors_from_the_server_raise():
    bad = FakeServer({"isError": True, "content": [{"type": "text", "text": "no such function"}]})
    with pytest.raises(McpError, match="no such function"):
        McpClient("https://h/mcp", W, session=bad).call_tool("t", {})


def test_tools_are_built_from_what_the_server_lists():
    client = McpClient("https://h/mcp", W, session=FakeServer())
    tools = mcp_tools(client, include={"find_clinic"})
    assert [t.name for t in tools] == ["find_clinic"]  # test function skipped
    assert tools[0].description == "Find clinics"
    assert tools[0].parameters["properties"] == {"service": {"type": "string"}}


def test_toolbox_passes_mcp_text_through_unchanged():
    client = McpClient("https://h/mcp", W, session=FakeServer())
    toolbox = Toolbox(mcp_tools(client, include={"find_clinic"}, rename={"find_clinic": "clinics"}))
    assert toolbox.run("clinics", '{"service": "blood tests"}') == "Larbank"


def test_names_and_urls():
    assert short_name("workspace__careconnect_dev__find_clinic") == "find_clinic"
    assert uc_functions_url(CFG, "https://h/") == (
        "https://h/api/2.0/mcp/functions/workspace/careconnect_dev"
    )


def test_demo_preview_reads_both_result_shapes():
    from careconnect.agent.main import _preview

    ours = {
        "source": "PHS",
        "rows": [{"board": "Scotland", "specialty": "ENT", "patient_type": "X"}],
    }
    mcp = {"columns": ["board", "specialty", "patient_type"], "rows": [["NHS Lothian", "ENT", "X"]]}
    clinics = {"columns": [{"name": "name"}], "rows": [["Larbank Health Centre"]]}
    assert _preview(json.dumps(ours)) == "1 row(s): Scotland / ENT / X"
    assert _preview(json.dumps(mcp)) == "1 row(s): NHS Lothian / ENT / X"
    assert _preview(json.dumps(clinics)).startswith("1 row(s): ")
    assert _preview("plain text, not JSON") == "plain text, not JSON"


def test_default_agent_backend_is_uc_tools_over_mcp_with_our_own_search():
    assert CFG.agent_tool_backend == "mcp"  # never "mcp-search": it lacks the current-only filter
