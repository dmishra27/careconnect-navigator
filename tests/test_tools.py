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


def test_all_specialties_rows_get_a_readable_name_not_a_code():
    assert "THEN 'All specialties'" in sql.get_waiting_times_sql(CFG)


def test_short_specialty_words_match_whole_words_and_aliases():
    text = sql.get_waiting_times_sql(CFG)
    assert "x IN ('ent', 'ear', 'ears')) THEN '%ear%nose%throat%'" in text  # everyday word
    assert "(^|[^a-z])" in text  # whole-word match, so "ENT" never matches "Dental"


def test_aliases_match_any_word_of_the_specialty_so_eye_operations_finds_ophthalmology():
    import re

    text = sql.get_waiting_times_sql(CFG)
    # the argument is split into words and each alias is checked against every word
    assert "exists(split(lower(trim(get_waiting_times.specialty)), '[^a-z]+')" in text
    words = re.split("[^a-z]+", "eye operations".lower())
    hits = [p for p, ws in sql.SPECIALTY_ALIASES.items() if set(ws) & set(words)]
    assert hits == ["%ophthalmolog%"]
    # "dental" splits to one word, so the "ent" alias can never fire on it
    assert not set(sql.SPECIALTY_ALIASES["%ear%nose%throat%"]) & set(re.split("[^a-z]+", "dental"))


def test_waiting_times_also_returns_weeks_so_the_model_does_not_convert():
    text = sql.get_waiting_times_sql(CFG)
    assert "median_wait_weeks DOUBLE" in text and "ROUND(w.median_wait_days / 7, 1)" in text
