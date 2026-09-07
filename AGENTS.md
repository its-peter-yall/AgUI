# A2UI Agent Guide

Orients agentic coding assistants. Follow commands, style rules below; match local patterns.

## Spec-Based Development

**ALL work must reference these specification documents:**

| Document | Purpose |
|----------|---------|
| `docs/ARCHITECTURE.md` | Vision, purpose, target audience, core capabilities, technical architecture |
| `docs/STACK.md` | Technology choices: React 19, FastAPI, OpenRouter, SQLite, Tailwind 4.x |
| `docs/TESTING.md` | TDD workflow, quality gates, testing patterns, definition of done |
| `docs/CONVENTIONS.md` | Coding conventions for TypeScript, Python, and HTML/CSS |
| `docs/STRUCTURE.md` | Directory layout and where to add new code |
| `docs/INTEGRATIONS.md` | External service integrations and configuration |
| `docs/CONCERNS.md` | Known tech debt, security considerations, performance bottlenecks |

**Rule**: Read relevant spec documents before implementing any feature.

## Repo Layout

- `client/`: Vite + React 19 + TypeScript frontend
  - `src/features/learning/`: Adaptive learning feature (primary)
  - `src/features/settings/`: Provider configuration
  - `src/components/`: Shared UI components
  - `src/hooks/`: Custom React hooks
  - `src/lib/`: API clients and utilities
  - `src/providers/`: React context providers
  - `src/types/`: TypeScript type definitions
- `server/`: FastAPI backend with Pydantic v2
  - `.venv/`: Python dependencies
  - `agents/`: AI agent pipeline (Planner, Generator, Quizzer)
  - `database/`: SQLite persistence layer
  - `routers/`: REST API endpoints
  - `schemas/`: Pydantic v2 domain models
  - `services/`: Business logic orchestration
  - `tests/`: Python unit tests
  - `utils/`: Instructor client wrapper
- `conductor/`: Product guidelines and UI/UX standards
- `docs/`: Codebase map (`ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, `CONCERNS.md`) plus feature plans

## Technology Versions

- **React**: 19
- **Tailwind CSS**: 4.x
- **Pydantic**: v2
- **TypeScript**: Strict mode enabled
- **Python**: 3.10+

## Dependencies

### Client
Core: React 19, React-DOM, TypeScript, Vite
Routing: `react-router-dom`
UI/Animation: `framer-motion`, `lucide-react`, `tailwindcss`
Content: `react-markdown`, `@tailwindcss/typography`
State/Query: `@tanstack/react-query`, `axios`
Testing: `vitest`, `@vitest/coverage-v8`, `@testing-library/react`, `jsdom`

### Server
Web Framework: `fastapi`, `uvicorn[standard]`
AI/ML: `openai`, `instructor`, `pydantic`
Database: SQLite (stdlib `sqlite3`, no ORM)
HTTP Client: `httpx`
Utilities: `tenacity` (retry logic), `python-dotenv`, `jsonref`, `watchdog`
Testing: `unittest` (stdlib)

## Build, Lint, and Test

### Client (A2UI/client)
```bash
cd client
npm install          # Install deps
npm run dev          # Dev server (http://localhost:5173)
npm run build        # Build (tsc -b + vite build)
npm run lint         # ESLint
```

### Server (A2UI/server)
```bash
cd server
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
python -m uvicorn server.main:app --reload --port 8000
python -m unittest                    # All tests
python -m unittest server.tests.test_chat.ChatSessionTests.test_invalid_session_id_returns_404  # Single test
```

### Env Configuration
- Backend: `.env` values (see `server/.env.example`)
- Client: `VITE_API_URL` (defaults to `http://localhost:8000`)
- OpenRouter: API key entered via frontend Settings panel (no server-side env needed)

## TypeScript Config Notes
- Strict mode: `strict: true` in `client/tsconfig.app.json`
- Unused locals/params are errors
- Path alias: `@/*` -> `client/src/*`
- `allowImportingTsExtensions` enabled
- Testing: `jsdom` environment via `vitest.setup.ts`

## Application Routes

Uses `react-router-dom` with routes:
- `/chat` - Main chat interface (default)
- `/learn` - Adaptive learning page

## Quick Reference: Code Style

### TypeScript/React (per `docs/CONVENTIONS.md`)
- Use `const` by default; never `var`
- **No default exports** (mandatory - use named exports only)
- Single quotes; explicit semicolons
- Avoid `any`, `as`, non-null assertions
- Optional params (`?`) preferred over `| undefined`
- `T[]` for simple arrays, `Array<T>` for unions
- `UpperCamelCase` for components/types, `CONSTANT_CASE` for constants
- Hooks start with `use`
- Type-only imports: `import type { Foo } from ...`

### Python/FastAPI (per `docs/CONVENTIONS.md`)
- 4-space indentation, **80-character line limit**
- Import grouping: stdlib → third-party → local (`server.*`)
- `snake_case` functions/vars, `PascalCase` classes
- No mutable default args; use `None` + fallback
- Type hints for public APIs; `Optional[T]` for nullable
- Docstrings with summary + Args/Returns/Raises
- F-strings preferred; no bare `except:`
- Pydantic: `Field` constraints, `ConfigDict(from_attributes=True)`
- **main() function pattern** for executable Python files

### HTML/CSS (per `docs/CONVENTIONS.md`)
- 2-space indentation; no tabs
- Lowercase: elements, attributes, selectors, properties
- Class selectors preferred; avoid ID selectors for styling
- Meaningful kebab-case class names
- Shorthand properties; omit units for zero
- Double quotes HTML attributes; single quotes CSS strings
- **Alphabetize CSS declarations within rules**
- Tailwind available; use `cn()` from `client/src/lib/utils.ts`

### Error Handling and Logging
- API routers: try/except → log → `HTTPException` with status codes
- Re-raise `HTTPException` untouched; wrap only unexpected exceptions
- Module-level: `logger = logging.getLogger(__name__)`
- Client API calls through `client/src/lib/api.ts` Axios instance
- Let Axios throw; handle at call sites or via interceptors

### Import Ordering
```ts
import { StrictMode } from 'react'
import type { Session } from '@/types/api'
import { api } from '@/lib/api'
import './index.css'
```
```python
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, status

from server.database.persistence import session_manager
```

## Testing Notes
- **Client**: Vitest + Testing Library (`@testing-library/react`)
  - File naming: `*.test.ts` or `*.test.tsx`
  - Co-located with source files (test in same directory as implementation)
  - Environment: `jsdom` configured in `vitest.setup.ts`
  - Coverage: Requires `@vitest/coverage-v8` package
- **Server**: stdlib `unittest` in `server/tests`
  - File naming: `test_*.py`
  - Located in `server/tests/` directory
- Keep tests small, deterministic; mock external dependencies
- Target: >80% code coverage per `docs/TESTING.md`

## Conventions to Preserve
- API routes in `server/routers`; schemas in `server/schemas`
- `APIRouter` with `summary`/`description` metadata
- Pydantic response models in router decorators are the contract
- Client uses React Query provider in `client/src/providers/QueryProvider.tsx`
- Axios base URL tied to `VITE_API_URL` fallback

## Server Directory Structure

### Routers (`server/routers/`)
- REST API endpoints with FastAPI `APIRouter`
- `learning.py`: Learning endpoints (generate, sessions, nodes, quizzes, revisions)
- `llm.py`: Model catalog proxy endpoint

### Schemas (`server/schemas/`)
- Pydantic v2 models for request/response validation
- `common.py`: Base classes (ResponseBase, TimestampMixin)
- `learning.py`: Learning domain models (NodeStatus, QuizCard, QuizSet, CourseOutline)
- `llm.py`: LLMContext, ModelResponse, AIProviderEnum

### Services (`server/services/`)
- Supporting business services that are not the course-generation runtime
- `quiz_randomization.py`: Deterministic quiz/option shuffling with seeds
- `concept_chat.py`: Streaming concept-specific chat support

### Graph (`server/graph/`)
- Permanent LangGraph course generation runtime
- `state.py`: CourseState and runtime context TypedDict contracts
- `nodes.py`: Planner, topic worker, fan-out, and response assembly nodes
- `build.py`: Graph factory, checkpoint path, and cached graph accessor
- `regen.py`: Regenerate Failed Node — standalone function to regenerate failed concept nodes without invoking full LangGraph course graph

### Utils (`server/utils/`)
- Shared utility modules
- `instructor_client.py`: Instructor library integration for structured LLM output

### Database (`server/database/`)
- Persistence layer (SQLite via sqlite3, no ORM)
- `persistence.py`: DB_PATH configuration
- `learning_persistence.py`: LearningManager with all CRUD operations

## Data Model Notes
- Timestamps: ISO strings in API responses
- Session list endpoints: support `limit` and `offset`
- `get_session_messages`: optional `limit` (None = full history)
- Database tables: `learning_sessions`, `concept_nodes`, `quiz_data`, `revision_sessions`, `quiz_attempts`, `revision_node_progress`

## Learning Feature Architecture

### Client Components
- **LearningPage**: Main learning interface route
- **LearningPathContainer**: Displays learning path tree structure
- **ConceptCard**: Individual concept node visualization
- **QuizModal**: Interactive quiz interface

### Server Components
- **Course Graph**: LangGraph state machine coordinating learning flow
- **PlannerAgent**: Generates learning roadmaps
- **GeneratorAgent**: Creates educational content
- **QuizzerAgent**: Generates and evaluates quizzes
- **LearningManager**: Persists sessions, nodes, quizzes, and revision state
- **Regenerate Failed Node**: Standalone function to regenerate failed concept nodes without invoking full LangGraph course graph

### Database Tables
- `concept_nodes`: Learning concept hierarchy
- `quiz_data`: Quiz questions and user answers
- `learning_sessions`: Learning session state tracking

### API Endpoints
- `POST /learning/generate` - Generate new learning content
- `GET /learning/sessions/{id}` - Get learning session details
- `PUT /learning/sessions/{id}/progress` - Update progress
- `GET /learning/sessions/{id}/next` - Get next content item

## AGENT BEHAVIOUR (Spec-Driven)

### Research-First Principle (per `docs/CONVENTIONS.md`)
- **ALWAYS web-search before implementing** unfamiliar libraries, APIs, or patterns
- **NEVER assume** library behavior — verify with official documentation
- **Search first** when encountering: new npm packages, Python libraries, framework features
- Use `librarian` agent for docs, `explore` agent for codebase patterns

### SWE Best Practices (per `docs/TESTING.md`)
- **Write tests BEFORE or WITH code**, not after — TDD required
- **Verify with diagnostics**: Run diagnostics before marking tasks complete
- **Build & test**: Run build/test commands after implementation
- **Type safety first**: Never suppress errors with `as any`, `@ts-ignore`
- **Error handling**: Never leave empty catch blocks `catch(e) {}`
- **Minimal changes**: Fix bugs without refactoring unrelated code
- **Running python files**: Use .venv in root of server directory, run with `python -m` for correct imports and environment

### Task Workflow (per `docs/TESTING.md`)
1. **Read specs**: Check `docs/ARCHITECTURE.md`, `docs/STACK.md`, `docs/CONVENTIONS.md`
2. **Select task**: Choose next task from roadmap in `.planning/`
3. **Mark in progress**: Update task status in `.planning/` roadmap
4. **Red phase**: Write failing tests first (verify they fail!)
5. **Green phase**: Implement to pass tests
6. **Refactor**: Improve clarity with passing tests as safety net
7. **Verify coverage**: >80% for new code
8. **Document deviations**: If implementation differs from stack, STOP and update `docs/STACK.md`
9. **Commit**: Clear message per `docs/TESTING.md` commit format

### Phase Checkpointing Protocol
When working on multi-phase tasks:
- **Stop at phase boundaries** to verify completeness
- **Document progress** in git notes: `git notes add -m "Phase X complete: ..."`
- **Review checkpoints** before starting next phase
- **Flag blockers** immediately if phase cannot complete

### Git Notes Workflow
Use git notes to track task summaries:
```bash
# Add note after completing significant work
git notes add -m "Implemented feature X with Y approach"

# Show notes in log
git log --show-notes

# Notes persist with commits and provide audit trail
```

### Use Sub-Agents to Extend Sessions
- Use suitable sub-agents to conserve context window
- Launch sub-agents for: long-running tasks, multi-file changes, complex exploration
- Benefits: Fresh context per subtask, parallel execution, domain focus

### File Header Requirements
**MANDATORY** for `.ts`, `.tsx`, `.py`, `.pyi`, `.js`, `.jsx`:

**TypeScript/JavaScript:**
```typescript
/**
 * ============================================================================
 * FILE: <filename>
 * LOCATION: <filepath>
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
 *    - Component2: What it does
 * ============================================================================
 */
```

**Python:**
```python
"""
============================================================================
FILE: <filename>
LOCATION: <filepath>
============================================================================
PURPOSE:
    Brief description of what this file does (1-2 sentences)
ROLE IN PROJECT:
    How this file fits into the larger system (2-3 lines)
    - Key responsibility 1
    - Key responsibility 2
KEY COMPONENTS:
    - Component1: What it does
    - Component2: What it does
============================================================================
"""
```

**Enforcement:**
- New files: ALWAYS add header before first write
- Existing files: Add header when modifying >30%
- Config files: Optional but encouraged
- Separator line: Exactly 76 `=` characters

## Product Context

### Product Nature
- **Pure Chat Application**: Direct LLM interaction without RAG or Graph DB
- **Target Audience**: Researchers, students, professionals seeking AI assistance
- **Tone**: Academic/professional communication

### Visual Identity (per `conductor/product-guidelines.md`)
- **Cyber Yellow (`#ffb74d`)**: Primary actions, accents, brand
- **Dark Backgrounds**: Deep grays/blacks for reduced eye strain
- **Typography**: Inter (UI), JetBrains Mono (code). Scoped override: Lexend (text) & Fira Code (code) exclusively for topic cards and chat messages.
- **Glassmorphism**: Light usage for cards/panels
- **Rounded Corners**: 8px-12px consistently

### UX Principles (per `conductor/product-guidelines.md`)
- **Minimalism**: Remove UI elements not contributing to chat/session management
- **Persistence**: Instant session switching, preserved draft content
- **Clarity**: Distinct visual cues for model states (thinking, generating, error)
- **Responsiveness**: Sidebar toggle on smaller viewports

### UX Requirements
- **Thinking Mode Visualization**: Show when model is processing/reasoning
- **Draft Content Preservation**: Maintain unsent message drafts across session switches
- **Academic Tone**: Professional, clear communication style

### Component Standards (per `conductor/product-guidelines.md`)
- **Message Bubbles**: User (distinct bg, right-aligned), AI (subtle bg, left-aligned, Markdown)
- **Input Area**: Auto-expanding textarea, Cyber Yellow send button, model toggles
- **Session Sidebar**: Clean list with active indicators, "New Session" button, rename/delete menus

## References
- `docs/ARCHITECTURE.md` - Product vision and architecture
- `conductor/product-guidelines.md` - UI/UX standards
- `docs/STACK.md` - Technology specifications
- `docs/TESTING.md` - Development workflow and quality gates
- `docs/CONVENTIONS.md` - Coding conventions for all languages
- `docs/STRUCTURE.md` - Directory layout
- `docs/INTEGRATIONS.md` - External service integrations
- `docs/CONCERNS.md` - Known issues and tech debt