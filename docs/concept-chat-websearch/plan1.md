# Concept Chat Message Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional nested `search` blob to `ConceptChatMessage` (Pydantic + TypeScript) and additive `status` / `search` / `warning` fields on `ConceptChatStreamChunk`, without breaking old `{role, content}` chats.

**Architecture:** Additive contract only. Server gets two small nested models (`ConceptChatSearchSource`, `ConceptChatSearch`) and an optional `search` field on existing `ConceptChatMessage`. Pydantic `extra` stays default ignore — never `forbid` — so old clients and stored messages still parse. Client mirrors the same snake_case shape. Stream chunk fields are client-only TypeScript; no SSE Pydantic model. Role stays `user` | `assistant`. `content` `min_length=1` stays.

**Tech Stack:** Pydantic v2, Python 3.10+ unittest, TypeScript strict (`client/tsconfig.app.json`), Vitest.

---

## Scope lock

**In scope**

- `server/schemas/learning.py`
- `client/src/types/learning.ts`
- Tests for those contracts only

**Out of scope (do not touch)**

- Formatter (`server/search/chat_format.py`)
- Tool loop (`server/services/concept_chat.py`)
- Router (`server/routers/learning.py`)
- `ChatPanel.tsx`, `useConceptChat.ts`, `chatApi.ts`
- `extra='forbid'`
- `role: "tool"`
- Server SSE Pydantic chunk model

---

## File Map

| File | Responsibility |
|------|----------------|
| `server/schemas/learning.py` | Nested `ConceptChatSearchSource` + `ConceptChatSearch`; optional `search` on `ConceptChatMessage`; keep `extra` ignore |
| `server/tests/test_concept_chat_message_schema.py` | Server contract tests (search accepted / missing / extras ignored / invalid rejected / role / content) |
| `client/src/types/learning.ts` | `ConceptChatSearchSource`, `ConceptChatSearch`; optional `search` on message; stream chunk `status` / `search` / `warning` |
| `client/src/types/learning.test.ts` | Client shape tests for message + stream chunk |

---

## Task 1: Server Pydantic search contract

**Files:**

- Create: `server/tests/test_concept_chat_message_schema.py`
- Modify: `server/schemas/learning.py` (CONCEPT CHAT SCHEMAS block, ~1252–1275)

- [ ] **Step 1: Write the failing test**

Create `server/tests/test_concept_chat_message_schema.py` with this exact content (file header uses 76 `=` characters):

```python
"""
============================================================================
FILE: test_concept_chat_message_schema.py
LOCATION: server/tests/test_concept_chat_message_schema.py
============================================================================
PURPOSE:
    Contract tests for optional search blobs on ConceptChatMessage.
ROLE IN PROJECT:
    Locks the concept-chat web-search history payload before the tool
    loop, formatter, or router consume it.
    - Optional nested search accepted
    - Old {role, content} messages still parse
    - Unknown extras ignored (never extra=forbid)
    - Invalid search fields rejected
KEY COMPONENTS:
    - ConceptChatMessageSchemaTests: Pydantic v2 validation cases
DEPENDENCIES:
    - External: unittest, pydantic
    - Internal: server.schemas.learning
USAGE:
    python -m unittest server.tests.test_concept_chat_message_schema -v
============================================================================
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from server.schemas.learning import (
    ConceptChatMessage,
    ConceptChatRequest,
    ConceptChatSearch,
    ConceptChatSearchSource,
)


_VALID_SEARCH = {
    "query": "LangChain BaseTool documentation",
    "tool_call_id": "call_abc123",
    "results": (
        'WEB SEARCH RESULTS for: "LangChain BaseTool documentation"'
    ),
    "sources": [
        {
            "title": "LangChain docs",
            "url": "https://python.langchain.com",
        }
    ],
}


class ConceptChatMessageSchemaTests(unittest.TestCase):
    def test_optional_search_accepted(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "Here is the answer.",
                "search": _VALID_SEARCH,
            }
        )
        self.assertEqual(msg.role, "assistant")
        self.assertEqual(msg.content, "Here is the answer.")
        self.assertIsNotNone(msg.search)
        self.assertIsInstance(msg.search, ConceptChatSearch)
        self.assertEqual(
            msg.search.query,
            "LangChain BaseTool documentation",
        )
        self.assertEqual(msg.search.tool_call_id, "call_abc123")
        self.assertIn("WEB SEARCH RESULTS", msg.search.results)
        self.assertEqual(len(msg.search.sources), 1)
        self.assertIsInstance(
            msg.search.sources[0],
            ConceptChatSearchSource,
        )
        self.assertEqual(
            msg.search.sources[0].title,
            "LangChain docs",
        )
        self.assertEqual(
            msg.search.sources[0].url,
            "https://python.langchain.com",
        )

    def test_missing_search_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {"role": "user", "content": "hello"}
        )
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "hello")
        self.assertIsNone(msg.search)

    def test_search_null_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "plain answer",
                "search": None,
            }
        )
        self.assertIsNone(msg.search)

    def test_empty_sources_ok(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "answer",
                "search": {
                    "query": "q",
                    "tool_call_id": "call_1",
                    "results": "blob",
                    "sources": [],
                },
            }
        )
        self.assertIsNotNone(msg.search)
        self.assertEqual(msg.search.sources, [])

    def test_unknown_extras_ignored(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "user",
                "content": "hello from old client",
                "timestamp": 1,
                "foo": "bar",
            }
        )
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "hello from old client")
        self.assertIsNone(msg.search)
        dumped = msg.model_dump()
        self.assertNotIn("timestamp", dumped)
        self.assertNotIn("foo", dumped)

    def test_nested_search_extras_ignored(self) -> None:
        msg = ConceptChatMessage.model_validate(
            {
                "role": "assistant",
                "content": "answer",
                "search": {
                    "query": "q",
                    "tool_call_id": "call_1",
                    "results": "blob",
                    "provider": "tavily",
                    "sources": [
                        {
                            "title": "T",
                            "url": "https://example.com",
                            "snippet": "ignored",
                        }
                    ],
                },
            }
        )
        self.assertIsNotNone(msg.search)
        dumped = msg.search.model_dump()
        self.assertNotIn("provider", dumped)
        self.assertNotIn("snippet", dumped["sources"][0])
        self.assertEqual(dumped["sources"][0]["title"], "T")
        self.assertEqual(
            dumped["sources"][0]["url"],
            "https://example.com",
        )

    def test_extra_is_not_forbid(self) -> None:
        self.assertNotEqual(
            ConceptChatMessage.model_config.get("extra"),
            "forbid",
        )
        self.assertNotEqual(
            ConceptChatSearch.model_config.get("extra"),
            "forbid",
        )
        self.assertNotEqual(
            ConceptChatSearchSource.model_config.get("extra"),
            "forbid",
        )

    def test_invalid_search_fields_rejected(self) -> None:
        base = {
            "role": "assistant",
            "content": "answer from concept",
        }
        invalid_searches = [
            "not-an-object",
            [],
            {},
            {
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "",
                "results": "blob",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "",
                "sources": [],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": "not-a-list",
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"url": "https://ex.com"}],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"title": "T"}],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [
                    {"title": "", "url": "https://ex.com"}
                ],
            },
            {
                "query": "q",
                "tool_call_id": "call_1",
                "results": "blob",
                "sources": [{"title": "T", "url": ""}],
            },
        ]
        for search in invalid_searches:
            with self.subTest(search=search):
                payload = {**base, "search": search}
                with self.assertRaises(ValidationError):
                    ConceptChatMessage.model_validate(payload)

    def test_role_rejects_tool(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptChatMessage.model_validate(
                {"role": "tool", "content": "search results"}
            )

    def test_content_min_length_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            ConceptChatMessage.model_validate(
                {"role": "user", "content": ""}
            )

    def test_request_history_preserves_search(self) -> None:
        req = ConceptChatRequest.model_validate(
            {
                "message": "follow up",
                "history": [
                    {"role": "user", "content": "first question"},
                    {
                        "role": "assistant",
                        "content": "grounded answer",
                        "search": _VALID_SEARCH,
                    },
                ],
            }
        )
        self.assertEqual(len(req.history), 2)
        self.assertIsNone(req.history[0].search)
        self.assertIsNotNone(req.history[1].search)
        self.assertEqual(
            req.history[1].search.tool_call_id,
            "call_abc123",
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Workdir: `D:\Peter\A2UI`

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_message_schema -v
```

Expected: FAIL during import:

```text
ImportError: cannot import name 'ConceptChatSearch' from 'server.schemas.learning'
```

Do not implement until this fail is observed.

- [ ] **Step 3: Write minimal implementation**

In `server/schemas/learning.py`, insert the two nested models **immediately before** `class ConceptChatMessage` (after the `CONCEPT CHAT SCHEMAS` banner, ~line 1256). Then add optional `search` on `ConceptChatMessage`. Do **not** set `extra='forbid'` on any of these models. Leave `model_config = ConfigDict(from_attributes=True)` (Pydantic v2 default extra is ignore).

Replace the current `ConceptChatMessage` class with:

```python
class ConceptChatSearchSource(BaseModel):
    """Title and URL for a source chip on an assistant message."""

    model_config = ConfigDict(from_attributes=True)

    title: str = Field(
        ...,
        description="Source title shown on UI chips",
        min_length=1,
    )
    url: str = Field(
        ...,
        description="Source URL shown on UI chips",
        min_length=1,
    )


class ConceptChatSearch(BaseModel):
    """Persisted web-search blob on an assistant chat message.

    extra stays default ignore so unknown nested keys drop. Do not
    set extra='forbid' — old clients and stored blobs must still parse.
    """

    model_config = ConfigDict(from_attributes=True)

    query: str = Field(
        ...,
        description="Query executed for this search",
        min_length=1,
    )
    tool_call_id: str = Field(
        ...,
        description="Tool call id used to rebuild history",
        min_length=1,
    )
    results: str = Field(
        ...,
        description="Formatted readable search results text",
        min_length=1,
    )
    sources: List[ConceptChatSearchSource] = Field(
        ...,
        description="UI source chips (title and url only)",
    )


class ConceptChatMessage(BaseModel):
    """A single chat message in concept chat history.

    Represents one turn in the ephemeral conversation between user and
    assistant. Role is constrained to 'user' or 'assistant'. Optional
    search blob rides on assistant messages for later-turn rebuild.
    extra stays default ignore. Do not set extra='forbid'.
    """

    model_config = ConfigDict(from_attributes=True)

    role: Literal["user", "assistant"] = Field(
        ...,
        description="Role of the message sender",
    )
    content: str = Field(
        ...,
        description="Message content text",
        min_length=1,
    )
    search: Optional[ConceptChatSearch] = Field(
        default=None,
        description="Optional web-search blob for later turns",
    )
```

Do not change `ConceptChatRequest`. History items pick up `search` because they are `List[ConceptChatMessage]`.

Keep Python lines at 80 characters. `Optional` and `List` are already imported in this file.

- [ ] **Step 4: Run test to verify it passes**

Workdir: `D:\Peter\A2UI`

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_message_schema -v
```

Expected: `OK` — all tests PASS, including subtests inside `test_invalid_search_fields_rejected`.

Also confirm existing concept-chat tests still pass (old `ConceptChatMessage(role=..., content=...)` constructors):

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_cache -v
```

Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add server/schemas/learning.py server/tests/test_concept_chat_message_schema.py
git commit -m "feat(learning): add optional search blob to ConceptChatMessage"
```

---

## Task 2: Client TypeScript message + stream chunk contract

**Files:**

- Create: `client/src/types/learning.test.ts`
- Modify: `client/src/types/learning.ts` (Concept Chat types block, ~346–364)

Vitest does **not** typecheck. Red phase for new type names is `tsc -b`. Runtime vitest asserts JSON shape after types exist.

- [ ] **Step 1: Write the failing test**

Create `client/src/types/learning.test.ts` with this exact content (file header uses 76 `=` characters):

```ts
/**
 * ============================================================================
 * FILE: learning.test.ts
 * LOCATION: client/src/types/learning.test.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Contract tests for concept-chat search blobs and stream chunks.
 *
 * ROLE IN PROJECT:
 *    Locks the client TypeScript shapes that mirror ConceptChatMessage
 *    and additive SSE fields before chatApi / ChatPanel consume them.
 *
 * KEY COMPONENTS:
 *    - ConceptChatMessage search optional blob
 *    - ConceptChatStreamChunk status / search / warning
 *
 * DEPENDENCIES:
 *    - External: vitest
 *    - Internal: ./learning
 *
 * USAGE:
 *    npx vitest run src/types/learning.test.ts
 * ============================================================================
 */

import { describe, expect, it } from 'vitest';
import type {
  ConceptChatMessage,
  ConceptChatSearch,
  ConceptChatSearchSource,
  ConceptChatStreamChunk,
} from './learning';

const sampleSource: ConceptChatSearchSource = {
  title: 'LangChain docs',
  url: 'https://python.langchain.com',
};

const sampleSearch: ConceptChatSearch = {
  query: 'LangChain BaseTool documentation',
  tool_call_id: 'call_abc123',
  results: 'WEB SEARCH RESULTS for: "LangChain BaseTool documentation"',
  sources: [sampleSource],
};

describe('ConceptChatMessage search contract', () => {
  it('accepts optional search on an assistant message', () => {
    const msg: ConceptChatMessage = {
      role: 'assistant',
      content: 'Here is the answer.',
      search: sampleSearch,
    };
    expect(msg.role).toBe('assistant');
    expect(msg.content).toBe('Here is the answer.');
    expect(msg.search?.query).toBe(
      'LangChain BaseTool documentation',
    );
    expect(msg.search?.tool_call_id).toBe('call_abc123');
    expect(msg.search?.results).toContain('WEB SEARCH RESULTS');
    expect(msg.search?.sources).toEqual([
      {
        title: 'LangChain docs',
        url: 'https://python.langchain.com',
      },
    ]);
  });

  it('parses old localStorage messages without search', () => {
    const raw = JSON.parse(
      '{"role":"user","content":"hello"}',
    ) as ConceptChatMessage;
    expect(raw.role).toBe('user');
    expect(raw.content).toBe('hello');
    expect(raw.search).toBeUndefined();
  });

  it('keeps role and content when unknown extras are present', () => {
    const raw = JSON.parse(
      '{"role":"user","content":"hello","timestamp":1}',
    ) as ConceptChatMessage;
    expect(raw.role).toBe('user');
    expect(raw.content).toBe('hello');
    expect(raw.search).toBeUndefined();
  });

  it('does not allow a tool role on the message type', () => {
    const msg: ConceptChatMessage = {
      role: 'user',
      content: 'question',
    };
    expect(msg.role === 'user' || msg.role === 'assistant').toBe(
      true,
    );
    expect(msg.role).not.toBe('tool');
  });
});

describe('ConceptChatStreamChunk additive fields', () => {
  it('keeps existing delta and error fields', () => {
    const deltaChunk: ConceptChatStreamChunk = { delta: 'Hello' };
    const errorChunk: ConceptChatStreamChunk = { error: 'boom' };
    expect(deltaChunk.delta).toBe('Hello');
    expect(errorChunk.error).toBe('boom');
  });

  it('accepts optional status searching', () => {
    const chunk: ConceptChatStreamChunk = { status: 'searching' };
    expect(chunk.status).toBe('searching');
  });

  it('accepts optional search payload', () => {
    const chunk: ConceptChatStreamChunk = { search: sampleSearch };
    expect(chunk.search?.query).toBe(
      'LangChain BaseTool documentation',
    );
    expect(chunk.search?.sources[0]?.title).toBe('LangChain docs');
  });

  it('accepts optional warning string', () => {
    const chunk: ConceptChatStreamChunk = {
      warning:
        'Web search unavailable; answering from the concept.',
    };
    expect(chunk.warning).toBe(
      'Web search unavailable; answering from the concept.',
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Workdir: `D:\Peter\A2UI\client`

```powershell
npx tsc -b --pretty false
```

Expected: FAIL. `tsc` reports that `./learning` has no exported member `ConceptChatSearch` (and/or `ConceptChatSearchSource`), for example:

```text
src/types/learning.test.ts: error TS2305: Module '"./learning"' has no exported member 'ConceptChatSearch'.
```

That is the red gate. Do not treat Vitest as the red signal — `import type` is erased, so this may still run:

```powershell
npx vitest run src/types/learning.test.ts
```

Vitest can pass or fail depending on whether object literals are evaluated before the missing types. Trust `tsc -b`.

- [ ] **Step 3: Write minimal implementation**

In `client/src/types/learning.ts`, replace the Concept Chat types block at the bottom (from `// --- Concept Chat types ---` through `ConceptChatStreamChunk`) with the following. Match the file's existing tab indentation and double quotes.

```ts
// --- Concept Chat types ---

export type ConceptChatRole = "user" | "assistant";

export interface ConceptChatSearchSource {
	title: string;
	url: string;
}

export interface ConceptChatSearch {
	query: string;
	tool_call_id: string;
	results: string;
	sources: ConceptChatSearchSource[];
}

export interface ConceptChatMessage {
	role: ConceptChatRole;
	content: string;
	search?: ConceptChatSearch;
}

export interface ConceptChatRequest {
	message: string;
	history: ConceptChatMessage[];
	selectedHeadingIds: string[];
}

export interface ConceptChatStreamChunk {
	delta?: string;
	error?: string;
	status?: "searching";
	search?: ConceptChatSearch;
	warning?: string;
}
```

Do not rename `tool_call_id` to camelCase. Do not add a `tool` role. Do not add runtime validators.

- [ ] **Step 4: Run test to verify it passes**

Workdir: `D:\Peter\A2UI\client`

```powershell
npx tsc -b --pretty false
npx vitest run src/types/learning.test.ts
```

Expected:

- `tsc -b` exits 0 (no `TS2305` / `TS2353` on these types)
- Vitest: all tests in `src/types/learning.test.ts` PASS

- [ ] **Step 5: Commit**

```bash
git add client/src/types/learning.ts client/src/types/learning.test.ts
git commit -m "feat(learning): add search fields to concept chat TS types"
```

---

## Verification (after both tasks)

From `D:\Peter\A2UI`:

```powershell
server\.venv\Scripts\python.exe -m unittest server.tests.test_concept_chat_message_schema -v
```

From `D:\Peter\A2UI\client`:

```powershell
npx vitest run src/types/learning.test.ts
npx tsc -b --pretty false
```

All green. No formatter, tool loop, ChatPanel, chatApi, or router changes in the diff.

---

## Spec coverage

| Locked requirement | Task |
|--------------------|------|
| Optional nested `search` `{ query, tool_call_id, results, sources: {title, url}[] }` on server + client | Task 1 + Task 2 |
| Keep extra=ignore; do not extra=forbid | Task 1 (`test_extra_is_not_forbid`, extras ignored) |
| Old `{role, content}` still parse | Task 1 `test_missing_search_ok`; Task 2 old JSON parse |
| `content` min_length=1 stays | Task 1 `test_content_min_length_rejected` |
| role stays user\|assistant (no tool role) | Task 1 `test_role_rejects_tool`; Task 2 role assertion |
| Client stream chunk optional `status`, `search`, `warning` beside `delta`/`error` | Task 2 |
| Tests: search accepted; missing OK; extras ignored; invalid search rejected on server | Task 1 |
| File headers with 76 `=` on new files | Both new test files |
| No formatter / tool loop / ChatPanel / chatApi / router | Scope lock |
