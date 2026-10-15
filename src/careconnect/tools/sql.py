# ruff: noqa: E501  (tool descriptions are kept on one line: the model reads them as written)
"""SQL for the agent's tool data and its Unity Catalog functions.

Kept as plain strings built from the config so they can be unit-tested without Spark.

The function and parameter COMMENTs matter: Databricks' UC functions MCP server and any
tool-calling client show them to the model as the tool and argument descriptions, so they
are written for the model, with examples of accepted values.
"""

from careconnect.config import ProjectConfig

CLINICS_TABLE = "silver_clinics"
WAITS_TABLE = "gold_phs_latest_waits"
WAITS_SOURCE = "silver_phs_ongoing_waits"
CLINICS_FILE = "reference/clinics.csv"

FIND_CLINIC = "find_clinic"
GET_WAITING_TIMES = "get_waiting_times"
LIST_SPECIALTIES = "list_waiting_time_specialties"
FUNCTIONS = (FIND_CLINIC, GET_WAITING_TIMES, LIST_SPECIALTIES)

PHS_SOURCE_LABEL = (
    "Public Health Scotland, Stage of Treatment Waiting Times: Ongoing Waits "
    "(Open Government Licence). National statistics, not Firth Valley figures."
)


def gold_waits_sql(cfg: ProjectConfig) -> str:
    """Latest month of ongoing waits per board, specialty and patient type."""
    src, dst = cfg.table(WAITS_SOURCE), cfg.table(WAITS_TABLE)
    return f"""
CREATE OR REPLACE TABLE {dst}
COMMENT 'Latest month of PHS ongoing waits per board, specialty and patient type, for the get_waiting_times tool'
AS SELECT
  CAST(month_ending AS DATE) AS month_ending,
  board_name,
  hbt AS board_code,
  is_scotland,
  patient_type,
  specialty AS specialty_code,
  specialty_name,
  is_all_specialties,
  CAST(number_waiting AS INT) AS number_waiting,
  CAST(waiting_over_12_weeks AS INT) AS waiting_over_12_weeks,
  ROUND(100 * share_over_12_weeks, 1) AS pct_over_12_weeks,
  median_wait_days,
  p90_wait_days
FROM {src}
WHERE month_ending = (SELECT max(month_ending) FROM {src})
  AND board_name IS NOT NULL
  AND number_waiting IS NOT NULL
"""


def find_clinic_sql(cfg: ProjectConfig) -> str:
    fn, table = cfg.table(FIND_CLINIC), cfg.table(CLINICS_TABLE)
    return f"""
CREATE OR REPLACE FUNCTION {fn}(
  service STRING DEFAULT NULL
    COMMENT 'What the patient needs, in plain words, e.g. "blood tests", "podiatry", "physiotherapy", "x-ray", "minor injuries", "contraception". Leave empty to list all sites.',
  town STRING DEFAULT NULL
    COMMENT 'Town to search in: Larbank, Grangeford, Inverbrae, Kilbrannan or Muirhead. Leave empty for all towns.'
)
RETURNS TABLE (
  name STRING, site_type STRING, town STRING, address STRING,
  phone STRING, opening_hours STRING, services STRING
)
COMMENT 'Find Firth Valley Health Board hospitals and community clinics by service and/or town. Returns name, address, phone, opening hours and services. Firth Valley is a fictional board used for this demo.'
RETURN
  SELECT c.name, c.site_type, c.town, c.address, c.phone, c.opening_hours, c.services
  FROM {table} AS c
  WHERE (find_clinic.service IS NULL OR trim(find_clinic.service) = ''
         OR c.services ILIKE concat('%', replace(lower(trim(find_clinic.service)), ' ', '_'), '%')
         OR c.services ILIKE concat('%', replace(lower(trim(find_clinic.service)), '-', ''), '%')
         OR c.name ILIKE concat('%', trim(find_clinic.service), '%'))
    AND (find_clinic.town IS NULL OR trim(find_clinic.town) = ''
         OR c.town ILIKE concat('%', trim(find_clinic.town), '%'))
  ORDER BY c.site_type, c.name
"""


# Everyday words patients use -> a pattern for the PHS specialty name. Matched against any
# whole word of the model's specialty argument, so "eye operations" and "my knee joint" work.
SPECIALTY_ALIASES: dict[str, tuple[str, ...]] = {
    "%ear%nose%throat%": ("ent", "ear", "ears"),
    "%orthopaedic%": (
        "bones",
        "joint",
        "joints",
        "knee",
        "hip",
        "ortho",
        "orthopedic",
        "orthopedics",
    ),
    "%ophthalmolog%": ("eye", "eyes", "cataract", "cataracts"),
    "%dermatolog%": ("skin",),
    "%cardiolog%": ("heart",),
}


def specialty_alias_case(arg: str = "get_waiting_times.specialty") -> str:
    """SQL CASE returning the PHS name pattern for the first alias word found in the argument."""
    words = f"split(lower(trim({arg})), '[^a-z]+')"
    whens = " ".join(
        f"WHEN exists({words}, x -> x IN ({', '.join(repr(w) for w in ws)})) THEN '{pattern}'"
        for pattern, ws in SPECIALTY_ALIASES.items()
    )
    return f"CASE {whens} END"


def get_waiting_times_sql(cfg: ProjectConfig) -> str:
    fn, table = cfg.table(GET_WAITING_TIMES), cfg.table(WAITS_TABLE)
    alias_case = specialty_alias_case()
    return f"""
CREATE OR REPLACE FUNCTION {fn}(
  specialty STRING DEFAULT NULL
    COMMENT 'Hospital specialty in plain words, e.g. "Orthopaedics", "Ophthalmology", "Dermatology", "Cardiology". Leave empty for all specialties combined.',
  patient_type STRING DEFAULT NULL
    COMMENT '"New Outpatient" for a first outpatient appointment, or "Inpatient" for an inpatient or day case operation. Leave empty for both.',
  board STRING DEFAULT NULL
    COMMENT 'A real NHS Scotland health board, e.g. "NHS Lothian", "NHS Greater Glasgow and Clyde". Leave empty for Scotland as a whole.'
)
RETURNS TABLE (
  month_ending DATE, board STRING, patient_type STRING, specialty STRING,
  number_waiting INT, waiting_over_12_weeks INT, pct_over_12_weeks DOUBLE,
  median_wait_days DOUBLE, median_wait_weeks DOUBLE, p90_wait_days DOUBLE,
  p90_wait_weeks DOUBLE, source STRING
)
COMMENT 'Latest published NHS Scotland waiting times (patients still waiting) for a specialty: number waiting, share waiting over 12 weeks, median and 90th percentile time waited so far in days and weeks. Real Public Health Scotland statistics for Scotland or a named real health board; they are not figures for the fictional Firth Valley Health Board.'
RETURN
  SELECT w.month_ending, w.board_name, w.patient_type,
         CASE WHEN w.is_all_specialties THEN 'All specialties'
              ELSE coalesce(w.specialty_name, w.specialty_code) END,
         w.number_waiting, w.waiting_over_12_weeks, w.pct_over_12_weeks,
         w.median_wait_days, ROUND(w.median_wait_days / 7, 1),
         w.p90_wait_days, ROUND(w.p90_wait_days / 7, 1),
         '{PHS_SOURCE_LABEL}'
  FROM {table} AS w
  WHERE (CASE WHEN get_waiting_times.board IS NULL OR trim(get_waiting_times.board) = ''
              THEN w.is_scotland
              ELSE w.board_name ILIKE concat('%', trim(get_waiting_times.board), '%') END)
    AND (CASE WHEN get_waiting_times.specialty IS NULL OR trim(get_waiting_times.specialty) = ''
              THEN w.is_all_specialties
              ELSE (
                -- 1. everyday words patients use, matched on ANY word ("eye operations")
                w.specialty_name ILIKE coalesce({alias_case}, '__no_alias__')
                -- 2. the word as a whole word (so "ENT" never matches "Dental")
                OR (length(regexp_replace(get_waiting_times.specialty, '[^A-Za-z]', '')) > 0
                    AND w.specialty_name RLIKE concat('(?i)(^|[^a-z])',
                        regexp_replace(get_waiting_times.specialty, '[^A-Za-z]', ''), '($|[^a-z])'))
                -- 3. longer words by stem ("Orthopaedics" finds "Orthopaedic Surgery")
                OR (length(trim(get_waiting_times.specialty)) > 4
                    AND w.specialty_name ILIKE concat('%', left(trim(get_waiting_times.specialty),
                        length(trim(get_waiting_times.specialty)) - 2), '%'))
              ) END)
    AND (get_waiting_times.patient_type IS NULL OR trim(get_waiting_times.patient_type) = ''
         OR w.patient_type ILIKE concat('%', split(trim(get_waiting_times.patient_type), ' ')[0], '%'))
  ORDER BY w.board_name, w.specialty_name, w.patient_type
  LIMIT 20
"""


def list_specialties_sql(cfg: ProjectConfig) -> str:
    fn, table = cfg.table(LIST_SPECIALTIES), cfg.table(WAITS_TABLE)
    return f"""
CREATE OR REPLACE FUNCTION {fn}()
RETURNS TABLE (specialty STRING)
COMMENT 'List the specialty names that get_waiting_times recognises, e.g. to find the exact name for "ENT" or "bones". Call this when get_waiting_times returns no rows.'
RETURN
  SELECT DISTINCT specialty_name FROM {table}
  WHERE is_scotland AND NOT is_all_specialties AND specialty_name IS NOT NULL
  ORDER BY specialty_name
"""


def function_sql(cfg: ProjectConfig) -> dict[str, str]:
    return {
        FIND_CLINIC: find_clinic_sql(cfg),
        GET_WAITING_TIMES: get_waiting_times_sql(cfg),
        LIST_SPECIALTIES: list_specialties_sql(cfg),
    }
