"""Run the evaluation and write a JSON report.

Retrieval (no LLM, fast): for each question, where does each strategy rank the chunk the
question was written from?  hit@k = share of questions with that chunk in the top k;
MRR@10 = mean of 1/rank (0 if not in the top 10).

Answers (LLM-judged, slower): the simple pipeline and the agent answer every question; a
judge model scores correctness against the reference answer and faithfulness to the
retrieved sources (1-5, reported as 0-100%). Also tracked: context recall (did the source
chunk reach the answer model?), latency, web usage, errors.
"""

import json
import re
import statistics
import time
from datetime import datetime, timezone

from ..agent.graph import run_agent
from ..generation.answer import answer as simple_answer
from ..llm import LLM
from ..retrieval.retriever import MODES
from ..retrieval.store import Hit
from ..services import Services
from . import LATEST_PATH, RESULTS_DIR, prompts

KS = (1, 3, 5, 10)


def _mean(xs: list[float]) -> float | None:
    return round(statistics.fmean(xs), 4) if xs else None


# ---------------------------------------------------------------- retrieval

def eval_retrieval(services: Services, testset: list[dict]) -> dict:
    retriever = services.retriever
    per_question = []
    latencies: dict[str, list[float]] = {m: [] for m in MODES}
    for item in testset:
        ranks = {}
        for mode in MODES:
            t = time.perf_counter()
            hits = retriever.retrieve(item["question"], mode, top_n=10).hits
            latencies[mode].append((time.perf_counter() - t) * 1000)
            ids = [h.chunk_id for h in hits]
            ranks[mode] = ids.index(item["chunk_id"]) + 1 if item["chunk_id"] in ids else None
        per_question.append({"id": item["id"], "ranks": ranks})
        print(f"  {item['id']} " + "  ".join(f"{m}={ranks[m] or '-'}" for m in MODES))

    modes = {}
    for mode in MODES:
        rs = [q["ranks"][mode] for q in per_question]
        modes[mode] = {
            **{f"hit@{k}": round(sum(1 for r in rs if r and r <= k) / len(rs), 4) for k in KS},
            "mrr@10": round(sum(1 / r for r in rs if r) / len(rs), 4),
            "latency_ms": round(statistics.median(latencies[mode]), 1),
        }
    return {"modes": modes, "per_question": per_question}


# ---------------------------------------------------------------- answers

def _judge(llm: LLM, item: dict, answer: str, sources: list[Hit], tier: str) -> dict:
    src = "\n\n".join(
        f"[{i}] {h.title} ({h.url or h.pages})\n{h.text[:600]}" for i, h in enumerate(sources[:8], start=1)
    ) or "(none)"
    out = llm.complete_json([{
        "role": "user",
        "content": prompts.JUDGE.format(question=item["question"], reference=item["reference"],
                                        sources=src, answer=answer),
    }], tier=tier, max_tokens=300)

    def score(key: str) -> int | None:
        try:
            v = int(out.get(key))
            return v if 1 <= v <= 5 else None
        except (TypeError, ValueError):
            return None

    return {"correctness": score("correctness"), "faithfulness": score("faithfulness"),
            "note": str(out.get("note", ""))[:300]}


def _run_simple(services: Services, llm: LLM, item: dict) -> tuple[str, list[Hit], dict]:
    hits = services.retriever.retrieve(item["question"], "hybrid_rerank").hits
    return simple_answer(llm, item["question"], hits), hits, {}


def _run_agent(services: Services, llm: LLM, item: dict) -> tuple[str, list[Hit], dict]:
    answer, sources, stages, grounded = "", [], [], None
    for ev in run_agent(services, llm, item["question"]):
        if ev["event"] == "step" and ev["status"] == "done":
            stages.append(ev["stage"])
        elif ev["event"] == "sources":
            sources = [Hit(**{k: s[k] for k in ("chunk_id", "doc_id", "title", "source", "text",
                                                 "page_start", "page_end", "scores", "url")}, context="")
                       for s in ev["sources"]]
        elif ev["event"] == "check":
            grounded = ev["grounded"]
        elif ev["event"] == "done":
            answer = ev["answer"]
    return answer, sources, {
        "used_web": "web_search" in stages,
        "rewrites": stages.count("rewrite"),
        "self_check": grounded,
    }


SYSTEMS = {"simple": _run_simple, "agent": _run_agent}


def eval_answers(services: Services, llm: LLM, testset: list[dict], systems: list[str],
                 judge_tier: str = "answer") -> dict:
    per_question = []
    for item in testset:
        row = {"id": item["id"]}
        for name in systems:
            t = time.perf_counter()
            try:
                answer, sources, extra = SYSTEMS[name](services, llm, item)
                latency = time.perf_counter() - t
                verdict = _judge(llm, item, answer, sources, judge_tier)
                row[name] = {
                    "answer": answer,
                    "latency_s": round(latency, 2),
                    "found_source": any(h.chunk_id == item["chunk_id"] for h in sources),
                    "n_sources": len(sources),
                    **verdict,
                    **extra,
                }
            except Exception as exc:  # rate limit, network: record and keep going
                # Reports are committed: scrub provider account identifiers from error text.
                msg = re.sub(r"\borg_[A-Za-z0-9]+", "org_[redacted]", f"{type(exc).__name__}: {exc}")
                row[name] = {"error": msg[:300]}
            r = row[name]
            print(f"  {item['id']} {name:<6} " + (
                f"correct={r.get('correctness')} faithful={r.get('faithfulness')} "
                f"source={'Y' if r.get('found_source') else 'n'} {r.get('latency_s')}s"
                + (" web" if r.get("used_web") else "")
                if "error" not in r else r["error"]))
        per_question.append(row)

    summary = {}
    for name in systems:
        rows = [q[name] for q in per_question if name in q]
        ok = [r for r in rows if "error" not in r]
        to_pct = lambda xs: _mean([(x - 1) / 4 for x in xs if x is not None])  # 1..5 -> 0..1
        summary[name] = {
            "n": len(rows),
            "errors": len(rows) - len(ok),
            "correctness": to_pct([r["correctness"] for r in ok]),
            "faithfulness": to_pct([r["faithfulness"] for r in ok]),
            "context_recall": _mean([1.0 if r["found_source"] else 0.0 for r in ok]),
            "latency_s": round(statistics.median([r["latency_s"] for r in ok]), 2) if ok else None,
            "web_rate": _mean([1.0 if r.get("used_web") else 0.0 for r in ok]) if name == "agent" else None,
        }
    return {"systems": summary, "per_question": per_question, "judge_model": llm.models[judge_tier]}


# ---------------------------------------------------------------- report

def build_report(services: Services, llm: LLM | None, testset: list[dict], retrieval: dict,
                 answers: dict | None) -> dict:
    s = services.settings
    return {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "questions": len(testset),
            "documents": len({t["doc_id"] for t in testset}),
            "llm_provider": llm.provider if llm else None,
            "answer_model": llm.models["answer"] if llm else None,
            "fast_model": llm.models["fast"] if llm else None,
            "dense_model": s.dense_model,
            "rerank_model": s.rerank_model,
            "retrieve_k": s.retrieve_k,
            "chunk_size": s.chunk_size,
            "context_mode": s.context_mode,
        },
        "retrieval": retrieval,
        "answers": answers,
        "testset": [{k: v for k, v in t.items() if k != "chunk_text"} for t in testset],
    }


def save_report(report: dict) -> str:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    body = json.dumps(report, indent=2, ensure_ascii=False)
    (RESULTS_DIR / f"run-{stamp}.json").write_text(body, encoding="utf-8")
    LATEST_PATH.write_text(body, encoding="utf-8")
    return str(LATEST_PATH)
