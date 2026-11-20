# ResearchPilot - web UI

Next.js 16 (App Router) + Tailwind 4 frontend for the ResearchPilot API.

```bash
npm install
cp .env.example .env.local   # optional: point NEXT_PUBLIC_API_URL at your backend
npm run dev                  # http://localhost:3000 (backend must run on :8000)
```

- `src/lib/api.ts`: typed API client and the SSE parser for `POST /ask`
- `src/components/AskView.tsx`: question input, live agent steps, streamed answer, sources
- `src/components/Playground.tsx`: one query through four retrieval strategies, side by side
- `src/components/Sidebar.tsx`: backend status, documents, upload and delete

See the [project README](../README.md) for the architecture.
