"""Heading-aware chunking with a token budget and overlap.

Each section (text under one heading path) is chunked on its own, so a chunk
never mixes two topics. Paragraphs are packed greedily up to ``max_tokens``;
paragraphs longer than the budget are split into sentences. The last
``overlap_tokens`` of each chunk are repeated at the start of the next one.
Every chunk gets a context line "Title > Section" so it stands alone in search.
"""

import re

from careconnect.ingest.models import PAGE_MARKER_RE, Chunk, Document

# a sentence may also start with a page marker, so a page break is a split point
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\u27e6])")


def count_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~1.3 tokens per word for English)."""
    return max(1, round(len(PAGE_MARKER_RE.sub(" ", text).split()) * 1.3))


def _strip_markers(text: str) -> str:
    return re.sub(r"[ \t]+", " ", PAGE_MARKER_RE.sub(" ", text)).strip()


def _paged_units(units: list[str], first_page: int | None) -> list[tuple[str, int | None]]:
    """Pair each unit (markers removed) with the page its first word is on."""
    paged: list[tuple[str, int | None]] = []
    page = first_page
    for unit in units:
        start = PAGE_MARKER_RE.match(unit)  # marker before any word: unit starts on that page
        unit_page = int(start.group(1)) if start else page
        markers = PAGE_MARKER_RE.findall(unit)
        if markers:
            page = int(markers[-1])
        text = _strip_markers(unit)
        if text:
            paged.append((text, unit_page))
    return paged


def _units(text: str, max_tokens: int) -> list[str]:
    """Paragraphs (or list items), with over-long ones split into sentences."""
    units: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        if count_tokens(para) <= max_tokens:
            units.append(para)
            continue
        for sent in _SENTENCE_END.split(para):
            sent = sent.strip()
            if not sent:
                continue
            if count_tokens(sent) <= max_tokens:
                units.append(sent)
            else:  # pathological sentence: hard split by words
                words = sent.split()
                step = int(max_tokens / 1.3)
                units.extend(" ".join(words[i : i + step]) for i in range(0, len(words), step))
    return units


def _size(parts: list[str]) -> int:
    """Token estimate of parts joined into one chunk (measured, not summed, to avoid drift)."""
    return count_tokens("\n\n".join(parts)) if parts else 0


def _pack(units: list[str], max_tokens: int, overlap_tokens: int) -> list[list[int]]:
    """Group unit indices into chunks; returns index lists so callers can recover pages."""

    def size(idx: list[int]) -> int:
        return _size([units[i] for i in idx])

    chunks: list[list[int]] = []
    current: list[int] = []
    for i in range(len(units)):
        if current and size(current + [i]) > max_tokens:
            chunks.append(current)
            # carry trailing units as overlap, newest first, within the overlap budget
            carry: list[int] = []
            for prev in reversed(current):
                if size([prev] + carry) > overlap_tokens:
                    break
                carry.insert(0, prev)
            # drop overlap from the front if it would push the next chunk over budget
            while carry and size(carry + [i]) > max_tokens:
                carry.pop(0)
            current = carry
        current.append(i)
    if current:
        chunks.append(current)
    return chunks


def chunk_document(doc: Document, max_tokens: int = 400, overlap_tokens: int = 60) -> list[Chunk]:
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")
    chunks: list[Chunk] = []
    for section in doc.sections:
        section_path = " > ".join(section.heading_path)
        paged = _paged_units(_units(section.text, max_tokens), section.page)
        texts = [text for text, _ in paged]
        for group in _pack(texts, max_tokens, overlap_tokens):
            body = "\n\n".join(texts[i] for i in group)
            idx = len(chunks)
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.doc_id}-{idx:04d}",
                    doc_id=doc.doc_id,
                    chunk_index=idx,
                    title=doc.title,
                    section_path=section_path,
                    text=f"{section_path}\n\n{body}",
                    token_count=count_tokens(body),
                    page=paged[group[0]][1],
                    source_type=doc.source_type,
                    status=doc.status,
                    effective_date=doc.effective_date,
                    service=doc.service,
                    audience=doc.audience,
                    source_url=doc.source_url,
                )
            )
    return chunks
