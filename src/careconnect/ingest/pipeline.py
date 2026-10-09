"""Ingest pipeline: sources -> bronze_documents, silver_chunks, ops_pii_quarantine.

Incremental by content hash: unchanged files are skipped, changed files have
their chunks replaced, and files removed from the source are removed from the
tables. silver_chunks has Change Data Feed enabled for AI Search Delta Sync.
"""

from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime

from careconnect.ingest.chunking import chunk_document
from careconnect.ingest.models import Chunk, Document
from careconnect.ingest.parsing import parse_markdown, parse_pdf
from careconnect.ingest.pii import scan
from careconnect.ingest.sources import SourceReader


@dataclass
class BuildResult:
    documents: list[Document] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)
    quarantined: list[dict] = field(default_factory=list)
    low_findings: list[dict] = field(default_factory=list)
    errors: list[dict] = field(default_factory=list)


def build(reader: SourceReader, max_tokens: int, overlap_tokens: int) -> BuildResult:
    """Parse, scan and chunk every source file. Pure Python, no Spark."""
    result = BuildResult()
    manifest = reader.policy_manifest()
    for src in reader.files():
        try:
            if src.kind == "leaflets":
                doc = parse_markdown(src.path, src.data)
            else:
                doc = parse_pdf(src.path, src.data, manifest)
        except Exception as exc:  # one bad file must not stop the run
            result.errors.append({"source_path": src.path, "error": repr(exc)})
            continue

        findings = scan(doc.raw_text)
        if findings.quarantine:
            result.quarantined.append(
                {
                    "doc_id": doc.doc_id,
                    "source_path": doc.source_path,
                    "content_hash": doc.content_hash,
                    "findings": "; ".join(f"{f.kind}: {f.excerpt}" for f in findings.findings),
                }
            )
            continue
        for f in findings.findings:
            result.low_findings.append({"doc_id": doc.doc_id, "kind": f.kind, "excerpt": f.excerpt})

        result.documents.append(doc)
        result.chunks.extend(chunk_document(doc, max_tokens, overlap_tokens))
    return result


# ------------------------------------------------------------- Spark writes

_DDL = {
    "bronze_documents": """
        doc_id STRING NOT NULL, source_path STRING, source_type STRING, title STRING,
        content_hash STRING, raw_text STRING, status STRING, effective_date DATE,
        review_date DATE, service STRING, audience STRING, source_url STRING,
        licence STRING, ingested_at TIMESTAMP""",
    "silver_chunks": """
        chunk_id STRING NOT NULL, doc_id STRING, chunk_index INT, title STRING,
        section_path STRING, text STRING, token_count INT, page INT, source_type STRING,
        status STRING, effective_date DATE, service STRING, audience STRING,
        source_url STRING, chunk_max_tokens INT, chunk_overlap_tokens INT,
        ingested_at TIMESTAMP""",
    "ops_pii_quarantine": """
        doc_id STRING, source_path STRING, content_hash STRING, findings STRING,
        detected_at TIMESTAMP""",
}


def _columns(ddl: str) -> list[tuple[str, str]]:
    cols = []
    for part in ddl.split(","):
        name, dtype = part.split()[:2]
        cols.append((name, dtype.upper()))
    return cols


def _to_rows(records: list[dict], ddl: str) -> list[tuple]:
    """Order values by the table schema and convert ISO date strings to dates."""
    cols = _columns(ddl)
    rows = []
    for rec in records:
        row = []
        for name, dtype in cols:
            value = rec.get(name)
            if dtype == "DATE" and isinstance(value, str):
                value = date.fromisoformat(value)
            row.append(value)
        rows.append(tuple(row))
    return rows


def _df(spark, records: list[dict], table: str):
    ddl = _DDL[table]
    return spark.createDataFrame(_to_rows(records, ddl), schema=ddl.replace("NOT NULL", ""))


def ensure_tables(spark, cfg) -> None:
    for name, cols in _DDL.items():
        props = (
            "TBLPROPERTIES (delta.enableChangeDataFeed = true)" if name == "silver_chunks" else ""
        )
        spark.sql(f"CREATE TABLE IF NOT EXISTS {cfg.table(name)} ({cols}) USING DELTA {props}")


def _existing_hashes(spark, cfg) -> dict[str, str]:
    rows = spark.sql(f"SELECT doc_id, content_hash FROM {cfg.table('bronze_documents')}").collect()
    return {r["doc_id"]: r["content_hash"] for r in rows}


def _in_list(ids) -> str:
    return ", ".join("'" + i.replace("'", "''") + "'" for i in ids)


def write(spark, cfg, result: BuildResult, max_tokens: int, overlap_tokens: int) -> dict:
    """Apply the build result to Delta tables incrementally. Returns run stats."""
    ensure_tables(spark, cfg)
    now = datetime.now(UTC).replace(tzinfo=None)
    existing = _existing_hashes(spark, cfg)
    current_ids = {d.doc_id for d in result.documents}

    changed = [d for d in result.documents if existing.get(d.doc_id) != d.content_hash]
    changed_ids = {d.doc_id for d in changed}
    removed_ids = set(existing) - current_ids

    stale = changed_ids | removed_ids
    if stale:
        ids = _in_list(stale)
        spark.sql(f"DELETE FROM {cfg.table('silver_chunks')} WHERE doc_id IN ({ids})")
        spark.sql(f"DELETE FROM {cfg.table('bronze_documents')} WHERE doc_id IN ({ids})")

    if changed:
        doc_rows = []
        for d in changed:
            row = asdict(d)
            row.pop("sections")
            row["ingested_at"] = now
            doc_rows.append(row)
        _df(spark, doc_rows, "bronze_documents").write.mode("append").saveAsTable(
            cfg.table("bronze_documents")
        )

        chunk_rows = []
        for c in result.chunks:
            if c.doc_id in changed_ids:
                row = asdict(c)
                row.update(
                    chunk_max_tokens=max_tokens,
                    chunk_overlap_tokens=overlap_tokens,
                    ingested_at=now,
                )
                chunk_rows.append(row)
        if chunk_rows:
            _df(spark, chunk_rows, "silver_chunks").write.mode("append").saveAsTable(
                cfg.table("silver_chunks")
            )

    if result.quarantined:
        q_rows = [dict(q, detected_at=now) for q in result.quarantined]
        _df(spark, q_rows, "ops_pii_quarantine").write.mode("append").saveAsTable(
            cfg.table("ops_pii_quarantine")
        )

    return {
        "documents_seen": len(result.documents),
        "documents_changed": len(changed),
        "documents_removed": len(removed_ids),
        "documents_unchanged": len(result.documents) - len(changed),
        "chunks_written": sum(1 for c in result.chunks if c.doc_id in changed_ids),
        "quarantined": len(result.quarantined),
        "errors": len(result.errors),
    }
