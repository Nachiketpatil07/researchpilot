"use client";

import { useState } from "react";
import { search, type RetrievalMode, type SearchResult } from "@/lib/api";
import { IconSearch, Spinner } from "./icons";

const MODES: { mode: RetrievalMode; label: string; desc: string; score: string }[] = [
  { mode: "dense", label: "Dense", desc: "Embedding similarity (bge-small)", score: "dense" },
  { mode: "sparse", label: "Sparse", desc: "Keyword match (BM25)", score: "sparse" },
  { mode: "hybrid", label: "Hybrid", desc: "Dense + BM25 fused with RRF", score: "hybrid" },
  { mode: "hybrid_rerank", label: "Hybrid + rerank", desc: "Then a cross-encoder re-scores", score: "rerank" },
];

const EXAMPLES = [
  "how does Self-RAG decide when to retrieve?",
  "retrieval evaluator confidence thresholds",
  "community summaries map-reduce",
];

/** Same chunk -> same colour in every column, so overlap between strategies is visible. */
function hue(id: string) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) % 360;
  return h;
}

export default function Playground({ disabled }: { disabled: boolean }) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Partial<Record<RetrievalMode, SearchResult>>>({});
  const [loading, setLoading] = useState<RetrievalMode | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);

  async function run(q: string) {
    q = q.trim();
    if (!q) return;
    setQuery(q);
    setResults({});
    setError(null);
    try {
      // Sequential on purpose: the embedded vector DB is single-process and CPU-bound anyway.
      for (const { mode } of MODES) {
        setLoading(mode);
        const r = await search(q, mode, 5);
        setResults((prev) => ({ ...prev, [mode]: r }));
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-7xl px-4 py-8">
        <h2 className="text-xl font-semibold tracking-tight">Retrieval playground</h2>
        <p className="mt-1 max-w-2xl text-sm text-zinc-500 dark:text-zinc-400">
          Run one query through four retrieval strategies side by side. The same chunk keeps the
          same colour in every column. Hover one to see where the other strategies ranked it.
        </p>

        <form
          className="mt-5 flex max-w-2xl gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            run(query);
          }}
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search query…"
            disabled={disabled}
            className="flex-1 rounded-xl border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            type="submit"
            disabled={disabled || !query.trim() || loading !== null}
            className="inline-flex items-center gap-1.5 rounded-xl bg-indigo-600 px-4 text-sm font-medium text-white hover:bg-indigo-500 disabled:opacity-40"
          >
            {loading ? <Spinner /> : <IconSearch />} Compare
          </button>
        </form>
        <div className="mt-2 flex flex-wrap gap-1.5">
          {EXAMPLES.map((q) => (
            <button
              key={q}
              type="button"
              disabled={disabled || loading !== null}
              onClick={() => run(q)}
              className="rounded-full border border-zinc-200 px-2.5 py-0.5 text-xs text-zinc-600 hover:border-indigo-300 disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-300"
            >
              {q}
            </button>
          ))}
        </div>
        {error && <p className="mt-3 text-sm text-red-600 dark:text-red-400">{error}</p>}

        <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {MODES.map(({ mode, label, desc, score }) => {
            const r = results[mode];
            return (
              <section key={mode} className="min-w-0 rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
                <header className="border-b border-zinc-200 px-3 py-2.5 dark:border-zinc-800">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold">{label}</span>
                    {loading === mode && <Spinner className="text-indigo-500" />}
                    {r && (
                      <span className="font-mono text-[11px] text-zinc-400">
                        {Math.round(Object.values(r.timings_ms).reduce((a, b) => a + b, 0))}ms
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400">{desc}</div>
                </header>
                <ol className="space-y-1.5 p-2">
                  {!r && loading !== mode && (
                    <li className="px-1 py-6 text-center text-xs text-zinc-400">—</li>
                  )}
                  {r?.hits.map((h) => {
                    const c = hue(h.chunk_id);
                    const active = hovered === h.chunk_id;
                    return (
                      <li
                        key={h.chunk_id}
                        onMouseEnter={() => setHovered(h.chunk_id)}
                        onMouseLeave={() => setHovered(null)}
                        className={`rounded-lg border p-2 text-xs transition ${
                          active
                            ? "border-indigo-400 bg-indigo-50 dark:border-indigo-500 dark:bg-indigo-950/40"
                            : hovered
                              ? "border-transparent opacity-50"
                              : "border-transparent"
                        }`}
                        style={{ borderLeft: `3px solid hsl(${c} 70% 55%)` }}
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="truncate font-medium">
                            {h.rank}. {h.source} <span className="font-normal text-zinc-400">{h.pages}</span>
                          </span>
                          <span className="shrink-0 font-mono text-[11px] text-zinc-500">
                            {h.scores[score]?.toFixed(score === "sparse" ? 1 : 3)}
                          </span>
                        </div>
                        <p className="mt-1 line-clamp-3 text-zinc-600 dark:text-zinc-400">{h.text}</p>
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })}
        </div>
      </div>
    </div>
  );
}
