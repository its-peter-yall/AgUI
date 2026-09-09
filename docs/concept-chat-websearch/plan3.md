# Concept Chat One-Shot Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `server/services/concept_chat_search.py` with the OpenAI `web_search` tool schema, duck-typed `ChatSearchLedger`, and `one_shot_chat_search` helper that runs one `ProviderCoordinator.search` using browser-sent `SearchContext` keys.

**Architecture:** New service module is the only production file. It does not import `chat_format`, `concept_chat`, routers, or `ResearchBudgetLedger`. The helper owns a short-lived `httpx.AsyncClient`, builds Researcher adapters, filters to `SearchContext.provider_ids`, constructs `ProviderCoordinator.create(..., persisted_order=[], ledger=ChatSearchLedger)`, sends `SearchQuery(query=query[:500], max_results=5)`, and closes the client in `finally`. Plan 4 will call this helper; this plan does not wire the stream loop.

**Tech Stack:** Python 3.10+, stdlib `unittest` (`IsolatedAsyncioTestCase`), `unittest.mock`, `httpx`, existing `server.search` adapters/coordinator/types, `server.schemas.search.SearchContext`.

---

## Out of scope (do not touch)

- `server/search/chat_format.py` and formatter tests
- `server/services/concept_chat.py` stream loop
- `server/routers/learning.py`
- Client files (`ChatPanel`, `useConceptChat`, `chatApi`, types)
- `server/search/coordinator.py`, adapters, `source_safety.py`, `budget.py`
- `server/services/__init__.py` (import the new module directly)
- Live network calls, `.env` keys, Brave/Tavily/Exa/SerpAPI probes

## File structure

| File | Responsibility |
|------|----------------|
| Create: `server/services/concept_chat_search.py` | `WEB_SEARCH_TOOL`, `ChatSearchLedger`, `one_shot_chat_search` |
| Create: `server/tests/test_concept_chat_search.py` | Unit tests; mock adapters/coordinator; no live HTTP |

## Locked contracts

### `WEB_SEARCH_TOOL`

OpenAI Chat Completions function tool:

- `type`: `"function"`
- `function.name`: `"web_search"`
- Single required argument: `query` (string)
- `max_results` is **not** a model argument (absent from schema JSON)
- `function.description` must contain what / when / how / 1-call / meticulous-query (exact text in Task 1)

### `ChatSearchLedger`

Duck-typed stub. **Not** `ResearchBudgetLedger`. Coordinator only needs:

- `reserve_search_call(amount=1)` — hard-stop with `RuntimeError` (not `ResearchBudgetExceeded`)
- `remaining_seconds() -> float` — `max(0.0, 25.0 - elapsed)` via `time.monotonic`; **never 0 at start**

`max_search_calls = 2 * provider_count` (first attempt + one retry each). Optional `clock` kwarg is test-only, same pattern as `server/search/budget.py`.

### `one_shot_chat_search`

```python
async def one_shot_chat_search(
    search_context: SearchContext,
    query: str,
    *,
    max_results: int = 5,
    timeout_seconds: float = 20.0,
) -> SearchResponse:
```

Build order (locked):

1. `client = httpx.AsyncClient()` (short-lived; caller of helper does not own it)
2. `all_adapters = build_search_adapters(client)`
3. Keep only `provider_id in search_context.provider_ids`
4. `credentials = {pid: search_context.get_api_key(pid) for pid in adapters}`
5. `ledger = ChatSearchLedger(max_search_calls=2 * len(adapters))`
6. `ProviderCoordinator.create(..., persisted_order=[], ledger=ledger)`
7. `SearchQuery(query=query[:500], max_results=max_results)`
8. `await coordinator.search(search_query, timeout_seconds=timeout_seconds)`
9. `await client.aclose()` in `finally` (even when search raises)

Do not catch `SearchError` / `AllProvidersUnavailable` / empty hits here. Plan 4 catches.

## How to run tests

Working directory: repo root `D:\Peter\A2UI`.

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Single test example:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search.WebSearchToolSchemaTests.test_schema_is_web_search_with_query_only
```

---

### Task 1: `WEB_SEARCH_TOOL` schema

**Files:**
- Create: `server/tests/test_concept_chat_search.py`
- Create: `server/services/concept_chat_search.py`

- [ ] **Step 1: Write the failing tests**

Create `server/tests/test_concept_chat_search.py` with this exact content:

```python
"""
============================================================================
FILE: test_concept_chat_search.py
LOCATION: server/tests/test_concept_chat_search.py
============================================================================
PURPOSE:
    Unit tests for the concept-chat web_search tool schema, ChatSearchLedger,
    and one-shot ProviderCoordinator helper.
ROLE IN PROJECT:
    Locks Plan 3 contracts so Plan 4 can call one_shot_chat_search without
    live network or research-budget types.
    - Tool schema: query-only web_search
    - Ledger: 2x providers, 25s window, RuntimeError hard-stop
    - Helper: filter adapters, empty persisted_order, close httpx client
KEY COMPONENTS:
    - WebSearchToolSchemaTests: OpenAI function schema
    - ChatSearchLedgerTests: duck-typed budget stub
    - OneShotChatSearchTests: mocked coordinator wiring
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.concept_chat_search, search types/context
USAGE:
    python -m unittest server.tests.test_concept_chat_search
============================================================================
"""

from __future__ import annotations

import json
import unittest

from server.services.concept_chat_search import WEB_SEARCH_TOOL


class WebSearchToolSchemaTests(unittest.TestCase):
    """Locks the OpenAI-compatible web_search tool exposed to the model."""

    def test_schema_is_web_search_with_query_only(self) -> None:
        self.assertEqual(WEB_SEARCH_TOOL["type"], "function")
        function = WEB_SEARCH_TOOL["function"]
        self.assertEqual(function["name"], "web_search")
        parameters = function["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(list(parameters["properties"].keys()), ["query"])
        self.assertEqual(parameters["properties"]["query"]["type"], "string")
        self.assertEqual(parameters["required"], ["query"])
        self.assertNotIn("max_results", json.dumps(WEB_SEARCH_TOOL))

    def test_description_states_what_when_how_and_one_call(self) -> None:
        description = WEB_SEARCH_TOOL["function"]["description"]
        lowered = description.lower()
        self.assertIn("search the public web", lowered)
        self.assertIn("concept content", lowered)
        self.assertIn("prior messages", lowered)
        self.assertIn("lack the context", lowered)
        self.assertIn("prior web_search results already", lowered)
        self.assertIn("one search per turn", lowered)
        self.assertIn("meticulous query", lowered)
        self.assertIn("specific terms", lowered)
        self.assertIn("versions", lowered)
        self.assertIn("concept-title", lowered)
        self.assertIn("disambiguation", lowered)
        self.assertNotIn("max_results", lowered)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: FAIL at import with `ModuleNotFoundError: No module named 'server.services.concept_chat_search'` (file does not exist yet).

- [ ] **Step 3: Write minimal implementation**

Create `server/services/concept_chat_search.py` with this exact content (header separator is 76 `=` characters):

```python
"""
============================================================================
FILE: concept_chat_search.py
LOCATION: server/services/concept_chat_search.py
============================================================================
PURPOSE:
    One-shot web search helper and OpenAI tool schema for concept chat.
ROLE IN PROJECT:
    Gives the concept-chat assistant a web_search tool backed by the same
    adapters and ProviderCoordinator as Researcher, without research jobs.
    - Exposes a stable tool definition (constraints in the description)
    - Caps coordinator retries with a tiny duck-typed ledger
    - Runs a single SearchQuery and always closes the httpx client
KEY COMPONENTS:
    - WEB_SEARCH_TOOL: OpenAI function schema (query only)
    - ChatSearchLedger: 2x-provider call cap and 25s monotonic window
    - one_shot_chat_search: Filter adapters and run ProviderCoordinator
DEPENDENCIES:
    - External: httpx
    - Internal: server.schemas.search, server.search adapters/coordinator/types
USAGE:
    from server.services.concept_chat_search import (
        WEB_SEARCH_TOOL,
        one_shot_chat_search,
    )
    response = await one_shot_chat_search(search_context, query)
============================================================================
"""

from __future__ import annotations

WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web for current facts, versions, APIs, or "
            "news that the concept card does not cover. Use only when the "
            "concept content and prior messages lack the context needed to "
            "answer. Do not search if prior web_search results already "
            "cover the question. One search per turn. Write one meticulous "
            "query using specific terms, versions, and concept-title "
            "disambiguation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Single meticulous search query. Include specific "
                        "terms, versions, and the concept title when needed "
                        "to disambiguate."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}
```

Do not add `ChatSearchLedger` or `one_shot_chat_search` yet.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: PASS (`OK`, 2 tests).

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_concept_chat_search.py server/services/concept_chat_search.py
git commit -m "feat(concept-chat-websearch): add web_search tool schema"
```

---

### Task 2: `ChatSearchLedger` stub

**Files:**
- Modify: `server/tests/test_concept_chat_search.py`
- Modify: `server/services/concept_chat_search.py`

- [ ] **Step 1: Write the failing tests**

In `server/tests/test_concept_chat_search.py`:

1. Change the concept_chat_search import to:

```python
from server.services.concept_chat_search import (
    WEB_SEARCH_TOOL,
    ChatSearchLedger,
)
```

2. Add this import next to the other imports:

```python
from server.search.budget import ResearchBudgetExceeded, ResearchBudgetLedger
```

3. Append this class after `WebSearchToolSchemaTests` (do not remove Task 1 tests):

```python
class ChatSearchLedgerTests(unittest.TestCase):
    """Duck-typed chat ledger: not ResearchBudgetLedger."""

    def test_is_not_research_budget_ledger(self) -> None:
        self.assertFalse(
            issubclass(ChatSearchLedger, ResearchBudgetLedger)
        )
        ledger = ChatSearchLedger(max_search_calls=2)
        self.assertIsInstance(ledger, ChatSearchLedger)
        self.assertNotIsInstance(ledger, ResearchBudgetLedger)

    def test_remaining_seconds_never_zero_at_start(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        remaining = ledger.remaining_seconds()
        self.assertGreater(remaining, 24.0)
        self.assertLessEqual(remaining, 25.0)
        self.assertEqual(ledger.max_search_calls, 2)
        self.assertEqual(ledger.max_elapsed_seconds, 25.0)

    def test_remaining_seconds_uses_25s_monotonic_window(self) -> None:
        class FakeClock:
            def __init__(self) -> None:
                self.now = 1000.0

            def __call__(self) -> float:
                return self.now

        clock = FakeClock()
        ledger = ChatSearchLedger(max_search_calls=4, clock=clock)
        self.assertEqual(ledger.remaining_seconds(), 25.0)
        clock.now = 1010.0
        self.assertEqual(ledger.remaining_seconds(), 15.0)
        clock.now = 1025.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)
        clock.now = 1040.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)

    def test_reserve_search_call_hard_stops_after_cap(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        ledger.reserve_search_call()
        ledger.reserve_search_call(1)
        with self.assertRaises(RuntimeError) as raised:
            ledger.reserve_search_call()
        self.assertNotIsInstance(
            raised.exception,
            ResearchBudgetExceeded,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: FAIL with `ImportError: cannot import name 'ChatSearchLedger' from 'server.services.concept_chat_search'`.

- [ ] **Step 3: Write minimal implementation**

In `server/services/concept_chat_search.py`, add these imports immediately after `from __future__ import annotations`:

```python
import time
from typing import Callable, Optional
```

Then append this class after `WEB_SEARCH_TOOL` (keep the tool dict unchanged):

```python
class ChatSearchLedger:
    """In-process search call/time cap for one concept-chat tool round.

    Duck-typed for ProviderCoordinator. Not a ResearchBudgetLedger.
    """

    def __init__(
        self,
        max_search_calls: int,
        *,
        max_elapsed_seconds: float = 25.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        """Store call cap and start the monotonic window.

        Args:
            max_search_calls: Hard cap (use 2 * provider count).
            max_elapsed_seconds: Wall window; default 25 so remaining
                is never 0 at start (coordinator clamps 0 to 10ms).
            clock: Optional monotonic clock for tests.
        """
        self.max_search_calls = max_search_calls
        self.max_elapsed_seconds = max_elapsed_seconds
        self._clock = clock or time.monotonic
        self._started_at = self._clock()
        self._search_calls = 0

    def remaining_seconds(self) -> float:
        """Seconds left in the 25s window, floored at 0."""
        elapsed = self._clock() - self._started_at
        return max(0.0, self.max_elapsed_seconds - elapsed)

    def reserve_search_call(self, amount: int = 1) -> None:
        """Reserve search attempts or raise RuntimeError.

        Args:
            amount: Calls to reserve (coordinator uses default 1).

        Raises:
            RuntimeError: When the call cap would be exceeded.
        """
        if self._search_calls + amount > self.max_search_calls:
            raise RuntimeError("Chat search call budget exceeded")
        self._search_calls += amount
```

Do not import `server.search.budget`. Do not add `one_shot_chat_search` yet.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: PASS (`OK`, 6 tests).

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_concept_chat_search.py server/services/concept_chat_search.py
git commit -m "feat(concept-chat-websearch): add ChatSearchLedger stub"
```

---

### Task 3: `one_shot_chat_search` helper

**Files:**
- Modify: `server/tests/test_concept_chat_search.py`
- Modify: `server/services/concept_chat_search.py`

- [ ] **Step 1: Write the failing tests**

Replace `server/tests/test_concept_chat_search.py` with this exact full file (keeps Task 1–2 tests; adds one-shot tests):

```python
"""
============================================================================
FILE: test_concept_chat_search.py
LOCATION: server/tests/test_concept_chat_search.py
============================================================================
PURPOSE:
    Unit tests for the concept-chat web_search tool schema, ChatSearchLedger,
    and one-shot ProviderCoordinator helper.
ROLE IN PROJECT:
    Locks Plan 3 contracts so Plan 4 can call one_shot_chat_search without
    live network or research-budget types.
    - Tool schema: query-only web_search
    - Ledger: 2x providers, 25s window, RuntimeError hard-stop
    - Helper: filter adapters, empty persisted_order, close httpx client
KEY COMPONENTS:
    - WebSearchToolSchemaTests: OpenAI function schema
    - ChatSearchLedgerTests: duck-typed budget stub
    - OneShotChatSearchTests: mocked coordinator wiring
DEPENDENCIES:
    - External: unittest, unittest.mock
    - Internal: server.services.concept_chat_search, search types/context
USAGE:
    python -m unittest server.tests.test_concept_chat_search
============================================================================
"""

from __future__ import annotations

import inspect
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from server.schemas.search import SearchContext
from server.search.budget import ResearchBudgetExceeded, ResearchBudgetLedger
from server.search.types import (
    AllProvidersUnavailable,
    SearchProviderId,
    SearchQuery,
    SearchResponse,
)
from server.services.concept_chat_search import (
    WEB_SEARCH_TOOL,
    ChatSearchLedger,
    one_shot_chat_search,
)


class WebSearchToolSchemaTests(unittest.TestCase):
    """Locks the OpenAI-compatible web_search tool exposed to the model."""

    def test_schema_is_web_search_with_query_only(self) -> None:
        self.assertEqual(WEB_SEARCH_TOOL["type"], "function")
        function = WEB_SEARCH_TOOL["function"]
        self.assertEqual(function["name"], "web_search")
        parameters = function["parameters"]
        self.assertEqual(parameters["type"], "object")
        self.assertEqual(list(parameters["properties"].keys()), ["query"])
        self.assertEqual(parameters["properties"]["query"]["type"], "string")
        self.assertEqual(parameters["required"], ["query"])
        self.assertNotIn("max_results", json.dumps(WEB_SEARCH_TOOL))

    def test_description_states_what_when_how_and_one_call(self) -> None:
        description = WEB_SEARCH_TOOL["function"]["description"]
        lowered = description.lower()
        self.assertIn("search the public web", lowered)
        self.assertIn("concept content", lowered)
        self.assertIn("prior messages", lowered)
        self.assertIn("lack the context", lowered)
        self.assertIn("prior web_search results already", lowered)
        self.assertIn("one search per turn", lowered)
        self.assertIn("meticulous query", lowered)
        self.assertIn("specific terms", lowered)
        self.assertIn("versions", lowered)
        self.assertIn("concept-title", lowered)
        self.assertIn("disambiguation", lowered)
        self.assertNotIn("max_results", lowered)


class ChatSearchLedgerTests(unittest.TestCase):
    """Duck-typed chat ledger: not ResearchBudgetLedger."""

    def test_is_not_research_budget_ledger(self) -> None:
        self.assertFalse(
            issubclass(ChatSearchLedger, ResearchBudgetLedger)
        )
        ledger = ChatSearchLedger(max_search_calls=2)
        self.assertIsInstance(ledger, ChatSearchLedger)
        self.assertNotIsInstance(ledger, ResearchBudgetLedger)

    def test_remaining_seconds_never_zero_at_start(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        remaining = ledger.remaining_seconds()
        self.assertGreater(remaining, 24.0)
        self.assertLessEqual(remaining, 25.0)
        self.assertEqual(ledger.max_search_calls, 2)
        self.assertEqual(ledger.max_elapsed_seconds, 25.0)

    def test_remaining_seconds_uses_25s_monotonic_window(self) -> None:
        class FakeClock:
            def __init__(self) -> None:
                self.now = 1000.0

            def __call__(self) -> float:
                return self.now

        clock = FakeClock()
        ledger = ChatSearchLedger(max_search_calls=4, clock=clock)
        self.assertEqual(ledger.remaining_seconds(), 25.0)
        clock.now = 1010.0
        self.assertEqual(ledger.remaining_seconds(), 15.0)
        clock.now = 1025.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)
        clock.now = 1040.0
        self.assertEqual(ledger.remaining_seconds(), 0.0)

    def test_reserve_search_call_hard_stops_after_cap(self) -> None:
        ledger = ChatSearchLedger(max_search_calls=2)
        ledger.reserve_search_call()
        ledger.reserve_search_call(1)
        with self.assertRaises(RuntimeError) as raised:
            ledger.reserve_search_call()
        self.assertNotIsInstance(
            raised.exception,
            ResearchBudgetExceeded,
        )


def _enabled_context() -> SearchContext:
    return SearchContext.from_plaintext_credentials(
        enabled=True,
        provider_ids=[SearchProviderId.TAVILY, SearchProviderId.EXA],
        credentials={
            SearchProviderId.TAVILY: "tvly-test-key",
            SearchProviderId.EXA: "exa-test-key",
        },
    )


def _all_adapters() -> dict[SearchProviderId, object]:
    return {
        SearchProviderId.TAVILY: object(),
        SearchProviderId.EXA: object(),
        SearchProviderId.BRAVE: object(),
        SearchProviderId.SERPAPI: object(),
    }


class OneShotChatSearchTests(unittest.IsolatedAsyncioTestCase):
    """one_shot_chat_search wiring; mocks only, no live network."""

    async def test_filters_adapters_builds_query_and_closes_client(
        self,
    ) -> None:
        adapters = _all_adapters()
        expected = SearchResponse(results=[], response_bytes=0)
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        captured: dict = {}

        def fake_create(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            coordinator = MagicMock()
            coordinator.search = AsyncMock(return_value=expected)
            captured["_coordinator"] = coordinator
            return coordinator

        with patch(
            "server.services.concept_chat_search.httpx.AsyncClient",
            return_value=fake_client,
        ), patch(
            "server.services.concept_chat_search.build_search_adapters",
            return_value=adapters,
        ) as build, patch(
            "server.services.concept_chat_search.ProviderCoordinator.create",
            side_effect=fake_create,
        ):
            result = await one_shot_chat_search(
                _enabled_context(),
                "LangChain BaseTool documentation",
            )

        self.assertIs(result, expected)
        build.assert_called_once_with(fake_client)
        self.assertEqual(
            set(captured["adapters"].keys()),
            {SearchProviderId.TAVILY, SearchProviderId.EXA},
        )
        self.assertIs(
            captured["adapters"][SearchProviderId.TAVILY],
            adapters[SearchProviderId.TAVILY],
        )
        self.assertIs(
            captured["adapters"][SearchProviderId.EXA],
            adapters[SearchProviderId.EXA],
        )
        self.assertEqual(
            captured["credentials"],
            {
                SearchProviderId.TAVILY: "tvly-test-key",
                SearchProviderId.EXA: "exa-test-key",
            },
        )
        self.assertEqual(captured["persisted_order"], [])
        ledger = captured["ledger"]
        self.assertIsInstance(ledger, ChatSearchLedger)
        self.assertNotIsInstance(ledger, ResearchBudgetLedger)
        self.assertEqual(ledger.max_search_calls, 4)

        search = captured["_coordinator"].search
        search.assert_awaited_once()
        called_query = search.await_args.args[0]
        self.assertIsInstance(called_query, SearchQuery)
        self.assertEqual(
            called_query.query,
            "LangChain BaseTool documentation",
        )
        self.assertEqual(called_query.max_results, 5)
        self.assertEqual(
            search.await_args.kwargs["timeout_seconds"],
            20.0,
        )
        fake_client.aclose.assert_awaited_once()

    async def test_truncates_query_to_500_and_closes_on_error(self) -> None:
        adapters = {
            SearchProviderId.TAVILY: object(),
        }
        fake_client = MagicMock()
        fake_client.aclose = AsyncMock()
        captured: dict = {}
        boom = AllProvidersUnavailable(
            provider_ids=(SearchProviderId.TAVILY,),
        )

        def fake_create(**kwargs: object) -> MagicMock:
            coordinator = MagicMock()
            coordinator.search = AsyncMock(side_effect=boom)
            captured["coordinator"] = coordinator
            captured["ledger"] = kwargs["ledger"]
            return coordinator

        long_query = "x" * 600
        context = SearchContext.from_plaintext_credentials(
            enabled=True,
            provider_ids=[SearchProviderId.TAVILY],
            credentials={SearchProviderId.TAVILY: "tvly-test-key"},
        )

        with patch(
            "server.services.concept_chat_search.httpx.AsyncClient",
            return_value=fake_client,
        ), patch(
            "server.services.concept_chat_search.build_search_adapters",
            return_value=adapters,
        ), patch(
            "server.services.concept_chat_search.ProviderCoordinator.create",
            side_effect=fake_create,
        ):
            with self.assertRaises(AllProvidersUnavailable):
                await one_shot_chat_search(context, long_query)

        search = captured["coordinator"].search
        search.assert_awaited_once()
        called_query = search.await_args.args[0]
        self.assertEqual(len(called_query.query), 500)
        self.assertEqual(called_query.query, "x" * 500)
        self.assertEqual(called_query.max_results, 5)
        self.assertEqual(captured["ledger"].max_search_calls, 2)
        fake_client.aclose.assert_awaited_once()

    def test_module_does_not_use_research_budget_or_formatter(self) -> None:
        import server.services.concept_chat_search as module

        source = inspect.getsource(module)
        self.assertNotIn("server.search.budget", source)
        self.assertNotIn("chat_format", source)
        self.assertNotIn("stream_concept_chat", source)
        self.assertNotIn("ResearchRunner", source)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: FAIL with `ImportError: cannot import name 'one_shot_chat_search' from 'server.services.concept_chat_search'`.

- [ ] **Step 3: Write minimal implementation**

In `server/services/concept_chat_search.py`, replace the import block after the future import so it is exactly:

```python
from __future__ import annotations

import time
from typing import Callable, Optional

import httpx

from server.schemas.search import SearchContext
from server.search.adapters import build_search_adapters
from server.search.coordinator import ProviderCoordinator
from server.search.types import SearchQuery, SearchResponse
```

Keep `WEB_SEARCH_TOOL` and `ChatSearchLedger` unchanged. Append this function at the end of the file:

```python
async def one_shot_chat_search(
    search_context: SearchContext,
    query: str,
    *,
    max_results: int = 5,
    timeout_seconds: float = 20.0,
) -> SearchResponse:
    """Run one ProviderCoordinator search for concept chat.

    Args:
        search_context: Runtime context with selected provider keys.
        query: Model query; truncated to SearchQuery max (500 chars).
        max_results: Server-chosen hit cap (default 5). Not a tool arg.
        timeout_seconds: Coordinator timeout (default 20).

    Returns:
        SearchResponse from the first successful provider.

    Raises:
        ValueError: Empty adapter set or mismatched credentials.
        SearchError: Non-rotatable provider failure.
        AllProvidersUnavailable: Every configured provider failed.
    """
    client = httpx.AsyncClient()
    try:
        all_adapters = build_search_adapters(client)
        selected = set(search_context.provider_ids)
        adapters = {
            provider_id: adapter
            for provider_id, adapter in all_adapters.items()
            if provider_id in selected
        }
        credentials = {
            provider_id: search_context.get_api_key(provider_id)
            for provider_id in adapters
        }
        ledger = ChatSearchLedger(
            max_search_calls=2 * len(adapters),
        )
        coordinator = ProviderCoordinator.create(
            adapters=adapters,
            credentials=credentials,
            persisted_order=[],
            ledger=ledger,
        )
        search_query = SearchQuery(
            query=query[:500],
            max_results=max_results,
        )
        return await coordinator.search(
            search_query,
            timeout_seconds=timeout_seconds,
        )
    finally:
        await client.aclose()
```

Do not import `chat_format`. Do not import `ResearchBudgetLedger`. Do not catch coordinator errors.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_search
```

Expected: PASS (`OK`, 9 tests).

If `inspect.getsource` fails because the module has no file on disk, the file was not saved; write it to `server/services/concept_chat_search.py` and re-run.

- [ ] **Step 5: Commit**

```bash
git add server/tests/test_concept_chat_search.py server/services/concept_chat_search.py
git commit -m "feat(concept-chat-websearch): add one_shot_chat_search helper"
```

---

## Final module shape (after Task 3)

`server/services/concept_chat_search.py` exports only:

- `WEB_SEARCH_TOOL`
- `ChatSearchLedger`
- `one_shot_chat_search`

`server/tests/test_concept_chat_search.py` classes:

- `WebSearchToolSchemaTests` (2 tests)
- `ChatSearchLedgerTests` (4 tests)
- `OneShotChatSearchTests` (3 tests)

No other production files.

## Self-review

**Spec coverage (Plan 3 slice of goal.md + research.md):**

| Requirement | Task |
|-------------|------|
| `WEB_SEARCH_TOOL` OpenAI function; description what/when/how/1-call/meticulous-query | Task 1 |
| Single required arg `query`; `max_results` not a model argument | Task 1 |
| `ChatSearchLedger` duck-typed; `max_search_calls = 2 * provider_count` | Task 2 / Task 3 wiring |
| `remaining_seconds()` 25s monotonic window; never 0 at start | Task 2 |
| `reserve_search_call()` hard-stop; not `ResearchBudgetLedger` | Task 2 |
| `one_shot_chat_search(search_context, query, max_results=5, timeout_seconds=20.0) -> SearchResponse` | Task 3 |
| Short-lived `httpx.AsyncClient`; `build_search_adapters`; filter to `provider_ids` | Task 3 |
| Credentials via `search_context.get_api_key` | Task 3 |
| `ProviderCoordinator.create(..., persisted_order=[], ledger=ledger)` | Task 3 |
| `SearchQuery(query=query[:500], max_results=5)` | Task 3 |
| Close client in `finally` | Task 3 |
| Tests mock adapters/coordinator; no live network; no `.env` keys | Task 3 |
| File header per AGENTS.md | Tasks 1–3 |
| No formatter / concept_chat loop / router / client | Out of scope + source guard test |

**Placeholder scan:** No TBD/TODO. Exact test code, commands, implementation, and commit messages included.

**Type consistency:** `ChatSearchLedger.max_search_calls`, `remaining_seconds()`, `reserve_search_call(amount=1)` match coordinator duck-typing in `server/search/coordinator.py`. `SearchContext.get_api_key` and `from_plaintext_credentials` match `server/schemas/search.py`. `SearchQuery` / `SearchResponse` match `server/search/types.py`.
