"""One entry point for every retrieval strategy, so they can be compared side by side."""

import time
from dataclasses import dataclass, field

from ..config import Settings
from .models import LocalModels
from .store import Hit, VectorStore

MODES = ("dense", "sparse", "hybrid", "hybrid_rerank")


@dataclass
class RetrievalResult:
    query: str
    mode: str
    hits: list[Hit]
    timings_ms: dict[str, float] = field(default_factory=dict)
    candidates: int = 0


class Retriever:
    def __init__(self, settings: Settings, store: VectorStore, local_models: LocalModels):
        self.settings = settings
        self.store = store
        self.m = local_models

    def retrieve(self, query: str, mode: str = "hybrid_rerank", top_n: int | None = None) -> RetrievalResult:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        top_n = top_n or self.settings.rerank_top_n
        k = self.settings.retrieve_k
        timings: dict[str, float] = {}

        t = time.perf_counter()
        if mode == "dense":
            hits = self.store.search_dense(query, k)
        elif mode == "sparse":
            hits = self.store.search_sparse(query, k)
        else:
            hits = self.store.search_hybrid(query, k)
        timings["search"] = (time.perf_counter() - t) * 1000
        candidates = len(hits)

        if mode == "hybrid_rerank" and hits:
            t = time.perf_counter()
            hits = self.rerank(query, hits)
            timings["rerank"] = (time.perf_counter() - t) * 1000

        return RetrievalResult(query=query, mode=mode, hits=hits[:top_n], timings_ms=timings, candidates=candidates)

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        """Cross-encoder reads (query, chunk) pairs together: slower but far more precise
        than comparing two independently computed embeddings."""
        scores = list(self.m.reranker.rerank(query, [h.text for h in hits]))
        for hit, score in zip(hits, scores):
            hit.scores["rerank"] = float(score)
        return sorted(hits, key=lambda h: h.scores["rerank"], reverse=True)
