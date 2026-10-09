from pathlib import Path

from careconnect.ingest.parsing import (
    clean_pdf_pages,
    markdown_sections,
    parse_markdown,
    pdf_sections,
    split_front_matter,
)

ROOT = Path(__file__).resolve().parents[1]
LEAFLETS = ROOT / "data" / "raw" / "leaflets"


def test_front_matter_is_split_from_body():
    meta, body = split_front_matter("---\ntitle: Hello\nstatus: current\n---\n# Hello\n\nText")
    assert meta == {"title": "Hello", "status": "current"}
    assert body.strip().startswith("# Hello")


def test_markdown_sections_keep_heading_path():
    body = (
        "# Guide\n\nIntro text.\n\n## Parking\n\nFree parking.\n\n"
        "### Blue Badge\n\nReserved spaces."
    )
    sections = markdown_sections(body, "Guide")
    assert [s.heading_path for s in sections] == [
        ["Guide"],
        ["Guide", "Parking"],
        ["Guide", "Parking", "Blue Badge"],
    ]
    assert sections[2].text == "Reserved spaces."


def test_real_leaflet_metadata():
    path = LEAFLETS / "16_making-a-complaint.md"
    doc = parse_markdown(str(path), path.read_bytes())
    assert doc.doc_id == "fvhb-16"
    assert doc.source_type == "leaflet"
    assert doc.status == "current"
    assert doc.effective_date == "2026-04-01"
    assert doc.service == "feedback"
    assert "Stage 1, early resolution" in doc.raw_text
    assert any(s.heading_path[-1] == "Time limits" for s in doc.sections)


def test_superseded_leaflet_is_marked():
    path = LEAFLETS / "02_booking-and-changing-appointments_2024.md"
    doc = parse_markdown(str(path), path.read_bytes())
    assert doc.status == "superseded"
    assert doc.doc_id == "fvhb-02-v1"


def test_pdf_cleaning_removes_running_headers_and_page_numbers():
    pages = [
        "NHS Guidance 2023\n1. Introduction\n"
        "The guarantee applies to all-\nowed patients.\nPage 1 of 4",
        "NHS Guidance 2023\nMore text here.\n2",
        "NHS Guidance 2023\n2. Purpose\nWhy we publish this.\n3",
        "NHS Guidance 2023\nClosing text.\n4",
    ]
    cleaned = clean_pdf_pages(pages)
    joined = "\n".join(cleaned)
    assert "NHS Guidance 2023" not in joined
    assert "Page 1 of 4" not in joined
    assert "allowed patients" in joined


def test_pdf_sections_detect_numbered_headings():
    pages = [
        "1. Introduction\nThe Treatment Time Guarantee\nis 12 weeks.",
        "2. Purpose\nThis guidance explains the rules.",
    ]
    sections = pdf_sections(pages, "Waiting Times Guidance")
    assert [s.heading_path for s in sections] == [
        ["Waiting Times Guidance", "1. Introduction"],
        ["Waiting Times Guidance", "2. Purpose"],
    ]
    assert sections[0].text == "The Treatment Time Guarantee is 12 weeks."
    assert sections[1].page == 2


def test_tiny_pdf_fragments_are_folded_into_next_section():
    pages = [
        "1. Introduction\nContents\n2. Purpose\nThis guidance explains the waiting time rules."
    ]
    sections = pdf_sections(pages, "Guide")
    assert len(sections) == 1
    assert sections[0].heading_path == ["Guide", "2. Purpose"]
    assert sections[0].text.startswith("Contents This guidance")
