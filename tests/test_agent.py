import json
from types import SimpleNamespace as NS

import mlflow
import pytest

from careconnect.agent.loop import FALLBACK, Agent
from careconnect.agent.tools import SqlRunner, Toolbox, make_search_tool, make_uc_tools
from careconnect.config import ProjectConfig
from careconnect.search.retriever import Hit

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


@pytest.fixture(autouse=True)
def no_tracing(tmp_path, monkeypatch):
    # keep MLflow off Databricks and out of the repo; tracing itself is not under test
    monkeypatch.setenv("MLFLOW_TRACKING_URI", tmp_path.as_uri())
    mlflow.set_tracking_uri(tmp_path.as_uri())
    mlflow.tracing.disable()
    yield
    mlflow.tracing.enable()


def _tool_call(name, args, call_id="c1"):
    return NS(id=call_id, function=NS(name=name, arguments=json.dumps(args)))


class FakeClient:
    """Replays scripted model replies and records what the agent sent."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kwargs):
        self.sent.append(kwargs)
        reply = self.replies.pop(0)
        return NS(choices=[NS(message=reply)])


class FakeRunner:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def call(self, function, args):
        self.calls.append((function, args))
        return [dict(r) for r in self.rows]


def _toolbox(runner=None):
    return Toolbox(make_uc_tools(CFG, runner or FakeRunner([{"name": "Larbank Health Centre"}])))


def test_answer_without_any_tool_call_is_replaced_by_the_out_of_scope_message():
    from careconnect.agent.guardrails import OUT_OF_SCOPE

    client = FakeClient([NS(content="Ibuprofen is best.", tool_calls=None)])
    result = Agent(client, "m", _toolbox()).run("best painkiller?")
    assert result.answer == OUT_OF_SCOPE  # never an answer from the model's memory
    assert result.guard == "no_grounding" and result.steps == 1
    assert client.sent[0]["messages"][0]["role"] == "system"
    assert {t["function"]["name"] for t in client.sent[0]["tools"]} >= {"find_clinic"}


def test_urgent_symptoms_are_answered_without_calling_the_model():
    client = FakeClient([])  # any model call would fail: there are no scripted replies
    result = Agent(client, "m", _toolbox()).run("My husband has chest pain and can't breathe")
    assert result.stopped == "urgent" and result.guard == "emergency"
    assert "999" in result.answer and not client.sent


def test_answer_after_only_failed_tool_calls_is_replaced():
    from careconnect.agent.guardrails import OUT_OF_SCOPE

    client = FakeClient(
        [
            NS(content=None, tool_calls=[_tool_call("no_such_tool", {})]),
            NS(content="Made-up answer.", tool_calls=None),
        ]
    )
    assert Agent(client, "m", _toolbox()).run("?").answer == OUT_OF_SCOPE


def test_agent_runs_the_requested_tool_and_feeds_the_result_back():
    runner = FakeRunner([{"name": "Larbank Health Centre"}])
    client = FakeClient(
        [
            NS(content=None, tool_calls=[_tool_call("find_clinic", {"service": "blood tests"})]),
            NS(content="Larbank Health Centre.", tool_calls=None),
        ]
    )
    result = Agent(client, "m", _toolbox(runner)).run("blood tests?")
    assert result.answer == "Larbank Health Centre."
    assert [c.name for c in result.tool_calls] == ["find_clinic"]
    assert runner.calls == [
        ("workspace.careconnect_dev.find_clinic", {"service": "blood tests", "town": None})
    ]
    second_turn = client.sent[1]["messages"]
    assert second_turn[-2]["tool_calls"][0]["function"]["name"] == "find_clinic"
    assert second_turn[-1] == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": json.dumps([{"name": "Larbank Health Centre"}]),
    }


def test_tool_errors_go_back_to_the_model_instead_of_crashing():
    client = FakeClient(
        [
            NS(content=None, tool_calls=[_tool_call("no_such_tool", {})]),
            NS(content=None, tool_calls=[_tool_call("find_clinic", {})]),
            NS(content="Larbank.", tool_calls=None),
        ]
    )
    result = Agent(client, "m", _toolbox()).run("?")
    assert "error" in json.loads(result.tool_calls[0].result)
    assert result.answer == "Larbank."  # recovered with a second, successful call


def test_agent_stops_after_max_steps():
    loop_forever = [NS(content=None, tool_calls=[_tool_call("find_clinic", {})])] * 3
    result = Agent(FakeClient(loop_forever), "m", _toolbox(), max_steps=3).run("?")
    assert result.stopped == "max_steps"
    assert result.answer == FALLBACK
    assert len(result.tool_calls) == 3


def test_waiting_times_states_its_source_once():
    rows = [{"board": "Scotland", "source": "PHS"}, {"board": "Scotland", "source": "PHS"}]
    out = json.loads(_toolbox(FakeRunner(rows)).run("get_waiting_times", "{}"))
    assert out["source"] == "PHS"
    assert all("source" not in r for r in out["rows"])


def test_search_tool_returns_citable_passages():
    hit = Hit("c", "fvhb-16", "Making a complaint", "Making a complaint > Time limits", None,
              "leaflet", "Making a complaint > Time limits\n\nWithin 6 months.", 0.9)  # fmt: skip
    retriever = NS(search=lambda q, k, f: [hit])
    out = make_search_tool(retriever).run("deadline")
    assert out == [
        {
            "title": "Making a complaint",
            "section": "Time limits",
            "page": None,
            "source_type": "leaflet",
            "text": "Within 6 months.",
        }
    ]


def test_sql_runner_passes_empty_arguments_as_null():
    from databricks.sdk.service.sql import StatementState

    sent = {}

    def execute_statement(**kwargs):
        sent.update(kwargs)
        return NS(
            status=NS(state=StatementState.SUCCEEDED),
            manifest=NS(schema=NS(columns=[NS(name="name")])),
            result=NS(data_array=[["Larbank Health Centre"]]),
        )

    w = NS(statement_execution=NS(execute_statement=execute_statement))
    rows = SqlRunner(w, warehouse_id="wh").call(
        "cat.sch.find_clinic", {"service": "x", "town": None}
    )
    assert rows == [{"name": "Larbank Health Centre"}]
    assert sent["statement"] == "SELECT * FROM cat.sch.find_clinic(:service, :town)"
    assert sent["parameters"][0].value == "x"
    assert sent["parameters"][1].value is None


def test_prompt_sets_the_waiting_time_rules():
    from careconnect.agent.prompts import SYSTEM_PROMPT

    for rule in (
        "so far",
        "not Firth Valley",
        "Treatment Time Guarantee",
        "30 June 2026",
        "12 weeks = 84 days",
        "ONLY with a wait the person has told you",
        'source_type "leaflet"',
        "Never present a partial match",
        "search for each part separately",  # m02: multi-part answers
        "Complaints Team phone number",  # m02
        "only reviews a complaint after stage 2",  # a16: PASS, not SPSO
        "Before saying a document does not cover something",  # a13: false absence
    ):
        assert rule in SYSTEM_PROMPT
