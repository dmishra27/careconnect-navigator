"""Plain data structures shared by the ingest steps (no Spark dependency)."""

from dataclasses import dataclass, field


@dataclass
class Section:
    """A run of text under one heading path, e.g. 'Making a complaint > Time limits'."""

    heading_path: list[str]
    text: str
    page: int | None = None


@dataclass
class Document:
    doc_id: str
    source_path: str
    source_type: str  # "leaflet" or "policy"
    title: str
    content_hash: str
    raw_text: str
    sections: list[Section]
    status: str = "current"
    effective_date: str | None = None
    review_date: str | None = None
    service: str | None = None
    audience: str | None = None
    source_url: str | None = None
    licence: str | None = None


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    chunk_index: int
    title: str
    section_path: str
    text: str  # chunk body with a "Title > Section" context line prepended
    token_count: int
    page: int | None
    source_type: str
    status: str
    effective_date: str | None
    service: str | None
    audience: str | None
    source_url: str | None


@dataclass
class PiiFinding:
    kind: str
    severity: str  # "high" quarantines the document, "low" is recorded only
    excerpt: str


@dataclass
class ScanResult:
    findings: list[PiiFinding] = field(default_factory=list)

    @property
    def quarantine(self) -> bool:
        return any(f.severity == "high" for f in self.findings)
