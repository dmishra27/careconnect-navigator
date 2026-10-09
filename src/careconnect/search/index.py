"""Create (or refresh) the AI Search endpoint and Delta Sync index over silver_chunks.

The index uses managed embeddings: AI Search calls the embedding endpoint on the
``text`` column itself, so we never store vectors. The pipeline is TRIGGERED, so
it only refreshes when ``sync`` is called (after each ingest run), which keeps
Free Edition usage low.

  uv run python -m careconnect.search.index --env dev
"""

import argparse
import time

from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound, ResourceDoesNotExist
from databricks.sdk.service.vectorsearch import (
    DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn,
    EndpointType,
    PipelineType,
    VectorIndexType,
)

from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config

PRIMARY_KEY = "chunk_id"
EMBEDDING_SOURCE = "text"
# Columns kept in the index for filtering and citations. Dates are left out on
# purpose; status already separates current from superseded guidance.
COLUMNS_TO_SYNC = [
    "chunk_id",
    "doc_id",
    "chunk_index",
    "title",
    "section_path",
    "text",
    "page",
    "source_type",
    "status",
    "service",
    "audience",
    "source_url",
    "token_count",
]

_MISSING = (NotFound, ResourceDoesNotExist)


def index_spec(cfg: ProjectConfig) -> DeltaSyncVectorIndexSpecRequest:
    return DeltaSyncVectorIndexSpecRequest(
        source_table=cfg.table("silver_chunks"),
        pipeline_type=PipelineType.TRIGGERED,
        embedding_source_columns=[
            EmbeddingSourceColumn(
                name=EMBEDDING_SOURCE, embedding_model_endpoint_name=cfg.embedding_endpoint
            )
        ],
        columns_to_sync=COLUMNS_TO_SYNC,
    )


def ensure_endpoint(w: WorkspaceClient, name: str) -> None:
    try:
        w.vector_search_endpoints.get_endpoint(name)
        print(f"Endpoint {name} exists")
        return
    except _MISSING:
        pass
    existing = [e.name for e in w.vector_search_endpoints.list_endpoints()]
    if existing:
        raise SystemExit(
            f"Endpoint '{name}' not found, but {existing} already exist. Free Edition allows one "
            "AI Search endpoint: set search_endpoint in project_config.yml to reuse it."
        )
    print(f"Creating endpoint {name} (takes a few minutes)...")
    w.vector_search_endpoints.create_endpoint_and_wait(
        name=name, endpoint_type=EndpointType.STANDARD
    )
    print(f"Endpoint {name} is online")


def ensure_index(w: WorkspaceClient, cfg: ProjectConfig) -> bool:
    """Create the index if missing, else trigger a sync. Returns True if newly created."""
    try:
        existing = w.vector_search_indexes.get_index(cfg.chunks_index)
    except _MISSING:
        print(f"Creating index {cfg.chunks_index} on {cfg.table('silver_chunks')}...")
        w.vector_search_indexes.create_index(
            name=cfg.chunks_index,
            endpoint_name=cfg.search_endpoint,
            primary_key=PRIMARY_KEY,
            index_type=VectorIndexType.DELTA_SYNC,
            delta_sync_index_spec=index_spec(cfg),
        )
        return True
    if not (existing.status and existing.status.ready):
        # still building (e.g. first run timed out): a sync would be rejected, so just wait
        print(f"Index {cfg.chunks_index} exists but is still building; waiting")
        return False
    print(f"Index {cfg.chunks_index} exists; triggering sync")
    w.vector_search_indexes.sync_index(cfg.chunks_index)
    return False


def wait_until_ready(
    w: WorkspaceClient, index_name: str, expected_rows: int | None, timeout_s: int = 3600
) -> int:
    """Poll until the index is ready and (if given) holds the expected row count."""
    start = time.monotonic()
    while True:
        status = w.vector_search_indexes.get_index(index_name).status
        rows = (status.indexed_row_count if status else None) or 0
        ready = bool(status and status.ready)
        elapsed = int(time.monotonic() - start)
        print(
            f"  {elapsed:>4}s ready={ready} indexed_rows={rows} {status.message if status else ''}"
        )
        if ready and (expected_rows is None or rows == expected_rows):
            return rows
        if elapsed > timeout_s:
            raise TimeoutError(f"Index {index_name} not ready after {timeout_s}s")
        time.sleep(30)


def _source_rows(w: WorkspaceClient, cfg: ProjectConfig) -> int | None:
    """Row count of silver_chunks, so we can wait until the index has caught up."""
    try:
        from careconnect.ingest.main import get_spark

        return get_spark().table(cfg.table("silver_chunks")).count()
    except Exception as exc:  # count is a nice-to-have for the wait condition
        print(f"(could not count source rows: {exc}); waiting for ready only")
        return None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Create or sync the AI Search index")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    w = WorkspaceClient()
    ensure_endpoint(w, cfg.search_endpoint)
    ensure_index(w, cfg)
    if args.no_wait:
        return
    expected = _source_rows(w, cfg)
    rows = wait_until_ready(w, cfg.chunks_index, expected)
    print(f"Index {cfg.chunks_index} ready with {rows} rows")


if __name__ == "__main__":
    main()
