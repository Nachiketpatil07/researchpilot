"""FastAPI app. Run: uvicorn app.api:app --reload --port 8000"""

import json
import logging
import re
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agent.graph import run_agent
from .generation.answer import cited_numbers, stream_answer
from .ingest.loaders import SUPPORTED
from .ingest.pipeline import ingest_file
from .llm import LLMNotConfigured
from .retrieval.store import Hit
from .services import get_services

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    get_services().close()


app = FastAPI(title="ResearchPilot API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    return {"status": "ok", "chunks": svc.store.count(), "llm": llm_info}


@app.get("/documents")
def list_documents():
    return get_services().store.list_documents()


@app.post("/documents")
def upload_documents(files: list[UploadFile] = File(...)):
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
    store = get_services().store
    if not store.has_document(doc_id):
        raise HTTPException(404, "document not found")
    store.delete_document(doc_id)
    return {"deleted": doc_id}


@app.post("/search")
def search(req: SearchRequest):
    """Retrieval only: lets the UI compare dense / sparse / hybrid / hybrid+rerank."""
    res = get_services().retriever.retrieve(req.query, req.mode, req.top_n)
    return {
        "query": res.query,
        "mode": res.mode,
        "candidates": res.candidates,
        "timings_ms": res.timings_ms,
        "hits": [hit_json(h, i) for i, h in enumerate(res.hits, start=1)],
    }


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
def ask(req: AskRequest):
    """Server-Sent Events: step* -> sources -> token* -> [check] -> done, or error.

    Each event's data is a JSON object; `step` events carry stage/status/detail/ms.
    """
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
            yield _sse("error", {"message": f"{type(exc).__name__}: {exc}"})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
