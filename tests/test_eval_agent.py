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
