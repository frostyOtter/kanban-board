# Sprint 1 Walkthrough — Hooks System

## Overview

Implemented an event-driven hooks system for the kanban board using the Observer pattern. This decouples side effects from board logic — the board fires events, and listeners react without knowing what happens downstream.

---

## What Was Implemented

### 1. Created `kanban/hooks.py` Module

**Components:**

- **`AsyncHookFn` type**: Type alias for `Callable[[Task], Awaitable[None]]`
- **`HookRegistry` class**: Maps event names to lists of async callables
  - `register(event, hook)`: Adds a hook to an event
  - `fire(event, task)`: Executes all hooks for an event, catching and logging errors
- **`log_transition` function**: Built-in hook that logs task transitions

**Key Design Decisions:**

- Hooks are async callables that receive a `Task` object
- Hook errors are caught and logged, never propagated to crash the board
- Three built-in events: `on_transition`, `on_done`, `on_stale_task`

**File:** `kanban/hooks.py`

### 2. Integrated Hooks into `AsyncKanbanBoard`

**Changes to `kanban/board.py`:**

- Added `hooks` parameter to `__init__` (optional, accepts `dict[str, list[AsyncHookFn]]`)
- Initialized `HookRegistry` and registered any provided hooks on construction
- Added `_fire_hook(event, task)` method to execute hooks
- Hooks are fired **after** lock release to avoid blocking and allow concurrency

**Hook Firing Points:**

- `create_task` → fires `on_transition` (task created in BACKLOG)
- `move_to_in_progress` → fires `on_transition` (task moved to IN_PROGRESS)
- `move_to_review` → fires `on_transition` (task moved to REVIEW)
- `approve` → fires `on_transition` **and** `on_done` (task moved to DONE)

**Key Pattern:**

```python
async with self._lock:
    # Mutate state
    task.stage = Stage.IN_PROGRESS
    self._save()

# Hook fires OUTSIDE the lock — allows concurrency
await self._fire_hook("on_transition", task)
```

### 3. Created Comprehensive Tests

**File:** `test/test_hooks.py` (14 tests, all passing)

**Test Coverage:**

- HookRegistry initialization and registration
- Hook firing and error handling
- Board accepts hooks at initialization
- `on_transition` fires on every stage change
- `on_done` fires specifically on task completion
- Multiple hooks can be registered for the same event
- Hooks fire after lock release (allowing concurrency)
- Task state is correct at hook call time
- Built-in `log_transition` hook works correctly

---

## Milestone Completion

All milestone criteria from `plans/sprint-01-hooks.md` are met:

### ✅ Board fires `on_transition` on every stage change, passing `Task`

- `create_task` fires when task is created (BACKLOG)
- `move_to_in_progress` fires when task enters IN_PROGRESS
- `move_to_review` fires when task enters REVIEW
- `approve` fires when task enters DONE
- All pass the complete `Task` object with updated state

**Verified by:** `test_on_transition_fired_on_create_task`, `test_on_transition_fired_on_move_to_in_progress`, `test_on_transition_fired_on_move_to_review`

### ✅ Board fires `on_done` specifically when a task reaches `Stage.DONE`

- `approve` method fires `on_done` after moving task to DONE
- Separate from `on_transition`, allows specialized completion handlers

**Verified by:** `test_on_done_fired_on_approve`

### ✅ Hook errors do not crash the board — errors are caught and logged

- `HookRegistry.fire()` wraps each hook in try/except
- Errors are logged via `logger.error`
- Other hooks continue to execute even if one fails

**Verified by:** `test_hook_error_does_not_crash`

### ✅ Tests assert correct call count and task state at call time

- Tests track call counts to verify hooks are called the right number of times
- Tests capture task state to ensure hooks see the correct snapshot
- All tests pass (14/14)

**Verified by:** `test_task_state_at_hook_call_time`, `test_multiple_hooks_for_same_event`

---

## What Was Learned

**Observer Pattern in Practice:**

- Decouples domain logic from side effects (logging, notifications, integrations)
- Board knows nothing about what happens after hooks fire
- Easy to add new behaviors without modifying board code

**Async Hook Execution:**

- Hooks run outside the lock to avoid blocking
- Multiple tasks can trigger hooks concurrently
- Hook failures are isolated and logged

**Type Safety:**

- `AsyncHookFn` type alias provides clear contract
- Hook signatures enforced at type-check time

---

## Files Modified/Created

**Created:**
- `kanban/hooks.py` — HookRegistry, AsyncHookFn, log_transition
- `test/test_hooks.py` — Comprehensive hooks tests (14 tests)

**Modified:**
- `kanban/board.py` — Added hooks parameter, HookRegistry integration, _fire_hook method

---

## Usage Example

```python
from kanban.board import AsyncKanbanBoard
from kanban.hooks import log_transition

# Custom hook
async def notify_on_complete(task):
    print(f"Task {task.id} is complete!")

# Board with hooks
board = AsyncKanbanBoard(
    persist_path=None,
    hooks={
        "on_transition": [log_transition],
        "on_done": [notify_on_complete],
    }
)

# Hooks fire automatically
task = await board.create_task("Test", "Desc")  # fires on_transition
await board.move_to_in_progress(task.id)  # fires on_transition
await board.move_to_review(task.id)  # fires on_transition
await board.approve(task.id)  # fires on_transition AND on_done
```

---

## Next Steps

The hooks system provides a foundation for:
- Sprint 2: Reviewer system (hooks for review events)
- Sprint 3: Reject notifications
- Sprint 4: Stale task monitoring
- Future: Webhooks, integrations, notifications
