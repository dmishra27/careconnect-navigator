"""Data-quality expectations for the silver waiting-times table.

Each expectation returns a boolean Series (True = row passes). Severity decides
what happens to failing rows:

* ``drop`` - the row is removed from silver and written to the rejects table
* ``warn`` - the row is kept; the failure count is recorded

Results are returned as plain dicts so they can be written to ``ops_dq_results``
and compared run to run.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd

KEY = ["month_ending", "hbt", "patient_type", "specialty"]


@dataclass(frozen=True)
class Expectation:
    name: str
    severity: str  # "drop" or "warn"
    description: str
    check: Callable[[pd.DataFrame], pd.Series]


def _both(df: pd.DataFrame, a: str, b: str) -> pd.Series:
    return df[a].notna() & df[b].notna()


def expectations(today: date | None = None) -> list[Expectation]:
    today_ts = pd.Timestamp(today or date.today())
    return [
        Expectation(
            "valid_month",
            "drop",
            "MonthEnding parses as a YYYYMMDD date",
            lambda df: df["month_ending"].notna(),
        ),
        Expectation(
            "month_not_in_future",
            "drop",
            "No reporting month after today",
            lambda df: df["month_ending"].isna() | (df["month_ending"] <= today_ts),
        ),
        Expectation(
            "board_present",
            "drop",
            "Health board of treatment code is not blank",
            lambda df: df["hbt"].str.len() > 0,
        ),
        Expectation(
            "non_negative_counts",
            "drop",
            "Waiting counts are not negative",
            lambda df: (
                (df["number_waiting"].isna() | (df["number_waiting"] >= 0))
                & (df["waiting_over_12_weeks"].isna() | (df["waiting_over_12_weeks"] >= 0))
            ),
        ),
        Expectation(
            "over_12_weeks_within_total",
            "drop",
            "Waits over 12 weeks do not exceed all waits",
            lambda df: (
                ~_both(df, "number_waiting", "waiting_over_12_weeks")
                | (df["waiting_over_12_weeks"] <= df["number_waiting"])
            ),
        ),
        Expectation(
            "median_not_above_p90",
            "warn",
            "Median wait is not above the 90th percentile",
            lambda df: (
                ~_both(df, "median_wait_days", "p90_wait_days")
                | (df["median_wait_days"] <= df["p90_wait_days"])
            ),
        ),
        Expectation(
            "count_present",
            "warn",
            "NumberWaiting is populated (blank usually means suppressed or not available)",
            lambda df: df["number_waiting"].notna(),
        ),
        Expectation(
            "known_board",
            "warn",
            "Board code is in the PHS health board or special board lookups",
            lambda df: df["board_name"].notna(),
        ),
        Expectation(
            "known_specialty",
            "warn",
            "Specialty code is in the PHS specialty lookup",
            lambda df: (
                df["specialty_name"].notna() | (df["specialty"] == "") | df["is_all_specialties"]
            ),
        ),
    ]


def apply(
    df: pd.DataFrame, rules: list[Expectation]
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """Run expectations. Returns (kept rows, rejected rows with reasons, results)."""
    total = len(df)
    results, failed_by_rule = [], {}
    for rule in rules:
        passed = rule.check(df).fillna(False).astype(bool)
        failed_by_rule[rule.name] = ~passed
        results.append(_result(rule.name, rule.severity, int((~passed).sum()), total))

    drop_rules = [r.name for r in rules if r.severity == "drop"]
    reasons = pd.Series([""] * total, index=df.index)
    for name in drop_rules:
        reasons = reasons.where(~failed_by_rule[name], reasons + name + ";")
    dropped = reasons != ""
    kept = df[~dropped]

    # duplicate keys: keep the last occurrence (later rows in a PHS file are the revision)
    dup = kept.duplicated(subset=KEY, keep="last")
    results.append(_result("unique_key", "drop", int(dup.sum()), total))
    rejects = pd.concat(
        [
            df[dropped].assign(failed_expectations=reasons[dropped].str.rstrip(";")),
            kept[dup].assign(failed_expectations="unique_key"),
        ]
    )
    return kept[~dup].reset_index(drop=True), rejects.reset_index(drop=True), results


def _result(name: str, severity: str, failed: int, total: int) -> dict:
    return {
        "expectation": name,
        "severity": severity,
        "failed_rows": failed,
        "total_rows": total,
        "pass_rate": 1.0 - failed / total if total else 1.0,
    }


def freshness(df: pd.DataFrame, today: date | None = None, max_age_days: int = 120) -> dict:
    """Table-level check: the newest month should be recent (PHS publishes monthly)."""
    latest = df["month_ending"].max()
    age = (pd.Timestamp(today or date.today()) - latest).days if pd.notna(latest) else None
    ok = age is not None and age <= max_age_days
    return {
        "expectation": "fresh_data",
        "severity": "warn",
        "failed_rows": 0 if ok else 1,
        "total_rows": 1,
        "pass_rate": 1.0 if ok else 0.0,
        "detail": f"latest month {latest.date() if pd.notna(latest) else None}, {age} days old",
    }
