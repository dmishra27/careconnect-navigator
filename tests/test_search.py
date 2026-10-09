import json
from types import SimpleNamespace as NS

from databricks.sdk.service.vectorsearch import PipelineType

from careconnect.config import ProjectConfig
from careconnect.search.index import COLUMNS_TO_SYNC, index_spec
from careconnect.search.retriever import Retriever, parse_response

CFG = ProjectConfig(
    env="dev",
    catalog="workspace",
    schema_name="careconnect_dev",
    experiment_name="/x",
    llm_endpoint="databricks-llm",
    judge_endpoint="databricks-judge",
    embedding_endpoint="databricks-gte-large-en",
)


def _response(rows):
    cols = ["chunk_id", "doc_id", "title", "section_path", "page", "source_type", "text", "score"]
    return NS(
        manifest=NS(columns=[NS(name=c) for c in cols]),
        result=NS(data_array=rows),
    )


def test_index_names_follow_the_environment_schema():
    assert CFG.chunks_index == "workspace.careconnect_dev.silver_chunks_index"
    assert CFG.search_endpoint == "careconnect-search"


def test_index_spec_uses_managed_embeddings_on_text():
    spec = index_spec(CFG)
    assert spec.source_table == "workspace.careconnect_dev.silver_chunks"
    assert spec.pipeline_type == PipelineType.TRIGGERED
    assert spec.embedding_source_columns[0].name == "text"
    assert spec.embedding_source_columns[0].embedding_model_endpoint_name == (
        "databricks-gte-large-en"
    )
    assert {"chunk_id", "status", "page", "source_type"} <= set(COLUMNS_TO_SYNC)


def test_parse_response_maps_columns_and_score():
    resp = _response(
        [["policy-x-0003", "policy-x", "Guide", "Guide > 2. Rules", 7.0, "policy", "T\n\nB", 0.03]]
    )
    (hit,) = parse_response(resp)
    assert hit.chunk_id == "policy-x-0003"
    assert hit.page == 7
    assert hit.score == 0.03


def test_parse_response_handles_empty_result():
    assert parse_response(NS(manifest=NS(columns=[]), result=NS(data_array=None))) == []


def test_search_always_filters_to_current_and_merges_extra_filters():
    calls = {}

    def query_index(**kwargs):
        calls.update(kwargs)
        return _response([])

    client = NS(vector_search_indexes=NS(query_index=query_index))
    Retriever(CFG, client).search("complaint", k=3, filters={"source_type": "policy"})
    assert json.loads(calls["filters_json"]) == {"status": "current", "source_type": "policy"}
    assert calls["query_type"] == "HYBRID"
    assert calls["num_results"] == 3
    assert calls["index_name"] == CFG.chunks_index


def test_existing_index_still_building_is_not_synced():
    from careconnect.search.index import ensure_index

    synced = []
    indexes = NS(
        get_index=lambda name: NS(status=NS(ready=False)),
        sync_index=lambda name: synced.append(name),
    )
    assert ensure_index(NS(vector_search_indexes=indexes), CFG) is False
    assert synced == []


def test_existing_ready_index_is_synced():
    from careconnect.search.index import ensure_index

    synced = []
    indexes = NS(
        get_index=lambda name: NS(status=NS(ready=True)),
        sync_index=lambda name: synced.append(name),
    )
    ensure_index(NS(vector_search_indexes=indexes), CFG)
    assert synced == [CFG.chunks_index]
