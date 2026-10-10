"""Inspect the ingest tables after a run (uses Databricks Connect on serverless)."""

from pathlib import Path

from databricks.connect import DatabricksSession

from careconnect.config import ProjectConfig

cfg = ProjectConfig.from_yaml(Path(__file__).resolve().parents[1] / "project_config.yml", "dev")
spark = DatabricksSession.builder.serverless(True).getOrCreate()

print("Documents by type and status")
spark.sql(f"""
    SELECT source_type, status, COUNT(*) AS documents
    FROM {cfg.table("bronze_documents")}
    GROUP BY ALL ORDER BY ALL
""").show()

print("Chunks per source type")
spark.sql(f"""
    SELECT source_type, COUNT(*) AS chunks, MIN(token_count) AS min_tokens,
           PERCENTILE_APPROX(token_count, 0.5) AS median_tokens, MAX(token_count) AS max_tokens
    FROM {cfg.table("silver_chunks")}
    GROUP BY ALL ORDER BY ALL
""").show()

print("Change Data Feed enabled on silver_chunks (needed for AI Search)")
spark.sql(f"SHOW TBLPROPERTIES {cfg.table('silver_chunks')}").filter(
    "key = 'delta.enableChangeDataFeed'"
).show(truncate=False)

print("Quarantined documents")
spark.sql(f"SELECT doc_id, findings FROM {cfg.table('ops_pii_quarantine')}").show(truncate=False)

print("Sample policy chunks")
spark.sql(f"""
    SELECT chunk_id, page, token_count, LEFT(text, 120) AS text
    FROM {cfg.table("silver_chunks")} WHERE source_type = 'policy'
    ORDER BY chunk_id LIMIT 5
""").show(truncate=False)

print("Page spread per policy (pages should increase through each document)")
spark.sql(f"""
    SELECT doc_id, COUNT(*) AS chunks, COUNT(DISTINCT page) AS distinct_pages,
           MIN(page) AS first_page, MAX(page) AS last_page
    FROM {cfg.table("silver_chunks")} WHERE source_type = 'policy'
    GROUP BY doc_id ORDER BY doc_id
""").show(truncate=False)

print("Tiny policy chunks (under 20 tokens) per document")
spark.sql(f"""
    SELECT doc_id, COUNT(*) AS chunks,
           SUM(CASE WHEN token_count < 20 THEN 1 ELSE 0 END) AS tiny_chunks
    FROM {cfg.table("silver_chunks")} WHERE source_type = 'policy'
    GROUP BY doc_id ORDER BY tiny_chunks DESC, doc_id
""").show(truncate=False)
