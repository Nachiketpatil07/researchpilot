"""Synthetic test set: sample chunks, have an LLM write a question each chunk answers.

Each item remembers the chunk it came from, which gives retrieval a ground truth:
a good retriever should rank that chunk near the top for its question.
"""

import json
import logging
import random
import re
from collections import defaultdict

from ..llm import LLM
from ..services import Services
from . import EVAL_DIR, TESTSET_PATH, prompts

log = logging.getLogger(__name__)

MIN_CHARS = 600


def _looks_like_boilerplate(text: str) -> bool:
    """Reference lists, numeric tables and prompt templates make poor questions."""
    years = len(re.findall(r"\b(19|20)\d\d\b", text))
    et_al = text.count("et al")
    digits = sum(c.isdigit() for c in text) / max(len(text), 1)
    return years > 8 or et_al > 5 or digits > 0.2


_POINTS_AT_SOURCE = re.compile(
    r"\b(the|this) (passage|paper|text|excerpt|section|study)\b|\b(table|figure|fig\.|appendix) ?\d+"
    r"|\bet al\b|\bpaper by\b",  # questions about cited references, not the paper itself
    re.IGNORECASE,
)


def _validate(llm: LLM, title: str, q: str, a: str) -> tuple[bool, str]:
    """Quality gate: cheap phrase check first, then an LLM review."""
    if _POINTS_AT_SOURCE.search(q):
        return False, "points at the source or a cited reference (passage/table/figure/et al.)"
    try:
        out = llm.complete_json([{
            "role": "user", "content": prompts.VALIDATE.format(title=title, question=q, answer=a),
        }], tier="fast", max_tokens=200)
    except Exception as exc:
        return False, f"validator failed: {exc}"
    return bool(out.get("keep")), str(out.get("reason", ""))


def _all_chunks(services: Services) -> list[dict]:
    store = services.store
    chunks, offset = [], None
    while True:
        points, offset = store.client.scroll(
            store.name, limit=256, offset=offset, with_payload=True, with_vectors=False
        )
        chunks.extend(p.payload for p in points)
        if offset is None:
            return chunks


def generate_testset(services: Services, llm: LLM, n: int = 30, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    by_doc: dict[str, list[dict]] = defaultdict(list)
    for c in _all_chunks(services):
        if len(c["text"]) >= MIN_CHARS and not _looks_like_boilerplate(c["text"]):
            by_doc[c["doc_id"]].append(c)
    for pool in by_doc.values():
        pool.sort(key=lambda c: c["index"])  # deterministic before shuffling
        rng.shuffle(pool)

    # Round-robin across documents so every paper is represented equally.
    items: list[dict] = []
    docs = sorted(by_doc)
    attempts = 0
    rejected = 0
    while len(items) < n and any(by_doc.values()) and attempts < n * 4:
        for doc_id in docs:
            if len(items) >= n or not by_doc[doc_id]:
                continue
            chunk = by_doc[doc_id].pop()
            attempts += 1
            pages = (f"{chunk['page_start']}" if chunk["page_start"] == chunk["page_end"]
                     else f"{chunk['page_start']}-{chunk['page_end']}")
            try:
                out = llm.complete_json([{
                    "role": "user",
                    "content": prompts.QUESTION.format(title=chunk["title"], pages=pages, text=chunk["text"]),
                }], tier="fast", max_tokens=400)
            except Exception as exc:
                log.warning("question generation failed: %s", exc)
                continue
            q, a = (out.get("question") or "").strip(), (out.get("answer") or "").strip()
            if out.get("skip") or not q or not a:
                continue
            keep, reason = _validate(llm, chunk["title"], q, a)
            if not keep:
                rejected += 1
                print(f"  rejected [{chunk['source']} p.{pages}] {q}\n           -> {reason}")
                continue
            items.append({
                "id": f"q{len(items) + 1:02d}",
                "question": q,
                "reference": a,
                "doc_id": chunk["doc_id"],
                "source": chunk["source"],
                "title": chunk["title"],
                "pages": pages,
                "chunk_id": chunk["chunk_id"],
                "chunk_text": chunk["text"],
            })
            print(f"  {items[-1]['id']} [{chunk['source']} p.{pages}] {q}")
    print(f"Kept {len(items)}, rejected {rejected} by the quality gate ({attempts} chunks tried)")
    return items


def save_testset(items: list[dict]) -> None:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    TESTSET_PATH.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def load_testset() -> list[dict]:
    if not TESTSET_PATH.exists():
        raise FileNotFoundError("No test set yet. Run: python -m app.cli eval-generate")
    return json.loads(TESTSET_PATH.read_text(encoding="utf-8"))
