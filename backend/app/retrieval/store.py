"""Qdrant (embedded, on-disk) holding a dense and a sparse (BM25) vector per chunk."""

import threading
from collections import defaultdict
from dataclasses import dataclass, field

from qdrant_client import QdrantClient, models

from ..config import Settings
from ..ingest.chunker import Chunk
from .models import LocalModels

DENSE = "dense"
SPARSE = "sparse"


@dataclass
class Hit:
    chunk_id: str
    doc_id: str
    title: str
    source: str
    text: str
    context: str
    page_start: int
    page_end: int
    scores: dict[str, float] = field(default_factory=dict)
    url: str = ""  # set for web results; empty for indexed documents

    @classmethod
    def from_point(cls, point, score_name: str) -> "Hit":
        p = point.payload or {}
        return cls(
            chunk_id=str(point.id),
            doc_id=p.get("doc_id", ""),
            title=p.get("title", ""),
            source=p.get("source", ""),
            text=p.get("text", ""),
            context=p.get("context", ""),
            page_start=p.get("page_start", 0),
            page_end=p.get("page_end", 0),
            scores={score_name: float(point.score)},
        )

    @property
    def pages(self) -> str:
        if self.url:
            return "web"
        if self.page_start == self.page_end:
            return f"p. {self.page_start}"
        return f"pp. {self.page_start}-{self.page_end}"


class _Serialized:
    """Proxy that runs every method of the wrapped object under one lock.

    Embedded (local-mode) Qdrant is not built for concurrent access, and the API serves
    requests from a thread pool. Only the client calls are serialized; embedding and
    reranking (the slow parts) still run in parallel.
    """

    def __init__(self, obj):
        self._obj = obj
        self._lock = threading.RLock()

    def __getattr__(self, name):
        attr = getattr(self._obj, name)
        if not callable(attr):
            return attr

        def locked(*args, **kwargs):
            with self._lock:
                return attr(*args, **kwargs)

        return locked


class VectorStore:
    def __init__(self, settings: Settings, local_models: LocalModels):
        self.settings = settings
        self.m = local_models
        self.name = settings.collection
        settings.qdrant_path.mkdir(parents=True, exist_ok=True)
        # Embedded mode: no server needed. Only one process may open the path at a time.
        self.client = _Serialized(QdrantClient(path=str(settings.qdrant_path)))
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.name):
            return
        self.client.create_collection(
            self.name,
            vectors_config={DENSE: models.VectorParams(size=self.m.dense_dim, distance=models.Distance.COSINE)},
            # IDF modifier turns raw term frequencies from the bm25 model into real BM25 scoring.
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )

    # ---------- writes ----------

    def upsert(self, chunks: list[Chunk], batch_size: int = 32) -> None:
        for start in range(0, len(chunks), batch_size):
            batch = chunks[start : start + batch_size]
            texts = [c.embed_text() for c in batch]
            dense_vecs = list(self.m.dense.passage_embed(texts))
            sparse_vecs = list(self.m.sparse.passage_embed(texts))
            points = [
                models.PointStruct(
                    id=c.chunk_id,
                    vector={
                        DENSE: d.tolist(),
                        SPARSE: models.SparseVector(indices=s.indices.tolist(), values=s.values.tolist()),
                    },
                    payload=c.to_payload(),
                )
                for c, d, s in zip(batch, dense_vecs, sparse_vecs)
            ]
            self.client.upsert(self.name, points=points)

    def delete_document(self, doc_id: str) -> None:
        self.client.delete(self.name, points_selector=models.FilterSelector(filter=self._doc_filter(doc_id)))

    # ---------- reads ----------

    def has_document(self, doc_id: str) -> bool:
        return self.client.count(self.name, count_filter=self._doc_filter(doc_id), exact=True).count > 0

    def count(self) -> int:
        return self.client.count(self.name, exact=True).count

    def list_documents(self) -> list[dict]:
        docs: dict[str, dict] = {}
        counts: dict[str, int] = defaultdict(int)
        pages: dict[str, int] = defaultdict(int)
        offset = None
        while True:
            points, offset = self.client.scroll(
                self.name,
                limit=256,
                offset=offset,
                with_payload=["doc_id", "title", "source", "page_end"],
                with_vectors=False,
            )
            for pt in points:
                p = pt.payload or {}
                did = p["doc_id"]
                docs.setdefault(did, {"doc_id": did, "title": p.get("title"), "source": p.get("source")})
                counts[did] += 1
                pages[did] = max(pages[did], p.get("page_end", 0))
            if offset is None:
                break
        return [{**d, "chunks": counts[k], "pages": pages[k]} for k, d in docs.items()]

    def search_dense(self, query: str, k: int) -> list[Hit]:
        vec = next(iter(self.m.dense.query_embed(query))).tolist()
        res = self.client.query_points(self.name, query=vec, using=DENSE, limit=k, with_payload=True)
        return [Hit.from_point(p, "dense") for p in res.points]

    def search_sparse(self, query: str, k: int) -> list[Hit]:
        res = self.client.query_points(
            self.name, query=self._sparse_query(query), using=SPARSE, limit=k, with_payload=True
        )
        return [Hit.from_point(p, "sparse") for p in res.points]

    def search_hybrid(self, query: str, k: int) -> list[Hit]:
        """Dense + BM25 candidates fused with Reciprocal Rank Fusion inside Qdrant."""
        dense_vec = next(iter(self.m.dense.query_embed(query))).tolist()
        res = self.client.query_points(
            self.name,
            prefetch=[
                models.Prefetch(query=dense_vec, using=DENSE, limit=k),
                models.Prefetch(query=self._sparse_query(query), using=SPARSE, limit=k),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=k,
            with_payload=True,
        )
        return [Hit.from_point(p, "hybrid") for p in res.points]

    # ---------- helpers ----------

    def _sparse_query(self, query: str) -> models.SparseVector:
        s = next(iter(self.m.sparse.query_embed(query)))
        return models.SparseVector(indices=s.indices.tolist(), values=s.values.tolist())

    @staticmethod
    def _doc_filter(doc_id: str) -> models.Filter:
        return models.Filter(must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))])
