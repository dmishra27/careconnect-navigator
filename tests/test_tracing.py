import mlflow
import pytest

from careconnect.agent import trace_report, tracing
from careconnect.config import ProjectConfig

pytestmark = pytest.mark.filterwarnings("ignore::FutureWarning")

CFG = ProjectConfig(
    env="dev",
    catalog="workspace",
    schema_name="careconnect_dev",
    experiment_name="careconnect-dev",
    llm_endpoint="databricks-llm",
    judge_endpoint="databricks-judge",
    embedding_endpoint="databricks-gte-large-en",
)


def test_prompt_hash_is_short_stable_and_changes_with_the_wording():
    a = tracing.prompt_hash("Answer from the tools.")
    assert a == tracing.prompt_hash("Answer from the tools.") and len(a) == 12
    assert a != tracing.prompt_hash("Answer from the tools!")


def test_experiment_traces_go_to_unity_catalog_tables_with_our_prefix(monkeypatch):
    calls = []
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "set_experiment", lambda name, **kw: calls.append((name, kw)))
    name = tracing.setup_agent_experiment(CFG, "me@example.com")
    assert name == "/Users/me@example.com/careconnect-dev-agent-uc-traces"
    location = calls[0][1]["trace_location"]
    assert (location.catalog_name, location.schema_name, location.table_prefix) == (
        "workspace",
        "careconnect_dev",
        "careconnect_agent",
    )
    assert tracing.trace_table(CFG) == "workspace.careconnect_dev.careconnect_agent_trace_unified"


def test_an_experiment_that_already_holds_traces_gets_a_clear_message(monkeypatch):
    def refuse(name, **kw):
        raise RuntimeError("BAD_REQUEST: Experiment 42 already contains traces. ...")

    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "set_experiment", refuse)
    with pytest.raises(RuntimeError, match="--experiment-traces"):
        tracing.setup_agent_experiment(CFG, "me")


def test_experiment_storage_remains_as_a_fallback(monkeypatch):
    calls = []
    monkeypatch.setattr(mlflow, "set_tracking_uri", lambda uri: None)
    monkeypatch.setattr(mlflow, "set_experiment", lambda name, **kw: calls.append((name, kw)))
    assert tracing.setup_agent_experiment(CFG, "me", uc=False).endswith("careconnect-dev-agent")
    assert calls[0][1] == {}


def test_tags_are_strings_none_is_dropped_and_tracing_errors_are_swallowed(monkeypatch):
    seen = {}
    monkeypatch.setattr(mlflow, "update_current_trace", lambda tags: seen.update(tags))
    tracing.tag_current_trace({"steps": 2, "guard": None, "backend": "mcp"})
    assert seen == {"steps": "2", "backend": "mcp"}

    def broken(tags):
        raise RuntimeError("no active trace")

    monkeypatch.setattr(mlflow, "update_current_trace", broken)
    tracing.tag_current_trace({"steps": 1})  # must not raise


def test_report_queries_read_the_unified_table_and_parameterise_the_run():
    table = tracing.trace_table(CFG)
    queries = trace_report.build_queries(table)
    assert set(queries) == {"runs", "outcome", "tools", "slowest", "prompts"}
    assert all(table in q for q in queries.values())
    assert "LATERAL VIEW explode(t.spans)" in queries["tools"]
    assert "= 'TOOL'" in queries["tools"] and "retried" in queries["tools"]
    assert ":eval_run" not in queries["runs"]
    filtered = trace_report.build_queries(table, "mcp-20261017-101500")
    assert all(":eval_run" in q for q in filtered.values())
    assert all("mcp-20261017-101500" not in q for q in filtered.values())  # never pasted in


def test_format_table_aligns_columns_and_handles_no_rows():
    out = trace_report.format_table(["tool", "calls"], [["find_clinic", "4"], ["x", None]])
    assert out.splitlines()[0].split() == ["tool", "calls"]
    assert "find_clinic  4" in out
    assert trace_report.format_table(["a"], []) == "   (no rows)"
