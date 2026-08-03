# A2UI - Agent to User Interface (UI)

A modern adaptive learning platform that transforms user-submitted topics into structured, AI-generated courses with mastery-based progression. Built with React 19, FastAPI, and OpenRouter for universal LLM access.

## What This Is

A2UI implements **retrieval-based learning** - a pedagogical approach where active recall through testing strengthens learning more effectively than passive review. Users submit a topic, receive AI-generated sequential learning paths with explanations and quizzes, and must pass assessments to unlock subsequent content.

## Core Features

### Adaptive Learning System
- **Multi-Agent AI Pipeline**: Planner, Generator, and Quizzer agents orchestrated via Scatter-Gather pattern
- **Sequential Learning Paths**: Topics decomposed into ordered concept nodes with narrative coherence
- **Mastery-Based Progression**: Server-enforced state machine (LOCKED → VIEWING_EXPLANATION → IN_QUIZ → COMPLETED)
- **Dynamic Quiz Generation**: 1-5 quizzes per topic based on complexity with difficulty gradients (Recall → Application → Synthesis)
- **Course Persistence**: SQLite-backed storage with progress tracking and session resumption
- **Revision Sessions**: Full review and quiz-only modes with performance comparison

### User Experience
- **Framer Motion Animations**: Gamified unlock experiences and smooth transitions
- **Dark Theme**: Optimized for long study sessions with Cyber Yellow accents
- **Responsive Design**: Mobile-friendly with collapsible navigation
- **Real-time Generation**: Skeleton loaders provide <15s perceived latency

### Chat Foundation
- **Session Management**: Create, list, rename, pin, and delete chat sessions
- **Persistent History**: All messages stored in SQLite database
- **Markdown Rendering**: Full markdown support with syntax highlighting
- **Thinking Mode**: Display model's reasoning process when available

## Tech Stack

### Frontend
| Technology | Purpose |
|------------|---------|
| React 19 | UI framework with latest features |
| TypeScript 5.9 | Type safety with strict mode |
| Vite 7 | Build tool & dev server |
| Tailwind CSS 4.x | Utility-first styling |
| TanStack Query 5 | Server state management & caching |
| Framer Motion | Animation library |
| React Markdown | Markdown rendering |

### Backend
| Technology | Purpose |
|------------|---------|
| FastAPI | Web framework with automatic docs |
| Python 3.10+ | Server language |
| Pydantic v2 | Data validation & serialization |
| SQLite | Data persistence |
| OpenRouter | Universal LLM gateway (300+ models) |
| Instructor | Structured LLM output validation |
| OpenAI SDK | OpenRouter-compatible HTTP client |
| Tenacity | Retry logic with exponential backoff |

### AI/ML Architecture
- **Planner Agent** (LLM via OpenRouter/General-Compute): Decomposes topics into structured course outlines
- **Generator Agent** (LLM via OpenRouter/General-Compute): Creates educational content using 5E model
- **Quizzer Agent** (LLM via OpenRouter/General-Compute): Generates assessments with plausible distractors
- **Scatter-Gather Pattern**: Parallel generation with partial failure handling
- **Model Flexibility**: Swap to Claude, GPT-4o, DeepSeek, or 300+ other models via OpenRouter

## Project Structure

```
A2UI/
├── client/                      # Frontend (React + TypeScript)
│   ├── src/
│   │   ├── main.tsx            # Entry point
│   │   ├── App.tsx             # Root component with routes
│   │   ├── components/         # Shared UI components
│   │   ├── features/
│   │   │   ├── learning/      # Learning feature (primary)
│   │   │   └── settings/      # Provider configuration
│   │   ├── hooks/              # Custom React hooks
│   │   ├── lib/                # API clients and utilities
│   │   ├── providers/          # React context providers
│   │   └── types/              # TypeScript definitions
│   └── package.json
│
├── server/                      # Backend (FastAPI + Python)
│   ├── main.py                 # FastAPI app entry point
│   ├── config.py               # Environment configuration
│   ├── routers/
│   │   ├── learning.py        # Learning API routes
│   │   └── llm.py             # Model catalog proxy
│   ├── schemas/                # Pydantic v2 models
│   │   ├── common.py          # Base classes
│   │   ├── learning.py        # Learning domain models
│   │   └── llm.py             # LLM context models
│   ├── graph/                  # LangGraph course generation
│   │   ├── state.py            # CourseState TypedDict schema
│   │   ├── nodes.py            # planner_node, topic_worker, etc.
│   │   ├── build.py            # Graph compile + caching
│   │   └── regen.py            # Single-node regen
│   ├── services/               # Business logic
│   │   ├── quiz_randomization.py   # Quiz shuffling
│   │   └── concept_chat.py         # Concept chat support
│   ├── agents/                 # AI agent implementations
│   │   ├── base.py            # Abstract base agent
│   │   ├── planner.py         # KLI curriculum decomposition
│   │   ├── generator.py       # 5E content generation
│   │   └── quizzer.py         # Retrieval-based quizzes
│   ├── database/               # SQLite persistence layer
│   │   ├── persistence.py     # DB_PATH config
│   │   └── learning_persistence.py  # All CRUD operations
│   ├── utils/                  # Shared utilities
│   │   └── instructor_client.py  # Instructor integration
│
|   setup.bat                    # installs python and node dependencies
└── run.bat                      # Windows startup script
```

## Installation

### Prerequisites
- **Node.js 18+** (for frontend)
- **Python 3.10+** (for backend)
- **OpenRouter API key** (free tier available at https://openrouter.ai)

### 1. Clone the Repository
```bash
git clone <repository-url>
cd A2UI
```

### 2. Run Setup (Windows)
```bash
setup.bat
```

This creates the Python virtual environment, installs all dependencies, and verifies prerequisites.

### 3. Manual Setup (macOS/Linux)

**Backend:**
```bash
cd server
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Frontend:**
```bash
cd client
npm install
```

### 4. OpenRouter Setup

1. Create a free account at [openrouter.ai](https://openrouter.ai) or [generalcompute.com](https://generalcompute.com)
2. Generate an API key from your dashboard
3. When you first launch the app, paste your key into the **Settings** panel in the UI
4. Pick a model 

No backend `.env` configuration is needed. The server receives your key per-request via the `X-OpenRouter-Key` header.

#### Frontend Environment (Optional)

Create `client/.env`:

```env
VITE_API_URL=http://localhost:8000
```

### Optional MongoDB Atlas Storage

Optional cloud persistence is documented in
[`docs/mongodb-atlas-storage/operations.md`](docs/mongodb-atlas-storage/operations.md).
Local SQLite remains default.

## Running the Application

### First Time?
Run `setup.bat` (Windows) or follow the manual setup steps above.

### Option 1: Using the Batch Script (Windows)

```bash
# From project root
run.bat
```

This starts both the backend and frontend servers.

### Option 2: Manual Start

**Terminal 1 - Start Backend:**

```bash
cd server
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # macOS/Linux

python -m uvicorn server.main:app --reload --port 8000
```

**Terminal 2 - Start Frontend:**

```bash
cd client
npm run dev
```

### Access Points

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8000 |
| API Documentation | http://localhost:8000/docs |
| Health Check | http://localhost:8000/health |

## Application Routes

### Frontend Routes
- `/` or `/chat` - Main chat interface
- `/learn` - Learning dashboard with course list
- `/learn/:sessionId` - Active learning session
- `/learn/:sessionId/revise/:revisionId` - Revision session
- `/settings` - Provider configuration

### Optional Internet Grounding

Progressive course generation can optionally research current sources before outlining.

- Master capability **defaults OFF**; each new course opt-in also **defaults OFF**.
- Provider registry: **Tavily**, **Exa**, **Brave Search**, **SerpAPI** (configure keys in Settings; verify current provider terms).
- Keys remain in browser localStorage at rest and are sent only on generate/resume requests that need them.
- `POST /learning/generate` returns **202** immediately; UI then uses credential-free SSE plus two-second polling repair.
- Progress stream: GET /learning/sessions/{id}/events (credential-free).
- Resume unfinished work: POST /learning/sessions/{id}/resume (fresh keys when research unfinished).
- Research degradation continues useful generation but never shows a grounded label.
- Operator runbook: `docs/internet-grounded-course-generation/operations.md`.

### API Endpoints (Learning System)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/learning/generate` | Accept course job (**202** shell); progressive generation |
| `GET` | `/learning/sessions` | List learning sessions (paginated) |
| `GET` | `/learning/sessions/{id}` | Pollable session snapshot with generation stage |
| `GET` | `/learning/sessions/{id}/events` | Replayable SSE progress stream |
| `GET` | `/learning/sessions/{id}/research` | Public research report and sources |
| `POST` | `/learning/sessions/{id}/cancel` | Cooperative cancel; retain artifacts |
| `POST` | `/learning/sessions/{id}/resume` | Resume paused/cancelled job with fresh keys |
| `GET` | `/learning/sessions/{id}/progress` | Get progress summary |
| `PATCH` | `/learning/sessions/{id}/last-active` | Update last active node |
| `DELETE` | `/learning/sessions/{id}` | Permanent cleanup (stop work + cascade delete) |
| `GET` | `/learning/nodes/{id}` | Get concept node with visibility |
| `POST` | `/learning/nodes/{id}/transition` | Transition node state |
| `POST` | `/learning/nodes/{id}/submit-quiz` | Submit quiz answer |
| `POST` | `/learning/nodes/{id}/retry-quiz` | Retry failed quiz |
| `POST` | `/learning/nodes/{id}/previous-quiz` | Go to previous quiz |
| `POST` | `/learning/nodes/{id}/regenerate` | Regenerate failed content |
| `GET` | `/learning/nodes/{id}/attempts` | Get quiz attempt history |
| `POST` | `/learning/sessions/{id}/revisions` | Create revision session |
| `GET` | `/learning/sessions/{id}/revisions` | List revision sessions |
| `GET` | `/learning/revisions/{id}` | Get revision with progress |
| `DELETE` | `/learning/revisions/{id}` | Delete revision session |
| `POST` | `/learning/revisions/{id}/nodes/{nodeId}/mark-reviewed` | Mark node reviewed |
| `POST` | `/learning/revisions/{id}/nodes/{nodeId}/submit-quiz` | Submit revision quiz |
| `GET` | `/learning/revisions/{id}/summary` | Get revision metrics |
| `GET` | `/llm/models` | List available AI models |

## Development

### Frontend Commands

```bash
cd client

npm run dev          # Start development server
npm run build        # Build for production
npm run lint         # Run ESLint
npm run test         # Run tests (watch mode)
npm run test -- --run  # Run tests once
npm run test:generation:coverage  # Focused >80% generation module coverage
```

### Backend Commands

```bash
cd server

# Start development server
python -m uvicorn server.main:app --reload --port 8000

# Run all tests
python -m unittest

# Run specific test module
python -m unittest server.tests.test_learning
```

## Testing

### Frontend Testing
Tests use Vitest and React Testing Library:

```bash
cd client

# Run all tests
npm run test

# Run specific test file
npm run test -- src/lib/api.test.ts

# Run tests matching pattern
npm run test -- -t "LearningPage"
```

### Backend Testing
Tests use Python's unittest framework:

```bash
cd server

# Run all tests
python -m unittest

# Run specific module
python -m unittest server.tests.test_orchestrator

# Run specific test
python -m unittest server.tests.test_learning.TestLearningSessions.test_create_session
```

## Design System

### Colors
| Name | Value | Usage |
|------|-------|-------|
| Primary (Cyber Yellow) | `#ffb74d` | Accent, buttons, highlights |
| Background | `hsl(240, 10%, 3.9%)` | Main background |
| Foreground | `hsl(0, 0%, 98%)` | Text |

### Typography
| Type | Font |
|------|------|
| Primary | Inter |
| Code | JetBrains Mono |

## Limitations

- **No Authentication** - Currently uses a placeholder user
- **No RAG** - Designed for AI-generated content without document retrieval
- **Local Database** - SQLite for simplicity; not suitable for multi-user deployment
- **OpenRouter/General-Compute Key Required** - Users must supply their own API key via the UI settings panel

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for new functionality (target >80% coverage)
4. Run linting and tests before committing:
   - `cd client && npm run lint && npm run test -- --run`
   - `cd server && python -m unittest`
5. Submit a pull request with a clear description


## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

Built with React, FastAPI, OpenRouter, and multi-agent orchestration
