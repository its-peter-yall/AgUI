# Internet-Grounded Course Generation — Operations Runbook

Operator and developer guide for optional progressive web grounding.

## Provider Configuration

Supported search providers (browser registry IDs):

| ID | Product | Signup / docs |
|----|---------|---------------|
| `tavily` | Tavily | https://tavily.com |
| `exa` | Exa | https://exa.ai |
| `brave` | Brave Search | https://brave.com/search/api/ |
| `serpapi` | SerpAPI | https://serpapi.com |

- Master capability and per-course opt-in both **default OFF**.
- Keys are stored only in browser localStorage at rest.
- Keys are sent only on generate and resume requests that need them (headers such as `X-Tavily-Key`, `X-Exa-Key`, `X-Brave-Key`, `X-SerpApi-Key`).
- Users must verify current provider terms and quotas; this project does not publish live-provider smoke commands.

## Generation Stages

Ordered lifecycle:

```
INITIALIZING
  → RESEARCHING (web ON only)
  → OUTLINING
  → PLANNING_PREVIEW
  → GENERATING_PREVIEW
  → PLANNING_BATCH / GENERATING_BATCH (repeat)
  → COMPLETE | COMPLETE_DEGRADED

Side states:
  PAUSED      — resumable after restart or resumable error
  CANCELLED   — retained artifacts; resume allowed
  FAILED      — terminal failure
```

Research degradation continues useful generation but never shows a grounded label (`COMPLETE_DEGRADED` + `grounding_status=DEGRADED`).

## Secret Boundary

**Allowed (live only while a task runs):**

- In-memory `LLMContext` / `SearchContext` on the worker
- Outbound HTTP to OpenRouter / search providers

**Forbidden:**

- SQLite rows, LangGraph checkpoints, progress events, research reports
- Public JSON, SSE frames, HTTP error `detail`, application logs
- Exception messages and tracebacks (use `log_external_failure`)

Keys are sent only on generate and resume. Polling and SSE are credential-free.

## Cancellation and Resume

- Cancel is cooperative at graph boundaries; Cancelled work remains available (report, TOC, completed cards, cursor, events).
- Resume requires fresh credentials when research is unfinished and web was requested.
- Duplicate resume while a worker owns the lock returns **409**.
- Delete permanently removes the session and all generation artifacts (distinct from cancel).

## Restart Recovery

- Startup calls `mark_orphaned_jobs_paused()` for incomplete jobs with expired/missing locks.
- No automatic secret recovery — client must resume with fresh keys when needed.
- Stable thread id: `thread_id=gen-{session_id}` (same node IDs on resume; no duplicates).

## SSE and Polling

- Stream: `GET /learning/sessions/{id}/events` with `Last-Event-ID` and/or `?after=`.
- Replay-then-tail; disconnect never cancels or deletes work.
- Client repair: two-second polling of `GET /learning/sessions/{id}`.
- Client reconciles poll snapshots by monotonic `last_event_id` so stale HTTP cannot undo newer SSE state.

## Research Limits

- Depth/concept adaptive budgets via research ledger.
- Hard caps on search calls, wall time, results examined, provider bytes, and excerpt/context size.
- Approved provider rotation on rotatable error classes; exhaustion → degraded fallback without false grounded label.

## Troubleshooting

| Symptom | Likely cause | Action |
|---------|--------------|--------|
| Missing web icon / toggle | Capability OFF | Enable web search in Settings |
| `401` missing key | Resume/research needs credentials | Re-enter provider key and resume |
| `409` already running | Second worker / duplicate resume | Wait or cancel first |
| `409` not resumable | Job not PAUSED/CANCELLED | Check stage |
| Degraded providers | All search providers failed | Continue offline course; fix keys |
| Stream fallback | SSE blocked | Rely on 2s poll repair |
| Retained cancellation | User stopped mid-run | Resume or delete |

## Verification Commands

From repo root (`D:\Peter\A2UI`):

```powershell
server\.venv\Scripts\python.exe -m unittest
```

From `client/`:

```powershell
npm run test -- --run
npm run test:generation:coverage
npm run lint
npm run build
```

Automated tests mock all external APIs (Tavily, Exa, Brave, SerpAPI, OpenRouter, General Compute). No default suite performs live provider calls.
