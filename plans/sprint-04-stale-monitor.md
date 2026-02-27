# Sprint 4 — Stale Task Monitor (Background Scheduler)

**Concept: Async Background Tasks / Lifecycle Management**
**Analogue: Craft Agents cron-based scheduling**

---

## Goal

Run a persistent background coroutine alongside the FastAPI server that detects tasks stuck in `IN_PROGRESS` too long and fires the `on_stale_task` hook.

---

## Deliverables

- `AsyncKanbanBoard.find_stale(threshold_seconds: int) -> list[Task]`
  - Returns tasks in `IN_PROGRESS` whose last transition timestamp is older than threshold
- `stale_task_monitor(board, threshold_seconds, poll_interval_seconds)` — standalone async coroutine
- Wired into FastAPI `lifespan` as a background `asyncio.Task`
  - Started on app startup, cancelled cleanly on shutdown
- `on_stale_task` hook fires per stale task found
- Config: `STALE_THRESHOLD_SECONDS` and `MONITOR_POLL_SECONDS` via env vars

---

## Milestone Definition of Done

- [ ] Monitor starts with the server and shuts down cleanly (no `asyncio.CancelledError` leaks)
- [ ] `find_stale` correctly identifies tasks by audit timestamp, not `created_at`
- [ ] `on_stale_task` hook fires for each stale task found per poll cycle
- [ ] A task that moves to `REVIEW` is no longer considered stale
- [ ] Tests: fast threshold + short poll, assert hook fires; assert task moving out of `IN_PROGRESS` stops triggering

---

## What You'll Learn

The `asyncio` task lifecycle. How to attach background work to FastAPI's `lifespan`. Graceful cancellation. Why background tasks need their own error boundaries.

---

## Implementation Notes

### Board Method

```python
from datetime import datetime, timezone

def find_stale(self, threshold_seconds: int = 300) -> list[Task]:
    """Find tasks stuck in IN_PROGRESS longer than threshold."""
    cutoff = datetime.now(timezone.utc).timestamp() - threshold_seconds
    stale = []

    for task in self._tasks.values():
        if task.stage != Stage.IN_PROGRESS:
            continue

        # Find the most recent transition to IN_PROGRESS
        transition_time = None
        for entry in reversed(task.history):
            if entry.to_stage == Stage.IN_PROGRESS:
                transition_time = datetime.fromisoformat(entry.timestamp).timestamp()
                break

        if transition_time and transition_time < cutoff:
            stale.append(task)

    return stale
```

### Monitor Coroutine

```python
async def stale_task_monitor(
    board: AsyncKanbanBoard,
    threshold_seconds: int = 300,
    poll_interval_seconds: int = 60,
) -> None:
    """Background task that polls for stale tasks and fires hooks."""
    logger.info(
        "Stale task monitor started (threshold: {}s, poll: {}s)",
        threshold_seconds,
        poll_interval_seconds,
    )

    try:
        while True:
            await asyncio.sleep(poll_interval_seconds)
            stale = board.find_stale(threshold_seconds)

            if stale:
                logger.warning("Found {} stale tasks", len(stale))
                for task in stale:
                    await board._fire_hook("on_stale_task", task)
    except asyncio.CancelledError:
        logger.info("Stale task monitor shutting down...")
        raise
    except Exception as e:
        logger.error("Stale task monitor crashed: {}", e)
        # Consider re-raising or implementing retry logic
```

### FastAPI Lifespan Integration

```python
import os

# kanban/api.py

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _board
    _board = AsyncKanbanBoard()

    # Environment config
    stale_threshold = int(os.getenv("STALE_THRESHOLD_SECONDS", "300"))
    poll_interval = int(os.getenv("MONITOR_POLL_SECONDS", "60"))

    # Start background monitor
    monitor_task = asyncio.create_task(
        stale_task_monitor(_board, stale_threshold, poll_interval)
    )

    yield

    # Clean shutdown
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        logger.info("Background monitor cancelled")

app = FastAPI(
    title="Kanban Board API",
    version="2.0.0",
    lifespan=lifespan,
)
```

### Hook Example

```python
async def alert_on_stale(task: Task) -> None:
    logger.warning(f"⚠️  Task {task.id} stuck in {task.stage.value}")
    # Could send alert to monitoring system
```

### Testing Strategy

```python
@pytest.mark.asyncio
async def test_stale_monitor():
    # Fast threshold and poll for testing
    threshold = 1  # 1 second
    poll_interval = 0.5  # 0.5 seconds

    board = AsyncKanbanBoard()
    task = await board.create_task("Stale Task", "Will become stale")
    await board.move_to_in_progress(task.id)

    hook_calls = []

    async def track_stale(t: Task) -> None:
        hook_calls.append(t.id)

    board._hook_registry.register("on_stale_task", track_stale)

    # Start monitor, wait for detection, then cancel
    monitor = asyncio.create_task(
        stale_task_monitor(board, threshold, poll_interval)
    )
    await asyncio.sleep(2)  # Wait for at least one poll cycle
    monitor.cancel()

    assert len(hook_calls) >= 1
    assert task.id in hook_calls
```
