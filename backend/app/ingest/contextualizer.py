"""Contextual retrieval: give each chunk a short note about where it sits.

A chunk like "It improves recall by 12%" is useless on its own. Prepending
"From the Self-RAG paper, section on retrieval evaluation" before embedding
makes it findable. Two modes:

- header: one LLM call per document -> a 2-sentence summary shared by all its
  chunks. Cheap, fits comfortably in free-tier rate limits.
- full:   one LLM call per chunk (Anthropic's "contextual retrieval" recipe).
  Best quality, but slow on free tiers for big documents.
"""

import logging

from ..llm import LLM
from .chunker import Chunk
from .loaders import LoadedDocument

log = logging.getLogger(__name__)

DOC_EXCERPT_CHARS = 6000

SUMMARY_PROMPT = """Here is the beginning of a document titled "{title}":

<document>
{excerpt}
</document>

In at most two sentences, say what this document is about and its main contribution.
Reply with the two sentences only."""

CHUNK_PROMPT = """<document title="{title}">
{excerpt}
</document>

Here is a chunk from that document:
<chunk>
{chunk}
</chunk>

Write one short sentence that situates this chunk within the overall document, to
improve search retrieval of the chunk. Reply with that sentence only."""


def contextualize(doc: LoadedDocument, chunks: list[Chunk], llm: LLM | None, mode: str) -> str:
    """Fill chunk.context in place. Returns the document summary ('' if none)."""
    mode = mode.lower()
    if mode == "off" or not chunks:
        return ""

    excerpt = doc.full_text[:DOC_EXCERPT_CHARS]
    summary = ""
    if llm is not None:
        try:
            summary = llm.complete(
                [{"role": "user", "content": SUMMARY_PROMPT.format(title=doc.title, excerpt=excerpt)}],
                tier="fast",
                max_tokens=150,
            )
        except Exception as exc:  # degrade gracefully: title-only context
            log.warning("Document summary failed for %s: %s", doc.source, exc)

    header = f"Document: {doc.title}." + (f" {summary}" if summary else "")

    for chunk in chunks:
        pages = f"p. {chunk.page_start}" if chunk.page_start == chunk.page_end else f"pp. {chunk.page_start}-{chunk.page_end}"
        chunk.context = f"{header} ({pages})"

    if mode == "full" and llm is not None:
        for chunk in chunks:
            try:
                note = llm.complete(
                    [{
                        "role": "user",
                        "content": CHUNK_PROMPT.format(title=doc.title, excerpt=excerpt, chunk=chunk.text),
                    }],
                    tier="fast",
                    max_tokens=80,
                )
                chunk.context = f"{chunk.context} {note}"
            except Exception as exc:
                log.warning("Chunk context failed (%s #%d): %s", doc.source, chunk.index, exc)

    return summary
