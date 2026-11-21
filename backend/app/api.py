"""FastAPI app. Run: uvicorn app.api:app --reload --port 8000"""

import asyncio
import json
import logging
import re
import threading
import time
from collections import defaultdict, deque
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent.graph import run_agent
from .config import get_settings
from .generation.answer import cited_numbers, stream_answer
from .ingest.loaders import SUPPORTED
from .ingest.pipeline import ingest_file
from .llm import LLMNotConfigured
from .retrieval.store import Hit
from .services import get_services

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Load models and open the vector store before serving, off the event loop.
    await asyncio.to_thread(get_services().warm_up)
    yield
    get_services().close()


settings = get_settings()

app = FastAPI(title="ResearchPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"]
    + [o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RateLimiter:
    """Sliding one-hour window per client IP. In-memory: fine for a single small server."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: float = 3600) -> int | None:
        """Record a hit; return seconds to wait if the limit is exceeded, else None."""
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= limit:
                return int(window - (now - q[0])) + 1
            q.append(now)
            return None


limiter = RateLimiter()


def _client_ip(request: Request) -> str:
    # Behind a proxy (Hugging Face, Vercel) the real client is the first X-Forwarded-For entry.
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "unknown")


def _demo_limit(request: Request, bucket: str, limit: int) -> None:
    if not settings.demo_mode:
        return
    wait = limiter.check(f"{bucket}:{_client_ip(request)}", limit)
    if wait is not None:
        raise HTTPException(
            429,
            f"Demo limit reached ({bucket}s: {limit} per hour per visitor). Try again in {wait // 60 + 1} min, "
            "or run ResearchPilot locally for unlimited use.",
        )


def _require_writable() -> None:
    if settings.demo_mode:
        raise HTTPException(403, "This is a read-only demo. Run ResearchPilot locally to add your own documents.")

Mode = Literal["dense", "sparse", "hybrid", "hybrid_rerank"]


class SearchRequest(BaseModel):
    query: str = Field(min_length=1)
    mode: Mode = "hybrid_rerank"
    top_n: int = Field(default=6, ge=1, le=30)


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    agent: bool = True  # False = single-pass pipeline (retrieve once, answer)
    mode: Mode = "hybrid_rerank"  # retrieval mode for the single-pass pipeline
    top_n: int = Field(default=6, ge=1, le=15)


def hit_json(h: Hit, rank: int) -> dict:
    return {"rank": rank, **asdict(h), "pages": h.pages}


@app.get("/health")
def health():
    svc = get_services()
    try:
        llm = svc.llm()
        llm_info = {"provider": llm.provider, "models": llm.models, "ready": True}
    except LLMNotConfigured as exc:
        llm_info = {"provider": svc.settings.llm_provider, "ready": False, "error": str(exc)}
    return {"status": "ok", "chunks": svc.store.count(), "llm": llm_info, "demo": settings.demo_mode}


@app.get("/documents")
def list_documents():
    return get_services().store.list_documents()


@app.post("/documents")
def upload_documents(files: list[UploadFile] = File(...)):
    _require_writable()
    svc = get_services()
    svc.settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    llm = svc.llm_or_none()
    reports, errors = [], []
    for f in files:
        name = re.sub(r"[^\w.\- ]", "_", f.filename or "upload")
        if not any(name.lower().endswith(ext) for ext in SUPPORTED):
            errors.append({"file": name, "error": f"unsupported type (use {', '.join(sorted(SUPPORTED))})"})
            continue
        dest = svc.settings.uploads_dir / name
        dest.write_bytes(f.file.read())
        try:
            reports.append(asdict(ingest_file(dest, svc.store, svc.settings, llm)))
        except ValueError as exc:
            errors.append({"file": name, "error": str(exc)})
    return {"indexed": reports, "errors": errors}


@app.delete("/documents/{doc_id}")
def delete_document(doc_id: str):
    _require_writable()
    store = get_services().store
    if not store.has_document(doc_id):
        raise HTTPException(404, "document not found")
    store.delete_document(doc_id)
    return {"deleted": doc_id}


@app.post("/search")
def search(req: SearchRequest, request: Request):
    """Retrieval only: lets the UI compare dense / sparse / hybrid / hybrid+rerank."""
    _demo_limit(request, "search", settings.search_limit_per_hour)
    res = get_services().retriever.retrieve(req.query, req.mode, req.top_n)
    return {
        "query": res.query,
        "mode": res.mode,
        "candidates": res.candidates,
        "timings_ms": res.timings_ms,
        "hits": [hit_json(h, i) for i, h in enumerate(res.hits, start=1)],
    }


@app.get("/eval/latest")
def eval_latest():
    """Latest evaluation report (written by `python -m app.cli eval-run`)."""
    from .evaluation import LATEST_PATH

    if not LATEST_PATH.exists():
        raise HTTPException(404, "No evaluation report yet. Run: python -m app.cli eval-run")
    return json.loads(LATEST_PATH.read_text(encoding="utf-8"))


def public_error(exc: Exception) -> str:
    """Error text that is safe to show any visitor: no provider account ids, no billing links."""
    if type(exc).__name__ == "RateLimitError":
        per_day = "per day" in str(exc) or "TPD" in str(exc)
        return ("The LLM provider's free daily token limit is used up; try again later."
                if per_day else "The LLM provider is rate-limiting requests; try again in a minute.")
    msg = re.sub(r"\borg_[A-Za-z0-9]+", "org_[redacted]", f"{type(exc).__name__}: {exc}")
    return re.sub(r"https?://\S*billing\S*", "", msg)[:300]


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _pipeline_events(svc, llm, req: AskRequest) -> Iterator[dict]:
    """Single pass: retrieve once, answer. Same event shapes as the agent."""
    t = time.perf_counter()
    yield {"event": "step", "stage": "retrieve", "status": "running", "detail": f"Searching ({req.mode})"}
    res = svc.retriever.retrieve(req.question, req.mode, req.top_n)
    yield {"event": "step", "stage": "retrieve", "status": "done", "ms": round((time.perf_counter() - t) * 1000),
           "detail": f"{res.candidates} candidates -> top {len(res.hits)}"}
    yield {"event": "sources", "sources": [hit_json(h, i) for i, h in enumerate(res.hits, start=1)]}

    t = time.perf_counter()
    yield {"event": "step", "stage": "generate", "status": "running", "detail": f"Writing answer ({llm.models['answer']})"}
    parts: list[str] = []
    for token in stream_answer(llm, req.question, res.hits):
        parts.append(token)
        yield {"event": "token", "text": token}
    full = "".join(parts)
    yield {"event": "step", "stage": "generate", "status": "done", "ms": round((time.perf_counter() - t) * 1000),
           "detail": "Answer written"}
    yield {"event": "done", "answer": full, "cited": cited_numbers(full, len(res.hits))}


@app.post("/ask")
def ask(req: AskRequest, request: Request):
    """Server-Sent Events: step* -> sources -> token* -> [check] -> done, or error.

    Each event's data is a JSON object; `step` events carry stage/status/detail/ms.
    """
    _demo_limit(request, "question", settings.ask_limit_per_hour)
    svc = get_services()

    def events() -> Iterator[str]:
        try:
            llm = svc.llm()
        except LLMNotConfigured as exc:
            yield _sse("error", {"message": str(exc)})
            return
        try:
            source = run_agent(svc, llm, req.question) if req.agent else _pipeline_events(svc, llm, req)
            for ev in source:
                name = ev.pop("event")
                yield _sse(name, ev)
        except Exception as exc:  # surface provider errors (rate limits etc.) to the UI
            logging.exception("ask failed")
            yield _sse("error", {"message": public_error(exc)})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
