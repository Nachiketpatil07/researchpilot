"""load -> chunk -> contextualize -> embed + index."""

import logging
import time
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..llm import LLM
from ..retrieval.store import VectorStore
from .chunker import chunk_document
from .contextualizer import contextualize
from .loaders import load_file

log = logging.getLogger(__name__)


@dataclass
class IngestReport:
    doc_id: str
    title: str
    source: str
    pages: int
    chunks: int
    summary: str
    skipped: bool
    seconds: float


def ingest_file(
    path: Path,
    store: VectorStore,
    settings: Settings,
    llm: LLM | None,
    force: bool = False,
) -> IngestReport:
    t = time.perf_counter()
    doc = load_file(path)

    if store.has_document(doc.doc_id):
        if not force:
            return IngestReport(doc.doc_id, doc.title, doc.source, len(doc.pages), 0, "", True, 0.0)
        store.delete_document(doc.doc_id)

    chunks = chunk_document(doc, settings.chunk_size, settings.chunk_overlap)
    summary = contextualize(doc, chunks, llm, settings.context_mode)
    store.upsert(chunks)

    report = IngestReport(
        doc_id=doc.doc_id,
        title=doc.title,
        source=doc.source,
        pages=len(doc.pages),
        chunks=len(chunks),
        summary=summary,
        skipped=False,
        seconds=round(time.perf_counter() - t, 2),
    )
    log.info("Indexed %s: %d chunks in %.1fs", doc.source, len(chunks), report.seconds)
    return report
