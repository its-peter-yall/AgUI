# Coding Conventions

**Analysis Date:** 2026-09-05

Conventions below come from real source under `client/` and `server/`, plus
`client/eslint.config.js`, `client/tsconfig.app.json`, and `client/vite.config.ts`.
No Prettier, Biome, EditorConfig, Ruff, Black, isort, flake8, or mypy config
exists in this repo.

---

## File Headers

Every `.ts`, `.tsx`, `.js`, `.jsx`, and `.py` file starts with a boxed header
(separator of 76 `=` characters). New files must include it before first write.
Existing files get a header when more than ~30% of the file changes.

**TypeScript / JavaScript** (`client/src/lib/utils.ts`):

```typescript
/**
 * ============================================================================
 * FILE: utils.ts
 * LOCATION: client/src/lib/utils.ts
 * ============================================================================
 *
 * PURPOSE:
 *    Brief 1-line description of what this file does
 *
 * ROLE IN PROJECT:
 *    How this file fits into the larger system (2-3 lines)
 *
 * KEY COMPONENTS:
 *    - Component1: What it does
 *
 * DEPENDENCIES:
 *    - External: List external libraries
 *    - Internal: List internal modules
 *
 * USAGE:
 *    Example snippet or how to use
 * ============================================================================
 */
```

**Python** (`server/schemas/common.py`):

```python
"""
============================================================================
FILE: common.py
LOCATION: server/schemas/common.py
============================================================================
PURPOSE:
    Brief description of what this file does (1-2 sentences)
ROLE IN PROJECT:
    How this file fits into the larger system (2-3 lines)
KEY COMPONENTS:
    - Component1: What it does
DEPENDENCIES:
    - External: List external libraries used
    - Internal: List internal modules imported
USAGE:
    Brief usage example or how to run/test
============================================================================
"""
```

Config files (`client/eslint.config.js`, `client/vite.config.ts`) use the same
header style. Env files (`.env`, `.env.*`) are secrets — never quote them;
`server/.env.example` exists as the documented template.

---

## Naming Patterns

### TypeScript / React (`client/src/`)

**Files:**
- React components: `PascalCase.tsx` — `ConceptCard.tsx`, `SettingsButton.tsx`, `QueryProvider.tsx`
- Hooks: `use` prefix, camelCase — `useTheme.ts`, `useSessionEvents.ts`, `useTypewriter.ts`
- Lib / API / utils: camelCase — `learningApi.ts`, `agentModelHeaders.ts`, `webSearchHeaders.ts`
- Types: camelCase matching domain — `learning.ts`, `generation.ts`, `provider.ts`
- Tests: co-located `*.test.ts` / `*.test.tsx` next to source
- Feature barrel: `index.ts` inside the feature folder

**Functions:**
- Named function exports for components and hooks: `export function SettingsButton()`, `export function useTheme()`
- camelCase for functions and callbacks: `buildAgentModelHeaders`, `handleClick`, `handleDownloadPdf`
- Event handlers: `handle` + verb — `handleClick`, `handleRetry`, `handleDownloadPdf`

**Variables:**
- `const` by default; never `var`
- camelCase locals: `queryClient`, `baseURL`, `webSearchEnabled`
- Boolean prefixes: `isRotating`, `isUnlocked`, `isExportingPdf`
- Module-level axios instances: short `api` or `queryClient`

**Types:**
- `UpperCamelCase` interfaces and type aliases: `ConceptNode`, `GenerationEvent`, `AIProviderSettings`
- String-literal unions for enums that mirror Python: `NodeStatus`, `LearningDepthMode`
- `CONSTANT_CASE` / `as const` objects: `TIMING`, `AGENT_ROLES`, `ROLE_HEADER_PREFIX`, `SEARCH_HEADER_NAMES`
- Props interfaces: `ComponentNameProps` — `LearningErrorBoundaryProps`, `CourseCardProps`

**Components:**
- PascalCase export matching filename
- Hooks start with `use`
- Context objects: `ThemeProviderContext`

### Python (`server/`)

**Files:**
- `snake_case.py` — `instructor_client.py`, `learning_persistence.py`, `generation_runtime.py`
- Tests: `server/tests/test_<area>.py`
- Packages: `routers/`, `schemas/`, `services/`, `database/`, `graph/`, `agents/`, `utils/`

**Functions:**
- `snake_case`: `generate_course`, `create_structured`, `log_external_failure`
- Private helpers: leading underscore — `_apply_node_visibility`, `_require_local`, `_status`
- FastAPI handlers: verb + resource — `list_models`, `connect_storage`

**Variables:**
- `snake_case`: `session_id`, `llm_context`, `search_context`
- Module logger: `logger = logging.getLogger(__name__)`
- Settings singleton: `settings`
- `CONSTANT_CASE` module constants: `CONTENT_VISIBLE_STATES`, `MAX_COURSE_TOPICS`, `MODE_TOPIC_BOUNDS`

**Types:**
- `PascalCase` classes and Pydantic models: `NodeStatus`, `QuizCard`, `LLMContext`, `TimestampMixin`
- `str, Enum` for domain enums: `NodeStatus.LOCKED = "LOCKED"`
- TypeVars: single capital — `T = TypeVar("T", bound=BaseModel)`

---

## Code Style

### TypeScript

**Formatting:**
- Tool used: Not detected (no Prettier / Biome / EditorConfig)
- Indent: 2 spaces in most files; some files use tabs (`client/src/types/learning.ts`, parts of `ConceptCard.test.tsx`)
- Quotes: mixed. Prefer single quotes in newer lib/test files (`learningApi.ts`, `utils.ts`); `App.tsx` and some hooks use double quotes. ESLint does not enforce quotes
- Semicolons: required in practice — source files terminate statements with `;`
- JSX: double-quoted HTML attributes when the surrounding file uses single-quoted JS strings (`className="h-5 w-5"`)

**Linting:**
- Tool: ESLint 9 flat config — `client/eslint.config.js`
- Extends: `@eslint/js` recommended, `typescript-eslint` recommended, `eslint-plugin-react-hooks` flat recommended, `eslint-plugin-react-refresh` Vite config
- Files: `**/*.{ts,tsx}` only; `dist/` globally ignored
- Key rule: `react-refresh/only-export-components` is `error`, with `allowExportNames: ['useErrorToast']` so `useErrorToast` may share a module with a component
- Command: `cd client && npm run lint` (`eslint .`)

**TypeScript compiler (`client/tsconfig.app.json`):**
- `strict: true`
- `noUnusedLocals: true`, `noUnusedParameters: true`
- `noFallthroughCasesInSwitch: true`
- `verbatimModuleSyntax: true` — type-only imports required
- `allowImportingTsExtensions: true`, `moduleResolution: "bundler"`, `noEmit: true`
- `jsx: "react-jsx"`, `target: "ES2022"`
- `erasableSyntaxOnly: true`
- Path alias: `"@/*": ["./src/*"]`

**Type safety:**
- Avoid `any`. No `as any` in `client/src`
- `as` assertions appear for test fixtures and EventSource doubles (`as LearningSessionWithNodes`, `as unknown as typeof EventSource`) — keep them in tests, not production
- Prefer `?` optional properties over `| undefined` on props
- `T[]` for simple arrays; `Array<T>` when the element is a union
- `import type { Foo }` for types (enforced by `verbatimModuleSyntax`)

### Python

**Formatting:**
- Tool used: Not detected (no Ruff, Black, isort, flake8, mypy)
- Indent: 4 spaces
- Quotes: double quotes dominate in schemas, routers, and tests
- Line wrapping: many signatures and call sites wrap near 80 columns; some import lines exceed 80. Wrap long `Field(...)`, `HTTPException(...)`, and function signatures with hanging indent
- `from __future__ import annotations` at the top of new modules (schemas, tests, routers)

**Typing:**
- Public functions take and return annotated types
- Nullable public fields: `Optional[T]` in schemas/utils (`server/schemas/common.py`, `server/utils/instructor_client.py`)
- Newer tests and some graph/search code use `T | None` and built-in generics (`list[str] | None`)
- No mutable default arguments: use `None` + fallback, or Pydantic/`dataclass` `default_factory=list`

**Pydantic v2 (`server/schemas/`):**
- `model_config = ConfigDict(from_attributes=True)` on response models
- `Field(..., description="...")` with constraints (`min_length`, `max_length`, `ge`, `pattern`)
- Domain enums: `class NodeStatus(str, Enum)`
- Validators: `@field_validator("field")` + `@classmethod`
- Mixins: `ResponseBase`, `TimestampMixin` in `server/schemas/common.py`

```python
class TimestampMixin(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Timestamp when the record was created",
    )
    updated_at: Optional[datetime] = Field(
        default=None, description="Timestamp when the record was last updated"
    )
```

**FastAPI routers (`server/routers/`):**
- `APIRouter(prefix="...", tags=[...])`
- Decorators include `response_model`, `summary`, and `description`
- Request/response models live in `server/schemas/` or as small router-local Pydantic classes
- Status codes via `fastapi.status` (`HTTP_202_ACCEPTED`, `HTTP_503_SERVICE_UNAVAILABLE`)

**Docstrings:**
- Module header plus Google-style `Args:` / `Returns:` / `Raises:` on public functions (`create_structured` in `server/utils/instructor_client.py`)

### HTML / CSS

**Formatting:**
- Tailwind CSS 4.x via `@tailwindcss/vite` and `client/src/index.css` (`@import "tailwindcss"`)
- Compose classes with `cn()` from `client/src/lib/utils.ts` (`clsx` + `tailwind-merge`)
- No CSS modules detected; global tokens live in `@theme` in `client/src/index.css`
- Class selectors / utility classes; do not introduce ID selectors for styling
- Meaningful Tailwind utilities; Cyber Yellow accent `#ffb74d` for primary actions
- JSX attributes: double quotes; CSS custom-property strings in `@theme` use double quotes
- 2-space indent in `client/src/index.css`

```tsx
import { cn } from '@/lib/utils';

<button
  className={cn(
    'inline-flex items-center justify-center rounded-md p-2 text-sm font-medium transition-colors',
    'hover:bg-accent/50 text-muted-foreground hover:text-[#ffb74d]',
  )}
/>
```

---

## Import Organization

### TypeScript

**Order:**
1. External packages (`react`, `axios`, `vitest`, `@tanstack/react-query`)
2. `import type { ... }` from external or `@/` (may sit with the value import from the same module)
3. Internal alias imports (`@/lib/...`, `@/types/...`, `@/features/...`)
4. Relative imports (`./providerSettings`, `./ConceptCard`)
5. Side-effect CSS last when present (`./index.css`)

`verbatimModuleSyntax` requires splitting types:

```typescript
import axios from 'axios';
import { getProviderSettings, getWebSearchSettings } from './providerSettings';
import { buildAgentModelHeaders } from './agentModelHeaders';
import type {
  ConceptNode,
  GenerateCourseRequest,
  LearningSessionWithNodes,
} from '../types/learning';
import type { ResearchReport } from '../types/generation';
```

**Path Aliases:**
- `@/*` → `client/src/*` (`client/tsconfig.app.json` + `client/vite.config.ts` `resolve.alias`)
- Use `@/features/learning`, `@/lib/utils`, `@/types/learning` from feature and app code
- Same-folder tests may use relative `./ConceptCard` or alias `@/lib/learningApi`

### Python

**Order:**
1. Future: `from __future__ import annotations`
2. Stdlib (`asyncio`, `logging`, `os`, `typing`)
3. Third-party (`fastapi`, `pydantic`, `instructor`, `openai`)
4. Local `server.*` (`server.config`, `server.schemas.learning`, `server.database...`)

Blank line between groups:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Type, TypeVar, cast

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

from server.config import settings
from server.schemas.llm import AIProviderEnum
```

---

## Error Handling

### TypeScript

**Patterns:**
- Axios instances attach a response interceptor that `console.error`s then `Promise.reject(error)` — do not swallow HTTP failures (`client/src/lib/learningApi.ts`)
- Let Axios throw; handle at call sites (React Query mutations, UI catch + `console.error`)
- Typed catch: `catch (err: unknown)` then narrow (`instanceof`, axios helpers)
- Re-throw domain errors unchanged (`WebSearchConfigurationError` in `client/src/lib/chatApi.ts`)
- User-facing recovery: `LearningErrorBoundary` logs `console.error` and renders retry/home UI
- Hook guard: throw if used outside provider (`useTheme` throws `'useTheme must be used within a ThemeProvider'`)
- Never empty `catch (e) {}`

```typescript
api.interceptors.response.use(
  (response) => response,
  (error) => {
    console.error(
      'API Request Failed:',
      error.config?.url,
      error.response?.data || error.message,
    );
    return Promise.reject(error);
  },
);
```

```typescript
} catch (err) {
  if (err instanceof WebSearchConfigurationError) {
    throw err;
  }
  throw err;
}
```

### Python

**Patterns:**
- Routers: `try` / `except HTTPException: raise` / `except Exception:` → log → `HTTPException` with a generic detail (no secret leakage)
- Map domain errors to HTTP status (`MongoConfigurationError` → 400, `MongoUnavailableError` → 503) and chain with `from exc`
- Use `status.HTTP_*` constants, not raw integers
- External failures that may contain secrets: `log_external_failure` in `server/utils/safe_logging.py` (type name only, no traceback/message)
- No bare `except:`

```python
    try:
        accepted = await runtime.start(...)
        return JSONResponse(
            content=accepted,
            status_code=status.HTTP_202_ACCEPTED,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error accepting course generation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )
```

```python
    except MongoConfigurationError as exc:
        logger.error(
            "Mongo operation failed operation=%s error=%s",
            "connect",
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MongoDB connection is invalid or unauthorized",
        ) from exc
```

---

## Logging

**Framework:**
- Server: stdlib `logging`
- Client: `console` (`console.error` in API interceptors, PDF export, error boundary)

**Patterns:**
- Module logger: `logger = logging.getLogger(__name__)`
- Levels: `debug` for init, `info` for successful structured calls, `warning` for recoverable validation, `error` / `exception` for failures
- Prefer `%s` interpolation (`logger.error("... %s", session_id)`); some older paths still use f-strings
- Unexpected router failures: `logger.exception("...")` so the traceback stays in logs
- Never log API keys, search keys, or exception text from external providers on generation failure paths — use `log_external_failure(logger, event=..., session_id=..., error=exc)`
- Client: log URL + response data/message on Axios failure; log error + component stack in `LearningErrorBoundary.componentDidCatch`

```python
def log_external_failure(
    logger: logging.Logger,
    *,
    event: str,
    session_id: str,
    error: BaseException,
) -> None:
    """Log safe external-failure metadata without message or traceback."""
    logger.error(
        "%s session_id=%s error_type=%s",
        event,
        session_id,
        type(error).__name__,
    )
```

---

## Comments

**When to Comment:**
- File header is mandatory (see File Headers)
- Section banners for animation/timing blocks (`// ============================================================`)
- Explain *why*, not what — e.g. `// Complete the rotation animation before navigating`, `// JSONResponse preserves store ISO timestamps`
- FastAPI `summary` / `description` and Pydantic `Field(description=...)` are the API contract comments

**JSDoc/TSDoc:**
- File-level block comment is the primary doc
- Extra JSDoc on non-obvious exported helpers (`buildAgentModelHeaders`, `getVariants`, carousel variants)
- Python: class docstring for enums (state flow), function docstring with Args/Returns on public APIs

Do not comment every line. Do not omit the file header.

---

## Function Design

**Size:** Keep handlers and helpers focused. Fat modules (`server/routers/learning.py`) still split helpers (`_apply_node_visibility`) from route functions. Client API modules export one function per endpoint.

**Parameters:**
- TypeScript: typed params; optional with `?` or `= {}` defaults (`GenerateCourseOptions = {}`); avoid `| undefined` on props when `?` suffices
- Python: type hints on public APIs; `Optional[T] = None`; keyword-only where it prevents positional mistakes (`log_external_failure(..., *, event=...)`)
- No mutable default args in Python

**Return Values:**
- TypeScript public API: explicit `Promise<T>` (`generateCourse` → `Promise<GenerateCourseAcceptedResponse>`)
- Python public API: annotated returns (`-> T`, `-> JSONResponse`, `-> bool`)
- FastAPI: Pydantic `response_model` on the decorator is the HTTP contract
- Hooks: return a small object or tuple (`{ theme, setTheme }`, Query result)

**Async:**
- Server I/O is `async def` with `await`
- Client API wrappers are `async` functions returning `response.data`
- Streaming: `fetch` + ReadableStream on the client; `StreamingResponse` on the server

---

## Module Design

**Exports:**
- TypeScript: named exports for components, hooks, utilities, and types
- Exception: `client/src/App.tsx` uses `export default App` (Vite app root). Third-party `.d.ts` may re-export a library default (`html2pdf`)
- Do not default-export feature components — `export function ConceptCard`, `export const QueryProvider`
- Python: import from `server.<package>.<module>`; packages re-export via `__all__`

**Barrel Files:**
- Feature public API: `client/src/features/learning/index.ts` re-exports components, hooks, types
- Animations: `client/src/features/learning/animations/index.ts` (variants + component re-exports)
- Routers: `server/routers/__init__.py` exposes `learning_router`, `llm_router`, `storage_router` via `__all__`
- Prefer importing pages from the barrel (`import { LearningPage } from '@/features/learning'`) unless a deep import is required (`RevisionPage`)

```typescript
// client/src/features/learning/index.ts
export { LearningPage } from './LearningPage';
export { useSessionEvents } from './useSessionEvents';
export type { ConceptNode, NodeStatus } from '@/types/learning';
```

```python
# server/routers/__init__.py
from server.routers.learning import router as learning_router
from server.routers.llm import router as llm_router
from server.routers.storage import router as storage_router

__all__ = ["learning_router", "llm_router", "storage_router"]
```

**Placement:**
- API routes → `server/routers/`
- Pydantic contracts → `server/schemas/`
- Business orchestration → `server/services/`
- Persistence → `server/database/`
- LangGraph runtime → `server/graph/`
- Client HTTP → `client/src/lib/*Api.ts`
- Shared UI → `client/src/components/`
- Feature UI → `client/src/features/<feature>/`

---

*Convention analysis: 2026-09-05*
