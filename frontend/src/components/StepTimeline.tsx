"use client";

import { useState } from "react";
import type { Stage, StepEvent } from "@/lib/api";
import {
  IconChevron, IconCompass, IconFilter, IconGlobe, IconPen, IconRefresh, IconSearch, IconShield, IconX, Spinner,
} from "./icons";

export interface Step extends StepEvent {
  key: string;
}

const META: Record<Stage, { label: string; Icon: typeof IconSearch }> = {
  plan: { label: "Plan", Icon: IconCompass },
  retrieve: { label: "Retrieve", Icon: IconSearch },
  grade: { label: "Grade", Icon: IconFilter },
  rewrite: { label: "Rewrite query", Icon: IconRefresh },
  web_search: { label: "Web search", Icon: IconGlobe },
  generate: { label: "Generate", Icon: IconPen },
  verify: { label: "Verify", Icon: IconShield },
};

const ROUTE_LABEL: Record<string, string> = { docs: "documents", both: "documents + web", web: "web" };

function fmt(ms?: number) {
  if (ms == null) return "";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`;
}

export default function StepTimeline({ steps, running }: { steps: Step[]; running: boolean }) {
  // Expanded while the agent works; collapses to a one-line summary once the answer is in.
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;

  const total = steps.reduce((sum, s) => sum + (s.ms ?? 0), 0);
  const expanded = running || open;

  return (
    <div className="rounded-xl border border-zinc-200 bg-white/60 dark:border-zinc-800 dark:bg-zinc-900/40">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        disabled={running}
        className="flex w-full items-center justify-between gap-3 px-4 py-2.5 text-left text-xs font-medium text-zinc-500 dark:text-zinc-400"
      >
        <span className="flex items-center gap-2">
          {running ? <Spinner className="text-indigo-500" /> : <IconCompass className="text-indigo-500" />}
          {running ? "Agent working…" : `${steps.length} steps · ${fmt(total)}`}
        </span>
        {!running && <IconChevron className={`transition-transform ${expanded ? "rotate-180" : ""}`} />}
      </button>

      {expanded && (
        <ol className="relative space-y-3 px-4 pb-4">
          {steps.map((s, i) => {
            const { label, Icon } = META[s.stage] ?? { label: s.stage, Icon: IconSearch };
            const last = i === steps.length - 1;
            return (
              <li key={s.key} className="relative flex gap-3">
                {!last && (
                  <span className="absolute top-7 bottom-[-0.75rem] left-[13px] w-px bg-zinc-200 dark:bg-zinc-800" />
                )}
                <span
                  className={`relative z-10 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border ${
                    s.status === "running"
                      ? "border-indigo-300 bg-indigo-50 text-indigo-600 dark:border-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                      : s.status === "error"
                        ? "border-red-300 bg-red-50 text-red-600 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
                        : "border-zinc-200 bg-white text-zinc-600 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-300"
                  }`}
                >
                  {s.status === "running" ? <Spinner /> : s.status === "error" ? <IconX /> : <Icon />}
                </span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-medium">
                      {label}
                      {s.route && (
                        <span className="ml-2 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] font-normal text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
                          route: {ROUTE_LABEL[s.route] ?? s.route}
                        </span>
                      )}
                    </span>
                    <span className="shrink-0 font-mono text-[11px] text-zinc-400">{fmt(s.ms)}</span>
                  </div>
                  {s.detail && <p className="mt-0.5 text-xs text-zinc-500 dark:text-zinc-400">{s.detail}</p>}
                  {/* Retrieve runs the queries already shown by plan/rewrite: don't repeat them. */}
                  {s.queries && s.queries.length > 0 && s.stage !== "retrieve" && (
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {s.queries.map((q) => (
                        <span
                          key={q}
                          className="rounded-md border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 font-mono text-[11px] text-zinc-600 dark:border-zinc-700 dark:bg-zinc-800/60 dark:text-zinc-300"
                        >
                          {q}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
