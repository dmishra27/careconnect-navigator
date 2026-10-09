"""PHS waiting times: download -> bronze -> silver with data-quality expectations.

  Laptop (downloads to data/raw/phs, uploads to the landing Volume, then runs):
    uv run phs --env dev --download

  Rerun from files already in the Volume:
    uv run phs --env dev

  Download and check transforms and expectations without touching Databricks:
    uv run phs --download --dry-run

Tables (in the environment schema):
  bronze_phs_ongoing_waits   raw strings + source file, hash and load time
  silver_phs_ongoing_waits   typed, enriched, rows that pass all "drop" expectations
  ops_phs_rejects            rows removed by "drop" expectations, with the reasons
  ops_dq_results             one row per expectation per run (appended)
"""

import argparse
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config, get_spark
from careconnect.ingest.sources import SourceReader
from careconnect.phs import expectations as dq
from careconnect.phs import sources
from careconnect.phs.transform import (
    INT_COLUMNS,
    board_lookup,
    read_csv,
    specialty_lookup,
    to_silver,
)

BRONZE = "bronze_phs_ongoing_waits"
SILVER = "silver_phs_ongoing_waits"
REJECTS = "ops_phs_rejects"
DQ_RESULTS = "ops_dq_results"
LOCAL_DIR = Path("data/raw/phs")


def load(reader: SourceReader, folder: str) -> dict[str, tuple[bytes, pd.DataFrame]]:
    out = {}
    for res in sources.RESOURCES:
        if res.key == "qualifiers":
            continue  # reference only, not needed for the transform
        data = reader.read(f"{folder}/{res.file_name}")
        out[res.key] = (data, read_csv(data))
    return out


def build(files: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, list[dict]]:
    raw = files["ongoing_waits"][1]
    optional = {k: files[k][1] for k in ("isd_boards", "other_residential") if k in files}
    boards = board_lookup(
        files["health_boards"][1],
        files["special_boards"][1],
        optional.get("isd_boards"),
        optional.get("other_residential"),
    )
    specialties = specialty_lookup(files["specialties"][1])
    silver = to_silver(raw, boards, specialties)
    kept, rejects, results = dq.apply(silver, dq.expectations())
    results.append(dq.freshness(kept))
    return raw, kept, rejects, results


def summary(raw, kept, rejects, results) -> dict:
    scot = kept[kept["is_scotland"] & kept["is_all_specialties"]]
    return {
        "raw_rows": len(raw),
        "silver_rows": len(kept),
        "rejected_rows": len(rejects),
        "months": f"{kept['month_ending'].min():%Y-%m} to {kept['month_ending'].max():%Y-%m}",
        "boards": int(kept["hbt"].nunique()),
        "specialties": int(kept["specialty"].nunique()),
        "patient_types": sorted(kept["patient_type"].unique().tolist()),
        "scotland_all_specialty_rows": len(scot),
        "unknown_boards": _top(kept.loc[kept["board_name"].isna(), "hbt"]),
        "unknown_specialties": _top(
            kept.loc[kept["specialty_name"].isna() & ~kept["is_all_specialties"], "specialty"]
        ),
        "blank_counts_by_patient_type": kept.loc[kept["number_waiting"].isna(), "patient_type"]
        .value_counts()
        .to_dict(),
        "failed_expectations": {
            r["expectation"]: r["failed_rows"] for r in results if r["failed_rows"]
        },
    }


def _top(codes: pd.Series, n: int = 5) -> dict[str, int]:
    """Most frequent codes, so unmatched lookups are easy to diagnose."""
    return {str(k): int(v) for k, v in codes.value_counts().head(n).items()}


# ------------------------------------------------------------------ Spark writes


def _spark_df(spark, pdf: pd.DataFrame):
    """pandas -> Spark with NaN turned into NULL and counts as BIGINT."""
    from pyspark.sql import functions as F

    pdf = pdf.copy()
    for name in pdf.columns:
        if pdf[name].dtype.kind not in "biufmM":  # text (object or pandas string dtype)
            # lookups leave NaN in text columns; Arrow needs None there
            pdf[name] = pdf[name].astype(object).where(pdf[name].notna(), None)
    sdf = spark.createDataFrame(pdf)
    for name, dtype in pdf.dtypes.items():
        if dtype.kind == "f":
            sdf = sdf.withColumn(name, F.when(F.isnan(F.col(name)), None).otherwise(F.col(name)))
    for name in INT_COLUMNS:
        if name in pdf.columns:
            sdf = sdf.withColumn(name, F.col(name).cast("bigint"))
    if "month_ending" in pdf.columns:
        sdf = sdf.withColumn("month_ending", F.col("month_ending").cast("date"))
    return sdf


def _overwrite(spark, pdf: pd.DataFrame, table: str) -> None:
    (
        _spark_df(spark, pdf)
        .write.mode("overwrite")
        .option("overwriteSchema", "true")
        .saveAsTable(table)
    )


def _current_hash(spark, cfg) -> str | None:
    # check first: querying a missing table makes Spark Connect log a long error
    if not spark.catalog.tableExists(cfg.table(BRONZE)):
        return None
    row = spark.sql(f"SELECT max(source_sha256) AS h FROM {cfg.table(BRONZE)}").first()
    return row["h"] if row else None


def write(spark, cfg, files, raw, kept, rejects, results, full_refresh: bool) -> dict:
    data = files["ongoing_waits"][0]
    digest = sources.sha256(data)
    if not full_refresh and _current_hash(spark, cfg) == digest:
        return {"skipped": "source file unchanged since last load (use --full-refresh)"}

    run_id = uuid.uuid4().hex[:12]
    now = datetime.now(UTC).replace(tzinfo=None)
    bronze = raw.assign(
        source_file=sources.BY_KEY["ongoing_waits"].file_name,
        source_sha256=digest,
        ingested_at=now,
    )
    _overwrite(spark, bronze, cfg.table(BRONZE))
    silver_sdf = _spark_df(spark, kept.assign(run_id=run_id, loaded_at=now))
    silver_sdf.write.mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        cfg.table(SILVER)
    )
    if len(rejects):
        _overwrite(spark, rejects.assign(run_id=run_id), cfg.table(REJECTS))
    else:  # pandas cannot give Spark a schema for an empty frame; reuse silver's
        from pyspark.sql import functions as F

        (
            silver_sdf.limit(0)
            .drop("loaded_at")
            .withColumn("failed_expectations", F.lit(""))
            .write.mode("overwrite")
            .option("overwriteSchema", "true")
            .saveAsTable(cfg.table(REJECTS))
        )

    dq_rows = pd.DataFrame([{"detail": "", **r} for r in results]).assign(
        run_id=run_id, run_at=now, table_name=cfg.table(SILVER)
    )
    _spark_df(spark, dq_rows).write.mode("append").option("mergeSchema", "true").saveAsTable(
        cfg.table(DQ_RESULTS)
    )
    return {"run_id": run_id, "bronze": len(bronze), "silver": len(kept), "rejects": len(rejects)}


# ------------------------------------------------------------------ CLI


def _volume_mounted(path: str) -> bool:
    return Path(path).exists()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="PHS waiting times: bronze -> silver with DQ")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--download", action="store_true", help="fetch the latest PHS files")
    parser.add_argument("--source", default=None, help="folder with the files (default: Volume)")
    parser.add_argument("--dry-run", action="store_true", help="transform and check only")
    parser.add_argument("--full-refresh", action="store_true")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    volume_dir = f"{cfg.landing_path}/phs"

    if args.download:
        if _volume_mounted(cfg.landing_path):  # inside Databricks: straight into the Volume
            print(f"Downloading PHS files to {volume_dir}")
            try:
                sources.download(Path(volume_dir))
            except OSError as exc:  # URLError is an OSError
                # Free Edition serverless has no internet access: load what is in the Volume
                print(f"WARNING: download failed ({exc}); using files already in {volume_dir}")
        else:
            print(f"Downloading PHS files to {LOCAL_DIR}")
            sources.download(LOCAL_DIR)
            if args.dry_run:  # nothing goes to Databricks; check the local copy
                args.source = args.source or str(LOCAL_DIR)
            else:
                sources.upload(LOCAL_DIR, volume_dir)

    folder = (args.source or volume_dir).rstrip("/")
    files = load(SourceReader(folder), folder)
    raw, kept, rejects, results = build(files)
    print(json.dumps(summary(raw, kept, rejects, results), indent=2, default=str))
    for r in results:
        flag = "FAIL" if r["failed_rows"] else "ok  "
        detail = f"  {r['detail']}" if r.get("detail") else ""
        print(f"  {flag} {r['severity']:<4} {r['expectation']:<28} {r['failed_rows']:>7}{detail}")

    if args.dry_run:
        return
    stats = write(get_spark(), cfg, files, raw, kept, rejects, results, args.full_refresh)
    print(json.dumps({"written": stats}, indent=2))


if __name__ == "__main__":
    main()
