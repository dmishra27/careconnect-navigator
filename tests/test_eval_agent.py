from pathlib import Path

import pytest

from careconnect.agent.guardrails import urgent_category
from careconnect.evals.agent import Case, load_cases, score_case, summarise

ROOT = Path(__file__).resolve().parents[1]
CASES = load_cases(ROOT / "data" / "eval" / "agent_questions.yml")


def test_case_ids_are_unique_and_every_case_checks_something():
    assert len(CASES) >= 25
    assert len({c.id for c in CASES}) == len(CASES)
    assert all(c.include or c.exclude or c.tools is not None for c in CASES)


@pytest.mark.parametrize("case", CASES, ids=[c.id for c in CASES])
def test_the_safety_guard_agrees_with_every_label(case):
    # urgent cases must trigger the guard and look-alikes must not, before any model call
    assert urgent_category(case.question) == case.guard


def test_a_correct_answer_passes():
    case = Case("x", "facts", "?", tools=["find_clinic"], include=["Larbank|Inverbrae"],
                exclude=["twice"])  # fmt: skip
    row = score_case(case, "Go to Larbank Health Centre.", ["find_clinic"], None)
    assert row["passed"] and row["facts_found"] == 1


def test_out_of_scope_label_accepts_a_plain_admission_but_not_an_invented_answer():
    o02 = next(c for c in CASES if c.id == "o02")
    honest = "I don't have information about a Tesco in Larbank."  # seen 15 Oct, a fair answer
    invented = "I don't have information on that, but Tesco is open until 10pm."
    assert score_case(o02, honest, ["find_clinic"], None)["passed"]
    assert not score_case(o02, invented, ["find_clinic"], None)["passed"]


def test_every_case_is_run_with_its_trace_tags():
    from types import SimpleNamespace as NS

    from careconnect.evals.agent import run_cases

    class FakeAgent:
        def __init__(self):
            self.tags = []

        def run(self, question, tags=None):
            self.tags.append(tags)
            return NS(answer="Larbank Health Centre", tool_calls=[], guard=None, steps=1)

    agent = FakeAgent()
    case = Case("a03", "clinics", "blood test?", include=["Larbank"])
    rows = run_cases(agent, [case], eval_run="mcp-20261017-101500")
    assert rows[0]["passed"]
    assert agent.tags == [
        {"case_id": "a03", "category": "clinics", "eval_run": "mcp-20261017-101500"}
    ]


def test_each_kind_of_failure_is_reported():
    case = Case("x", "facts", "?", tools=["search_guidance"], include=["once"], exclude=["twice"])
    row = score_case(case, "You can change it twice.", [], "emergency")
    assert not row["passed"]
    for reason in ("tools:", "guard:", "missing: once", "forbidden: twice"):
        assert reason in row["failures"]


def test_urgent_cases_must_not_call_tools():
    case = Case("s", "safety_urgent", "?", tools=[], guard="emergency", include=["999"])
    assert score_case(case, "Call 999 now.", [], "emergency")["passed"]
    assert not score_case(case, "Call 999 now.", ["search_guidance"], "emergency")["passed"]


def test_no_grounding_guard_is_not_counted_as_an_urgent_alarm():
    case = Case("o", "out_of_scope", "?", include=["GP"])
    assert score_case(case, "Speak to your GP.", [], "no_grounding")["guard_ok"]


def test_summary_metrics():
    rows = [
        score_case(Case("a", "facts", "?", tools=["t"], include=["x"]), "x", ["t"], None),
        score_case(Case("b", "facts", "?", tools=["t"], include=["y"]), "no", [], None),
        score_case(
            Case("s", "safety_urgent", "?", tools=[], guard="emergency"), "999", [], "emergency"
        ),  # fmt: skip
    ]
    m = summarise(rows)
    assert m["pass_rate"] == pytest.approx(2 / 3)
    assert m["tool_accuracy"] == pytest.approx(2 / 3)
    assert m["urgent_recall"] == 1.0 and m["false_alarm_rate"] == 0.0
    assert m["pass_rate_facts"] == 0.5


def test_each_row_records_failed_and_retried_tool_calls():
    import json as _json
    from types import SimpleNamespace as NS

    from careconnect.evals.agent import run_cases, tool_failed

    assert tool_failed(_json.dumps({"error": "TimeoutError: no answer"}))
    assert not tool_failed(_json.dumps({"source": "PHS", "rows": []}))  # empty is not an error
    assert not tool_failed("Larbank Health Centre")

    class FakeAgent:
        toolbox = NS(retries=0)

        def run(self, question, tags=None):
            self.toolbox.retries += 1  # one call needed the retry
            calls = [NS(name="find_clinic", result=_json.dumps({"error": "ReadTimeout"}))]
            return NS(answer="I could not find an answer", tool_calls=calls, guard=None, steps=2)

    rows = run_cases(FakeAgent(), [Case("a03", "clinics", "?", include=["Larbank"])])
    assert (rows[0]["tool_errors"], rows[0]["tool_retries"]) == (1, 1)
    metrics = summarise(rows)
    assert (metrics["tool_errors"], metrics["tool_retries"]) == (1, 1)
