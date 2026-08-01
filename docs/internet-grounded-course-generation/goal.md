# Goal: Internet-Grounded Course Generation

## Original Objective

Ground course planning and generation in current Internet material when users
explicitly request web search. Static model knowledge can miss new concepts,
revised methodologies, current versions, paradigm shifts, and deprecated
practices. Optional research must close that gap without making web access
mandatory for normal course generation.

Web-enabled generation adds a Researcher before the Planner. Researcher performs
iterative, bounded exploration, writes a detailed report in sections, and stores
normalized sources. Planner reads user query plus report, writes table of
contents first, then transfers topic-specific knowledge to Generators in staged
batches. Web-disabled generation uses same staged Planner and Generator flow but
without research context.

## Why

Current pipeline asks Planner to produce entire outline from model knowledge,
then generates first three topics while remaining topics run through router
background tasks. This creates four limits:

1. Knowledge remains constrained by selected model's training cutoff.
2. Planner passes topic summaries, not detailed current-domain knowledge, to
   Generator.
3. Initial request blocks until preview cards finish instead of exposing outline
   as soon as available.
4. Existing background generation is not represented as durable staged work.

Feature must improve currency, provenance, preview latency, and generation
control while preserving useful behavior when search is off or unavailable.

## Locked Product Decisions

1. Web search is optional feature flag in Settings and defaults OFF.
2. Search icon is hidden when Settings flag is OFF.
3. When Settings flag is ON and provider is configured, icon appears in topic
   input but starts OFF for every new course.
4. Search providers are curated. Registry includes only providers with verified
   free usage, including limited free tiers. Exact initial list must be confirmed
   through current-year provider research before implementation.
5. Users obtain and configure provider API keys. Keys remain client-side at rest
   and are sent only with requests that need them.
6. Configured providers are shuffled once per research job. Rotation occurs only
   for rate/quota exhaustion, timeout, or provider 5xx availability errors.
7. Authentication, malformed-request, and policy errors do not silently rotate.
8. Research uses adaptive bounded budgets based on resolved depth and estimated
   concept count, with hard call, time, result, and context limits.
9. If all providers become unavailable, generation continues without web
   grounding and shows a degraded warning.
10. Research sources appear as card citations and in a Course Sources panel.
11. Generation request returns session shell immediately. UI opens course and
    receives research, table-of-contents, module, warning, and completion updates
    as work progresses.
12. Planner writes table of contents first, detailed briefs for first three
    topics next, then briefs in batches of at most ten.
13. Each brief batch completes Generator and Quizzer fan-out before next Planner
    batch starts. This protects preview priority and limits concurrency.
14. Same staged Planner behavior applies when web search is OFF.
15. Cancellation retains partial course, report, outline, and completed cards.
    User may resume or delete later.
16. Architecture uses durable staged LangGraph workflow, SQLite persistence,
    SSE progress events, and existing polling as fallback. No external job queue
    is introduced.

## User Experience

### Settings

- Master web-search toggle defaults OFF.
- Provider list appears only after master toggle is enabled.
- Each curated provider card explains free-tier availability, links to key
  creation, accepts API key, and can be enabled or disabled.
- Settings validate required fields without sending keys to unrelated endpoints.
- Search icon activation requires at least one configured provider after master
  toggle is enabled.

### Course Submission

- Search icon is absent while master setting is OFF.
- Search icon appears when capability is enabled and at least one provider is
  configured.
- Icon starts OFF for each new course and clearly indicates selected state.
- Submitting navigates immediately to session page after `202` response.
- Session page displays current stage and can render research progress before
  table of contents exists.

### Progressive Course View

- Research sections and source count update during `RESEARCHING`.
- Table of contents and module skeletons appear immediately after outline is
  persisted.
- First three cards become available as preview batch completes.
- Later cards arrive in batches of up to ten.
- SSE applies events to React Query cache; two-second session polling repairs
  missed events and remains fallback when stream is unavailable.
- Degraded research warning remains visible and prevents false web-grounded
  labeling.
- Course Sources panel shows report sections, normalized source metadata,
  citations, provider status, and research warnings.
- Stop action cancels future work but keeps partial artifacts. Resume sends fresh
  credentials when required.

## Target Architecture

`POST /learning/generate` validates LLM and optional search configuration,
creates durable session and generation job, returns session shell, and starts
checkpointed graph asynchronously.

```text
INITIALIZING
    |
    +-- web ON --> RESEARCHING --> OUTLINING
    |
    +-- web OFF -----------------> OUTLINING
                                      |
                                      v
                             TOC + skeletons persisted
                                      |
                                      v
                            PLANNING_PREVIEW (3)
                                      |
                                      v
                         GENERATING_PREVIEW (<=3)
                                      |
                                      v
                       PLANNING_BATCH / GENERATING_BATCH
                               (repeat <=10 topics)
                                      |
                                      v
                      COMPLETE or COMPLETE_DEGRADED
```

Resumable states include `PAUSED` and retained `CANCELLED`; `FAILED` is terminal.
Stage transitions use explicit validation, persisted cursors, idempotent writes,
and per-session execution lock.

### Runtime and Secret Boundary

- Graph state/checkpoints contain job IDs and persisted artifact references, not
  API keys.
- Request-scoped LLM and search credentials live only in runtime context.
- Browser reload does not interrupt server work.
- Server restart leaves incomplete job resumable from persisted stage. Client
  must call resume endpoint with fresh secret headers before work continues.
- Keys must never appear in logs, SQLite rows, checkpoints, progress events,
  reports, or client-visible errors.

## Researcher Design

Researcher runs before Planner only when course request enables web search.

### Research Loop

1. Analyze query intent, resolved depth, expected audience, freshness-sensitive
   areas, and provisional concept count.
2. Build coverage map spanning fundamentals, current versions, conventions,
   active methodologies, paradigm shifts, deprecated approaches, migration
   concerns, and disputed claims when relevant.
3. Issue high-level searches sized from provisional concept count.
4. Evaluate coverage gaps and repeatedly choose focused follow-up searches.
5. Stop early when coverage criteria pass, or stop at hard budget.
6. Normalize and deduplicate sources by canonical URL and content identity.
7. Write report incrementally in theme-based sections because final course TOC
   does not exist yet.
8. Finalize report with limitations, freshness timestamps, and source map.

### Provider Abstraction

Each provider adapter exposes same internal search contract:

- Query and optional recency/domain controls.
- Normalized title, URL, snippet/content, publisher, published date, retrieval
  date, provider, and relevance data.
- Typed errors distinguishing authentication, invalid request, policy rejection,
  quota/rate limit, timeout, and provider availability.
- Adapter-specific retry metadata without leaking secrets.

Provider coordinator shuffles enabled providers per job, retries transient calls
with bounded exponential backoff and jitter, and rotates only for approved
availability classes. Health state is job-local because quotas and keys are
user-specific.

### Research Safety

Internet content is untrusted data:

- Allow only HTTP(S) source URLs.
- Strip active content and cap fetched text lengths.
- Delimit source text separately from system and user instructions.
- Tell Researcher and downstream agents to ignore instructions embedded in
  sources.
- Reject unsupported source IDs and malformed citations.
- Preserve source excerpts needed to audit cited claims.
- Do not treat search result rank as source authority.
- Record conflicting evidence and report uncertainty instead of synthesizing
  false consensus.

## Planner and Generator Contracts

### Planner Turn 1: Table of Contents

Planner receives user query, resolved depth, and completed or degraded report.
First structured write emits only course title and validated ordered topics.
Topic skeletons persist immediately so UI can display table of contents and
modules before content generation.

### Planner Later Turns: Generation Briefs

Planner writes one persisted `GenerationBrief` per topic. First call covers
exactly first three topics when available. Each later call covers next ten or
remaining fewer topics.

Each brief includes:

- Topic scope and measurable learning objectives.
- Required prerequisites and assumed knowledge.
- Current facts, versions, methodologies, and conventions.
- Deprecated approaches, migration notes, and important caveats.
- Approved source IDs and relevant source excerpts.
- Required examples or demonstrations.
- Common misconceptions and failure modes.
- Pedagogical guidance and expected depth.
- Boundaries with adjacent topics to limit duplication.
- Quiz learning targets and evidence expected from learner.

Briefs are internal and never exposed through session API.

### Generator and Quizzer

- Generator receives topic brief, adjacent summaries, and scoped cited excerpts,
  not entire report.
- Web-enabled Generator may cite only source IDs present in brief.
- Server validates source references before persistence and creates node-source
  links.
- Unsupported citations trigger bounded correction or are removed with warning;
  fabricated links never reach UI.
- Web-off briefs contain no report/source fields and use model knowledge.
- Quizzer uses generated content and brief targets under existing secure answer
  handling.
- Individual card failure preserves existing ERROR-card retry behavior while
  sibling work completes.

## Persistence Model

Use focused persistence modules rather than adding more unrelated behavior to
existing `LearningManager` god class.

Required durable concepts:

| Record | Purpose |
|--------|---------|
| Generation job | Stage, cursor, counts, web request flag, warnings, timestamps |
| Research report | Session-level status, summary, limitations, freshness |
| Research section | Ordered incremental topic/theme report writes |
| Research source | Canonical metadata, excerpt, provider, retrieval data |
| Generation brief | Private per-node Planner knowledge-transfer artifact |
| Node-source link | Validated card citation relationship |
| Progress event | Monotonic event ID and replayable non-secret payload |

Schema evolution must follow current SQLite startup-migration conventions unless
research identifies safe existing migration tooling already active in project.
Writes must be idempotent and transactional at stage/batch boundaries.

## API Contract Direction

Exact schema names may be refined during planning, but behavior is fixed:

- `POST /learning/generate` returns `202` with session shell and generation
  metadata.
- `GET /learning/sessions/{id}` includes stage, progress counts, research status,
  warnings, and visible module skeletons/content.
- `GET /learning/sessions/{id}/events` streams replayable SSE progress and honors
  reconnect cursor.
- `GET /learning/sessions/{id}/research` returns visible report and source data.
- `POST /learning/sessions/{id}/cancel` stops future work and retains artifacts.
- `POST /learning/sessions/{id}/resume` resumes from persisted cursor using fresh
  request credentials.
- Existing delete endpoint remains explicit permanent cleanup.

Progress event types include stage changed, research section ready, research
degraded, outline ready, module ready, module failed, generation paused,
generation cancelled, and generation complete.

## Error Handling and Recovery

- Research provider exhaustion: mark degraded, persist warning, continue Planner
  without web-grounding claim.
- Research auth/validation/policy error: stop research, surface actionable warning,
  continue degraded unless user resumes with corrected configuration.
- Planner outline failure: retry bounded structured call; if still invalid, pause
  or fail before creating duplicate skeletons.
- Planner brief batch failure: persist current cursor and pause resumably.
- Generator/Quizzer topic failure: persist ERROR card and continue sibling cards.
- SSE disconnect: generation continues; client reconnects and replays events or
  repairs state through polling.
- Cancellation: cooperative checks run between search calls, report sections,
  Planner calls, and fan-out batches.
- Duplicate start/resume: per-session lock and idempotency prevent parallel jobs.
- Unexpected process stop: persisted stage and artifacts remain; no secret is
  assumed recoverable.

## Performance Constraints

- Adaptive research budget has hard maximum calls, elapsed time, source count,
  fetched bytes, and LLM context size.
- Generator fan-out is capped per batch: three for preview, ten afterward.
- Runtime may set lower concurrency than batch size to protect provider limits
  and SQLite single-writer behavior.
- Report and source excerpts are scoped before Planner/Generator prompts to avoid
  unbounded context growth.
- Progress event retention is bounded or compacted after completion.
- Persistence batches related writes in single transactions where possible.

## Testing Strategy

Development follows test-driven workflow from
`.planning/codebase/TESTING.md`. External APIs are mocked in automated tests.

### Server

- Provider adapter normalization and typed error mapping.
- Provider shuffle, transient retry, approved rotation, and no-rotation classes.
- Adaptive budget sizing, early completion, and hard loop termination.
- Source deduplication, canonicalization, unsafe URL rejection, and content caps.
- Prompt-injection boundaries and source/citation validation.
- Incremental report persistence and source relationships.
- Generation stage transitions, cursor persistence, idempotency, and job locks.
- Web-on, web-off, degraded, paused, cancelled, resumed, and failed graph flows.
- Planner batches of 3 then 10, including final short batch.
- Generator fan-out limits and partial ERROR-card recovery.
- SSE ordering, reconnect replay, redaction, and polling-compatible session state.
- API request/response contracts and secret-header handling.
- SQLite migration tests for fresh and existing databases.

### Client

- Master toggle defaults OFF and provider controls visibility.
- Search icon visibility, per-course OFF default, and selected state.
- Provider key persistence and correct request-only secret headers.
- Immediate navigation from `202` session shell.
- Stage, research, TOC, skeleton, card, warning, cancellation, and completion UI.
- SSE cache updates, reconnect behavior, and polling fallback.
- Course Sources report rendering and card citation links.
- Resume and delete behavior for retained partial courses.

### Quality Gates

- Server full `unittest` suite passes.
- Client Vitest suite and coverage pass with more than 80% coverage for new code.
- Client ESLint passes.
- TypeScript and Vite production build pass.
- No API key appears in test snapshots, logs, DB fixtures, checkpoint fixtures, or
  SSE payloads.

## Success Criteria

- User can configure at least one currently verified free-usage search provider.
- Web feature remains invisible and inactive by default.
- Search requires explicit opt-in for each course.
- Session UI opens immediately and progressively displays report, TOC, and cards.
- Web-enabled course uses persisted research report before Planner creates TOC.
- Research loop explores beyond one query but always terminates within budget.
- Planner writes TOC, then briefs for 3 topics, then batches of up to 10.
- Generator receives full topic-specific knowledge transfer, not only title and
  short description.
- Cards expose only validated citations and Course Sources panel exposes report.
- Provider rate/availability failures rotate safely among configured providers.
- All-provider failure continues useful web-off generation with clear warning.
- Web-off course uses same progressive staged pipeline without Researcher.
- Cancellation retains partial work and resume continues without duplicate cards.
- Secrets remain ephemeral on server and never enter persisted artifacts.
- Automated tests, lint, build, and compile checks pass.

## Non-Goals

- Paid-only search providers in initial curated registry.
- General-purpose browser automation or arbitrary page interaction.
- RAG/vector database or permanent cross-course knowledge base.
- Automatic fact-checking beyond source validation and report conflict handling.
- External distributed job queue, Redis, Celery, or multi-server orchestration.
- Server-side permanent API-key vault.
- Full redesign of learning card pedagogy or revision workflow.
- Refactoring entire `LearningManager` or router outside touched boundaries.
- Real external provider calls in default automated test suite.

## Current Codebase Touchpoints

| Layer | Current files | Expected role |
|-------|---------------|---------------|
| Topic input | `client/src/features/learning/TopicInput.tsx` | Per-course search icon and immediate navigation |
| Settings | `client/src/features/settings/SettingsPage.tsx` | Master toggle and curated provider setup |
| Client config | `client/src/lib/providerSettings.ts` | Local web-provider settings and keys |
| Client API | `client/src/lib/learningApi.ts`, `client/src/lib/providerApi.ts` | Request headers, `202`, events, report, cancel/resume |
| Client types | `client/src/types/learning.ts` | Generation status, report, source, citation contracts |
| Learning UI | `client/src/features/learning/LearningPage.tsx`, `LearningPathContainer.tsx` | Progressive session, skeletons, warnings, sources |
| Router | `server/routers/learning.py` | Start/status/events/report/cancel/resume endpoints |
| LLM context | `server/schemas/llm.py` | Ephemeral search credential parsing boundary |
| Graph | `server/graph/build.py`, `nodes.py`, `state.py` | Research and staged planner/generator workflow |
| Agents | `server/agents/planner.py`, `generator.py`, new Researcher | Report, TOC, briefs, grounded cards |
| LLM client | `server/utils/instructor_client.py` | Researcher role and structured LLM calls |
| Persistence | `server/database/` | Focused job/research/source/brief/event storage |
| Tests | `server/tests/`, co-located client tests | TDD and regression coverage |

## High-Level Delivery Phases

1. Provider and research discovery, contracts, security model, and curated
   free-usage registry.
2. Durable generation-job, research, source, brief, citation, and event
   persistence.
3. Search adapters, failover coordinator, bounded Researcher loop, and report
   generation.
4. Staged graph with TOC-first Planner, 3/10 brief batches, controlled fan-out,
   cancellation, and resume.
5. Async generation API, progress SSE, report/source endpoints, and polling
   compatibility.
6. Settings, search icon, progressive course UI, citations, and Sources panel.
7. Integration hardening, security validation, full quality gates, and docs.

## Required Research

Research phase must use current-year sources and verify:

- Search providers that still offer usable free tiers, exact limits, key signup,
  API terms, rate-limit semantics, and result/fetch capabilities.
- Direct REST APIs versus SDK dependency trade-offs for each provider.
- Current LangGraph patterns for durable async execution, context secrets,
  dynamic fan-out, interrupts/resume, and streaming.
- FastAPI SSE disconnect/reconnect and background task lifecycle practices.
- Research-agent loop controls, citation grounding, web prompt-injection defense,
  and source-quality evaluation.
- Existing project patterns that can be reused without broad refactors.

Research findings may refine implementation details but may not change locked
product decisions without user approval.

## References

- `.planning/codebase/ARCHITECTURE.md`
- `.planning/codebase/STACK.md`
- `.planning/codebase/TESTING.md`
- `.planning/codebase/CONVENTIONS.md`
- `.planning/codebase/STRUCTURE.md`
- `.planning/codebase/INTEGRATIONS.md`
- `.planning/codebase/CONCERNS.md`
