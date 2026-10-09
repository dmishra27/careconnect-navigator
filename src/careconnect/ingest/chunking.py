"""Heading-aware chunking with a token budget and overlap.

Each section (text under one heading path) is chunked on its own, so a chunk
never mixes two topics. Paragraphs are packed greedily up to ``max_tokens``;
paragraphs longer than the budget are split into sentences. The last
``overlap_tokens`` of each chunk are repeated at the start of the next one.
Every chunk gets a context line "Title > Section" so it stands alone in search.
"""

import re

from careconnect.ingest.models import Chunk, Document

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def count_tokens(text: str) -> int:
    """Cheap, deterministic token estimate (~1.3 tokens per word for English)."""
    return max(1, round(len(text.split()) * 1.3))


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


def _pack(units: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for unit in units:
        n = count_tokens(unit)
        if current and size + n > max_tokens:
            chunks.append("\n\n".join(current))
            carry: list[str] = []
            carried = 0
            for prev in reversed(current):
                c = count_tokens(prev)
                if carried + c > overlap_tokens:
                    break
                carry.insert(0, prev)
                carried += c
            current, size = carry, carried
        current.append(unit)
        size += n
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def chunk_document(doc: Document, max_tokens: int = 400, overlap_tokens: int = 60) -> list[Chunk]:
    if overlap_tokens >= max_tokens:
        raise ValueError("overlap_tokens must be smaller than max_tokens")
    chunks: list[Chunk] = []
    for section in doc.sections:
        section_path = " > ".join(section.heading_path)
        for body in _pack(_units(section.text, max_tokens), max_tokens, overlap_tokens):
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
                    page=section.page,
                    source_type=doc.source_type,
                    status=doc.status,
                    effective_date=doc.effective_date,
                    service=doc.service,
                    audience=doc.audience,
                    source_url=doc.source_url,
                )
            )
    return chunks
