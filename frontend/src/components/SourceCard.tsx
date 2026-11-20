"use client";

import { useState } from "react";
import type { Source } from "@/lib/api";
import { IconExternal, IconFile, IconGlobe } from "./icons";

function host(url: string) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

export default function SourceCard({
  source,
  id,
  cited,
  flash,
}: {
  source: Source;
  id: string;
  cited: boolean;
  flash: boolean;
}) {
  const [open, setOpen] = useState(false);
  const isWeb = Boolean(source.url);
  const rerank = source.scores?.rerank;

  return (
    <div
      id={id}
      className={`scroll-mt-24 rounded-lg border p-3 text-sm transition-opacity ${
        cited
          ? "border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900"
          : "border-dashed border-zinc-200 bg-transparent opacity-70 dark:border-zinc-800"
      } ${flash ? "flash border-indigo-400 dark:border-indigo-500" : ""}`}
    >
      <div className="flex items-start gap-2">
        <span className="flex h-5 min-w-5 shrink-0 items-center justify-center rounded bg-indigo-100 px-1 font-mono text-[11px] font-semibold text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-200">
          {source.rank}
        </span>
        <div className="min-w-0 flex-1">
          <div className="line-clamp-1 font-medium" title={source.title}>
            {source.title}
          </div>
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-zinc-500 dark:text-zinc-400">
            {isWeb ? (
              <a href={source.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 hover:text-indigo-600 dark:hover:text-indigo-400">
                <IconGlobe width={12} height={12} /> {host(source.url)} <IconExternal width={11} height={11} />
              </a>
            ) : (
              <span className="inline-flex items-center gap-1">
                <IconFile width={12} height={12} /> {source.source} · {source.pages}
              </span>
            )}
            {rerank != null && <span className="font-mono">rerank {rerank.toFixed(2)}</span>}
            {!cited && <span>not cited</span>}
          </div>
        </div>
      </div>
      {/* line-clamp needs its own display value, so no `block` on the clamped element. */}
      <p className={`mt-2 text-xs leading-relaxed text-zinc-600 dark:text-zinc-300 ${open ? "" : "line-clamp-3"}`}>
        {source.text}
      </p>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="mt-1 text-[11px] font-medium text-indigo-600 hover:underline dark:text-indigo-400"
      >
        {open ? "Show less" : "Show full passage"}
      </button>
    </div>
  );
}
