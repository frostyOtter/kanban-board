# Kanban Board — Project Overview

A Python-based Kanban board implementation focused on core logic, flow discipline, and separation of concerns.

## Project Purpose

This is a laboratory for building robust task management systems. It demonstrates how to start simple, add discipline incrementally, and expose functionality through thin, well-defined interfaces.

## Core Concepts

### Task Lifecycle

Tasks move through four stages:

```
Backlog → In-Progress → Review → Done
```

When a task enters **In-Progress**, a coding assistant analyzes its description and generates a code snippet automatically. This assistant is injectable — swap the mock for a real Claude API call with a single argument.

### Two Hard Rules

1. **WIP Limit**: Caps how many tasks can be in-progress simultaneously, preventing context-switching overload
2. **Dependency Tracking**: A task cannot start until every task it depends on reaches Done

## Architecture

Three complementary implementations, each building on the previous:

### Layer 1: Sync Board (Foundation)
- Simple task entity with stage
- Linear flow enforcement
- JSON persistence
- Plain callable assistant (swap in one line)

### Layer 2: Async Board (Discipline)
- **WIP limit**: Natural pull system where capacity dictates flow
- **Asyncio.Lock**: Protects shared state under concurrent load
- **Optimization**: Assistant runs outside lock (pure I/O, no mutation)

### Layer 3: REST API (Separation)
- Translates HTTP ↔ domain
- Validates input (Pydantic)
- Maps exceptions to HTTP codes
- **No business logic** — all lives in the board

## Key Features

### Assistant Contract

```python
async def assistant(description: str) -> str:
    return code_snippet
```

The board doesn't care how you generate code — Claude, GPT, local model, or template. Swap without touching board logic.

### Hooks System

Event-driven architecture that decouples side effects from core logic. Available hook events:
- `on_transition`: Fired on every stage change
- `on_done`: Fired when task reaches DONE stage
- `on_stale_task`: Fired when a task is detected as stale
- `on_rejected`: Fired when a task is rejected from REVIEW

### Error as Policy

| Error | HTTP Code | Meaning |
|-------|-----------|---------|
| `WIPLimitError` | 429 | Overloaded — finish something first |
| `UnresolvedDependencyError` | 409 | Foundation incomplete |
| `InvalidTransitionError` | 422 | Skipping steps |
| `TaskNotFoundError` | 404 | Doesn't exist yet |

## Technology Stack

- **Python**: 3.14+
- **Web Framework**: FastAPI
- **Async Runtime**: asyncio, uvicorn
- **HTTP Client**: httpx
- **Logging**: loguru
- **Testing**: pytest, pytest-asyncio
- **Code Quality**: ruff

## Project Structure

```
kanban-board/
├── kanban/
│   ├── __init__.py
│   ├── domain.py       # Core types and exceptions
│   ├── board.py        # AsyncKanbanBoard (core logic)
│   ├── api.py          # FastAPI REST interface
│   ├── assistants.py   # Coding and reviewer assistants
│   └── hooks.py        # Event hook registry
├── legacy/             # Previous sync implementation
├── plans/              # Sprint-based development roadmap
├── test/               # Test suite
├── main.py             # Demo with mock requests
├── pyproject.toml      # Project configuration
└── README.md           # Architecture documentation
```

## Development Roadmap

The project follows a sprint-based approach, with each sprint teaching a distinct engineering concept:

| Sprint | Concept | Status |
|--------|---------|--------|
| 1 | Hooks System | ✅ Complete |
| 2 | Reviewer Assistant | ✅ Complete |
| 3 | Reject Transition | ✅ Complete |
| 4 | Stale Task Monitor | ✅ Complete |
| 5 | Skills System | 🔵 To Do |
| 6 | Session Export | 🔵 To Do |

See `plans/README.md` for detailed sprint documentation.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/tasks` | Create a task |
| GET | `/tasks` | List all tasks (optional `?stage=` filter) |
| GET | `/tasks/{id}` | Get a single task |
| POST | `/tasks/{id}/start` | Backlog → In-Progress |
| POST | `/tasks/{id}/review` | In-Progress → Review |
| POST | `/tasks/{id}/approve` | Review → Done |
| POST | `/tasks/{id}/reject` | Review → Backlog (with reason) |
| GET | `/board` | Board snapshot (all stages) |

## Running the Project

### Start the Server

```bash
python main.py
```

This starts a FastAPI server on `http://127.0.0.1:8000` and runs mock requests demonstrating the full flow.

### Run Tests

```bash
pytest
```

### Lint and Format

```bash
ruff check .
ruff format .
```

## Key Design Principles

1. **Separation of Concerns**: Business logic lives in the board, HTTP concerns in the API
2. **Dependency Injection**: Assistants and hooks are injected, making the board testable
3. **Error as Policy**: Domain exceptions encode business rules and map to HTTP codes
4. **Audit Trail**: Every state transition is logged for debugging and traceability
5. **Concurrency Safety**: Async locks protect shared state while I/O runs in parallel

## Future Enhancements

- **Skills System**: Config-driven behavior via YAML skills
- **Session Export**: Share task history as documentation
- **Real-time Notifications**: WebSocket-based task updates
- **Multi-board Support**: Separate workspaces for different projects
