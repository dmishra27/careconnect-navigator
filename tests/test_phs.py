from datetime import date

import pandas as pd
import pytest

from careconnect.phs import expectations as dq
from careconnect.phs.main import build, summary
from careconnect.phs.sources import RESOURCES
from careconnect.phs.transform import (
    SchemaError,
    board_lookup,
    read_csv,
    specialty_lookup,
    to_silver,
)

HEADER = (
    "_id,MonthEnding,HBT,HBTQF,PatientType,Specialty,SpecialtyQF,NumberWaiting,NumberWaitingQF,"
    "NumberWaitingOver12Weeks,NumberWaitingOver12WeeksQF,Median,MedianQF,90thPercentile,"
    "90thPercentileQF"
)
ROWS = [
    "1,20260630,S92000003,d,New Outpatient,Z9,d,500000,,200000,,90,,300,",  # Scotland total
    "2,20260630,S08000015,,New Outpatient,C8,,1200,,400,,85,,250,",  # good board row
    "3,20260630,S08000015,,Inpatient/Day case,C8,,-5,,,,10,,20,",  # negative count -> drop
    "4,20260630,S08000016,,New Outpatient,C8,,100,,150,,40,,90,",  # over12 > total -> drop
    "5,20990131,S08000015,,New Outpatient,C8,,10,,1,,5,,9,",  # future month -> drop
    "6,2026-06-30,S08000015,,New Outpatient,C8,,10,,1,,5,,9,",  # bad date -> drop
    "7,20260630,S08000099,,New Outpatient,C8,,10,,1,,50,,9,",  # unknown board, median>p90: warn
    "8,20260531,S08000015,,New Outpatient,C8,,,:,,:,,:,,:",  # suppressed: warn only
    "9,20260630,S08000015,,New Outpatient,C8,,1300,,410,,86,,251,",  # duplicate key of row 2
]
TODAY = date(2026, 10, 9)


def _csv(rows):
    return ("﻿" + "\n".join([HEADER, *rows]) + "\n").encode("utf-8")


def _files(rows=ROWS):
    hb = pd.DataFrame({"HB": ["S08000015", "S08000016"], "HBName": ["NHS Ayrshire", "NHS Borders"]})
    shb = pd.DataFrame({"SHB": ["SB0801"], "SHBName": ["Golden Jubilee"]})
    spec = pd.DataFrame({"Specialty": ["C8"], "SpecialtyName": ["Trauma and Orthopaedic"]})
    return {
        "ongoing_waits": (b"", read_csv(_csv(rows))),
        "health_boards": (b"", hb),
        "special_boards": (b"", shb),
        "specialties": (b"", spec),
    }


def _silver(rows=ROWS):
    f = _files(rows)
    boards = board_lookup(f["health_boards"][1], f["special_boards"][1])
    return to_silver(f["ongoing_waits"][1], boards, specialty_lookup(f["specialties"][1]))


def test_read_csv_strips_bom_and_datastore_id():
    raw = read_csv(_csv(ROWS[:1]))
    assert raw.columns[0] == "MonthEnding"
    assert "_id" not in raw.columns


def test_silver_types_and_enrichment():
    s = _silver()
    assert s.loc[0, "month_ending"] == pd.Timestamp("2026-06-30")
    assert s.loc[0, "board_name"] == "Scotland" and s.loc[0, "is_scotland"]
    assert s.loc[0, "is_all_specialties"]
    assert s.loc[1, "board_name"] == "NHS Ayrshire"
    assert s.loc[1, "specialty_name"] == "Trauma and Orthopaedic"
    assert s.loc[1, "share_over_12_weeks"] == pytest.approx(400 / 1200)
    assert pd.isna(s.loc[7, "number_waiting"])  # blank with ':' qualifier


def test_expectations_drop_bad_rows_and_warn_on_others():
    kept, rejects, results = dq.apply(_silver(), dq.expectations(TODAY))
    failed = {r["expectation"]: r["failed_rows"] for r in results}
    assert failed["non_negative_counts"] == 1
    assert failed["over_12_weeks_within_total"] == 1
    assert failed["month_not_in_future"] == 1
    assert failed["valid_month"] == 1
    assert failed["unique_key"] == 1
    assert failed["known_board"] == 1  # warn
    assert failed["median_not_above_p90"] == 1  # warn
    assert failed["count_present"] == 1  # warn
    assert len(rejects) == 5
    assert len(kept) == 4  # Scotland, board row (revised), unknown board, suppressed
    # the later duplicate wins: PHS revisions come later in the file
    board = kept[(kept["hbt"] == "S08000015") & (kept["month_ending"] == "2026-06-30")]
    assert board["number_waiting"].tolist() == [1300]
    assert "non_negative_counts" in set(rejects["failed_expectations"])


def test_missing_column_raises_schema_error():
    f = _files()
    raw = f["ongoing_waits"][1].drop(columns=["Median"])
    with pytest.raises(SchemaError):
        to_silver(raw, {}, {})


def test_freshness_flags_old_data():
    kept, _, _ = dq.apply(_silver(), dq.expectations(TODAY))
    assert dq.freshness(kept, today=TODAY)["failed_rows"] == 0
    assert dq.freshness(kept, today=date(2027, 6, 1))["failed_rows"] == 1


def test_build_and_summary_end_to_end():
    raw, kept, rejects, results = build(_files())
    s = summary(raw, kept, rejects, results)
    assert s["raw_rows"] == 9
    assert s["silver_rows"] + s["rejected_rows"] == 9
    assert s["scotland_all_specialty_rows"] == 1


def test_resources_are_unique_https_csv_sources():
    assert len({r.file_name for r in RESOURCES}) == len(RESOURCES)
    assert all(r.url.startswith("https://www.opendata.nhs.scot/") for r in RESOURCES)


def test_windows_1252_lookup_with_non_breaking_space():
    data = "SHB,SHBName,Country\nSB0801,Golden\xa0Jubilee ,S92000003\n".encode("cp1252")
    df = read_csv(data)
    assert df.loc[0, "SHBName"] == "Golden Jubilee"
