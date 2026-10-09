"""Scan text for patient-identifying data before it reaches the knowledge base.

Organisational contact details (service phone numbers, hospital addresses,
generic mailboxes) are expected in leaflets and are not flagged. The scan looks
for identifiers that belong to an individual patient.

high severity -> the whole document is quarantined, never indexed
low severity  -> recorded for review, document still indexed
"""

import re

from careconnect.ingest.models import PiiFinding, ScanResult

# CHI number: date of birth DDMMYY followed by 4 digits, optionally spaced.
_CHI = re.compile(r"\b(0[1-9]|[12]\d|3[01])(0[1-9]|1[0-2])\d{2}\s?\d{4}\b")
# UK National Insurance number.
_NINO = re.compile(
    r"\b(?!BG|GB|NK|KN|TN|NT|ZZ)[A-CEGHJ-PR-TY-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b"
)
# A labelled personal field with a value, e.g. "Patient name: Jane Doe", "DOB: 01/02/1960".
_LABELLED = re.compile(
    r"\b(patient name|patient's name|date of birth|dob|chi number|chi no\.?|nhs number)"
    r"\s*[:=]\s*[\w/.-]+",
    re.IGNORECASE,
)
_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+\.)+[a-z]{2,}\b", re.IGNORECASE)
_ORG_EMAIL_DOMAINS = (".example", "gov.scot", "nhs.scot", "nhs.net", "nhs.uk", "spso.org.uk")


def _excerpt(text: str, start: int, end: int, width: int = 20) -> str:
    """Short context with the matched value masked, so findings never store the PII itself."""
    before = text[max(0, start - width) : start]
    after = text[end : end + width]
    return f"...{before}[REDACTED]{after}...".replace("\n", " ")


def scan(text: str) -> ScanResult:
    result = ScanResult()
    for m in _CHI.finditer(text):
        result.findings.append(PiiFinding("chi_number", "high", _excerpt(text, *m.span())))
    for m in _NINO.finditer(text):
        result.findings.append(PiiFinding("ni_number", "high", _excerpt(text, *m.span())))
    for m in _LABELLED.finditer(text):
        result.findings.append(
            PiiFinding("labelled_personal_field", "high", _excerpt(text, *m.span()))
        )
    for m in _EMAIL.finditer(text):
        domain = m.group(0).split("@", 1)[1].lower()
        if not domain.endswith(_ORG_EMAIL_DOMAINS):
            result.findings.append(PiiFinding("email_address", "low", _excerpt(text, *m.span())))
    return result
