"""Bronze -> silver for PHS ongoing waits (pandas; Spark is only used to write).

The long-trend file is a full refresh every month (PHS revises past months), so
silver is rebuilt from the latest file rather than appended to.
"""

import io

import pandas as pd

SCOTLAND = "S92000003"
ALL_SPECIALTIES = "Z9"

RAW_COLUMNS = {
    "MonthEnding": "month_ending",
    "HBT": "hbt",
    "HBTQF": "hbt_qf",
    "PatientType": "patient_type",
    "Specialty": "specialty",
    "SpecialtyQF": "specialty_qf",
    "NumberWaiting": "number_waiting",
    "NumberWaitingQF": "number_waiting_qf",
    "NumberWaitingOver12Weeks": "waiting_over_12_weeks",
    "NumberWaitingOver12WeeksQF": "waiting_over_12_weeks_qf",
    "Median": "median_wait_days",
    "MedianQF": "median_wait_days_qf",
    "90thPercentile": "p90_wait_days",
    "90thPercentileQF": "p90_wait_days_qf",
}
INT_COLUMNS = ["number_waiting", "waiting_over_12_weeks"]
FLOAT_COLUMNS = ["median_wait_days", "p90_wait_days"]


class SchemaError(ValueError):
    """The source file no longer has the columns this pipeline expects."""


def decode(data: bytes) -> str:
    """PHS files are mostly UTF-8 (often with a BOM); some older lookups are Windows-1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def read_csv(data: bytes) -> pd.DataFrame:
    """Read a PHS CSV as strings: BOM removed, datastore '_id' dropped, cells trimmed."""
    df = pd.read_csv(io.StringIO(decode(data)), dtype=str, keep_default_na=False)
    df.columns = [c.replace("\xa0", " ") for c in df.columns]
    df = df.drop(columns=[c for c in df.columns if c == "_id"])
    df.columns = [c.strip() for c in df.columns]
    # non-breaking spaces (common in cp1252 lookups) would break code matching
    return df.apply(lambda col: col.str.replace("\xa0", " ").str.strip())


def check_schema(raw: pd.DataFrame) -> None:
    missing = sorted(set(RAW_COLUMNS) - set(raw.columns))
    if missing:
        raise SchemaError(f"ongoing waits file is missing columns {missing}")


def board_lookup(health_boards: pd.DataFrame, special_boards: pd.DataFrame) -> dict[str, str]:
    names = dict(zip(health_boards["HB"], health_boards["HBName"], strict=False))
    names.update(zip(special_boards["SHB"], special_boards["SHBName"], strict=False))
    names[SCOTLAND] = "Scotland"
    return names


def specialty_lookup(specialties: pd.DataFrame) -> dict[str, str]:
    return dict(zip(specialties["Specialty"], specialties["SpecialtyName"], strict=False))


def to_silver(
    raw: pd.DataFrame, boards: dict[str, str], specialties: dict[str, str]
) -> pd.DataFrame:
    """Rename, type and enrich. No rows are removed here; expectations decide that."""
    check_schema(raw)
    df = raw[list(RAW_COLUMNS)].rename(columns=RAW_COLUMNS)
    df["month_ending"] = pd.to_datetime(df["month_ending"], format="%Y%m%d", errors="coerce")
    for col in INT_COLUMNS + FLOAT_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["board_name"] = df["hbt"].map(boards)
    df["specialty_name"] = df["specialty"].map(specialties)
    df["is_scotland"] = df["hbt"] == SCOTLAND
    # PHS marks aggregate rows with a "d" (derived) qualifier; Z9 is "All Specialties"
    df["is_all_specialties"] = (df["specialty_qf"].str.lower() == "d") | (
        df["specialty"] == ALL_SPECIALTIES
    )
    df["share_over_12_weeks"] = (df["waiting_over_12_weeks"] / df["number_waiting"]).where(
        df["number_waiting"] > 0
    )
    return df
