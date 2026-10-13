from pathlib import Path

from careconnect.config import ProjectConfig
from careconnect.tools import sql

ROOT = Path(__file__).resolve().parents[1]
CFG = ProjectConfig.from_yaml(ROOT / "project_config.yml", env="dev")


def test_every_tool_has_ddl_with_a_description():
    ddl = sql.function_sql(CFG)
    assert set(ddl) == set(sql.FUNCTIONS)
    for name, text in ddl.items():
        assert f"FUNCTION {CFG.catalog}.{CFG.schema_name}.{name}(" in text
        assert "COMMENT '" in text  # the description the model sees


def test_parameters_are_qualified_so_they_never_shadow_columns():
    # `town` and `specialty` are also column names; unqualified they would be ambiguous
    assert "find_clinic.town" in sql.find_clinic_sql(CFG)
    assert "get_waiting_times.specialty" in sql.get_waiting_times_sql(CFG)


def test_waiting_times_are_labelled_as_national_statistics():
    text = sql.get_waiting_times_sql(CFG)
    assert "'" not in sql.PHS_SOURCE_LABEL  # embedded in a SQL string literal
    assert sql.PHS_SOURCE_LABEL in text
    assert "not Firth Valley figures" in sql.PHS_SOURCE_LABEL


def test_gold_table_reads_the_latest_month_of_silver():
    text = sql.gold_waits_sql(CFG)
    assert CFG.table(sql.WAITS_SOURCE) in text
    assert "max(month_ending)" in text


def test_clinics_file_has_the_columns_find_clinic_returns():
    header = (ROOT / "data" / "raw" / sql.CLINICS_FILE).read_text(encoding="utf-8").splitlines()[0]
    for col in ("name", "site_type", "town", "address", "phone", "opening_hours", "services"):
        assert col in header.split(",")
