// ---------- where the data comes from ----------
//
// live:   a real backend. NEXT_PUBLIC_API_URL, or http://localhost:8000 in development, or a
//         `?api=` link to a Cloudflare tunnel (for showing the live app from your own PC).
// replay: no backend configured (the hosted Vercel site). Recorded runs of the real backend
//         from /demo/replay.json, made by deploy/record_replay.py.

const ENV_API = (process.env.NEXT_PUBLIC_API_URL ?? (process.env.NODE_ENV === "development" ? "http://localhost:8000" : ""))
  .trim()
  .replace(/\/$/, "");
const SESSION_KEY = "researchpilot-api";

/** Only tunnels and localhost may be set through a link, so a shared URL can't point the
 * page at an arbitrary server. */
function allowedLiveUrl(raw: string): string | null {
  try {
    const u = new URL(raw);
    const local = u.hostname === "localhost" || u.hostname === "127.0.0.1";
    const tunnel = u.protocol === "https:" && u.hostname.endsWith(".trycloudflare.com");
    return local || tunnel ? u.origin : null;
  } catch {
    return null;
  }
}

export function apiBase(): string | null {
  if (typeof window !== "undefined") {
    const fromLink = new URLSearchParams(window.location.search).get("api");
    const ok = fromLink ? allowedLiveUrl(fromLink) : null;
    try {
      if (ok) sessionStorage.setItem(SESSION_KEY, ok);
      const saved = sessionStorage.getItem(SESSION_KEY);
      if (saved && allowedLiveUrl(saved)) return saved;
    } catch {
      if (ok) return ok;
    }
  }
  return ENV_API || null;
}

export const isReplay = () => apiBase() === null;

/** Human-readable backend location for messages. */
export const apiLabel = () => apiBase() ?? "replay data";

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
  demo?: boolean; // hosted read-only demo: no upload/delete, rate limited
  replay?: boolean; // recorded runs, no live backend
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

export interface RetrievalMetrics {
  "hit@1": number;
  "hit@3": number;
  "hit@5": number;
  "hit@10": number;
  "mrr@10": number;
  latency_ms: number;
}

export interface SystemSummary {
  n: number;
  errors: number;
  correctness: number | null;
  faithfulness: number | null;
  context_recall: number | null;
  latency_s: number | null;
  web_rate: number | null;
}

export interface SystemRun {
  answer?: string;
  latency_s?: number;
  found_source?: boolean;
  correctness?: number | null;
  faithfulness?: number | null;
  note?: string;
  used_web?: boolean;
  rewrites?: number;
  self_check?: string | null;
  error?: string;
}

export interface EvalReport {
  created_at: string;
  config: Record<string, string | number | null>;
  retrieval: {
    modes: Record<RetrievalMode, RetrievalMetrics>;
    per_question: { id: string; ranks: Record<RetrievalMode, number | null> }[];
  };
  answers: null | {
    judge_model: string;
    systems: Partial<Record<"simple" | "agent", SystemSummary>>;
    per_question: ({ id: string } & Partial<Record<"simple" | "agent", SystemRun>>)[];
  };
  testset: { id: string; question: string; reference: string; source: string; title: string; pages: string }[];
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

// ---------- replay data ----------

interface ReplayData {
  recorded_at: string;
  health: Health;
  documents: DocumentInfo[];
  eval: EvalReport;
  asks: Record<string, { agent: RecordedEvent[]; simple: RecordedEvent[] }>;
  searches: Record<string, Record<RetrievalMode, SearchResult>>;
}
type RecordedEvent = { t: number; event: AskEvent["event"]; data: unknown };

let replayData: Promise<ReplayData> | null = null;
const replay = () =>
  (replayData ??= fetch("/demo/replay.json").then((r) => {
    if (!r.ok) throw new Error("Replay data not found");
    return r.json() as Promise<ReplayData>;
  }));

export const REPLAY_HINT =
  "This is a replay of recorded runs. Pick one of the example questions, or run ResearchPilot locally to ask your own.";

const live = (path: string) => `${apiBase()}${path}`;

// ---------- API calls (live or replay) ----------

export const getHealth = async (): Promise<Health> =>
  isReplay() ? (await replay()).health : fetch(live("/health"), { cache: "no-store" }).then(json<Health>);

export const listDocuments = async (): Promise<DocumentInfo[]> =>
  isReplay() ? (await replay()).documents : fetch(live("/documents"), { cache: "no-store" }).then(json<DocumentInfo[]>);

export const deleteDocument = (docId: string) =>
  fetch(live(`/documents/${docId}`), { method: "DELETE" }).then(json<{ deleted: string }>);

export function uploadDocuments(files: File[]) {
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  return fetch(live("/documents"), { method: "POST", body: form }).then(
    json<{
      indexed: { title: string; source: string; chunks: number; skipped: boolean; seconds: number }[];
      errors: { file: string; error: string }[];
    }>,
  );
}

export const getEvalReport = async (): Promise<EvalReport> =>
  isReplay() ? (await replay()).eval : fetch(live("/eval/latest"), { cache: "no-store" }).then(json<EvalReport>);

export async function search(query: string, mode: RetrievalMode, top_n = 5): Promise<SearchResult> {
  if (isReplay()) {
    const recorded = (await replay()).searches[query.trim()]?.[mode];
    if (!recorded) throw new Error(REPLAY_HINT);
    await new Promise((r) => setTimeout(r, Math.min(600, 50 + (recorded.timings_ms.search ?? 0) + (recorded.timings_ms.rerank ?? 0) / 4)));
    return recorded;
  }
  return fetch(live("/search"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, mode, top_n }),
  }).then(json<SearchResult>);
}

export const replayExamples = async () => {
  const r = await replay();
  return { questions: Object.keys(r.asks), searches: Object.keys(r.searches), recordedAt: r.recorded_at };
};

/** Replay a recorded /ask stream at its real pace (long gaps capped so it never drags). */
async function replayAsk(question: string, agent: boolean, onEvent: (e: AskEvent) => void, signal?: AbortSignal) {
  const run = (await replay()).asks[question.trim()]?.[agent ? "agent" : "simple"];
  if (!run) throw new Error(REPLAY_HINT);
  let prev = 0;
  for (const ev of run) {
    const gap = Math.min(ev.t - prev, 2500);
    prev = ev.t;
    if (gap > 0) await new Promise((r) => setTimeout(r, gap));
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    onEvent({ event: ev.event, data: ev.data } as AskEvent);
  }
}

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
  if (isReplay()) return replayAsk(question, agent, onEvent, signal);
  const res = await fetch(live("/ask"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, agent }),
    signal,
  });
  if (!res.ok || !res.body) {
    // Surface the API's own message (e.g. the demo rate limit) instead of a bare status.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {}
    throw new Error(detail);
  }

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
