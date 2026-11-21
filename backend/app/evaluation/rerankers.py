"""Experiment: which cross-encoder (and which input) reranks best on the eval set?

All rerankers see the same hybrid candidates, so only the reranking differs. Each runs
twice: on the chunk text alone, and with the chunk's context header prepended.

Two scorings: strict (only the source chunk counts) and lenient (its neighbours count
too: chunks overlap by `chunk_overlap` characters, so a neighbour may hold the answer).
"""

import json
import time
import uuid

from fastembed.rerank.cross_encoder import TextCrossEncoder

from ..ingest.chunker import _NAMESPACE
from ..services import Services
from . import RESULTS_DIR

RERANKERS = [
    "Xenova/ms-marco-MiniLM-L-6-v2",
    "Xenova/ms-marco-MiniLM-L-12-v2",
    "jinaai/jina-reranker-v1-turbo-en",
    "BAAI/bge-reranker-base",
]


def _score(rankings: dict[str, list[str]], truth: dict[str, tuple[str, set[str]]]) -> dict:
    out = {}
    for name, ok in (("strict", lambda cid, q: cid == truth[q][0]),
                     ("lenient", lambda cid, q: cid in truth[q][1])):
        ranks = [next((k + 1 for k, cid in enumerate(ids[:10]) if ok(cid, q)), None)
                 for q, ids in rankings.items()]
        n = len(ranks)
        out[name] = {
            "hit@1": round(sum(r == 1 for r in ranks) / n, 4),
            "hit@5": round(sum(bool(r and r <= 5) for r in ranks) / n, 4),
            "mrr@10": round(sum(1 / r for r in ranks if r) / n, 4),
        }
    return out


def compare_rerankers(services: Services, testset: list[dict], models: list[str] = RERANKERS) -> list[dict]:
    store, settings = services.store, services.settings

    truth = {}
    for item in testset:
        p = store.client.retrieve(store.name, ids=[item["chunk_id"]], with_payload=["index", "doc_id"])[0].payload
        neighbours = {str(uuid.uuid5(_NAMESPACE, f"{p['doc_id']}:{i}")) for i in (p["index"] - 1, p["index"] + 1)}
        truth[item["id"]] = (item["chunk_id"], neighbours | {item["chunk_id"]})

    cands = {item["id"]: store.search_hybrid(item["question"], settings.retrieve_k) for item in testset}
    rows = [{"reranker": "none (hybrid only)", "context": False, "ms_per_query": 0,
             **_score({q: [h.chunk_id for h in c] for q, c in cands.items()}, truth)}]

    for model in models:
        enc = TextCrossEncoder(model, cache_dir=str(settings.models_cache))
        for with_ctx in (False, True):
            t = time.perf_counter()
            ranked = {}
            for item in testset:
                c = cands[item["id"]]
                docs = [f"{h.context}\n{h.text}" if with_ctx and h.context else h.text for h in c]
                scores = list(enc.rerank(item["question"], docs))
                ranked[item["id"]] = [h.chunk_id for _, h in sorted(zip(scores, c), key=lambda x: -x[0])]
            ms = round((time.perf_counter() - t) * 1000 / len(testset))
            rows.append({"reranker": model, "context": with_ctx, "ms_per_query": ms, **_score(ranked, truth)})
            s = rows[-1]["strict"]
            print(f"  {model.split('/')[1]:<34} {'+ctx' if with_ctx else '    '} "
                  f"hit@1={s['hit@1']:.2f} hit@5={s['hit@5']:.2f} mrr={s['mrr@10']:.3f} {ms}ms/q")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "rerankers.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows
