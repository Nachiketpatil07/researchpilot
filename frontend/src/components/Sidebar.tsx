"use client";

import { useRef, useState } from "react";
import { deleteDocument, uploadDocuments, type DocumentInfo, type Health } from "@/lib/api";
import { IconFile, IconTrash, IconUpload, Spinner } from "./icons";

export default function Sidebar({
  health,
  docs,
  backendDown,
  onChanged,
}: {
  health: Health | null;
  docs: DocumentInfo[];
  backendDown: boolean;
  onChanged: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [dragging, setDragging] = useState(false);
  const [deleting, setDeleting] = useState<string | null>(null);

  async function upload(files: File[]) {
    if (!files.length) return;
    setUploading(files.length === 1 ? files[0].name : `${files.length} files`);
    setMessage(null);
    try {
      const res = await uploadDocuments(files);
      const done = res.indexed.filter((r) => !r.skipped);
      const skipped = res.indexed.filter((r) => r.skipped);
      const parts = [];
      if (done.length) parts.push(`Indexed ${done.map((d) => `${d.source} (${d.chunks} chunks)`).join(", ")}`);
      if (skipped.length) parts.push(`${skipped.length} already indexed`);
      if (res.errors.length) parts.push(res.errors.map((e) => `${e.file}: ${e.error}`).join("; "));
      setMessage({ kind: res.errors.length && !done.length ? "err" : "ok", text: parts.join(". ") });
      onChanged();
    } catch (err) {
      setMessage({ kind: "err", text: (err as Error).message });
    } finally {
      setUploading(null);
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  async function remove(doc: DocumentInfo) {
    if (!window.confirm(`Remove "${doc.title}" from the index? The original file is not affected.`)) return;
    setDeleting(doc.doc_id);
    try {
      await deleteDocument(doc.doc_id);
      onChanged();
    } catch (err) {
      setMessage({ kind: "err", text: (err as Error).message });
    } finally {
      setDeleting(null);
    }
  }

  const llmReady = health?.llm.ready;

  return (
    <aside className="flex h-full w-72 flex-col border-r border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-950">
      <div className="border-b border-zinc-200 px-4 py-4 dark:border-zinc-800">
        <div className="flex items-center gap-2">
          <span className="flex h-7 w-7 items-center justify-center rounded-lg bg-indigo-600 text-sm font-bold text-white">R</span>
          <span className="font-semibold tracking-tight">ResearchPilot</span>
        </div>
        <div className="mt-3 space-y-1 text-xs text-zinc-500 dark:text-zinc-400">
          <div className="flex items-center gap-2">
            <span
              className={`h-2 w-2 rounded-full ${backendDown ? "bg-red-500" : llmReady ? "bg-emerald-500" : health ? "bg-amber-500" : "bg-zinc-300"}`}
            />
            {backendDown
              ? "Backend offline"
              : !health
                ? "Connecting…"
                : llmReady
                  ? `${health.llm.provider} · ${health.llm.models?.answer}`
                  : "LLM not configured"}
          </div>
          {health && <div className="pl-4">{health.chunks.toLocaleString()} chunks indexed</div>}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto px-3 py-3">
        <h2 className="px-1 pb-2 text-xs font-semibold tracking-wide text-zinc-500 uppercase dark:text-zinc-400">
          Documents ({docs.length})
        </h2>
        {docs.length === 0 && !backendDown && (
          <p className="px-1 text-xs text-zinc-400">No documents yet. Upload a PDF, Markdown or text file.</p>
        )}
        <ul className="space-y-1">
          {docs.map((d) => (
            <li
              key={d.doc_id}
              className="group flex items-start gap-2 rounded-lg px-2 py-2 hover:bg-zinc-100 dark:hover:bg-zinc-900"
            >
              <IconFile className="mt-0.5 shrink-0 text-zinc-400" />
              <div className="min-w-0 flex-1">
                <div className="line-clamp-2 text-[13px] leading-snug" title={d.title}>{d.title}</div>
                <div className="mt-0.5 text-[11px] text-zinc-400">
                  {d.pages} pp · {d.chunks} chunks
                </div>
              </div>
              <button
                type="button"
                onClick={() => remove(d)}
                disabled={deleting === d.doc_id}
                title="Remove from index"
                className="shrink-0 rounded p-1 text-zinc-400 opacity-0 group-hover:opacity-100 hover:bg-zinc-200 hover:text-red-600 focus:opacity-100 dark:hover:bg-zinc-800"
              >
                {deleting === d.doc_id ? <Spinner /> : <IconTrash />}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <div className="border-t border-zinc-200 p-3 dark:border-zinc-800">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            upload(Array.from(e.dataTransfer.files));
          }}
          className={`flex cursor-pointer flex-col items-center gap-1 rounded-xl border border-dashed px-3 py-4 text-center text-xs transition ${
            dragging
              ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-950/40"
              : "border-zinc-300 hover:border-indigo-300 dark:border-zinc-700"
          } ${backendDown || uploading ? "pointer-events-none opacity-60" : ""}`}
        >
          {uploading ? <Spinner className="text-indigo-500" /> : <IconUpload className="text-zinc-400" />}
          <span className="font-medium">{uploading ? `Indexing ${uploading}…` : "Upload documents"}</span>
          <span className="text-zinc-400">{uploading ? "~10s per paper on CPU" : "PDF, Markdown or text · drop or click"}</span>
          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.md,.markdown,.txt"
            className="sr-only"
            onChange={(e) => upload(Array.from(e.target.files ?? []))}
          />
        </label>
        {message && (
          <p className={`mt-2 text-xs ${message.kind === "err" ? "text-red-600 dark:text-red-400" : "text-emerald-700 dark:text-emerald-400"}`}>
            {message.text}
          </p>
        )}
      </div>
    </aside>
  );
}
