"""Split documents into overlapping chunks that remember their page numbers."""

import re
import uuid
from dataclasses import asdict, dataclass

from .loaders import LoadedDocument

_NAMESPACE = uuid.UUID("6f1c2a52-6b8e-4c4f-9a43-2b1f7c0d9e11")


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    source: str
    index: int
    text: str
    page_start: int
    page_end: int
    context: str = ""  # filled in by the contextualizer

    def embed_text(self) -> str:
        """What actually gets embedded: situating context + the chunk itself."""
        return f"{self.context}\n\n{self.text}" if self.context else self.text

    def to_payload(self) -> dict:
        return asdict(self)


@dataclass
class _Unit:
    text: str
    page: int


def _split_long(text: str, max_len: int) -> list[str]:
    """Split text into sentence-sized pieces no longer than max_len."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    pieces: list[str] = []
    for s in sentences:
        while len(s) > max_len:  # pathological sentence: hard split
            pieces.append(s[:max_len])
            s = s[max_len:]
        if s:
            pieces.append(s)
    return pieces


def _units(doc: LoadedDocument, max_len: int) -> list[_Unit]:
    units: list[_Unit] = []
    for page in doc.pages:
        for para in re.split(r"\n\s*\n", page.text):
            para = re.sub(r"\s*\n\s*", " ", para).strip()
            if not para:
                continue
            # Sentence-level units keep chunk boundaries from cutting sentences.
            for piece in _split_long(para, max_len // 2):
                units.append(_Unit(piece, page.number))
    return units


def chunk_document(doc: LoadedDocument, chunk_size: int = 1200, overlap: int = 200) -> list[Chunk]:
    units = _units(doc, chunk_size)
    chunks: list[Chunk] = []
    current: list[_Unit] = []
    length = 0

    def emit() -> None:
        text = " ".join(u.text for u in current).strip()
        if not text:
            return
        idx = len(chunks)
        chunks.append(
            Chunk(
                chunk_id=str(uuid.uuid5(_NAMESPACE, f"{doc.doc_id}:{idx}")),
                doc_id=doc.doc_id,
                title=doc.title,
                source=doc.source,
                index=idx,
                text=text,
                page_start=current[0].page,
                page_end=current[-1].page,
            )
        )

    for unit in units:
        if current and length + len(unit.text) + 1 > chunk_size:
            emit()
            # Carry the tail of the previous chunk forward as overlap.
            tail: list[_Unit] = []
            tail_len = 0
            for u in reversed(current):
                if tail_len + len(u.text) > overlap:
                    break
                tail.insert(0, u)
                tail_len += len(u.text) + 1
            current, length = tail, tail_len
        current.append(unit)
        length += len(unit.text) + 1

    emit()
    return chunks
