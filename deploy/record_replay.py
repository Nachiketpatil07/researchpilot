"""Record real API responses so the hosted frontend can replay them without a backend.

    uvicorn app.api:app --port 8000          # in backend/, normal (non-demo) mode
    python deploy/record_replay.py           # -> frontend/public/demo/replay.json

Every /ask stream is stored event by event with its time offset, so the replay shows the
agent's steps at their real pace. Nothing here is synthetic: it is what the backend sent.
"""

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

API = next((a for a in sys.argv[1:] if a.startswith("http")), "http://127.0.0.1:8000")
OUT = Path(__file__).resolve().parent.parent / "frontend" / "public" / "demo" / "replay.json"

# Must match EXAMPLES in frontend/src/components/AskView.tsx and Playground.tsx.
QUESTIONS = [
    "How do Self-RAG and Corrective RAG handle bad retrieved documents?",
    "What is LightRAG and how is it different from GraphRAG?",
    "How does ReAct combine reasoning and acting?",
    "What is the population of Pune, India?",
]
SEARCHES = [
    "how does Self-RAG decide when to retrieve?",
    "retrieval evaluator confidence thresholds",
    "community summaries map-reduce",
]
MODES = ["dense", "sparse", "hybrid", "hybrid_rerank"]


COOLDOWN_S = 65  # Groq free tier: 8k tokens/minute per model; start each run with a fresh minute


def degraded(events: list[dict]) -> list[str]:
    """Signs that a run hit rate limits: failed planner/verify, very slow steps."""
    issues = []
    for e in events:
        d = e["data"]
        if e["event"] == "step" and d.get("status") == "done":
            if "planner unavailable" in d.get("detail", ""):
                issues.append("planner failed")
            if d.get("stage") == "verify" and "unknown" in d.get("detail", ""):
                issues.append("verify failed")
            if d.get("stage") in ("plan", "grade", "rewrite", "verify") and d.get("ms", 0) > 10_000:
                issues.append(f"{d['stage']} took {d['ms'] / 1000:.0f}s")
    return issues


def record_ask(client: httpx.Client, question: str, agent: bool) -> list[dict]:
    events, t0, event = [], time.perf_counter(), "message"
    with client.stream("POST", f"{API}/ask", json={"question": question, "agent": agent}, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                events.append({"t": round((time.perf_counter() - t0) * 1000),
                               "event": event, "data": json.loads(line[5:])})
    kinds = [e["event"] for e in events]
    if "error" in kinds or "done" not in kinds:
        raise RuntimeError(f"bad run for {question!r} (agent={agent}): {events[-1]}")
    return events


def main() -> None:
    with httpx.Client() as client:
        health = client.get(f"{API}/health").json()
        replay = {
            "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "health": {**health, "demo": True, "replay": True},
            "documents": client.get(f"{API}/documents").json(),
            "eval": client.get(f"{API}/eval/latest").json(),
            "asks": {},
            "searches": {},
        }
        problems = []
        if "--no-asks" in sys.argv:  # UI testing without spending LLM tokens
            QUESTIONS.clear()
        for q in QUESTIONS:
            replay["asks"][q] = {}
            for agent in (True, False):
                time.sleep(COOLDOWN_S)
                events = record_ask(client, q, agent)
                replay["asks"][q]["agent" if agent else "simple"] = events
                issues = degraded(events)
                problems += [f"{q} ({'agent' if agent else 'simple'}): {i}" for i in issues]
                print(f"  {'agent ' if agent else 'simple'} {events[-1]['t'] / 1000:5.1f}s  {len(events):3d} events  {q}"
                      + (f"  !! {', '.join(issues)}" if issues else ""), flush=True)
        if problems:
            sys.exit("Degraded runs (rate limits?), not saving:\n  " + "\n  ".join(problems))
        for q in SEARCHES:
            replay["searches"][q] = {
                m: client.post(f"{API}/search", json={"query": q, "mode": m, "top_n": 5}).json() for m in MODES
            }
            print(f"  search {q}")
    body = json.dumps(replay, ensure_ascii=False)
    if re.search(r"\borg_[A-Za-z0-9]{6,}", body):
        sys.exit("Recording contains a provider org id; refusing to save a public file.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body, encoding="utf-8")
    print(f"Saved {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
