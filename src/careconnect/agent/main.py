"""Ask the agent a question from the command line. Each question is one MLflow trace.

  uv run agent "Where can I get a blood test in Larbank?"
  uv run agent --demo                 # five questions covering every tool
  uv run agent --model databricks-qwen3-next-80b-a3b-instruct "..."

Traces go to the MLflow experiment <experiment_name>-agent (e.g. careconnect-dev-agent).
"""

import argparse
import json
import warnings

import mlflow
from databricks.sdk import WorkspaceClient

from careconnect.agent.loop import Agent
from careconnect.agent.tools import SqlRunner, Toolbox, make_search_tool, make_uc_tools
from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config
from careconnect.search.retriever import Retriever

DEMO_QUESTIONS = [
    "Can I change my hospital appointment more than once?",
    "Where can I get a blood test in Larbank, and when is it open?",
    "How long are people waiting for a first orthopaedics appointment in Scotland?",
    "How long is the wait for ENT outpatients in NHS Lothian?",
    "I have been waiting 4 months for my knee operation. How long should I wait, and how do "
    "I complain?",
]


def build_agent(cfg: ProjectConfig, model: str | None = None) -> Agent:
    w = WorkspaceClient()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        client = w.serving_endpoints.get_open_ai_client()
    toolbox = Toolbox([make_search_tool(Retriever(cfg, w)), *make_uc_tools(cfg, SqlRunner(w))])
    return Agent(client, model or cfg.llm_endpoint, toolbox)


def _short(text: str, n: int = 110) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= n else text[: n - 3] + "..."


def ask(agent: Agent, question: str) -> None:
    print(f"\nQ: {question}")
    result = agent.run(question)
    for i, call in enumerate(result.tool_calls, 1):
        args = json.loads(call.arguments or "{}")
        print(f"   tool {i}: {call.name}({json.dumps(args)}) -> {_short(call.result, 80)}")
    print(f"   steps: {result.steps} ({result.stopped})")
    print(f"A: {result.answer}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ask CareConnect Navigator")
    parser.add_argument("question", nargs="?")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--model", default=None, help="serving endpoint (default: config)")
    parser.add_argument("--demo", action="store_true", help="run the five demo questions")
    args = parser.parse_args(argv)
    if not args.question and not args.demo:
        parser.error("give a question or --demo")

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    w = WorkspaceClient()
    mlflow.set_tracking_uri("databricks")
    mlflow.set_experiment(f"/Users/{w.current_user.me().user_name}/{cfg.agent_experiment_name}")
    mlflow.openai.autolog()

    agent = build_agent(cfg, args.model)
    print(f"model: {agent.model}   tools: {', '.join(agent.toolbox.tools)}")
    for q in DEMO_QUESTIONS if args.demo else [args.question]:
        ask(agent, q)
    print(f"\nTraces: MLflow experiment {cfg.agent_experiment_name}")


if __name__ == "__main__":
    main()
