# Internet-Grounded Course Generation Implementation Plan — Phase 1: Contracts & Curated Registry

> **Planning method:** I used writing-plans skill principles: TDD, bite-sized tasks, exact paths, and no placeholders.
>
> **For agentic workers:** REQUIRED: TDD via test-driven-development skill; execute via executing-plans or subagent-driven-development. Steps use `- [ ]` checkboxes.

**Goal:** Freeze server and client contracts for staged generation, research artifacts, progress events, runtime-only search credentials, and four curated search providers without making live search calls.

**Architecture:** Add focused Pydantic and TypeScript contract modules before persistence or runtime work. Keep LLM provider settings intact, extend `providerSettings.ts` with a separate `web_search_settings` localStorage record, and define search credentials as excluded `SecretStr` runtime data. Registry contains exactly Tavily, Exa, Brave, and SerpAPI, matching locked product decisions and `research.md` findings dated 2026-08-01.

**Tech Stack:** Python 3.10+, Pydantic v2, TypeScript strict mode, Vitest, stdlib `unittest`.

**Depends on:** None.

**Deliverable:** Importable, validated contracts on both sides of API boundary; exact curated provider metadata; web-search master setting defaulting OFF; no adapter, network request, database table, router endpoint, or UI control yet.

## Locked Names

These names become cross-phase contracts. Later phases extend behavior without renaming them.

```text
SearchProviderId
SearchErrorClass
SearchError
AllProvidersUnavailable
SearchQuery
NormalizedSearchResult
SearchResponse
SearchAdapter
SearchProviderMetadata
SEARCH_PROVIDER_REGISTRY
SearchContext

GenerationStage
GroundingStatus
GenerationCounts
GenerationWarning
ResearchCursor
GenerationCursor
BriefSourceExcerpt
GenerationBrief
GenerationBriefBatch
SourceCitation

ResearchStatus
ResearchProviderState
ResearchSource
ResearchSection
ResearchProviderStatus
ResearchReport

ProgressEventType
ProgressEvent

WebSearchProviderId
WebSearchProviderConfig
WebSearchSettings
WEB_SEARCH_PROVIDERS
getWebSearchSettings
setWebSearchSettings
setWebSearchMasterEnabled
setWebSearchProviderConfig
getConfiguredWebSearchProviders
hasWebSearchCapability
```

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `.gitignore` | Stop ignoring co-located Vitest files and `vitest.setup.ts` so TDD artifacts are visible to Git. |
| Create | `server/search/__init__.py` | Search package exports. |
| Create | `server/search/types.py` | Adapter-neutral provider IDs, requests, normalized results, and safe typed errors. |
| Create | `server/search/registry.py` | Metadata-only registry for Tavily, Exa, Brave, and SerpAPI. |
| Create | `server/schemas/search.py` | Runtime-only `SearchContext`; credentials excluded from dumps and repr. |
| Create | `server/schemas/generation.py` | Generation stages, cursors, counts, warnings, briefs, and citation contracts. |
| Create | `server/schemas/research.py` | Persisted/public research report, section, source, and provider-state contracts. |
| Create | `server/schemas/progress.py` | Closed progress-event type set and secret-safe payload contract. |
| Modify | `server/schemas/__init__.py` | Re-export new schema contracts without changing existing imports. |
| Create | `server/tests/test_search_contracts.py` | Registry, error taxonomy, URL/result limits, and runtime-secret tests. |
| Create | `server/tests/test_generation_contracts.py` | Stage, cursor, brief, batch, and citation validation tests. |
| Create | `server/tests/test_research_progress_contracts.py` | Research and event model validation tests. |
| Create | `client/src/types/webSearch.ts` | Browser web-search settings and provider metadata types. |
| Create | `client/src/types/generation.ts` | Client generation, research, source, citation, and progress-event contracts. |
| Create | `client/src/lib/webSearchProviders.ts` | Four-provider client metadata used by Settings and request header construction. |
| Create | `client/src/lib/webSearchProviders.test.ts` | Client registry contract tests. |
| Modify | `client/src/lib/providerSettings.ts` | Separate browser-only web-search settings read/write helpers. |
| Create | `client/src/lib/providerSettings.test.ts` | Defaults, malformed storage, partial migration, and capability tests. |

## Tasks

### Task 1.1: Freeze Server Search Contracts and Registry

**Files:**
- Create: `server/search/__init__.py`
- Create: `server/search/types.py`
- Create: `server/search/registry.py`
- Create: `server/schemas/search.py`
- Create: `server/tests/test_search_contracts.py`

- [ ] **Step 1: Write failing server contract tests**

Create `server/tests/test_search_contracts.py` with this complete content:

```python
"""
============================================================================
FILE: test_search_contracts.py
LOCATION: server/tests/test_search_contracts.py
============================================================================
PURPOSE:
    Verifies search provider metadata, normalized result limits, typed errors,
    and runtime-only credential serialization.
ROLE IN PROJECT:
    Freezes Phase 1 search contracts before adapters and API wiring exist.
KEY COMPONENTS:
    - SearchContractTests: Provider, error, result, and secret-boundary tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.search, server.search.registry, server.search.types
USAGE:
    python -m unittest server.tests.test_search_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from server.schemas.search import SearchContext
from server.search.registry import SEARCH_PROVIDER_REGISTRY
from server.search.types import (
    ROTATABLE_SEARCH_ERRORS,
    NormalizedSearchResult,
    SearchError,
    SearchErrorClass,
    SearchProviderId,
)


class SearchContractTests(unittest.TestCase):
    """Tests frozen search-provider and runtime-secret contracts."""

    def test_registry_contains_exact_locked_provider_order(self) -> None:
        self.assertEqual(
            list(SEARCH_PROVIDER_REGISTRY),
            [
                SearchProviderId.TAVILY,
                SearchProviderId.EXA,
                SearchProviderId.BRAVE,
                SearchProviderId.SERPAPI,
            ],
        )
        brave = SEARCH_PROVIDER_REGISTRY[SearchProviderId.BRAVE]
        self.assertTrue(brave.requires_payment_method)
        self.assertTrue(brave.attribution_required)
        self.assertEqual(brave.verified_at, "2026-08-01")
        self.assertEqual(
            SEARCH_PROVIDER_REGISTRY[SearchProviderId.TAVILY].key_header,
            "X-Tavily-Key",
        )
        self.assertEqual(
            SEARCH_PROVIDER_REGISTRY[SearchProviderId.SERPAPI].key_header,
            "X-SerpApi-Key",
        )

    def test_only_availability_errors_are_rotatable(self) -> None:
        self.assertEqual(
            ROTATABLE_SEARCH_ERRORS,
            frozenset(
                {
                    SearchErrorClass.RATE_LIMIT,
                    SearchErrorClass.QUOTA,
                    SearchErrorClass.TIMEOUT,
                    SearchErrorClass.AVAILABILITY,
                }
            ),
        )
        self.assertNotIn(
            SearchErrorClass.AUTHENTICATION,
            ROTATABLE_SEARCH_ERRORS,
        )
        self.assertNotIn(
            SearchErrorClass.INVALID_REQUEST,
            ROTATABLE_SEARCH_ERRORS,
        )
        self.assertNotIn(SearchErrorClass.POLICY, ROTATABLE_SEARCH_ERRORS)

    def test_search_error_uses_safe_generated_message(self) -> None:
        secret = "tvly-secret-never-render"
        error = SearchError(
            provider_id=SearchProviderId.TAVILY,
            error_class=SearchErrorClass.QUOTA,
            status_code=432,
            retry_after_seconds=1.5,
        )
        rendered = repr(error) + str(error) + secret[:0]
        self.assertIn("tavily", rendered)
        self.assertIn("quota", rendered)
        self.assertNotIn(secret, rendered)

    def test_normalized_result_rejects_unsafe_url(self) -> None:
        with self.assertRaises(ValidationError):
            NormalizedSearchResult(
                title="Unsafe",
                url="https://user:password@example.com/docs",
                canonical_url="https://example.com/docs",
                snippet="Unsafe URL",
                content="Evidence",
                publisher="Example",
                published_at=None,
                retrieved_at=datetime.now(timezone.utc),
                provider_id=SearchProviderId.EXA,
                provider_rank=1,
                raw_score=None,
            )

    def test_normalized_result_enforces_content_caps(self) -> None:
        with self.assertRaises(ValidationError):
            NormalizedSearchResult(
                title="Oversized",
                url="https://example.com/docs",
                canonical_url="https://example.com/docs",
                snippet="s" * 2001,
                content="c" * 8001,
                publisher=None,
                published_at=None,
                retrieved_at=datetime.now(timezone.utc),
                provider_id=SearchProviderId.BRAVE,
                provider_rank=1,
                raw_score=None,
            )

    def test_search_context_excludes_credentials_from_dumps_and_repr(
        self,
    ) -> None:
        secret = "exa-runtime-secret"
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.EXA],
            credentials={SearchProviderId.EXA: secret},
        )
        self.assertEqual(context.get_api_key(SearchProviderId.EXA), secret)
        self.assertNotIn(secret, repr(context))
        self.assertNotIn(secret, context.model_dump_json())
        self.assertNotIn("credentials", context.model_dump())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run from `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_search_contracts -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'server.search'`.

- [ ] **Step 3: Implement minimal server contracts**

Create each Python file with mandatory 76-character file header. Implement these exact contracts:

```python
# server/search/types.py public surface
class SearchProviderId(str, Enum):
    TAVILY = "tavily"
    EXA = "exa"
    BRAVE = "brave"
    SERPAPI = "serpapi"


class SearchErrorClass(str, Enum):
    AUTHENTICATION = "authentication"
    INVALID_REQUEST = "invalid_request"
    POLICY = "policy"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    TIMEOUT = "timeout"
    AVAILABILITY = "availability"
    INVALID_RESPONSE = "invalid_response"


ROTATABLE_SEARCH_ERRORS = frozenset(
    {
        SearchErrorClass.RATE_LIMIT,
        SearchErrorClass.QUOTA,
        SearchErrorClass.TIMEOUT,
        SearchErrorClass.AVAILABILITY,
    }
)


class SearchError(Exception):
    def __init__(
        self,
        *,
        provider_id: SearchProviderId,
        error_class: SearchErrorClass,
        status_code: Optional[int] = None,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        self.provider_id = provider_id
        self.error_class = error_class
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"{provider_id.value} search failed: {error_class.value}"
        )


class AllProvidersUnavailable(SearchError):
    """Raised after every configured provider has an approved outage."""


class SearchQuery(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=8, ge=1, le=20)
    recency_days: Optional[int] = Field(default=None, ge=1, le=3650)
    include_domains: list[str] = Field(default_factory=list, max_length=20)
    exclude_domains: list[str] = Field(default_factory=list, max_length=20)


class NormalizedSearchResult(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    title: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl
    canonical_url: AnyHttpUrl
    snippet: str = Field(default="", max_length=2000)
    content: str = Field(default="", max_length=8000)
    publisher: Optional[str] = Field(default=None, max_length=300)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    provider_id: SearchProviderId
    provider_rank: int = Field(ge=1)
    raw_score: Optional[float] = None

    @field_validator("url", "canonical_url")
    @classmethod
    def reject_url_credentials(cls, value: AnyHttpUrl) -> AnyHttpUrl:
        if value.username or value.password:
            raise ValueError("Source URLs cannot contain credentials")
        return value


class SearchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    results: list[NormalizedSearchResult]
    response_bytes: int = Field(ge=0)


class SearchAdapter(Protocol):
    provider_id: SearchProviderId

    async def search(
        self,
        query: SearchQuery,
        *,
        api_key: str,
        timeout_seconds: float = 20.0,
    ) -> SearchResponse:
        """Return normalized results or raise SearchError."""
```

`AllProvidersUnavailable` must be a separate exception with `provider_ids: tuple[SearchProviderId, ...]`, not a call site for raw provider text. If direct subclassing of `SearchError` makes construction awkward, subclass `RuntimeError` and generate `"All configured search providers are unavailable."` internally.

Create `server/search/registry.py` with frozen `SearchProviderMetadata` and an insertion-ordered `SEARCH_PROVIDER_REGISTRY` containing these exact rows:

| ID | Display | Free-tier summary | Signup URL | Docs URL | Endpoint | Key header | Payment method | Attribution | Recommended |
|---|---|---|---|---|---|---|---:|---:|---:|
| `tavily` | Tavily | `1,000 API credits each month; no card required.` | `https://app.tavily.com` | `https://docs.tavily.com/documentation/api-reference/endpoint/search` | `https://api.tavily.com/search` | `X-Tavily-Key` | false | false | true |
| `exa` | Exa | `$10 monthly free credits plus signup credits; no card required.` | `https://dashboard.exa.ai/api-keys` | `https://exa.ai/docs/reference/search` | `https://api.exa.ai/search` | `X-Exa-Key` | false | false | false |
| `brave` | Brave Search | `$5 monthly credits, about 1,000 searches; card required.` | `https://api-dashboard.search.brave.com/register` | `https://api-dashboard.search.brave.com/documentation/quickstart` | `https://api.search.brave.com/res/v1/web/search` | `X-Brave-Key` | true | true | false |
| `serpapi` | SerpAPI | `250 searches each month on recurring free plan.` | `https://serpapi.com/users/sign_up` | `https://serpapi.com/search-api` | `https://serpapi.com/search.json` | `X-SerpApi-Key` | false | false | false |

Every row uses `verified_at="2026-08-01"`. Registry stores metadata only; it imports no `httpx` adapter.

Create `server/schemas/search.py` with:

```python
class SearchContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    provider_ids: tuple[SearchProviderId, ...] = ()
    credentials: dict[SearchProviderId, SecretStr] = Field(
        default_factory=dict,
        exclude=True,
        repr=False,
    )

    @classmethod
    def from_plaintext_credentials(
        cls,
        *,
        enabled: bool,
        provider_ids: list[SearchProviderId],
        credentials: dict[SearchProviderId, str],
    ) -> "SearchContext":
        return cls(
            enabled=enabled,
            provider_ids=tuple(provider_ids),
            credentials={
                provider_id: SecretStr(value)
                for provider_id, value in credentials.items()
            },
        )

    def get_api_key(self, provider_id: SearchProviderId) -> str:
        credential = self.credentials.get(provider_id)
        if credential is None:
            raise KeyError(f"Missing search credential: {provider_id.value}")
        return credential.get_secret_value()
```

Add named exports in `server/search/__init__.py`. Do not add FastAPI `Header` parameters yet; Phase 5 owns HTTP parsing.

- [ ] **Step 4: Run test and verify green state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_search_contracts -v
```

Expected: 6 tests PASS; no network access.

- [ ] **Step 5: Commit search contracts**

```powershell
git add server/search server/schemas/search.py server/tests/test_search_contracts.py
git commit -m "feat(search): add provider contracts and curated registry"
```

### Task 1.2: Freeze Generation Stage, Cursor, Brief, and Citation Contracts

**Files:**
- Create: `server/schemas/generation.py`
- Modify: `server/schemas/__init__.py`
- Create: `server/tests/test_generation_contracts.py`

- [ ] **Step 1: Write failing generation contract tests**

Create `server/tests/test_generation_contracts.py`:

```python
"""
============================================================================
FILE: test_generation_contracts.py
LOCATION: server/tests/test_generation_contracts.py
============================================================================
PURPOSE:
    Freezes durable generation stages, cursors, briefs, batches, and citations.
ROLE IN PROJECT:
    Protects contracts shared by persistence, LangGraph, API, and client phases.
KEY COMPONENTS:
    - GenerationContractTests: Validation and serialization contract tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.generation
USAGE:
    python -m unittest server.tests.test_generation_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.generation import (
    BriefSourceExcerpt,
    GenerationBrief,
    GenerationBriefBatch,
    GenerationCursor,
    GenerationStage,
    GroundingStatus,
    ResearchCursor,
)


def _brief(topic_index: int) -> GenerationBrief:
    return GenerationBrief(
        topic_index=topic_index,
        topic_scope=f"Scope {topic_index}",
        learning_objectives=[f"Explain objective {topic_index}."],
        prerequisites=["Prior topic knowledge."],
        assumed_knowledge=["Basic terminology."],
        current_facts=["Current fact."],
        methodologies=["Current method."],
        conventions=["Current convention."],
        deprecated_approaches=["Deprecated method."],
        migration_notes=["Migration note."],
        caveats=["Important caveat."],
        source_excerpts=None,
        required_examples=["Worked example."],
        common_misconceptions=["Common misconception."],
        failure_modes=["Common failure."],
        pedagogical_guidance="Build from intuition to formal detail.",
        expected_depth="lite",
        boundaries_with_adjacent_topics="Do not duplicate adjacent topics.",
        quiz_learning_targets=["Identify correct application."],
        expected_learner_evidence=["Explain reasoning in one sentence."],
        grounding_status=GroundingStatus.DISABLED,
    )


class GenerationContractTests(unittest.TestCase):
    """Tests generation contract invariants."""

    def test_stage_values_match_locked_workflow(self) -> None:
        self.assertEqual(
            [stage.value for stage in GenerationStage],
            [
                "INITIALIZING",
                "RESEARCHING",
                "OUTLINING",
                "PLANNING_PREVIEW",
                "GENERATING_PREVIEW",
                "PLANNING_BATCH",
                "GENERATING_BATCH",
                "PAUSED",
                "CANCELLED",
                "COMPLETE",
                "COMPLETE_DEGRADED",
                "FAILED",
            ],
        )

    def test_cursor_caps_active_batch_at_ten(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationCursor(
                next_topic_index=3,
                active_batch_start=3,
                active_batch_size=11,
                batch_number=1,
                research=ResearchCursor(),
            )

    def test_disabled_brief_has_no_research_fields_when_dumped(self) -> None:
        payload = _brief(0).model_dump(exclude_none=True)
        self.assertNotIn("source_excerpts", payload)
        self.assertNotIn("research_report_id", payload)

    def test_grounded_brief_requires_approved_source_excerpt(self) -> None:
        data = _brief(0).model_dump()
        data["grounding_status"] = GroundingStatus.GROUNDED
        with self.assertRaises(ValidationError):
            GenerationBrief.model_validate(data)

        data["source_excerpts"] = [
            BriefSourceExcerpt(
                source_id="source-1",
                excerpt="Current supported evidence.",
            ).model_dump()
        ]
        brief = GenerationBrief.model_validate(data)
        self.assertEqual(brief.approved_source_ids, ["source-1"])

    def test_brief_rejects_duplicate_source_ids(self) -> None:
        data = _brief(0).model_dump()
        data["grounding_status"] = GroundingStatus.GROUNDED
        evidence = {
            "source_id": "source-1",
            "excerpt": "Current supported evidence.",
        }
        data["source_excerpts"] = [evidence, evidence]
        with self.assertRaises(ValidationError):
            GenerationBrief.model_validate(data)

    def test_brief_batch_requires_contiguous_expected_indices(self) -> None:
        with self.assertRaises(ValidationError):
            GenerationBriefBatch(
                start_index=0,
                briefs=[_brief(0), _brief(2)],
            )
        batch = GenerationBriefBatch(
            start_index=0,
            briefs=[_brief(0), _brief(1), _brief(2)],
        )
        self.assertEqual(batch.end_index_exclusive, 3)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_contracts -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'server.schemas.generation'`.

- [ ] **Step 3: Implement generation contracts**

Create `server/schemas/generation.py` with mandatory header and these exact model rules:

```python
class GenerationStage(str, Enum):
    INITIALIZING = "INITIALIZING"
    RESEARCHING = "RESEARCHING"
    OUTLINING = "OUTLINING"
    PLANNING_PREVIEW = "PLANNING_PREVIEW"
    GENERATING_PREVIEW = "GENERATING_PREVIEW"
    PLANNING_BATCH = "PLANNING_BATCH"
    GENERATING_BATCH = "GENERATING_BATCH"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    COMPLETE = "COMPLETE"
    COMPLETE_DEGRADED = "COMPLETE_DEGRADED"
    FAILED = "FAILED"


class GroundingStatus(str, Enum):
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    GROUNDED = "GROUNDED"
    DEGRADED = "DEGRADED"


class GenerationCounts(BaseModel):
    topics_total: int = Field(default=0, ge=0, le=30)
    briefs_ready: int = Field(default=0, ge=0, le=30)
    topics_ready: int = Field(default=0, ge=0, le=30)
    topics_failed: int = Field(default=0, ge=0, le=30)
    research_sections: int = Field(default=0, ge=0)
    sources: int = Field(default=0, ge=0, le=40)


class GenerationWarning(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=500)
    provider_id: Optional[SearchProviderId] = None


class ResearchCursor(BaseModel):
    iteration: int = Field(default=0, ge=0, le=10)
    next_section_index: int = Field(default=0, ge=0)
    pending_queries: list[str] = Field(default_factory=list, max_length=20)
    completed_themes: list[str] = Field(default_factory=list, max_length=20)
    search_calls: int = Field(default=0, ge=0, le=20)
    llm_turns: int = Field(default=0, ge=0, le=10)
    results_examined: int = Field(default=0, ge=0, le=120)
    provider_bytes: int = Field(default=0, ge=0, le=5_000_000)
    excerpt_chars: int = Field(default=0, ge=0, le=100_000)


class GenerationCursor(BaseModel):
    next_topic_index: int = Field(default=0, ge=0, le=30)
    active_batch_start: Optional[int] = Field(default=None, ge=0, le=29)
    active_batch_size: int = Field(default=0, ge=0, le=10)
    batch_number: int = Field(default=0, ge=0, le=4)
    provider_order: list[SearchProviderId] = Field(
        default_factory=list,
        max_length=4,
    )
    research: ResearchCursor = Field(default_factory=ResearchCursor)


class BriefSourceExcerpt(BaseModel):
    source_id: str = Field(min_length=1, max_length=100)
    excerpt: str = Field(min_length=1, max_length=8000)


class GenerationBrief(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    topic_index: int = Field(ge=0, le=29)
    topic_scope: str = Field(min_length=1)
    learning_objectives: list[str] = Field(min_length=1)
    prerequisites: list[str]
    assumed_knowledge: list[str]
    current_facts: list[str]
    methodologies: list[str]
    conventions: list[str]
    deprecated_approaches: list[str]
    migration_notes: list[str]
    caveats: list[str]
    research_report_id: Optional[str] = None
    source_excerpts: Optional[list[BriefSourceExcerpt]] = None
    required_examples: list[str]
    common_misconceptions: list[str]
    failure_modes: list[str]
    pedagogical_guidance: str = Field(min_length=1)
    expected_depth: Literal["lite", "full"]
    boundaries_with_adjacent_topics: str = Field(min_length=1)
    quiz_learning_targets: list[str] = Field(min_length=1)
    expected_learner_evidence: list[str] = Field(min_length=1)
    grounding_status: GroundingStatus

    @model_validator(mode="after")
    def validate_grounding(self) -> "GenerationBrief":
        excerpts = self.source_excerpts or []
        source_ids = [item.source_id for item in excerpts]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("GenerationBrief source IDs must be unique")
        if self.grounding_status == GroundingStatus.GROUNDED and not excerpts:
            raise ValueError("Grounded brief requires approved source excerpts")
        if self.grounding_status == GroundingStatus.DISABLED:
            if self.research_report_id is not None or excerpts:
                raise ValueError("Disabled brief cannot contain research fields")
        return self

    @property
    def approved_source_ids(self) -> list[str]:
        return [item.source_id for item in self.source_excerpts or []]


class GenerationBriefBatch(BaseModel):
    start_index: int = Field(ge=0, le=29)
    briefs: list[GenerationBrief] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def validate_indices(self) -> "GenerationBriefBatch":
        expected = list(
            range(self.start_index, self.start_index + len(self.briefs))
        )
        actual = [brief.topic_index for brief in self.briefs]
        if actual != expected:
            raise ValueError("GenerationBriefBatch indices must be contiguous")
        return self

    @property
    def end_index_exclusive(self) -> int:
        return self.start_index + len(self.briefs)


class SourceCitation(BaseModel):
    source_id: str = Field(min_length=1, max_length=100)
    claim: str = Field(min_length=1, max_length=1000)
```

Use `ConfigDict(from_attributes=True)` on all models and `extra="forbid"` on artifact models that consume LLM output. Add imports to `server/schemas/__init__.py`; preserve existing exports.

- [ ] **Step 4: Run test and verify green state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_generation_contracts -v
```

Expected: 6 tests PASS.

- [ ] **Step 5: Commit generation contracts**

```powershell
git add server/schemas/generation.py server/schemas/__init__.py server/tests/test_generation_contracts.py
git commit -m "feat(generation): add staged generation contracts"
```

### Task 1.3: Freeze Research and Progress Event Contracts

**Files:**
- Create: `server/schemas/research.py`
- Create: `server/schemas/progress.py`
- Modify: `server/schemas/__init__.py`
- Create: `server/tests/test_research_progress_contracts.py`

- [ ] **Step 1: Write failing research and progress tests**

Create `server/tests/test_research_progress_contracts.py`:

```python
"""
============================================================================
FILE: test_research_progress_contracts.py
LOCATION: server/tests/test_research_progress_contracts.py
============================================================================
PURPOSE:
    Verifies research artifact and replayable progress-event contracts.
ROLE IN PROJECT:
    Prevents unsupported source relationships and untyped event payloads.
KEY COMPONENTS:
    - ResearchProgressContractTests: Research and event validation tests
DEPENDENCIES:
    - External: pydantic, unittest
    - Internal: server.schemas.progress, server.schemas.research
USAGE:
    python -m unittest server.tests.test_research_progress_contracts -v
============================================================================
"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from server.schemas.generation import GenerationStage
from server.schemas.progress import (
    ProgressEvent,
    ProgressEventType,
    StageChangedPayload,
)
from server.schemas.research import (
    ResearchProviderState,
    ResearchProviderStatus,
    ResearchReport,
    ResearchSection,
    ResearchSource,
    ResearchStatus,
)
from server.search.types import SearchErrorClass, SearchProviderId


def _source(source_id: str = "source-1") -> ResearchSource:
    return ResearchSource(
        id=source_id,
        title="Current documentation",
        url="https://example.com/docs",
        publisher="Example",
        published_at=None,
        retrieved_at=datetime.now(timezone.utc),
        provider_id=SearchProviderId.TAVILY,
        snippet="Current documentation summary.",
        excerpt="Current documentation evidence.",
        relevance_score=0.9,
    )


class ResearchProgressContractTests(unittest.TestCase):
    """Tests public and persisted research/progress invariants."""

    def test_section_rejects_duplicate_source_ids(self) -> None:
        with self.assertRaises(ValidationError):
            ResearchSection(
                id="section-1",
                sequence_index=0,
                theme="Current versions",
                markdown="Current evidence.",
                source_ids=["source-1", "source-1"],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_report_rejects_unknown_section_source(self) -> None:
        section = ResearchSection(
            id="section-1",
            sequence_index=0,
            theme="Current versions",
            markdown="Current evidence.",
            source_ids=["missing-source"],
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        with self.assertRaises(ValidationError):
            ResearchReport(
                id="report-1",
                session_id="session-1",
                status=ResearchStatus.COMPLETE,
                summary="Research summary.",
                limitations=[],
                freshness_note="Retrieved 2026-08-01.",
                sections=[section],
                sources=[_source()],
                provider_statuses=[],
                warnings=[],
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )

    def test_provider_status_exposes_only_safe_error_class(self) -> None:
        status = ResearchProviderStatus(
            provider_id=SearchProviderId.EXA,
            state=ResearchProviderState.AUTH_FAILED,
            search_calls=1,
            result_count=0,
            error_class=SearchErrorClass.AUTHENTICATION,
        )
        payload = status.model_dump(mode="json")
        self.assertNotIn("error_body", payload)
        self.assertNotIn("api_key", payload)

    def test_event_type_set_matches_locked_contract(self) -> None:
        self.assertEqual(
            [event.value for event in ProgressEventType],
            [
                "stage_changed",
                "research_section_ready",
                "research_degraded",
                "outline_ready",
                "module_ready",
                "module_failed",
                "generation_paused",
                "generation_cancelled",
                "generation_complete",
            ],
        )

    def test_event_rejects_payload_for_wrong_type(self) -> None:
        with self.assertRaises(ValidationError):
            ProgressEvent(
                id=1,
                session_id="session-1",
                event_type=ProgressEventType.MODULE_READY,
                payload=StageChangedPayload(
                    previous_stage=GenerationStage.INITIALIZING,
                    stage=GenerationStage.RESEARCHING,
                ),
                created_at=datetime.now(timezone.utc),
            )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_research_progress_contracts -v
```

Expected: FAIL because `server.schemas.research` and `server.schemas.progress` do not exist.

- [ ] **Step 3: Implement research and event models**

Create `server/schemas/research.py` with exact enums and limits:

```python
class ResearchStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    COMPLETE = "COMPLETE"
    DEGRADED = "DEGRADED"
    CANCELLED = "CANCELLED"


class ResearchProviderState(str, Enum):
    READY = "READY"
    USED = "USED"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TIMED_OUT = "TIMED_OUT"
    UNAVAILABLE = "UNAVAILABLE"
    AUTH_FAILED = "AUTH_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"
    POLICY_REJECTED = "POLICY_REJECTED"


class ResearchSource(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    title: str = Field(min_length=1, max_length=500)
    url: AnyHttpUrl
    publisher: Optional[str] = Field(default=None, max_length=300)
    published_at: Optional[datetime] = None
    retrieved_at: datetime
    provider_id: SearchProviderId
    snippet: str = Field(default="", max_length=2000)
    excerpt: str = Field(default="", max_length=8000)
    relevance_score: Optional[float] = Field(default=None, ge=0, le=1)


class ResearchSection(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    sequence_index: int = Field(ge=0)
    theme: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=20_000)
    source_ids: list[str] = Field(default_factory=list, max_length=40)
    created_at: datetime
    updated_at: datetime

    @field_validator("source_ids")
    @classmethod
    def source_ids_are_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("ResearchSection source IDs must be unique")
        return values


class ResearchProviderStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    provider_id: SearchProviderId
    state: ResearchProviderState
    search_calls: int = Field(ge=0, le=20)
    result_count: int = Field(ge=0, le=120)
    error_class: Optional[SearchErrorClass] = None


class ResearchReport(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: str
    session_id: str
    status: ResearchStatus
    summary: Optional[str] = Field(default=None, max_length=20_000)
    limitations: list[str] = Field(default_factory=list, max_length=30)
    freshness_note: Optional[str] = Field(default=None, max_length=2000)
    sections: list[ResearchSection] = Field(default_factory=list)
    sources: list[ResearchSource] = Field(default_factory=list, max_length=40)
    provider_statuses: list[ResearchProviderStatus] = Field(
        default_factory=list,
        max_length=4,
    )
    warnings: list[GenerationWarning] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def section_sources_exist(self) -> "ResearchReport":
        source_ids = {source.id for source in self.sources}
        referenced = {
            source_id
            for section in self.sections
            for source_id in section.source_ids
        }
        unknown = referenced - source_ids
        if unknown:
            raise ValueError(f"Unknown research source IDs: {sorted(unknown)}")
        return self
```

Create `server/schemas/progress.py` with the nine event values from test. Define payload models:

```text
StageChangedPayload(previous_stage, stage)
ResearchSectionReadyPayload(report_id, section_id, sequence_index, source_count)
ResearchDegradedPayload(warning)
OutlineReadyPayload(course_title, topic_count)
ModuleReadyPayload(node_id, sequence_index)
ModuleFailedPayload(node_id, sequence_index, failed_step, warning)
GenerationPausedPayload(stage, warning)
GenerationCancelledPayload(stage)
GenerationCompletePayload(stage, counts, grounding_status)
```

Use a discriminated model validator in `ProgressEvent` to map each `event_type` to exactly one payload class. Configure every payload `extra="forbid"`; therefore `api_key`, `authorization`, raw headers, and provider bodies fail validation rather than entering event persistence. `ProgressEvent.id` is `int ge=1`, `session_id` is non-empty, and `created_at` is `datetime`.

Add named re-exports to `server/schemas/__init__.py`.

- [ ] **Step 4: Run test and verify green state**

Run:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_research_progress_contracts -v
```

Expected: 5 tests PASS.

- [ ] **Step 5: Commit research and event contracts**

```powershell
git add server/schemas/research.py server/schemas/progress.py server/schemas/__init__.py server/tests/test_research_progress_contracts.py
git commit -m "feat(research): add report and progress event contracts"
```

### Task 1.4: Add Client Generation Types and Four-Provider Metadata

**Files:**
- Modify: `.gitignore`
- Create: `client/src/types/webSearch.ts`
- Create: `client/src/types/generation.ts`
- Create: `client/src/lib/webSearchProviders.ts`
- Create: `client/src/lib/webSearchProviders.test.ts`

- [ ] **Step 1: Expose test files and write failing registry test**

Delete only these three ignore rules from `.gitignore`:

```gitignore
*.test.ts
*.test.tsx
vitest.setup.ts
```

Keep coverage output ignored. Create `client/src/lib/webSearchProviders.test.ts`:

```typescript
/**
 * ============================================================================
 * FILE: webSearchProviders.test.ts
 * LOCATION: client/src/lib/webSearchProviders.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Verifies curated client search provider metadata.
 *
 * ROLE IN PROJECT:
 *    Prevents provider drift between Settings, headers, and server contracts.
 *
 * KEY COMPONENTS:
 *    - WEB_SEARCH_PROVIDER_IDS contract tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/webSearchProviders
 *
 * USAGE:
 *    npm run test -- --run src/lib/webSearchProviders.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';

import {
  WEB_SEARCH_PROVIDER_IDS,
  WEB_SEARCH_PROVIDERS,
} from '@/lib/webSearchProviders';

describe('WEB_SEARCH_PROVIDERS', () => {
  it('contains exactly four locked providers in display order', () => {
    expect(WEB_SEARCH_PROVIDER_IDS).toEqual([
      'tavily',
      'exa',
      'brave',
      'serpapi',
    ]);
  });

  it('contains complete current-year metadata and header names', () => {
    expect(WEB_SEARCH_PROVIDERS.tavily.recommended).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.brave.requiresPaymentMethod).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.brave.attributionRequired).toBe(true);
    expect(WEB_SEARCH_PROVIDERS.serpapi.keyHeader).toBe('X-SerpApi-Key');

    for (const providerId of WEB_SEARCH_PROVIDER_IDS) {
      const provider = WEB_SEARCH_PROVIDERS[providerId];
      expect(provider.id).toBe(providerId);
      expect(provider.freeTierSummary.length).toBeGreaterThan(10);
      expect(provider.signupUrl).toMatch(/^https:\/\//);
      expect(provider.docsUrl).toMatch(/^https:\/\//);
      expect(provider.verifiedAt).toBe('2026-08-01');
    }
  });
});
```

- [ ] **Step 2: Run test and verify red state**

Run from `D:\Peter\A2UI\client`:

```powershell
npm run test -- --run src/lib/webSearchProviders.test.ts
```

Expected: FAIL with `Failed to resolve import "@/lib/webSearchProviders"`.

- [ ] **Step 3: Implement client types and metadata**

Create `client/src/types/webSearch.ts` with mandatory header and:

```typescript
export type WebSearchProviderId =
  | 'tavily'
  | 'exa'
  | 'brave'
  | 'serpapi';

export interface WebSearchProviderConfig {
  apiKey: string;
  enabled: boolean;
}

export interface WebSearchSettings {
  masterEnabled: boolean;
  providers: Record<WebSearchProviderId, WebSearchProviderConfig>;
}

export interface WebSearchProviderMetadata {
  id: WebSearchProviderId;
  displayName: string;
  freeTierSummary: string;
  signupUrl: string;
  docsUrl: string;
  keyHeader: string;
  keyPlaceholder: string;
  requiresPaymentMethod: boolean;
  attributionRequired: boolean;
  recommended: boolean;
  verifiedAt: string;
}
```

Create `client/src/lib/webSearchProviders.ts` with the same provider rows, order, copy, URLs, headers, and date specified in Task 1.1. Export a readonly tuple `WEB_SEARCH_PROVIDER_IDS` and typed record `WEB_SEARCH_PROVIDERS`. Named exports only.

Create `client/src/types/generation.ts` with client mirrors of:

```text
GenerationStage
GroundingStatus
GenerationCounts
GenerationWarning
ResearchStatus
ResearchProviderState
ResearchSource
ResearchSection
ResearchProviderStatus
ResearchReport
NodeCitation
ProgressEventType
GenerationEvent
```

Use snake_case properties for API payloads, matching FastAPI JSON exactly. `GenerationEvent` contains `id`, `session_id`, `event_type`, typed `payload`, and `created_at`. Do not add `GenerationBrief` because briefs are private and must never cross session API.

- [ ] **Step 4: Run test and TypeScript build**

Run:

```powershell
npm run test -- --run src/lib/webSearchProviders.test.ts
npm run build
```

Expected: 2 tests PASS; TypeScript and Vite build PASS.

- [ ] **Step 5: Commit client contracts and test discovery fix**

```powershell
git add .gitignore client/src/types/webSearch.ts client/src/types/generation.ts client/src/lib/webSearchProviders.ts client/src/lib/webSearchProviders.test.ts
git commit -m "feat(client): add web search and generation contracts"
```

### Task 1.5: Extend Browser Provider Settings with Default-Off Web Search

**Files:**
- Modify: `client/src/lib/providerSettings.ts`
- Create: `client/src/lib/providerSettings.test.ts`

- [ ] **Step 1: Write failing localStorage tests**

Create `client/src/lib/providerSettings.test.ts`:

```typescript
/**
 * ============================================================================
 * FILE: providerSettings.test.ts
 * LOCATION: client/src/lib/providerSettings.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Tests AI and web-search settings persistence boundaries.
 *
 * ROLE IN PROJECT:
 *    Guarantees web capability is hidden and inactive by default while keys
 *    remain browser-local at rest.
 *
 * KEY COMPONENTS:
 *    - Web-search defaults, parsing, updates, and capability tests
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: @/lib/providerSettings
 *
 * USAGE:
 *    npm run test -- --run src/lib/providerSettings.test.ts
 * ============================================================================
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  WEB_SEARCH_STORAGE_KEY,
  getConfiguredWebSearchProviders,
  getWebSearchSettings,
  hasWebSearchCapability,
  setWebSearchMasterEnabled,
  setWebSearchProviderConfig,
} from '@/lib/providerSettings';

describe('web search provider settings', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('defaults master and every provider to off', () => {
    expect(getWebSearchSettings()).toEqual({
      masterEnabled: false,
      providers: {
        tavily: { apiKey: '', enabled: false },
        exa: { apiKey: '', enabled: false },
        brave: { apiKey: '', enabled: false },
        serpapi: { apiKey: '', enabled: false },
      },
    });
    expect(hasWebSearchCapability()).toBe(false);
  });

  it('recovers safely from malformed storage', () => {
    localStorage.setItem(WEB_SEARCH_STORAGE_KEY, '{bad json');
    expect(getWebSearchSettings().masterEnabled).toBe(false);
    expect(getConfiguredWebSearchProviders()).toEqual([]);
  });

  it('normalizes partial records and discards unknown providers', () => {
    localStorage.setItem(
      WEB_SEARCH_STORAGE_KEY,
      JSON.stringify({
        masterEnabled: true,
        providers: {
          tavily: { apiKey: '  tvly-key  ', enabled: true },
          unknown: { apiKey: 'unknown-key', enabled: true },
        },
      }),
    );
    expect(getWebSearchSettings()).toEqual({
      masterEnabled: true,
      providers: {
        tavily: { apiKey: '  tvly-key  ', enabled: true },
        exa: { apiKey: '', enabled: false },
        brave: { apiKey: '', enabled: false },
        serpapi: { apiKey: '', enabled: false },
      },
    });
  });

  it('requires master, enabled provider, and nonblank key for capability', () => {
    setWebSearchProviderConfig('exa', {
      apiKey: 'exa-key',
      enabled: true,
    });
    expect(hasWebSearchCapability()).toBe(false);

    setWebSearchMasterEnabled(true);
    expect(hasWebSearchCapability()).toBe(true);
    expect(getConfiguredWebSearchProviders()).toEqual(['exa']);

    setWebSearchProviderConfig('exa', { apiKey: '   ' });
    expect(hasWebSearchCapability()).toBe(false);
  });

  it('does not mix web keys into AI provider storage', () => {
    setWebSearchMasterEnabled(true);
    setWebSearchProviderConfig('brave', {
      apiKey: 'brave-browser-key',
      enabled: true,
    });
    expect(localStorage.getItem('ai_provider_settings')).toBeNull();
    expect(localStorage.getItem(WEB_SEARCH_STORAGE_KEY)).toContain(
      'brave-browser-key',
    );
  });
});
```

- [ ] **Step 2: Run test and verify red state**

Run:

```powershell
npm run test -- --run src/lib/providerSettings.test.ts
```

Expected: FAIL because web-search exports do not exist.

- [ ] **Step 3: Add separate web-search storage helpers**

Preserve all existing AI-provider behavior in `providerSettings.ts`. Add imports from `@/types/webSearch` and `WEB_SEARCH_PROVIDER_IDS`. Add exact constant and default factory:

```typescript
export const WEB_SEARCH_STORAGE_KEY = 'web_search_settings';

function createDefaultWebSearchSettings(): WebSearchSettings {
  return {
    masterEnabled: false,
    providers: {
      tavily: { apiKey: '', enabled: false },
      exa: { apiKey: '', enabled: false },
      brave: { apiKey: '', enabled: false },
      serpapi: { apiKey: '', enabled: false },
    },
  };
}
```

Implement exact behavior:

```typescript
export function getWebSearchSettings(): WebSearchSettings;
export function setWebSearchSettings(settings: WebSearchSettings): void;
export function setWebSearchMasterEnabled(enabled: boolean): void;
export function setWebSearchProviderConfig(
  providerId: WebSearchProviderId,
  config: Partial<WebSearchProviderConfig>,
): void;
export function getConfiguredWebSearchProviders(): WebSearchProviderId[];
export function hasWebSearchCapability(): boolean;
```

`getWebSearchSettings()` parses with runtime `typeof` checks, accepts only four registry IDs, defaults missing fields, and returns fresh nested objects. It does not rewrite malformed storage. `setWebSearchSettings()` persists only to `WEB_SEARCH_STORAGE_KEY`. Configured provider order follows `WEB_SEARCH_PROVIDER_IDS`; provider qualifies only when `enabled` and `apiKey.trim().length > 0`. Capability additionally requires `masterEnabled`.

Do not attach headers, validate keys remotely, show UI, or alter `getProviderSettings()`.

- [ ] **Step 4: Run tests, lint, and build**

Run:

```powershell
npm run test -- --run src/lib/providerSettings.test.ts src/lib/webSearchProviders.test.ts
npm run lint
npm run build
```

Expected: 7 targeted tests PASS; ESLint PASS; build PASS.

- [ ] **Step 5: Commit browser settings extension**

```powershell
git add client/src/lib/providerSettings.ts client/src/lib/providerSettings.test.ts
git commit -m "feat(settings): persist optional web search providers"
```

## Phase Checkpoint

- [ ] Run complete Phase 1 verification:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_search_contracts server.tests.test_generation_contracts server.tests.test_research_progress_contracts -v
```

```powershell
Set-Location client
npm run test -- --run src/lib/providerSettings.test.ts src/lib/webSearchProviders.test.ts
npm run lint
npm run build
```

- [ ] Confirm no live-search dependency or call exists:

```powershell
rg "httpx|AsyncClient|\.search\(" server/search server/schemas/search.py
```

Expected: no adapter or HTTP client matches; protocol method declaration is the only permitted `.search(` match.

- [ ] Confirm every locked provider appears on server and client:

```powershell
rg "tavily|exa|brave|serpapi" server/search/registry.py client/src/lib/webSearchProviders.ts
```

Expected: all four IDs in both files.

- [ ] Record checkpoint on latest task commit:

```powershell
git notes add -m "Phase 1 complete: contracts and four-provider curated registry verified"
```
