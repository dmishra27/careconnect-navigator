"""Query the AI Search index: hybrid (vector + keyword) search over current guidance.

uv run python -m careconnect.search.retriever "How do I complain about my GP?"
"""

import argparse
import json
from dataclasses import dataclass

from databricks.sdk import WorkspaceClient

from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config

RETURN_COLUMNS = ["chunk_id", "doc_id", "title", "section_path", "page", "source_type", "text"]
DEFAULT_FILTERS = {"status": "current"}  # never surface superseded leaflets


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    section_path: str
    page: int | None
    source_type: str
    text: str
    score: float


def parse_response(response) -> list[Hit]:
    """Turn a query_index response (manifest + data_array) into Hits.

    The score is appended by the service as the last column of each row.
    """
    if not response.result or not response.result.data_array:
        return []
    names = [c.name for c in response.manifest.columns]
    hits = []
    for row in response.result.data_array:
        rec = dict(zip(names, row, strict=False))
        page = rec.get("page")
        hits.append(
            Hit(
                chunk_id=rec["chunk_id"],
                doc_id=rec["doc_id"],
                title=rec.get("title") or "",
                section_path=rec.get("section_path") or "",
                page=int(float(page)) if page not in (None, "") else None,
                source_type=rec.get("source_type") or "",
                text=rec.get("text") or "",
                score=float(rec.get("score", row[-1])),
            )
        )
    return hits


class Retriever:
    def __init__(self, cfg: ProjectConfig, client: WorkspaceClient | None = None):
        self.cfg = cfg
        self.w = client or WorkspaceClient()

    def search(
        self,
        query: str,
        k: int = 5,
        filters: dict | None = None,
        query_type: str = "HYBRID",
    ) -> list[Hit]:
        merged = {**DEFAULT_FILTERS, **(filters or {})}
        response = self.w.vector_search_indexes.query_index(
            index_name=self.cfg.chunks_index,
            columns=RETURN_COLUMNS,
            query_text=query,
            query_type=query_type,
            filters_json=json.dumps(merged),
            num_results=k,
        )
        return parse_response(response)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Search CareConnect guidance")
    parser.add_argument("query")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("-k", type=int, default=5)
    parser.add_argument("--type", default="HYBRID", choices=["HYBRID", "ANN", "FULL_TEXT"])
    parser.add_argument("--source-type", choices=["leaflet", "policy"], default=None)
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    filters = {"source_type": args.source_type} if args.source_type else None
    for i, hit in enumerate(Retriever(cfg).search(args.query, args.k, filters, args.type), 1):
        page = f" p.{hit.page}" if hit.page else ""
        print(f"\n{i}. [{hit.score:.4f}] {hit.section_path}{page}  ({hit.chunk_id})")
        body = hit.text.split("\n\n", 1)[-1].replace("\n", " ")
        print("   " + body[:220] + ("..." if len(body) > 220 else ""))


if __name__ == "__main__":
    main()
