# Kanban Board

A Python Kanban board focused on logic, not UI.

---

## Core Flow

```mermaid
graph LR
    A[Backlog] -->|start work| B[In-Progress]
    B -->|assistant runs| C[Review]
    C -->|approve| D[Done]
```

Tasks move through four stages. When a task enters In-Progress, a coding assistant analyzes its description and generates a code snippet automatically.

The assistant is injectable — swap the mock for a real Claude API call with one argument.

---

## Two Hard Rules

```mermaid
graph TD
    A[Start Work?] --> B{WIP Limit}
    B -->|free slot| C[Proceed]
    B -->|full| D[Blocked]
    
    E[Start Work?] --> F{Dependencies Done?}
    F -->|yes| C
    F -->|no| D
```

**WIP Limit**: Caps how many tasks can be in-progress simultaneously. Prevents context-switching overload.

**Dependency Tracking**: A task can't start until every task it depends on reaches Done.

---

## Architecture

```mermaid
graph TB
    subgraph Layer 1
        A[Sync Board]
    end
    
    subgraph Layer 2
        B[Async Board<br/>+ WIP Limit<br/>+ Concurrency Lock]
    end
    
    subgraph Layer 3
        C[REST API<br/>Thin HTTP wrapper]
    end
    
    A --> B --> C
```

Three complementary implementations, each building on the previous:

### Sync Board — Foundation
- Simple task entity with stage
- Linear flow enforcement
- JSON persistence
- Plain callable assistant (swap in one line)

### Async Board — Discipline
- **WIP limit**: natural pull system, capacity dictates flow
- **Asyncio.Lock**: protects shared state under concurrent load
- **Optimization**: assistant runs outside lock (pure I/O, no mutation)

### REST API — Separation
- Translates HTTP ↔ domain
- Validates input (Pydantic)
- Maps exceptions to HTTP codes
- **No business logic** — all lives in board

---

## The Assistant Contract

```python
async def assistant(description: str) -> str:
    return code_snippet
```

That's it. The board doesn't care how you generate code — Claude, GPT, local model, or template. Swap without touching board logic.

---

## Flow in Practice

```mermaid
sequenceDiagram
    participant User
    participant Board
    participant Assistant
    
    User->>Board: move_to_in_progress(task)
    Board->>Board: check WIP limit
    Board->>Board: check dependencies
    Board->>Board: stage = IN_PROGRESS
    Board-->>User: task updated
    
    par Async (outside lock)
        Board->>Assistant: analyze(description)
        Assistant-->>Board: code_snippet
        Board->>Board: update task
    end
```

**Key**: The assistant runs concurrently and outside the lock. Multiple tasks can be analyzed in parallel while state mutations stay thread-safe.

---

## Error as Policy

| Error | Meaning | HTTP Code |
|-------|---------|-----------|
| `WIPLimitError` | Overloaded. Finish something first. | 429 |
| `UnresolvedDependencyError` | Foundation incomplete. | 409 |
| `InvalidTransitionError` | Skipping steps. | 422 |
| `TaskNotFoundError` | Doesn't exist yet. | 404 |

---

## The Bigger Idea

This isn't a task tracker. It's a laboratory for flow, discipline, and separation.

**Start simple → add discipline → expose through thin interfaces**

This is how robust systems grow.
