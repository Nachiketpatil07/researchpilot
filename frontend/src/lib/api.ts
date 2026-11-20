export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

// ---------- types (mirror backend/app/api.py) ----------

export type Stage = "plan" | "retrieve" | "grade" | "rewrite" | "web_search" | "generate" | "verify";
export type RetrievalMode = "dense" | "sparse" | "hybrid" | "hybrid_rerank";

export interface Source {
  rank: number;
  chunk_id: string;
  doc_id: string;
  title: string;
  source: string;
  text: string;
  pages: string;
  page_start: number;
  page_end: number;
  scores: Record<string, number>;
  url: string;
}

export interface StepEvent {
  stage: Stage;
  status: "running" | "done" | "error";
  detail?: string;
  ms?: number;
  queries?: string[];
  route?: string;
}

export interface CheckEvent {
  grounded: "yes" | "partial" | "no" | "unknown";
  unsupported: string[];
}

export type AskEvent =
  | { event: "step"; data: StepEvent }
  | { event: "sources"; data: { sources: Source[] } }
  | { event: "token"; data: { text: string } }
  | { event: "check"; data: CheckEvent }
  | { event: "done"; data: { answer: string; cited: number[] } }
  | { event: "error"; data: { message: string } };

export interface Health {
  status: string;
  chunks: number;
  llm: { provider: string; ready: boolean; models?: { answer: string; fast: string }; error?: string };
}

export interface DocumentInfo {
  doc_id: string;
  title: string;
  source: string;
  chunks: number;
  pages: number;
}

export interface SearchResult {
  query: string;
  mode: RetrievalMode;
  candidates: number;
  timings_ms: Record<string, number>;
  hits: Source[];
}

// ---------- helpers ----------

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export const getHealth = () => fetch(`${API_URL}/health`, { cache: "no-store" }).then(json<Health>);

export const listDocuments = () =>
  fetch(`${API_URL}/documents`, { cache: "no-store" }).then(json<DocumentInfo[]>);

export const deleteDocument = (docId: string) =>
  fetch(`${API_URL}/documents/${docId}`, { method: "DELETE" }).then(json<{ deleted: string }>);

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return fetch(`${API_URL}/documents`, { method: "POST", body: form }).then(
    json<{
      indexed: { title: string; source: string; chunks: number; skipped: boolean; seconds: number }[];
      errors: { file: string; error: string }[];
    }>,
  );
}

export const search = (query: string, mode: RetrievalMode, top_n = 5) =>
  fetch(`${API_URL}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, top_n }),
  }).then(json<SearchResult>);

/**
 * POST /ask and parse the Server-Sent Events stream.
 * (EventSource only supports GET, so the stream is read and split by hand.)
 */
export async function streamAsk(
  question: string,
  agent: boolean,
  onEvent: (e: AskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, agent }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`${res.status} ${res.statusText}`);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    // Events are separated by a blank line.
    let sep: number;
    while ((sep = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      let event = "message";
      const dataLines: string[] = [];
      for (const line of raw.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (!dataLines.length) continue;
      try {
        onEvent({ event, data: JSON.parse(dataLines.join("\n")) } as AskEvent);
      } catch {
        // ignore malformed event
      }
    }
  }
}
