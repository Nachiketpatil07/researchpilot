"use client";

import { useCallback, useEffect, useState } from "react";
import { apiLabel, getHealth, listDocuments, type DocumentInfo, type Health } from "@/lib/api";
import AskView from "./AskView";
import EvalView from "./EvalView";
import Playground from "./Playground";
import Sidebar from "./Sidebar";
import { IconMenu, IconX } from "./icons";

type Tab = "ask" | "playground" | "eval";

export default function AppShell() {
  const [tab, setTab] = useState<Tab>("ask");
  const [health, setHealth] = useState<Health | null>(null);
  const [docs, setDocs] = useState<DocumentInfo[]>([]);
  const [backendDown, setBackendDown] = useState(false);
  const [drawer, setDrawer] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [h, d] = await Promise.all([getHealth(), listDocuments()]);
      setHealth(h);
      setDocs(d);
      setBackendDown(false);
    } catch {
      setBackendDown(true);
    }
  }, []);

  // Poll the backend (an external system): health + document list every 15s.
  useEffect(() => {
    const first = setTimeout(refresh, 0);
    const id = setInterval(refresh, 10000);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [refresh]);

  const replayMode = Boolean(health?.replay);
  const localBackend = /localhost|127\.0\.0\.1/.test(apiLabel());

  const askDisabled = backendDown
    ? "Backend offline."
    : health && !health.llm.ready
      ? `LLM not configured: ${health.llm.error ?? "add an API key to backend/.env"}`
      : health && health.chunks === 0
        ? "Upload a document first (left panel)."
        : undefined;

  const sidebar = <Sidebar health={health} docs={docs} backendDown={backendDown} onChanged={refresh} />;

  return (
    <div className="flex h-dvh overflow-hidden">
      <div className="hidden md:flex">{sidebar}</div>

      {drawer && (
        <div className="fixed inset-0 z-40 flex md:hidden">
          <div className="relative z-10 h-full">{sidebar}</div>
          <button type="button" aria-label="Close menu" className="flex-1 bg-black/40" onClick={() => setDrawer(false)} />
        </div>
      )}

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-zinc-200 px-4 py-2 dark:border-zinc-800">
          <button
            type="button"
            className="rounded-md p-1.5 hover:bg-zinc-100 md:hidden dark:hover:bg-zinc-900"
            onClick={() => setDrawer((d) => !d)}
            aria-label="Toggle documents"
          >
            {drawer ? <IconX /> : <IconMenu />}
          </button>
          <nav className="flex gap-1 text-sm" role="tablist">
            {(
              [
                ["ask", "Ask"],
                ["playground", "Playground"],
                ["eval", "Evaluation"],
              ] as const
            ).map(([t, label]) => (
              <button
                key={t}
                type="button"
                role="tab"
                aria-selected={tab === t}
                onClick={() => setTab(t)}
                className={`rounded-lg px-3 py-1.5 ${
                  tab === t
                    ? "bg-zinc-100 font-medium dark:bg-zinc-800"
                    : "text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
                }`}
              >
                {label}
              </button>
            ))}
          </nav>
          <a
            href="https://github.com/Nachiketpatil07/researchpilot"
            target="_blank"
            rel="noreferrer"
            className="ml-auto text-xs text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200"
          >
            GitHub ↗
          </a>
        </header>

        {replayMode && (
          <div className="border-b border-indigo-200 bg-indigo-50 px-4 py-2 text-xs text-indigo-900 sm:text-sm dark:border-indigo-900 dark:bg-indigo-950/40 dark:text-indigo-200">
            <span className="font-medium">Replay demo.</span>{" "}
            <span className="hidden sm:inline">
              You&apos;re watching recorded runs of the real agent (same events, same pace). Try the example questions
              and playground queries; the Evaluation tab shows the real results.{" "}
            </span>
            <span className="sm:hidden">Recorded runs of the real agent. </span>
            <a
              href="https://github.com/Nachiketpatil07/researchpilot#setup-windows"
              target="_blank"
              rel="noreferrer"
              className="underline"
            >
              Run it locally
            </a>{" "}
            to ask anything.
          </div>
        )}

        {backendDown && (
          <div className="border-b border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700 dark:border-red-900 dark:bg-red-950/40 dark:text-red-300">
            {localBackend ? (
              <>
                Can&apos;t reach the backend at <code className="font-mono">{apiLabel()}</code>. Start it from{" "}
                <code className="font-mono">backend/</code> with{" "}
                <code className="font-mono">uvicorn app.api:app --port 8000</code>.
              </>
            ) : (
              <>
                Can&apos;t reach the live backend at <code className="font-mono">{apiLabel()}</code>. The tunnel may
                be closed or the server still starting; this page retries automatically.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => {
                    // Forget the tunnel address and reload without ?api= (full reload resets the mode).
                    try { sessionStorage.clear(); } catch {}
                    window.location.href = window.location.pathname;
                  }}
                >
                  Switch to the replay demo
                </button>
                .
              </>
            )}
          </div>
        )}

        <div className="min-h-0 flex-1">
          {/* Both views stay mounted so switching tabs keeps the conversation. */}
          <div className={tab === "ask" ? "h-full" : "hidden"}>
            <AskView disabledReason={askDisabled} examplesOnly={replayMode} />
          </div>
          <div className={tab === "playground" ? "h-full" : "hidden"}>
            <Playground disabled={backendDown || (health?.chunks ?? 0) === 0} examplesOnly={replayMode} />
          </div>
          <div className={tab === "eval" ? "h-full" : "hidden"}>
            <EvalView active={tab === "eval"} />
          </div>
        </div>
      </main>
    </div>
  );
}
