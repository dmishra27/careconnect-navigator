from datetime import date
from pathlib import Path

from careconnect.ingest.pipeline import _to_rows, build
from careconnect.ingest.sources import SourceReader

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


def test_build_over_local_leaflets():
    result = build(SourceReader(str(RAW)), max_tokens=400, overlap_tokens=60)
    leaflets = [d for d in result.documents if d.source_type == "leaflet"]
    assert len(leaflets) == 22
    assert result.quarantined == []
    assert result.errors == []
    ids = [c.chunk_id for c in result.chunks]
    assert len(ids) == len(set(ids)), "chunk ids must be unique"


def test_rows_follow_schema_order_and_convert_dates():
    ddl = "doc_id STRING NOT NULL, effective_date DATE, page INT"
    rows = _to_rows([{"page": 3, "doc_id": "a", "effective_date": "2026-04-01"}], ddl)
    assert rows == [("a", date(2026, 4, 1), 3)]
