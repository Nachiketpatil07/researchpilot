"""Grounded answer generation with numbered, checkable citations."""

import re
from collections.abc import Iterator

from ..llm import LLM
from ..retrieval.store import Hit

SYSTEM_PROMPT = """You are ResearchPilot, a research assistant that answers strictly from the provided sources.

Rules:
- Use only facts stated in the sources. Do not use outside knowledge.
- Sources marked "web:" are short search-result snippets; prefer document sources when both cover a point.
- Cite every factual sentence with the source number in plain square brackets, e.g. [2] or [1][3].
  Use exactly that format: no other citation styles, line numbers or special brackets.
- If the sources do not contain enough information, say exactly what is missing instead of guessing.
- Be concise: a short direct answer first, then supporting detail if useful.
- Use Markdown for lists or emphasis when it helps readability."""


def format_sources(hits: list[Hit]) -> str:
    blocks = []
    for i, h in enumerate(hits, start=1):
        where = f"web: {h.url}" if h.url else h.pages
        blocks.append(f"[{i}] {h.title} ({where})\n{h.text}")
    return "\n\n---\n\n".join(blocks)


def build_messages(question: str, hits: list[Hit]) -> list[dict]:
    user = f"<sources>\n{format_sources(hits)}\n</sources>\n\nQuestion: {question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


# gpt-oss models sometimes fall back to their native citation style: 【4†L1-L4】
_NATIVE_CITE = re.compile(r"【(\d+)[^】]*】")


def normalize_citations(tokens: Iterator[str]) -> Iterator[str]:
    """Rewrite 【n†...】 to [n] on the fly. Holds back text only while inside a 【...】."""
    buf = ""
    for tok in tokens:
        # Models like to emit non-breaking hyphens/spaces; plain ones copy and search better.
        buf += tok.replace("‑", "-").replace(" ", " ").replace(" ", " ")
        start = buf.find("【")
        if start == -1:
            yield buf
            buf = ""
            continue
        end = buf.find("】", start)
        if end == -1:
            if start:  # emit everything before the open bracket, keep the rest
                yield buf[:start]
                buf = buf[start:]
            continue
        yield _NATIVE_CITE.sub(r"[\1]", buf[: end + 1])
        buf = buf[end + 1 :]
    if buf:
        yield _NATIVE_CITE.sub(r"[\1]", buf)


def stream_answer(llm: LLM, question: str, hits: list[Hit]) -> Iterator[str]:
    if not hits:
        yield "I couldn't find anything relevant in the indexed documents. Try uploading a document that covers this topic."
        return
    yield from normalize_citations(llm.stream(build_messages(question, hits), tier="answer", max_tokens=1200))


def answer(llm: LLM, question: str, hits: list[Hit]) -> str:
    return "".join(stream_answer(llm, question, hits))


def cited_numbers(text: str, n_sources: int) -> list[int]:
    """Source numbers actually cited in the answer (ignores out-of-range numbers)."""
    nums = {int(n) for n in re.findall(r"\[(\d+)\]", text)}
    return sorted(n for n in nums if 1 <= n <= n_sources)
