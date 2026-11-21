"use client";

import { useEffect, useRef, useState } from "react";
import { REPLAY_HINT, streamAsk, type AskEvent, type CheckEvent, type Source } from "@/lib/api";
import AnswerMarkdown from "./AnswerMarkdown";
import SourceCard from "./SourceCard";
import StepTimeline, { type Step } from "./StepTimeline";
import { IconSend, IconShield, IconStop } from "./icons";

interface Turn {
  id: string;
  question: string;
  agent: boolean;
  steps: Step[];
  sources: Source[];
  answer: string;
  cited: number[];
  check?: CheckEvent;
  error?: string;
  status: "running" | "done" | "error";
  elapsedMs?: number;
}

const EXAMPLES = [
  { q: "How do Self-RAG and Corrective RAG handle bad retrieved documents?", tag: "compares 2 papers" },
  { q: "What is LightRAG and how is it different from GraphRAG?", tag: "documents + web" },
  { q: "How does ReAct combine reasoning and acting?", tag: "single paper" },
  { q: "What is the population of Pune, India?", tag: "web only" },
];

function applyEvent(turn: Turn, ev: AskEvent): Turn {
  switch (ev.event) {
    case "step": {
      const s = ev.data;
      const steps = [...turn.steps];
      if (s.status === "running") {
        steps.push({ ...s, key: `${s.stage}-${steps.length}` });
      } else {
        // Close the most recent running step of the same stage (stages can repeat after a rewrite).
        let idx = -1;
        for (let i = steps.length - 1; i >= 0; i--) {
          if (steps[i].stage === s.stage && steps[i].status === "running") { idx = i; break; }
        }
        if (idx === -1) steps.push({ ...s, key: `${s.stage}-${steps.length}` });
        else steps[idx] = { ...steps[idx], ...s, detail: s.detail ?? steps[idx].detail };
      }
      return { ...turn, steps };
    }
    case "sources":
      return { ...turn, sources: ev.data.sources };
    case "token":
      return { ...turn, answer: turn.answer + ev.data.text };
    case "check":
      return { ...turn, check: ev.data };
    case "done":
      return { ...turn, answer: ev.data.answer || turn.answer, cited: ev.data.cited, status: "done" };
    case "error":
      return { ...turn, error: ev.data.message, status: "error" };
  }
}

function Grounded({ check }: { check: CheckEvent }) {
  const styles = {
    yes: ["Grounded in sources", "bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-900"],
    partial: ["Partially grounded", "bg-amber-50 text-amber-800 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-900"],
    no: ["Not grounded", "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/50 dark:text-red-300 dark:border-red-900"],
    unknown: ["Groundedness unknown", "bg-zinc-50 text-zinc-600 border-zinc-200 dark:bg-zinc-900 dark:text-zinc-400 dark:border-zinc-800"],
  } as const;
  const [label, cls] = styles[check.grounded] ?? styles.unknown;
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs ${cls}`}>
      <div className="flex items-center gap-1.5 font-medium">
        <IconShield width={14} height={14} /> {label}
      </div>
      {check.unsupported.length > 0 && (
        <ul className="mt-1.5 list-disc space-y-0.5 pl-5">
          {check.unsupported.map((c) => <li key={c}>Unsupported: {c}</li>)}
        </ul>
      )}
    </div>
  );
}

function TurnView({ turn }: { turn: Turn }) {
  const [flashRank, setFlashRank] = useState<number | null>(null);
  const running = turn.status === "running";
  const generating = running && turn.steps.some((s) => s.stage === "generate" && s.status === "running");
  const cited = new Set(turn.cited);

  const onCite = (n: number) => {
    document.getElementById(`${turn.id}-src-${n}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    setFlashRank(null);
    requestAnimationFrame(() => setFlashRank(n));
    setTimeout(() => setFlashRank((r) => (r === n ? null : r)), 2600);
  };

  return (
    <article className="space-y-4">
      <div className="flex justify-end">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-indigo-600 px-4 py-2.5 text-[15px] text-white shadow-sm">
          {turn.question}
          <div className="mt-1 text-right text-[11px] text-indigo-200">{turn.agent ? "agent" : "simple pipeline"}</div>
        </div>
      </div>

      <StepTimeline steps={turn.steps} running={running} />

      {(turn.answer || generating) && (
        <div className="rounded-xl border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
          <AnswerMarkdown text={turn.answer} streaming={running} onCite={onCite} />
          {!running && turn.elapsedMs != null && (
            <div className="mt-3 text-[11px] text-zinc-400">
              {(turn.elapsedMs / 1000).toFixed(1)}s total · {turn.cited.length} of {turn.sources.length} sources cited
            </div>
          )}
        </div>
      )}

      {turn.check && <Grounded check={turn.check} />}

      {turn.error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/50 dark:text-red-300">
          {turn.error}
        </div>
      )}

      {turn.sources.length > 0 && (
        <section>
          <h3 className="mb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
            Sources
          </h3>
          <div className="grid gap-2 sm:grid-cols-2">
            {turn.sources.map((s) => (
              <SourceCard
                key={s.chunk_id}
                id={`${turn.id}-src-${s.rank}`}
                source={s}
                cited={running || cited.has(s.rank)}
                flash={flashRank === s.rank}
              />
            ))}
          </div>
        </section>
      )}
    </article>
  );
}

export default function AskView({ disabledReason, examplesOnly = false }: { disabledReason?: string; examplesOnly?: boolean }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [agent, setAgent] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const busy = turns.some((t) => t.status === "running");

  useEffect(() => {
    const el = textareaRef.current;
    if (el) {
      el.style.height = "auto";
      el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
    }
  }, [input]);

  const update = (id: string, fn: (t: Turn) => Turn) =>
    setTurns((ts) => ts.map((t) => (t.id === id ? fn(t) : t)));

  async function ask(question: string) {
    question = question.trim();
    if (!question || busy) return;
    const id = `t${Date.now()}`;
    const started = performance.now();
    setTurns((ts) => [
      ...ts,
      { id, question, agent, steps: [], sources: [], answer: "", cited: [], status: "running" },
    ]);
    setInput("");
    setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);

    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamAsk(question, agent, (ev) => update(id, (t) => applyEvent(t, ev)), controller.signal);
      update(id, (t) => ({
        ...t,
        status: t.status === "running" ? "done" : t.status,
        elapsedMs: performance.now() - started,
      }));
    } catch (err) {
      const aborted = controller.signal.aborted;
      update(id, (t) => ({
        ...t,
        status: "error",
        error: aborted
          ? "Stopped."
          : (err as Error).message.startsWith("Demo limit") || (err as Error).message === REPLAY_HINT
            ? (err as Error).message
            : `Could not reach the backend: ${(err as Error).message}`,
        steps: t.steps.map((s) => (s.status === "running" ? { ...s, status: "error" } : s)),
      }));
    } finally {
      abortRef.current = null;
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-10 px-4 py-8">
          {turns.length === 0 && (
            <div className="pt-6 text-center sm:pt-12">
              <h2 className="text-2xl font-semibold tracking-tight">Ask your documents anything</h2>
              <p className="mx-auto mt-2 max-w-lg text-sm text-zinc-500 dark:text-zinc-400">
                The agent plans its searches, grades what it finds, falls back to the web when your
                documents fall short, and checks its answer against the sources.
              </p>
              <div className="mt-8 grid gap-2 text-left sm:grid-cols-2">
                {EXAMPLES.map((e) => (
                  <button
                    key={e.q}
                    type="button"
                    disabled={Boolean(disabledReason)}
                    onClick={() => ask(e.q)}
                    className="rounded-xl border border-zinc-200 bg-white p-3 text-sm transition hover:border-indigo-300 hover:shadow-sm disabled:opacity-50 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-indigo-700"
                  >
                    <span className="block">{e.q}</span>
                    <span className="mt-1 block text-[11px] text-zinc-400">{e.tag}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
          {turns.map((t) => <TurnView key={t.id} turn={t} />)}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="border-t border-zinc-200 bg-background/80 backdrop-blur dark:border-zinc-800">
        <form
          className="mx-auto max-w-3xl px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            ask(input);
          }}
        >
          {disabledReason && <p className="mb-2 text-xs text-amber-600 dark:text-amber-400">{disabledReason}</p>}
          {examplesOnly && turns.length > 0 && (
            <div className="mb-2 flex flex-wrap gap-1.5">
              {EXAMPLES.map((e) => (
                <button
                  key={e.q}
                  type="button"
                  disabled={busy}
                  onClick={() => ask(e.q)}
                  className="rounded-full border border-zinc-200 px-2.5 py-0.5 text-xs text-zinc-600 hover:border-indigo-300 disabled:opacity-50 dark:border-zinc-800 dark:text-zinc-300"
                >
                  {e.q}
                </button>
              ))}
            </div>
          )}
          <div className="flex items-end gap-2 rounded-2xl border border-zinc-300 bg-white p-2 shadow-sm focus-within:border-indigo-400 dark:border-zinc-700 dark:bg-zinc-900">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              rows={1}
              placeholder={examplesOnly ? "Replay demo: pick an example question above" : "Ask a question about your documents…"}
              disabled={Boolean(disabledReason) || examplesOnly}
              className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-[15px] outline-none placeholder:text-zinc-400"
            />
            {busy ? (
              <button
                type="button"
                onClick={() => abortRef.current?.abort()}
                className="flex h-9 w-9 items-center justify-center rounded-xl bg-zinc-200 text-zinc-700 hover:bg-zinc-300 dark:bg-zinc-700 dark:text-zinc-200"
                title="Stop"
              >
                <IconStop />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim() || Boolean(disabledReason) || examplesOnly}
                className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-600 text-white hover:bg-indigo-500 disabled:opacity-40"
                title="Ask"
              >
                <IconSend />
              </button>
            )}
          </div>
          <div className="mt-2 flex items-center justify-between text-xs text-zinc-500 dark:text-zinc-400">
            <div className="inline-flex rounded-lg border border-zinc-200 p-0.5 dark:border-zinc-800" role="radiogroup">
              {[
                { v: true, label: "Agent", hint: "plan → grade → rewrite/web → verify" },
                { v: false, label: "Simple", hint: "one retrieval, one answer" },
              ].map((o) => (
                <button
                  key={o.label}
                  type="button"
                  role="radio"
                  aria-checked={agent === o.v}
                  title={o.hint}
                  onClick={() => setAgent(o.v)}
                  className={`rounded-md px-2.5 py-1 ${
                    agent === o.v ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900" : "hover:text-zinc-800 dark:hover:text-zinc-200"
                  }`}
                >
                  {o.label}
                </button>
              ))}
            </div>
            <span className="hidden sm:inline">Enter to send · Shift+Enter for a new line</span>
          </div>
        </form>
      </div>
    </div>
  );
}
