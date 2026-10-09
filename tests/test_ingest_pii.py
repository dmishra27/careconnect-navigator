from pathlib import Path

import pytest

from careconnect.ingest.pii import scan

LEAFLETS = Path(__file__).resolve().parents[1] / "data" / "raw" / "leaflets"


@pytest.mark.parametrize(
    "text, kind",
    [
        ("Patient CHI 0101601234 attended clinic.", "chi_number"),
        ("CHI: 310175 4321 on the referral.", "chi_number"),
        ("NI number AB 12 34 56 C recorded.", "ni_number"),
        ("Patient name: Jane Doe, seen on Monday.", "labelled_personal_field"),
        ("DOB: 01/02/1960", "labelled_personal_field"),
    ],
)
def test_patient_identifiers_quarantine(text, kind):
    result = scan(text)
    assert result.quarantine
    assert any(f.kind == kind for f in result.findings)


def test_excerpt_never_contains_the_identifier():
    result = scan("Patient CHI 0101601234 attended clinic.")
    assert all("0101601234" not in f.excerpt for f in result.findings)


def test_service_contact_details_are_not_flagged():
    text = (
        "Call 01632 960 100 or email patientservices@firthvalley.example. "
        "Write to Royal Infirmary Road, Larbank FV1 4QX. Have your date of birth ready."
    )
    assert scan(text).findings == []


def test_personal_email_is_low_severity_only():
    result = scan("Contact jane.doe@gmail.com for details.")
    assert not result.quarantine
    assert result.findings[0].kind == "email_address"


@pytest.mark.parametrize("path", sorted(LEAFLETS.glob("*.md")), ids=lambda p: p.name)
def test_no_leaflet_is_quarantined(path):
    assert not scan(path.read_text(encoding="utf-8")).quarantine
