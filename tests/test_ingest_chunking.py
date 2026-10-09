from pathlib import Path

import pytest

from careconnect.ingest.chunking import chunk_document, count_tokens
from careconnect.ingest.models import Document, Section
from careconnect.ingest.parsing import parse_markdown

LEAFLETS = Path(__file__).resolve().parents[1] / "data" / "raw" / "leaflets"


def _doc(sections):
    return Document(
        doc_id="d1",
        source_path="x",
        source_type="leaflet",
        title="T",
        content_hash="h",
        raw_text="",
        sections=sections,
    )


def test_short_section_is_one_chunk_with_context_line():
    doc = _doc([Section(["Guide", "Parking"], "Parking is free.")])
    chunks = chunk_document(doc, max_tokens=50, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].text == "Guide > Parking\n\nParking is free."
    assert chunks[0].section_path == "Guide > Parking"


def test_chunks_never_cross_sections():
    doc = _doc([Section(["A"], "Alpha text."), Section(["B"], "Beta text.")])
    chunks = chunk_document(doc, max_tokens=400, overlap_tokens=60)
    assert [c.section_path for c in chunks] == ["A", "B"]


def test_long_section_respects_budget_and_overlaps():
    paras = [f"Paragraph {i} " + "word " * 30 for i in range(12)]
    doc = _doc([Section(["Long"], "\n\n".join(paras))])
    chunks = chunk_document(doc, max_tokens=120, overlap_tokens=45)
    assert len(chunks) > 1
    assert all(c.token_count <= 120 for c in chunks)
    # the last paragraph of a chunk is repeated at the start of the next one
    first_body = chunks[0].text.split("\n\n", 1)[1]
    second_body = chunks[1].text.split("\n\n", 1)[1]
    assert first_body.split("\n\n")[-1] == second_body.split("\n\n")[0]


def test_overlap_must_be_smaller_than_budget():
    with pytest.raises(ValueError):
        chunk_document(_doc([Section(["A"], "x")]), max_tokens=50, overlap_tokens=50)


def test_chunk_ids_are_stable_and_ordered():
    doc = _doc([Section(["A"], "one"), Section(["B"], "two")])
    assert [c.chunk_id for c in chunk_document(doc)] == ["d1-0000", "d1-0001"]


def test_all_real_leaflets_chunk_within_budget():
    for path in sorted(LEAFLETS.glob("*.md")):
        doc = parse_markdown(str(path), path.read_bytes())
        chunks = chunk_document(doc, max_tokens=400, overlap_tokens=60)
        assert chunks, path.name
        assert all(count_tokens(c.text.split("\n\n", 1)[1]) <= 400 for c in chunks)
        assert all(c.status == doc.status for c in chunks)
