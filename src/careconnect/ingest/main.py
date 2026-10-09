"""Command-line entry point for the ingest pipeline.

Examples (from the project root):

  Dry run on local files, no Databricks needed:
    uv run python -m careconnect.ingest.main --source data/raw --dry-run

  Real run from the laptop (reads the Volume, writes Delta via Databricks Connect):
    uv run python -m careconnect.ingest.main --env dev

  In the Databricks job the wheel entry point `ingest` is called with --env.
"""

import argparse
import json
import os
from collections import Counter
from pathlib import Path

from careconnect.config import ProjectConfig
from careconnect.ingest.pipeline import build, write
from careconnect.ingest.sources import SourceReader


def _find_config() -> Path:
    for base in (Path.cwd(), *Path(__file__).resolve().parents):
        candidate = base / "project_config.yml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("project_config.yml not found; pass --config")


def get_spark():
    if "DATABRICKS_RUNTIME_VERSION" in os.environ:  # running inside Databricks
        from pyspark.sql import SparkSession

        return SparkSession.builder.getOrCreate()
    from databricks.connect import DatabricksSession  # running on a laptop

    return DatabricksSession.builder.serverless(True).getOrCreate()


def _summary(result) -> dict:
    tokens = sorted(c.token_count for c in result.chunks) or [0]
    return {
        "documents": len(result.documents),
        "by_type": dict(Counter(d.source_type for d in result.documents)),
        "chunks": len(result.chunks),
        "tokens_min": tokens[0],
        "tokens_median": tokens[len(tokens) // 2],
        "tokens_max": tokens[-1],
        "quarantined": [q["doc_id"] for q in result.quarantined],
        "low_findings": len(result.low_findings),
        "errors": result.errors,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ingest source documents into Delta tables")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None, help="path to project_config.yml")
    parser.add_argument(
        "--source", default=None, help="local folder or /Volumes path (default: landing Volume)"
    )
    parser.add_argument("--max-tokens", type=int, default=None)
    parser.add_argument("--overlap-tokens", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="parse and chunk only, no Spark writes"
    )
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    max_tokens = args.max_tokens or cfg.chunk_max_tokens
    overlap = args.overlap_tokens if args.overlap_tokens is not None else cfg.chunk_overlap_tokens
    source = args.source or cfg.landing_path

    result = build(SourceReader(source), max_tokens, overlap)
    print(json.dumps({"source": source, **_summary(result)}, indent=2))

    if args.dry_run:
        for c in result.chunks[:2]:
            print(
                "\n--- sample chunk", c.chunk_id, f"({c.token_count} tokens) ---\n" + c.text[:600]
            )
        return

    stats = write(get_spark(), cfg, result, max_tokens, overlap)
    print(json.dumps({"written": stats}, indent=2))
    if result.errors:
        raise SystemExit(f"{len(result.errors)} file(s) failed to parse; see errors above")


if __name__ == "__main__":
    main()
