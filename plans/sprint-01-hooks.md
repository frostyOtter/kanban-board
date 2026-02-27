# Sprint 1 — Hooks System

**Concept: Event-Driven / Observer Pattern**
**Analogue: Craft Agents hooks system**

---

## Goal

Decouple side effects from board logic. The board fires events; listeners react. Nothing inside `board.py` knows or cares what happens downstream.

---

## Deliverables

- `HookRegistry` — maps event names to lists of async callables
- Events: `on_transition`, `on_done`, `on_stale_task`
- `AsyncKanbanBoard` accepts `hooks: dict[str, list[AsyncHookFn]]` at init
- Hooks fire **after** lock is released, same pattern as the assistant today
- Built-in hook: `log_transition` (loguru, replaces scattered `logger.info` calls)

---

## Milestone Definition of Done

- [ ] Board fires `on_transition` on every stage change, passing `Task`
- [ ] Board fires `on_done` specifically when a task reaches `Stage.DONE`
- [ ] A hook that raises does **not** crash the board — errors are caught and logged
- [ ] Tests: mock hooks assert correct call count and task state at call time

---

## What You'll Learn

The Observer pattern. Why side effects don't belong in domain logic. How async callables compose without coupling.

---

## Implementation Notes

### Type Definitions

```python
from typing import Callable, Awaitable

AsyncHookFn = Callable[[Task], Awaitable[None]]

class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[AsyncHookFn]] = {
            "on_transition": [],
            "on_done": [],
            "on_stale_task": [],
        }

    def register(self, event: str, hook: AsyncHookFn) -> None:
        if event not in self._hooks:
            raise ValueError(f"Unknown hook event: {event}")
        self._hooks[event].append(hook)

    async def fire(self, event: str, task: Task) -> None:
        for hook in self._hooks.get(event, []):
            try:
                await hook(task)
            except Exception as e:
                logger.error(f"Hook {event} failed: {e}")
```

### Board Integration

```python
class AsyncKanbanBoard:
    def __init__(
        self,
        hooks: dict[str, list[AsyncHookFn]] | None = None,
        # ... other params
    ) -> None:
        self._hook_registry = HookRegistry()
        if hooks:
            for event, hook_list in hooks.items():
                for hook in hook_list:
                    self._hook_registry.register(event, hook)
        # ... rest of init

    async def _fire_hook(self, event: str, task: Task) -> None:
        await self._hook_registry.fire(event, task)
```

### Built-in Hook

```python
async def log_transition(task: Task) -> None:
    logger.info(f"Task {task.id} → {task.stage.value}")
```
