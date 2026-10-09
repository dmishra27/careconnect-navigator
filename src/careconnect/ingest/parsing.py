"""Turn raw Markdown leaflets and PDF policies into cleaned, sectioned Documents."""

import hashlib
import io
import re
from collections import Counter

import yaml

from careconnect.ingest.models import PAGE_MARKER, PAGE_MARKER_RE, Document, Section

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_NUMBERED_HEADING = re.compile(r"^(\d{1,2}(\.\d{1,2}){0,2})\.?\s+([A-Z][^.!?]{2,80})$")
_KEYWORD_HEADING = re.compile(r"^(Annex|Appendix|Part|Section|Chapter|Schedule)\s+[\w.]+\b.{0,70}$")
# contents-page entry: "Appendix 3: Assessment Matrix .. 46" or "1. Introduction ....... 4"
_TOC_LINE = re.compile(r"(\.\s?){2,}\s*\d{1,3}\s*$")
_PAGE_NUMBER = re.compile(r"^\s*(page\s*)?\d{1,3}(\s*(of|/)\s*\d{1,3})?\s*$", re.IGNORECASE)


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ---------------------------------------------------------------- Markdown


def split_front_matter(text: str) -> tuple[dict, str]:
    """Return (metadata, body) for a Markdown file with optional YAML front matter."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return yaml.safe_load(parts[1]) or {}, parts[2]
    return {}, text


def markdown_sections(body: str, title: str) -> list[Section]:
    """Split Markdown into sections keyed by their heading path."""
    sections: list[Section] = []
    path: list[str] = []
    buf: list[str] = []

    def flush():
        text = normalise_whitespace("\n".join(buf))
        if text:
            sections.append(Section(heading_path=list(path) or [title], text=text))
        buf.clear()

    for line in body.splitlines():
        m = _MD_HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            path[:] = path[: level - 1] + [m.group(2).strip()]
        else:
            buf.append(line)
    flush()
    return sections


def parse_markdown(path: str, data: bytes) -> Document:
    text = data.decode("utf-8")
    meta, body = split_front_matter(text)
    title = str(meta.get("title") or path.rsplit("/", 1)[-1])
    return Document(
        doc_id=str(meta.get("doc_id") or path.rsplit("/", 1)[-1].removesuffix(".md")),
        source_path=path,
        source_type="leaflet",
        title=title,
        content_hash=content_hash(data),
        raw_text=normalise_whitespace(body),
        sections=markdown_sections(body, title),
        status=str(meta.get("status", "current")),
        effective_date=str(meta["effective_date"]) if meta.get("effective_date") else None,
        review_date=str(meta["review_date"]) if meta.get("review_date") else None,
        service=meta.get("service"),
        audience=meta.get("audience"),
        licence=meta.get("licence"),
    )


# --------------------------------------------------------------------- PDF


def _is_pdf_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 90 or line.endswith((".", ",", ";")):
        return False
    if _NUMBERED_HEADING.match(line) or _KEYWORD_HEADING.match(line):
        return True
    words = line.split()
    return 1 <= len(words) <= 8 and line.isupper() and any(c.isalpha() for c in line)


def clean_pdf_pages(pages: list[str]) -> list[str]:
    """Remove page numbers and running headers/footers, fix hyphenation."""
    line_counts: Counter[str] = Counter()
    split_pages = [[ln.strip() for ln in p.splitlines()] for p in pages]
    for lines in split_pages:
        line_counts.update({ln for ln in lines if ln})
    threshold = max(3, int(0.5 * len(pages)))
    repeated = {ln for ln, n in line_counts.items() if n >= threshold and len(ln) < 120}

    cleaned = []
    for lines in split_pages:
        kept = [
            ln
            for ln in lines
            if ln and ln not in repeated and not _PAGE_NUMBER.match(ln) and not _TOC_LINE.search(ln)
        ]
        text = "\n".join(kept)
        text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join hyphenated words
        cleaned.append(text)
    return cleaned


def pdf_sections(pages: list[str], title: str) -> list[Section]:
    """Detect headings in cleaned page text; paragraphs are rebuilt from wrapped lines."""
    sections: list[Section] = []
    heading = title
    buf: list[str] = []
    start_page = 1

    def flush(page: int):
        if buf:
            text = normalise_whitespace(" ".join(buf))
            text = re.sub(r"\s*•\s*", "\n- ", text)  # bullet characters become list items
            if text:
                path = [title] if heading == title else [title, heading]
                sections.append(Section(heading_path=path, text=text, page=page))
        buf.clear()

    lines = [(n, ln) for n, page in enumerate(pages, start=1) for ln in page.splitlines()]
    buf_page = 1  # page of the last line added to buf
    for i, (page_no, line) in enumerate(lines):
        # a "heading" followed by a lowercase line is really a wrapped sentence
        nxt = lines[i + 1][1].lstrip() if i + 1 < len(lines) else ""
        if _is_pdf_heading(line) and not nxt[:1].islower():
                flush(start_page)
                heading = line.strip()
                start_page = page_no
            else:
                if not buf:
                    start_page = page_no
                elif page_no != buf_page:
                    buf.append(PAGE_MARKER.format(page_no))  # section continues on a new page
                buf.append(line.strip())
                buf_page = page_no
    flush(start_page)
    return _merge_tiny_sections(sections)


MIN_PDF_SECTION_WORDS = 4


def _merge_tiny_sections(sections: list[Section]) -> list[Section]:
    """Fold PDF fragments shorter than MIN_PDF_SECTION_WORDS into the following section.

    Stray lines between two headings (a lone label, a contents entry) would
    otherwise become near-empty chunks that only add noise to search.
    """
    merged: list[Section] = []
    pending = ""
    for sec in sections:
        text = f"{pending} {sec.text}".strip() if pending else sec.text
        if len(PAGE_MARKER_RE.sub(" ", text).split()) < MIN_PDF_SECTION_WORDS:
            pending = text
            continue
        merged.append(Section(heading_path=sec.heading_path, text=text, page=sec.page))
        pending = ""
    if pending:  # trailing fragment: attach to the last section, or keep if it is all there is
        if merged:
            last = merged[-1]
            merged[-1] = Section(last.heading_path, f"{last.text} {pending}", last.page)
        else:
            merged.append(Section(sections[-1].heading_path, pending, sections[-1].page))
    return merged


def extract_pdf_pages(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return [page.extract_text() or "" for page in reader.pages]


def parse_pdf(path: str, data: bytes, manifest: dict[str, dict] | None = None) -> Document:
    name = path.rsplit("/", 1)[-1]
    info = (manifest or {}).get(name, {})
    title = info.get("title") or name.removesuffix(".pdf").replace("-", " ").title()
    pages = clean_pdf_pages(extract_pdf_pages(data))
    return Document(
        doc_id="policy-" + name.removesuffix(".pdf"),
        source_path=path,
        source_type="policy",
        title=title,
        content_hash=content_hash(data),
        raw_text=normalise_whitespace("\n\n".join(pages)),
        sections=pdf_sections(pages, title),
        status="current",
        source_url=info.get("url"),
        licence=info.get("licence"),
    )
