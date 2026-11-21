"use client";

import { Fragment, useEffect, useState } from "react";
import { getEvalReport, type EvalReport, type RetrievalMode, type SystemRun } from "@/lib/api";
import AnswerMarkdown from "./AnswerMarkdown";
import { IconChevron, IconRefresh, Spinner } from "./icons";

const MODE_LABEL: Record<RetrievalMode, string> = {
  dense: "Dense",
  sparse: "Sparse (BM25)",
  hybrid: "Hybrid (RRF)",
  hybrid_rerank: "Hybrid + rerank",
};
const MODES = Object.keys(MODE_LABEL) as RetrievalMode[];
const RET_METRICS = ["hit@1", "hit@3", "hit@5", "hit@10", "mrr@10"] as const;
const SYSTEMS = [
  { key: "simple", label: "Simple RAG", color: "var(--series-1)" },
  { key: "agent", label: "Agent", color: "var(--series-2)" },
] as const;
const ANSWER_METRICS = [
  { key: "correctness", label: "Correctness", hint: "Matches the reference answer (LLM judge)" },
  { key: "faithfulness", label: "Faithfulness", hint: "Claims supported by the retrieved sources (LLM judge)" },
  { key: "context_recall", label: "Context recall", hint: "Source passage reached the answer model" },
] as const;

const pct = (v: number | null | undefined) => (v == null ? "–" : `${Math.round(v * 100)}%`);

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="text-xs text-zinc-500 dark:text-zinc-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
      {sub && <div className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{sub}</div>}
    </div>
  );
}

/** Thin magnitude bar: one hue, rounded data end, recessive track. */
function Bar({ value, color = "var(--series-1)", title }: { value: number; color?: string; title?: string }) {
  return (
    <div className="h-1.5 w-full rounded-full" style={{ background: "var(--track)" }} title={title}>
      <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: color }} />
    </div>
  );
}

function RankChip({ rank }: { rank: number | null }) {
  if (rank == null) return <span className="text-zinc-400" title="Not in the top 10">–</span>;
  const cls =
    rank === 1
      ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
      : rank <= 5
        ? "bg-zinc-200 text-zinc-800 dark:bg-zinc-700 dark:text-zinc-100"
        : "text-zinc-500 dark:text-zinc-400";
  return (
    <span className={`inline-flex h-5 min-w-5 items-center justify-center rounded px-1 font-mono text-[11px] ${cls}`} title={`Rank ${rank}`}>
      {rank}
    </span>
  );
}

function Score({ run }: { run?: SystemRun }) {
  if (!run) return <span className="text-zinc-400">–</span>;
  if (run.error) return <span className="text-xs text-red-600 dark:text-red-400" title={run.error}>error</span>;
  return (
    <span className="font-mono text-xs tabular-nums" title={run.note}>
      {run.correctness ?? "–"}/5
      {run.used_web && <span className="ml-1 rounded bg-zinc-100 px-1 text-[10px] text-zinc-500 dark:bg-zinc-800">web</span>}
    </span>
  );
}

export default function EvalView({ active }: { active: boolean }) {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      setReport(await getEvalReport());
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  // Load the first time the tab is shown.
  useEffect(() => {
    if (!active || report || error) return;
    const t = setTimeout(load, 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  if (!report) {
    return (
      <div className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h2 className="text-xl font-semibold">Evaluation</h2>
        {loading || (!error && !report) ? (
          <Spinner className="mx-auto mt-6 text-indigo-500" />
        ) : (
          <>
            <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">{error}</p>
            <pre className="mx-auto mt-4 max-w-md rounded-lg bg-zinc-100 p-3 text-left font-mono text-xs dark:bg-zinc-900">
              {"cd backend\npython -m app.cli eval-generate   # test set\npython -m app.cli eval-run        # scores"}
            </pre>
            <button type="button" onClick={load} className="mt-4 text-sm text-indigo-600 hover:underline dark:text-indigo-400">
              Try again
            </button>
          </>
        )}
      </div>
    );
  }

  const r = report.retrieval.modes;
  const best = Object.fromEntries(RET_METRICS.map((m) => [m, Math.max(...MODES.map((mode) => r[mode][m]))]));
  const bestMode = MODES.reduce((a, b) => (r[b]["mrr@10"] > r[a]["mrr@10"] ? b : a));
  const sys = report.answers?.systems;
  const qById = Object.fromEntries(report.testset.map((t) => [t.id, t]));
  const ansById = Object.fromEntries((report.answers?.per_question ?? []).map((a) => [a.id, a]));

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-6xl space-y-8 px-4 py-8">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold tracking-tight">Evaluation</h2>
            <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
              {report.config.questions} synthetic questions over {report.config.documents} papers ·{" "}
              {new Date(report.created_at).toLocaleString()} · answers by {String(report.config.answer_model)}
              {report.answers && <> · judged by {report.answers.judge_model}</>}
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-1.5 rounded-lg border border-zinc-200 px-2.5 py-1 text-xs hover:bg-zinc-100 dark:border-zinc-800 dark:hover:bg-zinc-900"
          >
            {loading ? <Spinner /> : <IconRefresh width={12} height={12} />} Reload
          </button>
        </div>

        {/* KPI row */}
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Tile label="Best retrieval (MRR@10)" value={r[bestMode]["mrr@10"].toFixed(3)} sub={MODE_LABEL[bestMode]} />
          <Tile label="Source in top 5" value={pct(r[bestMode]["hit@5"])} sub={MODE_LABEL[bestMode]} />
          <Tile
            label="Answer correctness"
            value={sys ? `${pct(sys.simple?.correctness)} → ${pct(sys.agent?.correctness)}` : "–"}
            sub="Simple RAG → Agent"
          />
          <Tile
            label="Faithfulness"
            value={sys ? `${pct(sys.simple?.faithfulness)} → ${pct(sys.agent?.faithfulness)}` : "–"}
            sub={sys?.agent?.web_rate != null ? `Agent used the web on ${pct(sys.agent.web_rate)} of questions` : "Simple RAG → Agent"}
          />
        </div>

        {/* Retrieval */}
        <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <header className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <h3 className="text-sm font-semibold">Retrieval: where does each strategy rank the source passage?</h3>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              hit@k = share of questions whose source chunk is in the top k. MRR@10 = mean of 1/rank. Best per column in bold.
            </p>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Strategy</th>
                  {RET_METRICS.map((m) => <th key={m} className="px-3 py-2 font-medium">{m.replace("mrr@10", "MRR@10")}</th>)}
                  <th className="px-3 py-2 text-right font-medium">Median latency</th>
                </tr>
              </thead>
              <tbody>
                {MODES.map((mode) => (
                  <tr key={mode} className="border-t border-zinc-100 dark:border-zinc-800">
                    <td className="px-4 py-2.5 font-medium whitespace-nowrap">{MODE_LABEL[mode]}</td>
                    {RET_METRICS.map((m) => {
                      const v = r[mode][m];
                      return (
                        <td key={m} className="w-[14%] px-3 py-2.5">
                          <div className={`mb-1 font-mono text-xs tabular-nums ${v === best[m] ? "font-bold" : "text-zinc-600 dark:text-zinc-300"}`}>
                            {m === "mrr@10" ? v.toFixed(3) : pct(v)}
                          </div>
                          <Bar value={v} title={`${MODE_LABEL[mode]} ${m}: ${m === "mrr@10" ? v.toFixed(3) : pct(v)}`} />
                        </td>
                      );
                    })}
                    <td className="px-3 py-2.5 text-right font-mono text-xs text-zinc-600 tabular-nums dark:text-zinc-300">
                      {Math.round(r[mode].latency_ms)}ms
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {/* Answers */}
        {sys && (
          <section className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h3 className="text-sm font-semibold">Answer quality: simple RAG vs agent</h3>
              <div className="flex gap-4 text-xs text-zinc-600 dark:text-zinc-300" aria-label="Legend">
                {SYSTEMS.map((s) => (
                  <span key={s.key} className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: s.color }} />
                    {s.label}
                  </span>
                ))}
              </div>
            </div>
            <div className="mt-4 grid gap-6 md:grid-cols-3">
              {ANSWER_METRICS.map((m) => (
                <div key={m.key}>
                  <div className="text-xs font-medium">{m.label}</div>
                  <div className="text-[11px] text-zinc-500 dark:text-zinc-400">{m.hint}</div>
                  <div className="mt-3 space-y-[2px]">
                    {SYSTEMS.map((s) => {
                      const v = sys[s.key]?.[m.key] ?? null;
                      return (
                        <div key={s.key} className="flex items-center gap-2" title={`${s.label} ${m.label}: ${pct(v)}`}>
                          <div className="h-3.5 flex-1">
                            <div
                              className="h-full rounded-r"
                              style={{ width: `${(v ?? 0) * 100}%`, background: s.color, minWidth: v ? 4 : 0 }}
                            />
                          </div>
                          <span className="w-10 text-right font-mono text-xs tabular-nums">{pct(v)}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs text-zinc-500 dark:text-zinc-400">
              Every question was written from one passage, which suits single-pass retrieval; the agent&apos;s strengths
              (multi-part questions, comparisons, web fallback) are not exercised here.
              {(sys.simple?.errors || sys.agent?.errors) ? (
                <> Errors excluded from scores: simple {sys.simple?.errors ?? 0}, agent {sys.agent?.errors ?? 0} (API rate limits).</>
              ) : null}
            </p>
          </section>
        )}

        {/* Per question */}
        <section className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
          <header className="border-b border-zinc-200 px-4 py-3 dark:border-zinc-800">
            <h3 className="text-sm font-semibold">Per question</h3>
            <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">
              Rank of the source passage per strategy (– = not in top 10) and judged correctness. Click a row for answers.
            </p>
          </header>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-sm">
              <thead>
                <tr className="text-left text-xs text-zinc-500 dark:text-zinc-400">
                  <th className="px-4 py-2 font-medium">Question</th>
                  {MODES.map((m) => <th key={m} className="px-2 py-2 text-center font-medium whitespace-nowrap">{MODE_LABEL[m].split(" ")[0]}{m === "hybrid_rerank" ? "+RR" : ""}</th>)}
                  {report.answers && <>
                    <th className="px-2 py-2 text-center font-medium">Simple</th>
                    <th className="px-2 py-2 text-center font-medium">Agent</th>
                  </>}
                </tr>
              </thead>
              <tbody>
                {report.retrieval.per_question.map((row) => {
                  const q = qById[row.id];
                  const a = ansById[row.id];
                  const isOpen = open === row.id;
                  return (
                    <Fragment key={row.id}>
                      <tr
                        onClick={() => setOpen(isOpen ? null : row.id)}
                        className="cursor-pointer border-t border-zinc-100 align-top hover:bg-zinc-50 dark:border-zinc-800 dark:hover:bg-zinc-800/40"
                      >
                        <td className="px-4 py-2">
                          <div className="flex gap-2">
                            <IconChevron width={14} height={14} className={`mt-0.5 shrink-0 text-zinc-400 transition-transform ${isOpen ? "rotate-180" : ""}`} />
                            <div>
                              <div className="leading-snug">{q?.question}</div>
                              <div className="mt-0.5 text-[11px] text-zinc-400">{q?.source} · p. {q?.pages}</div>
                            </div>
                          </div>
                        </td>
                        {MODES.map((m) => <td key={m} className="px-2 py-2 text-center"><RankChip rank={row.ranks[m]} /></td>)}
                        {report.answers && <>
                          <td className="px-2 py-2 text-center"><Score run={a?.simple} /></td>
                          <td className="px-2 py-2 text-center"><Score run={a?.agent} /></td>
                        </>}
                      </tr>
                      {isOpen && (
                        <tr className="bg-zinc-50 dark:bg-zinc-950/40">
                          <td colSpan={7} className="space-y-3 px-4 py-3 text-xs leading-relaxed">
                            <div><span className="font-semibold">Reference:</span> {q?.reference}</div>
                            {SYSTEMS.map((s) => {
                              const run = a?.[s.key];
                              if (!run) return null;
                              return (
                                <div key={s.key}>
                                  <span className="font-semibold">{s.label}</span>
                                  {run.error ? (
                                    <span className="text-red-600"> error: {run.error}</span>
                                  ) : (
                                    <>
                                      <span className="text-zinc-500">
                                        {" "}· correctness {run.correctness}/5 · faithfulness {run.faithfulness}/5 · source{" "}
                                        {run.found_source ? "found" : "missed"} · {run.latency_s}s
                                        {run.used_web ? " · used web" : ""}
                                      </span>
                                      {run.note && <div className="text-zinc-500 italic">Judge: {run.note}</div>}
                                      <div className="mt-1 max-h-48 overflow-y-auto rounded-md border border-zinc-200 bg-white p-2 text-zinc-700 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300 [&_.md]:text-xs">
                                        <AnswerMarkdown text={run.answer ?? ""} streaming={false} onCite={() => {}} />
                                      </div>
                                    </>
                                  )}
                                </div>
                              );
                            })}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  );
}
