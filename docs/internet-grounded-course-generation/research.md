# Research: Internet-Grounded Course Generation

**Access date:** 2026-08-01  
**Scope:** Implementation-detail research only. Locked product decisions in `goal.md` stand.

## Commit

- `61ccbdc55c4e9caec47de207594e6ed854061dda` — docs: research internet-grounded course generation

---

## 1. Executive Summary

Feature needs optional web search before Planner, durable staged LangGraph generation, SSE progress, and curated free-tier search providers. Research (2025–2026 sources) finds:

| Area | Finding |
|------|---------|
| **Providers** | Best free-usable APIs: **Tavily** (1k credits/mo, no CC), **Exa** ($10/mo free credits + $20 signup), **Brave** (~1k searches via $5 monthly credits; CC + attribution), **SerpAPI** (250/mo forever free). Exclude Google CSE (closed to new customers), Bing (retired 2025), DuckDuckGo scrapers (ToS/reliability). |
| **LangGraph** | Project already on `langgraph==1.2.4` + `AsyncSqliteSaver`. Use existing `context_schema` / `Runtime` for secrets; expand graph with researcher + staged planner/generator loops; `thread_id` = session/job id; do **not** cancel work on SSE disconnect. |
| **SSE** | Existing `regen_stream.py` is request-bound streaming. New architecture must **decouple job from connection**: persist progress events, SSE = replay-then-tail, poll as fallback. FastAPI native `EventSourceResponse` (or `StreamingResponse` + `text/event-stream`) with `Last-Event-ID`. |
| **Researcher** | Bounded ReAct-style loop: hard call/time/source/byte budgets; early stop on coverage; treat web text as untrusted; cite only validated source IDs. |
| **Codebase** | Reuse `CourseGraphContext`, `get_llm_context`, `providerSettings`/`buildProviderHeaders`, `Send()` fan-out, ERROR-card pattern. **New focused DB modules** — do not grow `LearningManager` god class. Prefer raw `httpx` adapters over new search SDKs. |

**Key architectural recommendation:** Flip `POST /learning/generate` from synchronous graph-until-done (today cancels + deletes session on disconnect) to **202 Accepted + durable job**. Run graph via `asyncio.create_task` with checkpointer `thread_id`; secrets only in runtime `context`; progress written to SQLite event log; SSE/poll consumers attach later. Staged planner (TOC → briefs×3 → briefs×10) and optional researcher sit inside same checkpointed graph.

---

## 2. Curated Provider Registry Recommendation

### 2.1 Candidate matrix (2026)

| Provider | Free tier | CC required? | Content extract? | Official signup | Verdict |
|----------|-----------|--------------|------------------|-----------------|---------|
| **Tavily** | 1,000 credits/mo (basic search = 1 credit); resets monthly | No | Yes (snippets/content in search; Extract API) | https://app.tavily.com | **INCLUDE #1** |
| **Exa** | $20 signup + **$10/mo** free credits (~1.4k basic searches/mo at $7/1k) | No for free tier | Yes (text/highlights in first 10 results) | https://dashboard.exa.ai/api-keys | **INCLUDE #2** |
| **Brave Search** | $5 monthly credits ≈ **1,000** Search req at $5/1k | **Yes** (anti-fraud) | Snippets; LLM Context endpoint available | https://api-dashboard.search.brave.com | **INCLUDE #3** (UX friction) |
| **SerpAPI** | **250 searches/mo** forever free; 50/hr | No | Organic snippets; not full-page fetch | https://serpapi.com | **INCLUDE #4** (low volume backup) |
| **Serper** | 2,500 queries **one-time** trial | No | SERP snippets | https://serper.dev | **EXCLUDE** initial registry (not recurring free) |
| **You.com** | $100 signup credits; Web Search $5/1k | No for trial | Snippets + optional livecrawl | https://you.com/platform | **DEFER** (strong trial; not monthly free) |
| **Google CSE** | 100/day (legacy) | N/A | Snippets | Closed to **new** customers; sunsets **2027-01-01** | **EXCLUDE** |
| **Bing/Azure Web Search** | N/A | N/A | N/A | Public Bing Search APIs **retired 2025-08-11** | **EXCLUDE** |
| **DuckDuckGo unofficial** (`ddgs` scrapers) | “Free” until blocked | No | Parsed HTML | No official SERP API | **EXCLUDE** (ToS, rate limits, breakage) |
| **SearXNG** | Self-host unlimited | N/A | Depends on engines | Self-host | **EXCLUDE** curated registry (ops burden; optional later advanced) |

### 2.2 Per-provider detail (include set)

#### Tavily (rank 1)

| Field | Value |
|-------|--------|
| Free tier | 1,000 API credits/month; basic/fast/ultra-fast = 1 credit; advanced = 2 |
| Rate limits | Dev key: 100 RPM; Prod: 1,000 RPM (prod needs paid/PAYGO) |
| Signup | https://app.tavily.com — no CC |
| Endpoint | `POST https://api.tavily.com/search` |
| Auth | `Authorization: Bearer tvly-...` |
| Response shape | `{ results: [{ title, url, content, score, published_date? }], answer?, query }` |
| Content | Included in `content`; separate Extract/Crawl endpoints |
| Rate-limit HTTP | 429; respect `retry-after` |
| Python client | Official `tavily-python` **or** raw httpx (prefer httpx) |
| Terms note | Built for AI agents; student free tier exists via support |
| **Why include** | Best DX for educational agents; monthly free; no CC; content-ready |

#### Exa (rank 2)

| Field | Value |
|-------|--------|
| Free tier | $20 on signup + $10/mo free credits; no payment method required |
| Pricing ref | Search ~$7/1k (up to 10 results w/ contents); Answer $5/1k |
| Rate limits | `/search` ~10 QPS default |
| Signup | https://dashboard.exa.ai/api-keys |
| Endpoint | `POST https://api.exa.ai/search` |
| Auth | `x-api-key` header or Bearer |
| Response shape | `{ results: [{ title, url, publishedDate, author, text, highlights, summary? }], costDollars? }` |
| Content | Text/highlights included for first 10 |
| Rate-limit HTTP | 429; 402 when credits exhausted |
| Python client | Official `exa-py` **or** httpx |
| **Why include** | Neural/semantic search strong for course topics; recurring free credits; content in-box |

#### Brave Search (rank 3)

| Field | Value |
|-------|--------|
| Free tier | $5 credits/mo per plan ≈ 1,000 Search requests; credits do not roll over |
| Friction | **Credit card required**; attribution (“POWERED BY BRAVE”) required to keep free credits |
| Rate limits | Search plan up to ~50 QPS; headers `X-RateLimit-*` |
| Signup | https://api-dashboard.search.brave.com/register |
| Endpoint | `GET https://api.search.brave.com/res/v1/web/search?q=...` |
| Auth | `X-Subscription-Token: <key>` |
| Response shape | `{ web: { results: [{ title, url, description, age?, extra_snippets? }] } }` |
| Content | Snippets; optional LLM Context endpoint (same plan family) |
| Rate-limit HTTP | 429 + rate-limit headers |
| Python client | REST via httpx (no mandatory SDK) |
| Terms note | Often restricts long-term result storage / training; transient operational storage OK — align retention with ToS (store only excerpts needed for course citations) |
| **Why include** | Independent index diversity; usable free credits; well-documented REST |
| **Why not #1** | CC barrier + attribution UI requirement |

#### SerpAPI (rank 4)

| Field | Value |
|-------|--------|
| Free tier | 250 searches/month recurring; 50/hour throughput |
| Signup | https://serpapi.com/users/sign_up |
| Endpoint | `GET https://serpapi.com/search.json?q=...&api_key=...` |
| Auth | Query param `api_key` or header |
| Response shape | Google SERP JSON: `organic_results[{ title, link, snippet, position }]` |
| Content | Snippets only (no full page) |
| Rate-limit HTTP | 429 |
| Python client | Official `google-search-results` **or** httpx |
| **Why include** | True forever-free monthly; good failover when others exhausted |
| **Why low rank** | Low monthly quota; no page body — may need separate fetch or accept snippet-only grounding |

### 2.3 Decision: initial curated registry

**Ship these four** (user enables any subset):

1. **tavily** — default recommended in Settings copy  
2. **exa** — semantic diversity  
3. **brave** — independent index (document CC + attribution)  
4. **serpapi** — low-volume always-free backup  

**Do not ship initially:** Serper (one-shot trial), You.com (trial credits only — revisit), Google CSE, Bing, DDG scrapers, SearXNG.

**Settings card fields per provider:** `id`, display name, free-tier blurb, signup URL, docs URL, `apiKey` (localStorage), `enabled`, optional `attributionRequired` (Brave).

---

## 3. Adapter Contract Sketch

Prefer **httpx-only** adapters under `server/search/` — no new SDK deps unless pain is severe.

```python
# server/search/types.py (sketch)
from enum import Enum
from typing import Optional, Protocol
from pydantic import BaseModel, Field, HttpUrl

class SearchErrorClass(str, Enum):
    AUTH = "auth"                 # 401/403 — do NOT rotate
    INVALID_REQUEST = "invalid"   # 400 — do NOT rotate
    POLICY = "policy"             # 451/blocked — do NOT rotate
    RATE_LIMIT = "rate_limit"     # 429 — rotate after backoff
    QUOTA = "quota"               # 402/quota exhausted — rotate
    TIMEOUT = "timeout"           # rotate
    AVAILABILITY = "availability" # 5xx — rotate
    UNKNOWN = "unknown"

class SearchError(Exception):
    def __init__(
        self,
        message: str,
        *,
        error_class: SearchErrorClass,
        provider: str,
        status_code: Optional[int] = None,
        retry_after_s: Optional[float] = None,
    ) -> None: ...

class SearchQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    max_results: int = Field(default=8, ge=1, le=20)
    recency_days: Optional[int] = Field(default=None, ge=1, le=3650)
    include_domains: list[str] = Field(default_factory=list)
    exclude_domains: list[str] = Field(default_factory=list)

class NormalizedHit(BaseModel):
    title: str
    url: str
    snippet: str = ""
    content: str = ""          # capped excerpt
    publisher: Optional[str] = None
    published_at: Optional[str] = None  # ISO if known
    retrieved_at: str                  # ISO
    provider: str
    raw_score: Optional[float] = None
    canonical_url: str                 # normalized for dedupe

class SearchAdapter(Protocol):
    provider_id: str

    async def search(
        self,
        query: SearchQuery,
        *,
        api_key: str,
        timeout_s: float = 20.0,
    ) -> list[NormalizedHit]:
        """Raise SearchError with typed error_class."""
        ...
```

```python
# server/search/coordinator.py (sketch)
class ProviderCoordinator:
    """Shuffle once per job; rotate only rate/quota/timeout/5xx."""

    def __init__(self, adapters: list[SearchAdapter], keys: dict[str, str]) -> None: ...

    async def search(self, query: SearchQuery) -> list[NormalizedHit]:
        # 1. try current provider with exponential backoff + jitter (bounded)
        # 2. on RATE_LIMIT/QUOTA/TIMEOUT/AVAILABILITY → mark unhealthy, next
        # 3. on AUTH/INVALID/POLICY → surface warning, do not rotate silently
        # 4. if all dead → raise AllProvidersUnavailable
        ...
```

**URL safety helpers:** allow only `http`/`https`; reject credentials-in-URL; canonicalize (strip tracking params carefully; lowercase host; drop fragment).

**Content caps:** e.g. snippet ≤ 2k chars, content ≤ 8k chars per hit, total fetched bytes budget per job.

---

## 4. LangGraph Architecture Recommendations

### 4.1 Current project baseline

| Piece | Location | Behavior |
|-------|----------|----------|
| Graph | `server/graph/build.py` | `StateGraph(CourseState, context_schema=CourseGraphContext)` |
| Checkpointer | `server/main.py` lifespan | `AsyncSqliteSaver` → `app.state.checkpointer` |
| Secrets | `CourseGraphContext.llm_context` | Runtime context — not checkpoint channels |
| Invoke | `learning.py:_generate_course_with_graph` | `ainvoke` + **cancel on disconnect + delete session** |
| Fan-out | `fan_out_generators` / `fan_out_quizzers` | `Send()`; preview first 3 topics only |
| Background tail | `_generate_remaining_nodes_bg` | Batches of 5 + 30s sleep via `BackgroundTasks` |
| Versions | `requirements.txt` | `langgraph==1.2.4`, `langgraph-checkpoint-sqlite==3.1.0`, `aiosqlite==0.22.1` |

### 4.2 Target graph shape (aligned with goal.md)

```text
START
  → route_web?
       yes → researcher_node → outline_planner_node
       no  → outline_planner_node
  → persist_toc_skeletons
  → brief_planner_preview (≤3)
  → fan_out_generators_preview → fan_out_quizzers_preview
  → loop: brief_planner_batch (≤10) → gen fan-out → quiz fan-out
  → finalize_node → END
```

**Interrupt / pause:** cooperative cancel flag in DB (or LangGraph interrupt) checked between researcher calls, planner turns, and batch boundaries. Resume = new HTTP call supplies fresh secrets in `context`, `ainvoke(None, config)` or `aupdate_state` + continue from checkpoint.

### 4.3 Runtime context (secrets never checkpointed)

Extend existing pattern — already correct direction:

```python
class CourseGraphContext(TypedDict):
    llm_context: LLMContext
    session_ref: dict[str, str]
    # NEW — request-scoped only
    search_credentials: NotRequired[dict[str, str]]  # provider_id -> api_key
    web_search_enabled: NotRequired[bool]
    cancel_event: NotRequired[Any]  # asyncio.Event or job-local flag reader
```

Invoke (background, not tied to HTTP body lifetime):

```python
config = {
    "configurable": {
        "thread_id": f"gen-{session_id}",  # stable, resumable
    }
}
context = {
    "llm_context": llm_context,
    "session_ref": session_ref,
    "search_credentials": search_keys,  # ephemeral
    "web_search_enabled": web_on,
}
asyncio.create_task(
    graph.ainvoke(input_state, config=config, context=context)
)
# Do NOT cancel this task when SSE client disconnects.
```

### 4.4 Custom progress events

Prefer **DB-backed progress events** as source of truth (survives restart better than only stream_writer). Optionally also emit via LangGraph custom stream for live tail:

```python
from langgraph.config import get_stream_writer

async def researcher_node(state, runtime):
    writer = get_stream_writer()  # optional dual-write
    section = await write_section(...)
    event = persist_progress(session_id, "research_section_ready", payload)
    writer({"type": "research_section_ready", "id": event["id"], ...})
    return {"research_report_id": ...}
```

For product SSE, **poll DB by cursor** is more reliable than attaching solely to `astream` of a fire-and-forget task (multiple subscribers, reconnect). Pattern: graph writes events → SSE reads events.

### 4.5 Batched Send() fan-out

Reuse `Send` but gate by cursor:

```python
def fan_out_batch(state: CourseState) -> list[Send]:
    start = state["batch_start"]  # 0, then 3, 13, ...
    size = 3 if start == 0 else 10
    topics = state["outline"]["topics"][start:start + size]
    return [
        Send("generator_node", {..., "sequence_index": t["index"]})
        for t in topics
    ]
```

After quiz batch completes, planner brief node advances `batch_start` or routes to END.

### 4.6 Checkpointer practices

- Keep lifespan-scoped `AsyncSqliteSaver` (already correct; avoids hang-on-exit if connection closed properly).
- One `thread_id` per generation job/session.
- Checkpoint state holds: stage, cursors, outline refs, report id, counts — **never** API keys.
- On server restart: job stays `PAUSED` or `INCOMPLETE` until client `POST .../resume` with fresh headers.
- Note upstream: AsyncSqliteSaver not ideal for multi-writer production; fine for single-user A2UI.

### 4.7 Staged planner contract (briefs internal)

```python
class CourseTOC(BaseModel):
    course_title: str
    topics: list[TopicSkeleton]  # title, summary, complexity, key_terms, quiz_count

class GenerationBrief(BaseModel):
    topic_index: int
    objectives: list[str]
    prerequisites: list[str]
    current_facts: list[str]
    deprecated_notes: list[str]
    source_ids: list[str] = []
    source_excerpts: list[str] = []
    examples: list[str]
    misconceptions: list[str]
    pedagogy: str
    boundaries: str
    quiz_targets: list[str]
```

Briefs never leave session API responses.

---

## 5. SSE / Progress Architecture

### 5.1 Problem with current generate path

Today `_generate_course_with_graph` **cancels graph and deletes session** on client disconnect. Goal requires opposite: work continues; UI reconnects.

### 5.2 Recommended pattern: durable events + replay-then-tail

```text
POST /learning/generate → 202 { session, job }
     └─ asyncio task runs graph; writes progress_events rows

GET /learning/sessions/{id}/events?after={cursor}
     └─ SSE: replay id > cursor, then tail new rows (long-poll/sleep)
     └─ on disconnect: exit generator ONLY — do not cancel job

GET /learning/sessions/{id} every 2s
     └─ fallback repair (already natural for React Query)
```

### 5.3 SSE frame sketch (reuse regen_stream style)

Existing `regen_stream.py` uses:

```text
data: {"delta": "..."}\n\n
data: [DONE]\n\n
```

Extend with event id for reconnect:

```python
async def stream_session_events(
    session_id: str,
    last_event_id: int | None,
) -> AsyncGenerator[str, None]:
    cursor = last_event_id or 0
    while True:
        rows = event_store.list_after(session_id, cursor, limit=50)
        if not rows:
            # heartbeat comment keeps proxies happy
            yield ": keepalive\n\n"
            await asyncio.sleep(0.5)
            if job_terminal(session_id):
                yield f"id: {cursor}\ndata: {json.dumps({'type': 'generation_complete'})}\n\n"
                return
            continue
        for row in rows:
            cursor = row["id"]
            payload = row["payload_json"]  # already redacted
            yield f"id: {cursor}\nevent: {row['type']}\ndata: {json.dumps(payload)}\n\n"
            if row["type"] in TERMINAL:
                return
```

Router:

```python
@router.get("/sessions/{session_id}/events")
async def session_events(
    session_id: str,
    last_event_id: Annotated[Optional[str], Header(alias="Last-Event-ID")] = None,
    after: Optional[int] = Query(None),
):
    cursor = int(after or last_event_id or 0)
    return StreamingResponse(
        stream_session_events(session_id, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

Optional: FastAPI `EventSourceResponse` / `ServerSentEvent` if available in project’s FastAPI version — same semantics.

### 5.4 Event types (goal.md)

`stage_changed`, `research_section_ready`, `research_degraded`, `outline_ready`, `module_ready`, `module_failed`, `generation_paused`, `generation_cancelled`, `generation_complete`.

### 5.5 Redaction rules

Never put in events/logs/DB: API keys, raw `Authorization` headers, full provider error bodies that echo keys. Mask provider errors to `error_class` + safe message.

### 5.6 Client

- `EventSource` or fetch-stream with `Last-Event-ID`.
- Apply events into React Query cache (`setQueryData` for session).
- 2s `refetchInterval` while stage non-terminal.
- Immediate navigate on 202 shell (change `generateCourse` timeout/expect 202).

---

## 6. Researcher Loop Design

### 6.1 Loop algorithm

```text
1. Analyze intent → coverage map (fundamentals, versions, conventions,
   methodologies, shifts, deprecations, disputes)
2. Budget = f(resolved_depth, provisional_concept_count)
3. While budget remaining and coverage incomplete:
     a. Pick next query (gap-driven)
     b. coordinator.search(query)
     c. normalize + dedupe by canonical_url
     d. optional focused follow-ups
     e. write/update theme section incrementally
     f. check cancel flag
4. Finalize report: summary, limitations, freshness, source map
5. If zero successful searches → degraded flag, empty/partial report
```

### 6.2 Hard budgets (defaults — tune in impl)

| Budget | Lite | Full | Hard max |
|--------|------|------|----------|
| Search API calls | 6 | 14 | 20 |
| LLM researcher turns | 4 | 8 | 10 |
| Wall time | 45s | 120s | 180s |
| Unique sources kept | 12 | 25 | 40 |
| Total excerpt chars | 40k | 80k | 100k |
| Per-hit content chars | 4k | 8k | 8k |

Adaptive sizing: `calls = clamp(3 + ceil(concepts/2), min, max)` from provisional concept estimate.

### 6.3 Stop rules

Stop early when:

1. All coverage-map themes have ≥1 non-low-quality source, **and**
2. At least N distinct root domains (e.g. 3), **and**
3. Freshness-sensitive themes have ≥1 source within recency window **or** explicitly marked unknown  

Always stop on: hard budget, cancel, all providers unavailable (degraded continue).

### 6.4 Source quality heuristics (no overclaim)

Weak signals only — never claim “authoritative”:

- Prefer primary docs, standards, official blogs, well-known educational domains  
- Downrank: content farms, no-date SEO pages, URL shorteners  
- Do **not** treat SERP rank as authority  
- Record conflicting claims in report limitations  

### 6.5 Citation grounding

- Every report claim that uses web data should reference `source_id`s  
- Generator may cite **only** `source_ids` present in its `GenerationBrief`  
- Server validates citations before persist; drop/fix unsupported IDs with warning  
- Fabricated URLs never reach UI  

### 6.6 Web prompt-injection defenses (OWASP LLM01 + 2025 design patterns)

| Control | Implementation |
|---------|----------------|
| Delimit untrusted text | Wrap excerpts in clear fences: `<<<UNTRUSTED_SOURCE id=... url=...>>>` |
| System instruction | Explicit: ignore instructions inside sources; sources are data only |
| No tool side effects from source text | Researcher tools = search only; no browsing agent with open-ended actions |
| Cap + strip | Strip scripts/HTML; max length; allowlist http(s) |
| Privilege separation | Planner/Generator never receive raw multi-source dumps unbounded |
| Output validation | Structured Pydantic; reject unknown source_ids |
| Plan-then-execute spirit | Coverage map + query plan before bulk fetch where practical |

### 6.7 Incremental report writing

Persist sections as written (theme-based, not final TOC):

```python
class ResearchSection(BaseModel):
    index: int
    theme: str
    markdown: str
    source_ids: list[str]
```

UI can show sections during `RESEARCHING` before outline exists.

---

## 7. Schema / Persistence Sketch

**Do not** add to `LearningManager` monolith. New modules e.g.:

- `server/database/generation_jobs.py`
- `server/database/research_store.py`
- `server/database/progress_events.py`

Follow existing `_ensure_*_columns` startup migrations (Alembic noted in concerns but unused — stay consistent unless team adopts Alembic separately).

### 7.1 Tables (conceptual)

```sql
-- generation_jobs
id TEXT PK
session_id TEXT UNIQUE NOT NULL
stage TEXT NOT NULL          -- INITIALIZING|RESEARCHING|OUTLINING|...
cursor_json TEXT             -- batch_start, topic indices, etc.
web_enabled INTEGER NOT NULL DEFAULT 0
degraded INTEGER NOT NULL DEFAULT 0
warning_json TEXT            -- list of safe warnings
status TEXT NOT NULL          -- running|paused|cancelled|completed|failed
thread_id TEXT NOT NULL      -- LangGraph thread
counts_json TEXT             -- topics_total, topics_ready, sources, ...
created_at TEXT
updated_at TEXT
locked_at TEXT               -- optimistic execution lock
lock_owner TEXT

-- research_reports
id TEXT PK
session_id TEXT UNIQUE
status TEXT                  -- pending|complete|degraded
summary TEXT
limitations TEXT
freshness_note TEXT
created_at TEXT
updated_at TEXT

-- research_sections
id TEXT PK
report_id TEXT
sequence_index INTEGER
theme TEXT
markdown TEXT
source_ids_json TEXT
UNIQUE(report_id, sequence_index)

-- research_sources
id TEXT PK                   -- public source_id
session_id TEXT
canonical_url TEXT
url TEXT
title TEXT
publisher TEXT
published_at TEXT
retrieved_at TEXT
provider TEXT
excerpt TEXT
content_hash TEXT
UNIQUE(session_id, canonical_url)

-- generation_briefs  (PRIVATE — no API exposure)
id TEXT PK
session_id TEXT
topic_index INTEGER
brief_json TEXT
UNIQUE(session_id, topic_index)

-- node_sources
node_id TEXT
source_id TEXT
PRIMARY KEY(node_id, source_id)

-- progress_events
id INTEGER PK AUTOINCREMENT  -- monotonic cursor
session_id TEXT
type TEXT
payload_json TEXT            -- redacted
created_at TEXT
INDEX(session_id, id)
```

Idempotent writes at stage boundaries: upsert by natural keys; transactions around TOC skeleton create + stage flip.

### 7.2 Stage machine

Validate transitions explicitly (mirror node status pattern in `learning_persistence`). Terminal: `FAILED`. Retained: `CANCELLED`, `PAUSED`. Success: `COMPLETE`, `COMPLETE_DEGRADED`.

---

## 8. Client Settings / Header Patterns

### 8.1 Extend `providerSettings.ts` pattern

Add parallel storage key e.g. `web_search_settings`:

```typescript
interface WebSearchProviderConfig {
  apiKey: string;
  enabled: boolean;
}

interface WebSearchSettings {
  masterEnabled: boolean; // default false
  providers: Record<WebSearchProviderId, WebSearchProviderConfig>;
}
```

Master OFF → no provider UI, no search icon.  
Master ON → show curated cards; icon only if ≥1 enabled provider with non-empty key.

### 8.2 Headers (mirror LLM keys)

```http
X-Web-Search: true|false          # per-course opt-in
X-Web-Search-Providers: tavily,exa
X-Tavily-Key: ...
X-Exa-Key: ...
X-Brave-Key: ...
X-SerpApi-Key: ...
```

Only attach search keys on generate/resume (and any endpoint that continues research) — not on every quiz submit.

```typescript
// learningApi.ts sketch
function buildWebSearchHeaders(perCourseSearchOn: boolean): Record<string, string> {
  const ws = getWebSearchSettings();
  if (!ws.masterEnabled || !perCourseSearchOn) {
    return { 'X-Web-Search': 'false' };
  }
  const headers: Record<string, string> = { 'X-Web-Search': 'true' };
  const enabled = ...;
  headers['X-Web-Search-Providers'] = enabled.map(p => p.id).join(',');
  for (const p of enabled) {
    headers[p.keyHeader] = p.apiKey;
  }
  return headers;
}
```

Server: `get_search_context()` FastAPI dependency analogous to `get_llm_context()` — validate shape, never log keys.

### 8.3 TopicInput

- Search icon toggles local `webSearchOn` default **false** each new course  
- Submit → expect **202** → `navigate(/learn/${sessionId})` immediately  
- Drop wait-for-full-generation UX  

### 8.4 Settings page

Reuse card patterns from `OpenRouterSettingsPanel`: mask keys (`maskApiKey`), link out to signup URLs from registry metadata, free-tier one-liners.

---

## 9. Risk Register & Open Technical Choices

### 9.1 Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Free-tier exhaustion mid-course | Med | Shuffle + rotate; degraded continue; clear warning |
| Brave CC / attribution friction | Med | Honest Settings copy; not default recommended |
| Provider ToS on result storage | Med | Store excerpts + metadata for citations only; document retention |
| Prompt injection via web pages | High | Delimiters, caps, no open browser agent, citation allowlist |
| SQLite single-writer under fan-out | Med | Cap concurrency; batch transactions; short writes |
| Secrets in checkpoints/logs | High | context-only keys; redaction tests; no keys in events |
| Disconnect cancel regresses | High | Remove cancel-on-disconnect from generate path; tests |
| LearningManager growth | Med | New modules only |
| LangGraph task orphan after process kill | Med | Resume endpoint + stage cursor; no secret recovery |
| SSE proxy buffering | Low | `X-Accel-Buffering: no`, heartbeats |
| Exa/Tavily pricing change | Med | Registry metadata versioned; re-verify before release |

### 9.2 Open implementation choices (not product locks)

1. **sse-starlette vs raw StreamingResponse** — raw matches `regen_stream.py`; FastAPI native SSE if version supports `EventSourceResponse`.  
2. **Dual-write stream_writer + DB** vs **DB-only events** — recommend DB-only for multi-subscriber simplicity.  
3. **LangGraph interrupt()** vs cooperative DB cancel flag — DB flag simpler with current codebase.  
4. **Snippet-only vs fetch page bodies** for SerpAPI/Brave — start snippet-only; optional later httpx fetch with strict caps (non-goal: full browser).  
5. **thread_id = session_id** vs separate job id — prefer stable `gen-{session_id}`.  
6. **Whether researcher uses Instructor structured steps** each turn vs one big structured plan — prefer small structured turns with budget counters.  
7. **Concurrency within batch** — start serial or 2-way parallel to protect SQLite/LLM rate limits; goal allows lower than batch size.  
8. **Progress event compaction** — delete or roll up after COMPLETE after N days.  

---

## 10. Codebase Reuse Map

### 10.1 Extend (prefer)

| File | Reuse |
|------|--------|
| `server/graph/state.py` | Extend `CourseState` / `CourseGraphContext` |
| `server/graph/build.py` | New nodes/edges; keep checkpointer wiring |
| `server/graph/nodes.py` | Patterns: `_get_llm_context`, `Send`, error handlers, ERROR cards |
| `server/graph/regen_stream.py` | SSE framing style |
| `server/agents/base.py` | New `ResearcherAgent(BaseAgent)` |
| `server/utils/instructor_client.py` | Add `researcher` role in `MODEL_CONFIGS` |
| `server/schemas/llm.py` | Add `get_search_context` dependency |
| `server/schemas/learning.py` | TOC/brief/report response models (briefs internal) |
| `server/routers/learning.py` | 202 generate, events, research, cancel, resume |
| `server/main.py` | Lifespan checkpointer already OK |
| `client/src/lib/providerSettings.ts` | Clone pattern for web search settings |
| `client/src/lib/providerApi.ts` | `buildProviderHeaders` sibling for search keys |
| `client/src/lib/learningApi.ts` | 202 + EventSource helpers |
| `client/src/features/settings/` | Provider cards UI patterns |
| `client/src/features/learning/TopicInput.tsx` | Icon + navigate-on-202 |
| `server/tests/test_graph.py`, `test_regen_stream.py` | Test patterns |

### 10.2 New modules (prefer)

```text
server/search/
  __init__.py
  types.py
  coordinator.py
  adapters/tavily.py
  adapters/exa.py
  adapters/brave.py
  adapters/serpapi.py
  url_safety.py
server/agents/researcher.py
server/database/generation_jobs.py
server/database/research_store.py
server/database/progress_events.py
server/schemas/research.py
server/schemas/generation.py
client/src/lib/webSearchSettings.ts
client/src/features/settings/WebSearchSettingsPanel.tsx
client/src/features/learning/CourseSourcesPanel.tsx
client/src/features/learning/useSessionEvents.ts
```

### 10.3 Avoid

- Expanding `learning_persistence.py` with research/job APIs  
- Celery/Redis/external queue  
- Server-side permanent key vault  
- Unofficial DDG scraping  
- Paid-only providers in default registry  

### 10.4 Dependency recommendations

| Need | Recommendation |
|------|----------------|
| HTTP to search APIs | Existing **httpx** |
| Structured LLM | Existing **instructor** + **openai** |
| Graph | Existing **langgraph** 1.2.4 |
| Retry | Existing **tenacity** (adapters + coordinator) |
| SSE | stdlib + FastAPI `StreamingResponse` (optional `sse-starlette` only if needed) |
| HTML strip | stdlib + careful regex, or tiny existing approach; avoid heavy browser stack |
| **Do not add** initially | `tavily-python`, `exa-py`, `brave-search`, celery, redis, playwright |

`package.json`: no required new deps for EventSource (browser native); optional polyfill none for modern browsers.

---

## 11. Best-Practice Snippets

### 11.1 202 generate shell

```python
@router.post("/generate", status_code=202)
async def generate_course(...):
    session = learning_manager.create_learning_session_shell(...)
    job = generation_jobs.create(session_id=session["id"], stage="INITIALIZING", ...)
    asyncio.create_task(run_generation_job(session["id"], llm_context, search_context))
    return SessionShellResponse(session=session, job=job.to_public())
```

### 11.2 Degraded research path

```python
try:
    report = await researcher.run(...)
except AllProvidersUnavailable:
    persist_warning(session_id, "web_search_unavailable")
    mark_degraded(session_id)
    report = empty_report(status="degraded")
# always continue to outline_planner
```

### 11.3 Citation validation

```python
allowed = set(brief.source_ids)
clean = [c for c in model_citations if c.source_id in allowed]
if len(clean) < len(model_citations):
    warnings.append("removed_unsupported_citations")
```

### 11.4 Execution lock

```python
if not jobs.try_acquire(session_id, owner=worker_id, ttl_s=600):
    raise HTTPException(409, "Generation already running")
```

---

## 12. Testing Implications (from research)

Mock all search HTTP with `httpx.MockTransport` or `unittest.mock`. Cover:

- Adapter error_class mapping (401 vs 429 vs 500)  
- Coordinator rotate vs no-rotate  
- Budget hard stop  
- URL allowlist / caps  
- SSE replay from cursor  
- Generate disconnect does **not** delete session  
- Resume requires headers; no keys in DB fixtures  

---

## 13. Sources / Links

Access date unless noted: **2026-08-01**.

### Search providers

- Tavily credits: https://docs.tavily.com/documentation/api-credits  
- Tavily quickstart: https://docs.tavily.com/documentation/quickstart  
- Tavily rate limits: https://docs.tavily.com/documentation/rate-limits  
- Tavily search API: https://docs.tavily.com/documentation/api-reference/endpoint/search  
- Tavily pricing: https://www.tavily.com/pricing  
- Exa pricing: https://exa.ai/pricing  
- Exa billing/free tier: https://exa.ai/docs/reference/billing  
- Exa rate limits: https://exa.ai/docs/reference/rate-limits  
- Exa search API: https://exa.ai/docs/reference/search  
- Brave pricing: https://api-dashboard.search.brave.com/documentation/pricing  
- Brave product: https://brave.com/search/api/  
- Brave quickstart: https://api-dashboard.search.brave.com/documentation/quickstart  
- Brave rate limiting: https://api-dashboard.search.brave.com/documentation/guides/rate-limiting  
- Brave plan changes (2026): https://brave.com/blog/most-powerful-search-api-for-ai/  
- Serper: https://serper.dev/  
- SerpAPI pricing: https://serpapi.com/pricing  
- You.com billing: https://you.com/docs/administration/billing  
- You.com pricing: https://you.com/pricing  
- Google CSE overview (closed/sunset): https://developers.google.com/custom-search/v1/overview  
- DuckDuckGo unofficial caveats: https://link.sc/blog/duckduckgo-search-api-guide  

### LangGraph / FastAPI / safety

- LangGraph streaming: https://docs.langchain.com/oss/python/langgraph/streaming  
- LangGraph Runtime: https://reference.langchain.com/python/langgraph/runtime/Runtime  
- LangGraph checkpoints: https://reference.langchain.com/python/langgraph/checkpoints  
- AsyncSqliteSaver source notes: https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-sqlite/langgraph/checkpoint/sqlite/aio.py  
- FastAPI SSE: https://fastapi.tiangolo.com/tutorial/server-sent-events/  
- FastAPI SSE reference: https://fastapi.tiangolo.com/reference/sse/  
- Replay-then-tail SSE pattern: https://dev.to/akshatsoni26/5-minute-ai-jobs-and-closed-tabs-why-we-built-replay-then-tail-sse-2fn1  
- FastAPI disconnect discussion: https://github.com/fastapi/fastapi/discussions/14552  
- OWASP LLM01 Prompt Injection: https://genai.owasp.org/llmrisk/llm01-prompt-injection/  
- Design patterns securing LLM agents (2025): https://arxiv.org/html/2506.08837v3  
- Inference-time budget control for search agents (2026): https://arxiv.org/html/2605.05701v1  

### Internal

- `docs/internet-grounded-course-generation/goal.md`  
- `.planning/codebase/ARCHITECTURE.md`, `STACK.md`, `INTEGRATIONS.md`, `CONCERNS.md`, `STRUCTURE.md`  
- `server/graph/*`, `server/routers/learning.py`, `server/schemas/llm.py`  
- `client/src/lib/providerSettings.ts`, `providerApi.ts`, `learningApi.ts`  

---

## 14. Summary Ranking for Implementers

**Providers to implement first:** Tavily → Exa → Brave → SerpAPI.

**Architecture one-liner:** Durable checkpointed LangGraph job + SQLite progress log + secret-free state + SSE replay; researcher optional hop before staged TOC/brief/generate pipeline.

**Do not implement in research phase:** application feature code (this document only).
