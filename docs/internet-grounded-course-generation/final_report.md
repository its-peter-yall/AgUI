# Final Report: Internet-Grounded Course Generation

**Date:** 2026-08-01  
**Status:** COMPLETE (post-review fixes applied)  
**Final commit (this report):** `22885ba`

---

## 1. Original objective

Ground course planning and generation in current Internet material when users
explicitly enable web search. Overcome static LLM knowledge cutoffs with a
bounded Researcher, then feed a staged Planner that writes TOC first and
topic-level knowledge-transfer briefs (3 preview, then batches of 10) to
Generators. Web-off keeps the same progressive staged pipeline without research.

## 2. Research findings (summary)

Document: `research.md`  
Commits: `61ccbdc`, `873ccdb`, `511c546`

| Area | Decision |
|------|----------|
| **Providers** | Curated free-usable: **Tavily**, **Exa**, **Brave**, **SerpAPI** |
| **Excluded** | Serper (one-shot), Google CSE (closed), Bing (retired 2025), DDG scrapers |
| **Architecture** | `202` + durable LangGraph job; secrets in runtime context only |
| **Progress** | SQLite event log; SSE replay-then-tail; 2s poll fallback |
| **HTTP** | Raw `httpx` adapters; no new search SDKs |

## 3. Plan

Documents: `plan1.md` … `plan7.md` (commit `be1508d`)

| Phase | Focus |
|-------|--------|
| 1 | Contracts + curated registry |
| 2 | Focused SQLite persistence |
| 3 | Adapters, coordinator, Researcher |
| 4 | Staged LangGraph (TOC → 3 → ×10) |
| 5 | API: 202, SSE, research, cancel, resume |
| 6 | Settings, icon, progressive UI, Sources |
| 7 | Acceptance, security, coverage gates |

## 4. Implementation summary

### Server

- **Search package** `server/search/`: types, registry, httpx adapters (Tavily/Exa/Brave/SerpAPI), `ProviderCoordinator` (shuffle once; rotate rate/quota/timeout/5xx only), shared durable budget ledger, source safety, streamed byte-capped HTTP.
- **Researcher** `server/agents/researcher.py` + `server/services/research_runner.py`: bounded loop, incremental report sections, degraded-on-empty/incomplete, production wiring via real `ProviderCoordinator`.
- **Persistence** (focused modules, not LearningManager bloat): generation jobs/locks, research store, artifacts/briefs/citations, progress events + compaction.
- **Graph** staged workflow: optional research → outline → brief batches → gen/quiz fan-out → advance barrier; unique worker locks; cancel → retain; shutdown/startup pause; depth auto resolve once.
- **API**: `POST /learning/generate` → 202 shell; session poll with progressive columns; SSE events; research GET; cancel/resume with fresh secret headers.

### Client

- Settings: master web-search OFF default; four provider cards; keys localStorage-only.
- TopicInput: globe icon only when capable; per-course starts OFF; navigate on 202.
- LearningPage: generation status, SSE + poll, skeletons/TOC, Sources panel, citations, cancel retain + resume, ERROR per-card regen.

## 5. Code review outcomes

Document: `review.md`  
Initial verdict: **NO_SHIP** (7 critical, 14 major, 7 minor)  
Review commits: `0f82b60`, `72a13c7`

### Criticals fixed (`0f326e6` … `8d1dc25`)

| ID | Issue | Fix |
|----|--------|-----|
| C1 | Dead `SearchCoordinator` import | Wire `ProviderCoordinator` + adapters + ledger + lock |
| C2 | Lock not fencing writes | Unique worker UUID; fenced stage/progress; heartbeat abort |
| C3 | Poll missing progressive columns | SELECT `title_finalized` / `generation_status` |
| C4 | Cancel/restart wrong semantics | Research cancel cancels job; startup/shutdown PAUSED |
| C5 | Synthetic events / swallowed SQLite | Raise persist errors; no fake event id=1 |
| C6 | Secret leak via exception logs | `SecretStr` LLM key; `log_external_failure` |
| C7 | Build fail + weak acceptance | Fixture TS fix; production research path test |

### Majors fixed (`95fa243` … `856bead`)

M1–M14: shared durable budget, grounded completion rules, coverage integrity, topic-scoped briefs, step idempotency, batch barrier counts, depth resolve, streamed HTTP caps, resume events / poll race, list API shape, TOC on skeletons, ERROR regen + citations UX, citation sanitize/regen, event compact + coordinated delete.

### Minors

N1–N4, N6 fixed; N5 deferred (a11y/mobile); N7 partial (smoke removed; some React act/DOM-prop warnings remain).

## 6. Quality gates (verified 2026-08-01)

| Gate | Result |
|------|--------|
| Server `unittest discover -s server.tests` | **207 PASS** |
| Client `npm run test -- --run` | **87 PASS** |
| Client `npm run lint` | **PASS** (0 errors; coverage HTML warnings only) |
| Client `npm run build` | **PASS** (`tsc -b` + vite) |

## 7. Remaining known risks (non-blocking)

1. N5 keyboard/mobile a11y still imperfect.
2. Client test `act()` / framer-motion DOM-prop warnings (noise, tests pass).
3. Occasional LangGraph “coroutine never awaited” RuntimeWarning under forced mid-batch cancel in recovery tests.
4. Some acceptance paths still mock external LLM/HTTP (by design); full live provider E2E is manual.
5. Regen citation replace soft-fails when no brief/sources (logged).

## 8. How to use (manual smoke)

1. **Settings → Web Search**: master OFF by default → ON → configure ≥1 provider key (Tavily recommended).
2. **Learn home**: globe icon appears only when capable; starts OFF; enable for one course → submit.
3. Session opens immediately (`202`): research stage (if on) → TOC/skeletons → first 3 cards → later batches.
4. **Sources** panel + card citations when grounded; degraded warning if providers fail.
5. **Stop** retains partial course; **Resume** sends fresh LLM + search headers; **Delete** permanent cleanup.

### API surface

| Method | Path |
|--------|------|
| POST | `/learning/generate` → 202 |
| GET | `/learning/sessions/{id}` |
| GET | `/learning/sessions/{id}/events?after=N` |
| GET | `/learning/sessions/{id}/research` |
| POST | `/learning/sessions/{id}/cancel` |
| POST | `/learning/sessions/{id}/resume` |
| DELETE | `/learning/sessions/{id}` |

Search headers (generate/resume): `X-Web-Search`, `X-Web-Search-Providers`, `X-Tavily-Key`, `X-Exa-Key`, `X-Brave-Key`, `X-SerpApi-Key`.

## 9. Key docs & commit anchors

| Artifact | Path / hash |
|----------|-------------|
| Goal | `docs/internet-grounded-course-generation/goal.md` (`4251b40`) |
| Research | `research.md` (`61ccbdc`+) |
| Plans | `plan1.md`–`plan7.md` (`be1508d`) |
| Review | `review.md` (`0f82b60`) |
| Phase 7 harden | `458f183` |
| Critical fixes | `0f326e6`–`8d1dc25` |
| Major/minor fixes | `95fa243`–`22539c7` |
| HEAD at report write | `22539c7` |

## 10. Workflow complete

MAW steps executed: brainstorm/goal → research → phased plans → workers P1–P7 → hostile code review → fixers (criticals + majors) → full gates → this final report.
