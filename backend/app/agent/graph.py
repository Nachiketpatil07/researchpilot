"""Agentic RAG as a LangGraph state machine.

    plan ──► retrieve ──► grade ──► generate ──► verify ──► END
      │          ▲          │           ▲
      │          └─ rewrite ◄┤ (nothing relevant, 1 retry)
      │                      │           │
      └──────────────► web_search ───────┘ (still nothing, or planner routed to web)

Ideas borrowed from the papers in the demo corpus: query decomposition, relevance grading
and web fallback (Corrective RAG), and a final groundedness check (Self-RAG).

Every node reports progress through LangGraph's custom stream, so the API can forward
each step to the UI as it happens.
"""

import logging
import re
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import TypedDict

from ddgs import DDGS
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from ..generation.answer import cited_numbers, stream_answer
from ..llm import LLM
from ..retrieval.store import Hit
from ..services import Services
from . import prompts

log = logging.getLogger(__name__)

MAX_REWRITES = 1
MIN_RELEVANT = 2  # relevant chunks needed before answering from documents alone
MAX_SOURCES = 8  # chunks passed to the answer model
RERANK_FLOOR = -3.0  # cross-encoder score below which a chunk is rejected without asking the LLM
WEB_RESULTS = 5
VERIFY_EXCERPT = 800  # characters per source shown to the groundedness check


class AgentState(TypedDict, total=False):
    question: str
    route: str
    queries: list[str]
    tried: list[str]
    candidates: list[Hit]
    found_by: dict[str, str]
    relevant: list[Hit]
    web: list[Hit]
    rewrites: int
    answer: str


def _emit(event: str, **data) -> None:
    get_stream_writer()({"event": event, **data})


class _Step:
    """Context manager that emits running/done (with timing) for a graph node."""

    def __init__(self, stage: str, detail: str):
        self.stage, self.detail = stage, detail

    def __enter__(self):
        self.t = time.perf_counter()
        _emit("step", stage=self.stage, status="running", detail=self.detail)
        return self

    def done(self, detail: str, **extra) -> None:
        ms = round((time.perf_counter() - self.t) * 1000)
        _emit("step", stage=self.stage, status="done", detail=detail, ms=ms, **extra)

    def __exit__(self, exc_type, exc, tb):
        if exc is not None:
            _emit("step", stage=self.stage, status="error", detail=str(exc))
        return False


def build_agent(services: Services, llm: LLM):
    retriever = services.retriever
    top_n = services.settings.rerank_top_n

    # ---------------- nodes ----------------

    def plan(state: AgentState) -> AgentState:
        question = state["question"]
        titles = "\n".join(f"- {d['title']}" for d in services.store.list_documents()) or "(none)"
        with _Step("plan", "Analyzing the question") as step:
            try:
                out = llm.complete_json(
                    [{"role": "user", "content": prompts.PLAN.format(titles=titles, question=question)}]
                )
                route = out.get("route") if out.get("route") in ("docs", "both", "web") else "docs"
                queries = [q.strip() for q in out.get("queries", []) if isinstance(q, str) and q.strip()][:3]
                reason = out.get("reason", "")
            except Exception as exc:  # planning is an optimisation; fall back to a plain search
                log.warning("plan failed: %s", exc)
                route, queries, reason = "docs", [], "planner unavailable, searching directly"
            queries = queries or [question]
            # Guard: if the question names something from an indexed title (e.g. "GraphRAG"),
            # never skip the documents, even when the planner wants the web.
            named = _title_terms(titles) & _words(question)
            if route in ("web", "both") and named:
                if route == "web":
                    reason = f"{reason} Mentions indexed topic(s) {', '.join(sorted(named))}: searching documents too."
                route = "both"
                # Make sure at least one query targets the indexed topic itself.
                for term in sorted(named):
                    if not any(term in q.lower() and "vs" not in q.lower() for q in queries):
                        queries.append(f"How does {term} work: method overview")
                queries = queries[:3]
            if titles == "(none)":
                route = "web"
            step.done(reason or f"route={route}", route=route, queries=queries)
        return {"route": route, "queries": queries, "tried": [], "relevant": [], "web": [], "rewrites": 0}

    def retrieve(state: AgentState) -> AgentState:
        queries = state["queries"]
        seen = {h.chunk_id for h in state.get("relevant", [])}
        merged: dict[str, Hit] = {}
        found_by: dict[str, str] = {}  # chunk_id -> the query whose search scored it highest
        with _Step("retrieve", f"Hybrid search + rerank for {len(queries)} quer{'y' if len(queries) == 1 else 'ies'}") as step:
            for q in queries:
                for h in retriever.retrieve(q, "hybrid_rerank", top_n).hits:
                    if h.chunk_id in seen:
                        continue
                    best = merged.get(h.chunk_id)
                    if best is None or h.scores.get("rerank", 0) > best.scores.get("rerank", 0):
                        merged[h.chunk_id] = h
                        found_by[h.chunk_id] = q
            candidates = sorted(merged.values(), key=lambda h: h.scores.get("rerank", 0), reverse=True)
            step.done(f"{len(candidates)} candidate chunks", queries=queries)
        return {"candidates": candidates, "found_by": found_by, "tried": state.get("tried", []) + queries}

    def grade(state: AgentState) -> AgentState:
        candidates = state.get("candidates", [])
        with _Step("grade", f"Checking relevance of {len(candidates)} chunks") as step:
            plausible = [h for h in candidates if h.scores.get("rerank", 0) >= RERANK_FLOOR]
            rejected_fast = len(candidates) - len(plausible)

            # One grading call per sub-query, in parallel.
            found_by = state.get("found_by", {})
            groups: dict[str, list[Hit]] = {}
            for h in plausible:
                groups.setdefault(found_by.get(h.chunk_id, state["question"]), []).append(h)

            def grade_group(query: str, hits: list[Hit]) -> list[Hit]:
                passages = "\n\n".join(
                    f"[{i}] ({h.title}, {h.pages})\n{h.text[:700]}" for i, h in enumerate(hits, start=1)
                )
                try:
                    out = llm.complete_json([{
                        "role": "user", "content": prompts.GRADE.format(query=query, passages=passages),
                    }])
                    ids = {int(i) for i in out.get("relevant", []) if str(i).isdigit()}
                    return [h for i, h in enumerate(hits, start=1) if i in ids]
                except Exception as exc:  # fall back to the reranker's judgement
                    log.warning("grade failed for %r: %s", query, exc)
                    return [h for h in hits if h.scores.get("rerank", 0) > 0]

            keep: list[Hit] = []
            if groups:
                with ThreadPoolExecutor(max_workers=len(groups)) as pool:
                    for kept in pool.map(lambda kv: grade_group(*kv), groups.items()):
                        keep.extend(kept)
            relevant = sorted(
                state.get("relevant", []) + keep, key=lambda h: h.scores.get("rerank", 0), reverse=True
            )[:MAX_SOURCES]
            step.done(
                f"{len(keep)} relevant, {len(candidates) - len(keep)} rejected"
                + (f" ({rejected_fast} by reranker score)" if rejected_fast else ""),
                relevant=len(relevant),
            )
        return {"relevant": relevant}

    def rewrite(state: AgentState) -> AgentState:
        with _Step("rewrite", "Not enough relevant passages, rewriting the search") as step:
            try:
                out = llm.complete_json([{
                    "role": "user",
                    "content": prompts.REWRITE.format(question=state["question"], tried="; ".join(state["tried"])),
                }])
                queries = [q for q in out.get("queries", []) if isinstance(q, str) and q.strip()][:2]
            except Exception as exc:
                log.warning("rewrite failed: %s", exc)
                queries = []
            queries = queries or [state["question"]]
            step.done("New queries: " + " | ".join(queries), queries=queries)
        return {"queries": queries, "rewrites": state.get("rewrites", 0) + 1}

    def web_search(state: AgentState) -> AgentState:
        # Search with the planner's focused queries (the raw question is often too wordy).
        queries = (state.get("queries") or [state["question"]])[:2]
        per_query = max(2, WEB_RESULTS // len(queries))
        with _Step("web_search", "Searching the web: " + " | ".join(queries)) as step:
            web: list[Hit] = []
            seen_urls: set[str] = set()
            failures = 0
            for q in queries:
                results = _web_search(q, per_query)
                if results is None:
                    failures += 1
                    continue
                for r in results:
                    body, url = (r.get("body") or "").strip(), r.get("href") or ""
                    if not body or not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    web.append(Hit(
                        chunk_id=f"web-{len(web)}", doc_id="web", title=(r.get("title") or url)[:120],
                        source=url, text=body, context="", page_start=0, page_end=0, url=url,
                    ))
            if failures == len(queries):
                step.done("Web search unavailable right now (all backends failed)")
            else:
                step.done(f"{len(web)} web results")
        return {"web": web}

    def generate(state: AgentState) -> AgentState:
        sources = state.get("relevant", []) + state.get("web", [])
        _emit("sources", sources=[_hit_dict(h, i) for i, h in enumerate(sources, start=1)])
        with _Step("generate", f"Writing answer ({llm.models['answer']}) from {len(sources)} sources") as step:
            parts: list[str] = []
            for token in stream_answer(llm, state["question"], sources):
                parts.append(token)
                _emit("token", text=token)
            answer = "".join(parts)
            step.done("Answer written", cited=cited_numbers(answer, len(sources)))
        return {"answer": answer}

    def verify(state: AgentState) -> AgentState:
        sources = state.get("relevant", []) + state.get("web", [])
        if not sources:
            return {}
        with _Step("verify", "Checking the answer against its sources") as step:
            try:
                # Excerpts, not full chunks: verify was the largest call in the run, and Groq's
                # free tier allows 8k tokens per minute per model.
                excerpts = "\n\n".join(
                    f"[{i}] {h.title}\n{h.text[:VERIFY_EXCERPT]}" for i, h in enumerate(sources, start=1)
                )
                out = llm.complete_json([{
                    "role": "user",
                    "content": prompts.VERIFY.format(sources=excerpts, answer=state["answer"]),
                }])
                grounded = out.get("grounded") if out.get("grounded") in ("yes", "partial", "no") else "unknown"
                unsupported = [c for c in out.get("unsupported", []) if isinstance(c, str)][:3]
            except Exception as exc:
                log.warning("verify failed: %s", exc)
                grounded, unsupported = "unknown", []
            _emit("check", grounded=grounded, unsupported=unsupported)
            step.done(f"Grounded: {grounded}")
        return {}

    # ---------------- routing ----------------

    def after_plan(state: AgentState) -> str:
        return "web_search" if state["route"] == "web" else "retrieve"

    def after_grade(state: AgentState) -> str:
        if len(state.get("relevant", [])) >= MIN_RELEVANT:
            # "both": documents cover part of the question, the web fills in the rest.
            return "web_search" if state.get("route") == "both" else "generate"
        if state.get("rewrites", 0) < MAX_REWRITES:
            return "rewrite"
        return "web_search"

    g = StateGraph(AgentState)
    for name, fn in [("plan", plan), ("retrieve", retrieve), ("grade", grade), ("rewrite", rewrite),
                     ("web_search", web_search), ("generate", generate), ("verify", verify)]:
        g.add_node(name, fn)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", after_plan, ["retrieve", "web_search"])
    g.add_edge("retrieve", "grade")
    g.add_conditional_edges("grade", after_grade, ["generate", "rewrite", "web_search"])
    g.add_edge("rewrite", "retrieve")
    g.add_edge("web_search", "generate")
    g.add_edge("generate", "verify")
    g.add_edge("verify", END)
    return g.compile()


WEB_BACKENDS = ("auto", "yahoo", "brave")  # free metasearch backends are flaky; try in turn


_GENERIC = {
    "from", "with", "that", "this", "what", "into", "over", "under", "their", "using", "towards",
    "generate", "retrieve", "critique", "reac", "synergizing", "self-reflection",
    "about", "approach", "language", "languages", "learning", "model", "models", "retrieval",
    "generation", "augmented", "through", "local", "global", "tasks", "query", "focused",
    "summarization", "knowledge", "intensive", "reasoning", "acting", "corrective", "self",
}


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", text)}


def _title_terms(titles: str) -> set[str]:
    """Distinctive words from indexed titles (method names like graphrag, self-rag, react)."""
    return {w for w in _words(titles) if w not in _GENERIC}


def _web_search(query: str, max_results: int) -> list[dict] | None:
    """Returns results, [] if every backend answered with nothing, None if all errored."""
    errors = 0
    for backend in WEB_BACKENDS:
        try:
            results = DDGS().text(query, max_results=max_results, backend=backend)
            if results:
                return results
        except Exception as exc:
            errors += 1
            log.info("web backend %s failed for %r: %s", backend, query, exc)
    return None if errors == len(WEB_BACKENDS) else []


def _hit_dict(h: Hit, rank: int) -> dict:
    return {
        "rank": rank, "chunk_id": h.chunk_id, "doc_id": h.doc_id, "title": h.title, "source": h.source,
        "text": h.text, "pages": h.pages, "page_start": h.page_start, "page_end": h.page_end,
        "scores": h.scores, "url": h.url,
    }


def run_agent(services: Services, llm: LLM, question: str) -> Iterator[dict]:
    """Yields events: step, sources, token, check, and finally done {answer, cited}."""
    graph = build_agent(services, llm)
    final: dict = {}
    for mode, chunk in graph.stream({"question": question}, stream_mode=["custom", "values"]):
        if mode == "custom":
            yield chunk
        else:
            final = chunk
    sources = final.get("relevant", []) + final.get("web", [])
    answer = final.get("answer", "")
    yield {"event": "done", "answer": answer, "cited": cited_numbers(answer, len(sources))}
