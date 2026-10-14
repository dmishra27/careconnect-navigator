# Agent tool backend: Unity Catalog tools over MCP, our own search tool

- Date: 2026-10-14
- Status: accepted

## Context

The agent has four tools: `search_guidance` (leaflets and policy), `find_clinic`,
`get_waiting_times` and `list_waiting_time_specialties` (Unity Catalog functions). Three
ways of providing them were built (`uv run agent --tools ...`):

| Backend | Search | UC tools |
|---------|--------|----------|
| `direct` | Our retriever (AUTO query type, `status = current` filter) | Called by our code through the SQL Statement Execution API |
| `mcp` | Our retriever | Discovered (`tools/list`) and called (`tools/call`) through Databricks' UC functions MCP server |
| `mcp-search` | Databricks' Vector Search MCP server | Through the UC functions MCP server |

With MCP, tool names, descriptions and argument schemas come from Unity Catalog (the
function and parameter COMMENTs), so a new function becomes an agent tool with no code
change.

## Evidence

Same five demo questions, Llama 3.3 70B, 13 and 14 October 2026 (MLflow experiment
`careconnect-dev-agent`):

| | direct (13 Oct, run 3) | mcp (14 Oct) | mcp-search (14 Oct) |
|---|---|---|---|
| Answers meeting every rule | 4 of 5 | 4 of 5 | 3 of 5 |
| Q1 "change my appointment more than once?" | Once, 01632 960 100 (current) | Once, 01632 960 100 (current) | **"Twice", 01632 960 150, 48 hours: superseded 2024 leaflet** |
| Time per question (warm) | not measured | 4.3 to 6.5 s | 3.8 to 6.1 s |

The Vector Search MCP searches the whole index and cannot apply the `status = current`
filter or the AUTO query type, so it returned the superseded leaflet and the model
answered from it with a citation. Under `mcp-search` Q5 also cited a page number for a
leaflet, which has none (probably invented).

## Decision

Default backend is `mcp` (`agent_tool_backend` in `ProjectConfig`): Unity Catalog tools
over Databricks' MCP server, plus our own search tool. `direct` stays as a fallback that
does not depend on MCP. `mcp-search` is not used for patient answers.

## Revisit when

- The search index contains only current documents (for example, an index built from a
  current-only table), which would make the Vector Search MCP safe to test again.
- Step 6 evaluation results are available for `direct` and `mcp` on the full question set.
