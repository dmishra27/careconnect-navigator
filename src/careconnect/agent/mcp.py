"""A small MCP client for Databricks' managed MCP servers, and tools built from it.

MCP (Model Context Protocol) over HTTP is JSON-RPC: the client says `initialize`, then asks
`tools/list` (each tool's name, description and JSON input schema) and `tools/call`.
The agent never hard-codes these tools: names, descriptions and argument schemas all come
from the server, so a function added to Unity Catalog appears in the agent with no code
change.

Servers used here (both found working by scripts/check_week3.py):
  UC functions   https://<workspace>/api/2.0/mcp/functions/<catalog>/<schema>
  Vector Search  https://<workspace>/api/2.0/mcp/vector-search/<catalog>/<schema>
"""

import json
from itertools import count

import requests

from careconnect.agent.tools import Tool
from careconnect.config import ProjectConfig

PROTOCOL_VERSION = "2025-06-18"


class McpError(RuntimeError):
    pass


class McpClient:
    def __init__(self, url: str, w, session=None, timeout_s: int = 45):
        self.url, self.w, self.timeout_s = url, w, timeout_s
        self.http = session or requests.Session()
        self.session_id: str | None = None
        self._ids = count(1)
        self._initialised = False

    # ------------------------------------------------------------- transport
    def _headers(self) -> dict:
        headers = {
            **self.w.config.authenticate(),  # fresh token each call
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    @staticmethod
    def _parse(resp) -> dict:
        """Responses come as plain JSON or as a server-sent event stream."""
        if "text/event-stream" in resp.headers.get("Content-Type", ""):
            for line in resp.text.splitlines():
                if line.startswith("data:"):
                    return json.loads(line[5:])
            return {}
        return resp.json() if resp.text else {}

    def _post(self, payload: dict) -> dict:
        resp = self.http.post(
            self.url, headers=self._headers(), json=payload, timeout=self.timeout_s
        )
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code} from {self.url}: {resp.text[:200]}")
        if resp.headers.get("Mcp-Session-Id"):
            self.session_id = resp.headers["Mcp-Session-Id"]
        return self._parse(resp)

    def _request(self, method: str, params: dict | None = None) -> dict:
        self._ensure_initialised()
        return self._rpc(method, params)

    def _rpc(self, method: str, params: dict | None = None) -> dict:
        body = self._post({"jsonrpc": "2.0", "id": next(self._ids), "method": method,
                           "params": params or {}})  # fmt: skip
        if "error" in body:
            raise McpError(f"{method}: {body['error']}")
        return body.get("result", {})

    def _ensure_initialised(self) -> None:
        if self._initialised:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "careconnect-navigator", "version": "0.1"},
            },
        )
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialised = True

    # ------------------------------------------------------------- protocol
    def list_tools(self) -> list[dict]:
        return self._request("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._request("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(
            part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"
        )
        if result.get("isError"):
            raise McpError(text or f"{name} failed")
        return text


def uc_functions_url(cfg: ProjectConfig, host: str) -> str:
    return f"{host.rstrip('/')}/api/2.0/mcp/functions/{cfg.catalog}/{cfg.schema_name}"


def vector_search_url(cfg: ProjectConfig, host: str) -> str:
    return f"{host.rstrip('/')}/api/2.0/mcp/vector-search/{cfg.catalog}/{cfg.schema_name}"


def short_name(mcp_name: str) -> str:
    """workspace__careconnect_dev__find_clinic -> find_clinic (what the model sees)."""
    return mcp_name.split("__")[-1]


def mcp_tools(client: McpClient, include: set[str] | None = None, rename: dict | None = None):
    """Build agent tools from whatever the MCP server lists.

    include: short names to keep (others are skipped, e.g. throwaway test functions).
    rename:  short name -> name the model should see (e.g. the index -> search_guidance).
    """
    rename = rename or {}
    tools = []
    for spec in client.list_tools():
        full = spec["name"]
        name = short_name(full)
        if include is not None and name not in include:
            continue

        def run(_full=full, **kwargs):
            return client.call_tool(_full, kwargs)

        tools.append(
            Tool(
                name=rename.get(name, name),
                description=spec.get("description") or name,
                parameters=spec.get("inputSchema") or {"type": "object", "properties": {}},
                run=run,
            )
        )
    return tools
