"""Build the agent's tool data and register the tools as Unity Catalog functions.

  uv run tools --env dev

Steps (all idempotent, safe to rerun):
  1. silver_clinics          from the landing Volume (reference/clinics.csv)
  2. gold_phs_latest_waits   latest month of silver_phs_ongoing_waits
  3. UC functions            find_clinic, get_waiting_times, list_waiting_time_specialties
  4. Smoke test              calls each function and prints the rows

Registered functions are served automatically by Databricks' UC functions MCP server at
  https://<workspace>/api/2.0/mcp/functions/<catalog>/<schema>
"""

import argparse

from careconnect.config import ProjectConfig
from careconnect.ingest.main import _find_config, get_spark
from careconnect.tools import sql

SMOKE_TESTS = [
    ("find_clinic", "'blood tests', 'Larbank'"),
    ("find_clinic", "'x-ray', NULL"),
    ("get_waiting_times", "'Orthopaedics', 'New Outpatient', NULL"),
    ("get_waiting_times", "NULL, NULL, NULL"),
    ("get_waiting_times", "'Ophthalmology', 'Inpatient', 'NHS Lothian'"),
    ("get_waiting_times", "'ENT', 'New Outpatient', 'NHS Lothian'"),
    ("get_waiting_times", "'eyes', 'New Outpatient', NULL"),
    ("list_waiting_time_specialties", ""),
]


def build_clinics(spark, cfg: ProjectConfig) -> int:
    path = f"{cfg.landing_path}/{sql.CLINICS_FILE}"
    df = spark.read.option("header", True).option("escape", '"').csv(path)
    df.write.mode("overwrite").option("overwriteSchema", True).saveAsTable(
        cfg.table(sql.CLINICS_TABLE)
    )
    return df.count()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Build tool data and register UC functions")
    parser.add_argument("--env", default="dev")
    parser.add_argument("--config", default=None)
    parser.add_argument("--no-smoke", action="store_true", help="skip calling the functions")
    args = parser.parse_args(argv)

    cfg = ProjectConfig.from_yaml(args.config or _find_config(), env=args.env)
    spark = get_spark()

    n = build_clinics(spark, cfg)
    print(f"{cfg.table(sql.CLINICS_TABLE)}: {n} sites")

    spark.sql(sql.gold_waits_sql(cfg))
    row = spark.sql(
        f"SELECT count(*) AS n, max(month_ending) AS month FROM {cfg.table(sql.WAITS_TABLE)}"
    ).collect()[0]
    print(f"{cfg.table(sql.WAITS_TABLE)}: {row['n']} rows for month ending {row['month']}")

    for name, ddl in sql.function_sql(cfg).items():
        spark.sql(ddl)
        print(f"registered {cfg.table(name)}")

    if args.no_smoke:
        return
    for name, call_args in SMOKE_TESTS:
        print(f"\n{name}({call_args})")
        df = spark.sql(f"SELECT * FROM {cfg.table(name)}({call_args})")
        cols = [c for c in df.columns if c != "source"]
        rows = df.select(*cols).limit(6).collect()
        if not rows:
            print("   (no rows)")
        for r in rows:
            print("   " + " | ".join(str(v) for v in r))


if __name__ == "__main__":
    main()
