"""Command line tools.

  python -m app.cli samples                 download demo arXiv papers
  python -m app.cli ingest data/samples     index a folder (or file)
  python -m app.cli docs                    list indexed documents
  python -m app.cli search "query" --compare
  python -m app.cli ask "question"

Stop the API server first: embedded Qdrant allows one process at a time.
"""

import argparse
import logging
import sys
from pathlib import Path

import httpx

from .generation.answer import stream_answer
from .ingest.loaders import SUPPORTED
from .ingest.pipeline import ingest_file
from .retrieval.retriever import MODES
from .services import get_services

# Public arXiv papers that fit the project theme (RAG + agents).
SAMPLE_PAPERS = {
    "2005.11401": "rag-lewis-2020.pdf",          # Retrieval-Augmented Generation for Knowledge-Intensive NLP
    "2310.11511": "self-rag-2023.pdf",           # Self-RAG
    "2401.15884": "corrective-rag-2024.pdf",     # Corrective RAG (CRAG)
    "2404.16130": "graphrag-2024.pdf",           # From Local to Global: GraphRAG
    "2210.03629": "react-2022.pdf",              # ReAct: reasoning + acting
}


def cmd_samples(_args) -> None:
    out = get_services().settings.samples_dir
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=60, headers={"User-Agent": "ResearchPilot/0.1"}) as client:
        for arxiv_id, name in SAMPLE_PAPERS.items():
            dest = out / name
            if dest.exists():
                print(f"  have  {name}")
                continue
            r = client.get(f"https://arxiv.org/pdf/{arxiv_id}")
            r.raise_for_status()
            if not r.content.startswith(b"%PDF"):
                print(f"  skip  {name} (not a PDF response)")
                continue
            dest.write_bytes(r.content)
            print(f"  got   {name} ({len(r.content) // 1024} KB)")
    print(f"Saved to {out}")


def cmd_ingest(args) -> None:
    svc = get_services()
    target = Path(args.path)
    files = [target] if target.is_file() else sorted(p for p in target.rglob("*") if p.suffix.lower() in SUPPORTED)
    if not files:
        sys.exit(f"No supported files found in {target}")
    llm = svc.llm_or_none() if svc.settings.context_mode != "off" else None
    print(f"Context mode: {svc.settings.context_mode} | LLM: {'yes' if llm else 'no (title-only context)'}")
    for f in files:
        try:
            r = ingest_file(f, svc.store, svc.settings, llm, force=args.force)
        except ValueError as exc:
            print(f"  error {f.name}: {exc}")
            continue
        if r.skipped:
            print(f"  skip  {r.source} (already indexed, use --force)")
        else:
            print(f"  done  {r.source}: {r.pages} pages -> {r.chunks} chunks in {r.seconds}s")
    print(f"Total chunks in index: {svc.store.count()}")


def cmd_docs(_args) -> None:
    for d in get_services().store.list_documents():
        print(f"{d['doc_id']}  {d['chunks']:>4} chunks  {d['pages']:>3} pp  {d['title']}")


def _print_hits(res) -> None:
    t = ", ".join(f"{k} {v:.0f}ms" for k, v in res.timings_ms.items())
    print(f"\n== {res.mode}  ({res.candidates} candidates; {t})")
    for i, h in enumerate(res.hits, start=1):
        scores = " ".join(f"{k}={v:.3f}" for k, v in h.scores.items())
        snippet = h.text[:140].replace("\n", " ")
        print(f" {i}. [{h.source} {h.pages}] {scores}\n    {snippet}...")


def cmd_search(args) -> None:
    retriever = get_services().retriever
    for mode in MODES if args.compare else [args.mode]:
        _print_hits(retriever.retrieve(args.query, mode, args.top_n))


def cmd_ask(args) -> None:
    svc = get_services()
    llm = svc.llm()
    if args.simple:
        res = svc.retriever.retrieve(args.question, args.mode)
        _print_hits(res)
        print("\n== answer\n")
        for token in stream_answer(llm, args.question, res.hits):
            print(token, end="", flush=True)
        print()
        return

    from .agent.graph import run_agent

    streaming = False
    for ev in run_agent(svc, llm, args.question):
        kind = ev["event"]
        if kind == "step" and ev["status"] != "running":
            if streaming:
                print("\n")
                streaming = False
            extra = ""
            if ev.get("queries"):
                extra = "\n        queries: " + " | ".join(ev["queries"])
            print(f"  [{ev['stage']:<10}] {ev['status']:<5} {ev.get('ms', 0):>5}ms  {ev.get('detail', '')}{extra}")
        elif kind == "sources":
            print("\n== sources")
            for s in ev["sources"]:
                print(f" [{s['rank']}] {s['url'] or s['source']} ({s['pages']})")
            print("\n== answer\n")
        elif kind == "token":
            streaming = True
            print(ev["text"], end="", flush=True)
        elif kind == "check":
            print(f"== groundedness: {ev['grounded']}" + "".join(f"\n   - unsupported: {c}" for c in ev["unsupported"]))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.WARNING)
    p = argparse.ArgumentParser(prog="python -m app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("samples", help="download demo papers").set_defaults(fn=cmd_samples)

    s = sub.add_parser("ingest", help="index a file or folder")
    s.add_argument("path")
    s.add_argument("--force", action="store_true", help="re-index documents already in the store")
    s.set_defaults(fn=cmd_ingest)

    sub.add_parser("docs", help="list indexed documents").set_defaults(fn=cmd_docs)

    s = sub.add_parser("search", help="retrieval only")
    s.add_argument("query")
    s.add_argument("--mode", choices=MODES, default="hybrid_rerank")
    s.add_argument("--compare", action="store_true", help="run every retrieval mode")
    s.add_argument("--top-n", type=int, default=5)
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("ask", help="agentic answer with citations")
    s.add_argument("question")
    s.add_argument("--simple", action="store_true", help="single-pass pipeline instead of the agent")
    s.add_argument("--mode", choices=MODES, default="hybrid_rerank", help="retrieval mode for --simple")
    s.set_defaults(fn=cmd_ask)

    args = p.parse_args()
    try:
        args.fn(args)
    finally:
        get_services().close()


if __name__ == "__main__":
    main()
