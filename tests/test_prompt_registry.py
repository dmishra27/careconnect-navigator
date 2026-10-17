from types import SimpleNamespace as NS

import mlflow
import pytest

from careconnect.agent import prompt_registry as pr
from careconnect.agent.prompts import SYSTEM_PROMPT
from careconnect.config import ProjectConfig

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
def offline(monkeypatch):
    # never touch Databricks: the registry calls are replaced test by test
    monkeypatch.setattr(pr, "_use_unity_catalog", lambda: None)


def test_the_prompt_lives_in_our_unity_catalog_schema():
    assert CFG.agent_prompt == "workspace.careconnect_dev.careconnect_agent_prompt"
    assert pr._uri(CFG, "production").endswith("careconnect_agent_prompt@production")
    assert pr._uri(CFG, "2") == "prompts:/workspace.careconnect_dev.careconnect_agent_prompt/2"


def test_the_production_version_is_loaded_from_the_registry(monkeypatch):
    seen = []

    def load(uri, **kw):
        seen.append(uri)
        return NS(template="Use the tools.", version=3)

    monkeypatch.setattr(mlflow.genai, "load_prompt", load)
    p = pr.load_system_prompt(CFG)
    assert (p.text, p.version, p.source) == ("Use the tools.", "3", "registry")
    assert seen == ["prompts:/workspace.careconnect_dev.careconnect_agent_prompt@production"]
    assert "version 3" in p.describe()


def test_an_unreachable_registry_falls_back_to_the_prompt_in_code(monkeypatch):
    def down(uri, **kw):
        raise ConnectionError("registry down")

    monkeypatch.setattr(mlflow.genai, "load_prompt", down)
    p = pr.load_system_prompt(CFG)
    assert (p.text, p.version, p.source) == (SYSTEM_PROMPT, "code", "code")
    assert "registry down" in p.describe()
    with pytest.raises(ConnectionError):  # promotion must never compare against a fallback
        pr.load_system_prompt(CFG, "2", strict=True)


def _client(monkeypatch, versions):
    client = NS(search_prompt_versions=lambda name: NS(prompt_versions=versions))
    monkeypatch.setattr(mlflow, "MlflowClient", lambda: client)


def test_identical_wording_is_not_registered_twice(monkeypatch):
    _client(monkeypatch, [NS(version="1", template="A"), NS(version="2", template="B")])
    monkeypatch.setattr(mlflow.genai, "register_prompt", lambda **kw: pytest.fail("registered"))
    assert pr.register(CFG, "B", "again", "prompts.py") == ("2", False)


def test_new_wording_becomes_a_new_version_tagged_with_its_hash(monkeypatch):
    _client(monkeypatch, [NS(version="1", template="A")])
    sent = {}

    def register_prompt(**kw):
        sent.update(kw)
        return NS(version=2)

    monkeypatch.setattr(mlflow.genai, "register_prompt", register_prompt)
    assert pr.register(CFG, "B", "shorter answers", "prompts.py") == ("2", True)
    assert sent["name"] == CFG.agent_prompt and sent["template"] == "B"
    assert sent["tags"]["prompt_hash"] == pr.prompt_hash("B")
    assert sent["tags"]["source"] == "prompts.py" and sent["commit_message"] == "shorter answers"


def _run(pass_rate=1.0, urgent=1.0, alarms=0.0, violations=0.0, n=28):
    return {"pass_rate": pass_rate, "urgent_recall": urgent, "false_alarm_rate": alarms,
            "violation_rate": violations, "n_cases": n}  # fmt: skip


def test_a_candidate_as_good_as_production_is_promoted():
    ok, reasons = pr.decide([_run(), _run(27 / 28), _run()], [_run(), _run(), _run(27 / 28)])
    assert ok and all(not r.startswith("FAIL") for r in reasons)


@pytest.mark.parametrize(
    "candidate, failed",
    [
        ([_run(), _run(26 / 28), _run()], "pass_rate"),  # one worse run is enough to keep
        ([_run(), _run(urgent=0.75), _run()], "urgent"),  # a missed urgent case
        ([_run(alarms=1 / 24), _run(), _run()], "false_alarm_rate"),
        ([_run(violations=1 / 28), _run(), _run()], "violation_rate"),
    ],
)
def test_a_worse_candidate_is_not_promoted_and_the_reason_is_given(candidate, failed):
    ok, reasons = pr.decide([_run(), _run(27 / 28), _run()], candidate)
    assert not ok
    assert any(r.startswith("FAIL") and failed in r for r in reasons)


def test_runs_on_different_question_sets_are_not_compared():
    ok, reasons = pr.decide([_run()], [_run(n=20)])
    assert not ok and "same number of questions" in reasons[0]
    assert pr.decide([], [_run()])[0] is False


def test_production_can_only_be_set_directly_the_first_time(monkeypatch):
    monkeypatch.setattr(
        pr, "alias_version", lambda cfg, alias: "1" if alias == "production" else None
    )
    monkeypatch.setattr(pr, "register", lambda *a: pytest.fail("must refuse before registering"))
    with pytest.raises(SystemExit, match="go through `promote`"):
        pr.main(["register", "--set-production"])


def test_rollback_swaps_production_and_previous(monkeypatch):
    aliases = {"production": "2", "previous": "1"}
    monkeypatch.setattr(pr, "alias_version", lambda cfg, a: aliases.get(a))
    monkeypatch.setattr(pr, "set_alias", lambda cfg, a, v: aliases.__setitem__(a, v))
    pr.main(["rollback"])
    assert aliases == {"production": "1", "previous": "2"}
