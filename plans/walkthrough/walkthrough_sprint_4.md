# Sprint 4 Walkthrough — Stale Task Monitor

## Overview

Implemented a persistent background coroutine that runs alongside the FastAPI server to detect tasks stuck in `IN_PROGRESS` too long. The monitor polls periodically, identifies stale tasks using their audit trail timestamps, and fires the `on_stale_task` hook for each stale task found.

---

## What Was Implemented

### 1. Added `find_stale` Method to `AsyncKanbanBoard`

**File:** `kanban/board.py` (lines 241-266)

**Method Signature:**
```python
def find_stale(self, threshold_seconds: int = 300) -> list[Task]:
```

**Implementation:**
- Calculates cutoff timestamp: `datetime.now(timezone.utc).timestamp() - threshold_seconds`
- Iterates through all tasks in the board
- Filters for tasks in `Stage.IN_PROGRESS`
- For each IN_PROGRESS task, searches history backwards to find the most recent IN_PROGRESS transition
- Compares transition timestamp to cutoff
- Returns list of tasks where transition time is older than threshold

**Key Design Decision:**
- Uses **audit trail timestamp** (from `task.history`), NOT `task.created_at`
- This correctly handles tasks that were created long ago but recently moved to IN_PROGRESS
- Tasks that move out of IN_PROGRESS are automatically no longer considered stale

**Verified by:** `test_find_stale_uses_audit_timestamp_not_created_at`

### 2. Created `stale_task_monitor` Background Coroutine

**File:** `kanban/board.py` (lines 269-376)

**Function Signature:**
```python
async def stale_task_monitor(
    board: "AsyncKanbanBoard",
    threshold_seconds: int = 300,
    poll_interval_seconds: int = 60,
) -> None:
```

**Implementation:**
- Logs startup with threshold and poll interval configuration
- Runs in infinite loop:
  - Sleeps for `poll_interval_seconds`
  - Calls `board.find_stale(threshold_seconds)`
  - If stale tasks found:
    - Logs warning with count
    - Fires `on_stale_task` hook for each stale task
- Handles `asyncio.CancelledError` for graceful shutdown
- Catches and logs other exceptions (consider adding retry logic in production)

**Error Handling:**
- `CancelledError` is caught, logged, and re-raised (expected shutdown path)
- Other exceptions are logged but don't crash the monitor

**Verified by:** `test_stale_monitor`, `test_stale_monitor_respects_stage_changes`, `test_stale_monitor_handles_multiple_stale_tasks`

### 3. Integrated Monitor into FastAPI Lifespan

**File:** `kanban/api.py` (lines 25-26, 31-32, 52-72)

**Changes:**
1. Added imports:
   - `import asyncio`
   - `import os`
   - `from .board import AsyncKanbanBoard, stale_task_monitor`

2. Updated `lifespan` function:
   ```python
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
           pass
   ```

**Environment Variables:**
- `STALE_THRESHOLD_SECONDS`: Default 300 (5 minutes), max time allowed in IN_PROGRESS
- `MONITOR_POLL_SECONDS`: Default 60, how often to check for stale tasks

**Lifecycle Management:**
- Monitor starts on app startup (before yielding)
- Monitor runs in background while app serves requests
- On shutdown:
  - `monitor_task.cancel()` sends cancellation signal
  - `await monitor_task` waits for graceful termination
  - `CancelledError` is caught and ignored (expected shutdown)

**Verified by:** Manual testing (monitor starts/stops cleanly), all tests pass without leaks

### 4. Added Comprehensive Tests

**File:** `test/test_async_kanban_board.py` (7 new tests)

**Test Coverage:**

1. **`test_find_stale_no_stale_tasks`**
   - Returns empty list when no tasks are stale
   - Verifies basic filtering works

2. **`test_find_stale_with_stale_task`**
   - Correctly identifies a single stale IN_PROGRESS task
   - Manually sets old transition timestamp to simulate staleness

3. **`test_find_stale_ignores_non_in_progress`**
   - Tasks in BACKLOG, REVIEW, DONE are never considered stale
   - Only IN_PROGRESS tasks are checked

4. **`test_find_stale_uses_audit_timestamp_not_created_at`**
   - Uses audit trail timestamp, NOT `task.created_at`
   - Old created_at but recent IN_PROGRESS transition = not stale
   - Old created_at AND old IN_PROGRESS transition = stale

5. **`test_stale_monitor`**
   - Monitor detects stale tasks and fires hooks
   - Hook is called for each stale task found
   - Monitor can be started, run, and cancelled cleanly

6. **`test_stale_monitor_respects_stage_changes`**
   - Tasks moved out of IN_PROGRESS stop being stale
   - Hook fires while task is stale
   - Hook stops firing after task moves to REVIEW

7. **`test_stale_monitor_handles_multiple_stale_tasks`**
   - Multiple stale tasks all fire hooks
   - Fresh tasks (recently moved to IN_PROGRESS) don't fire hooks
   - Hook fires correct number of times for each task

**File:** `test/test_hooks.py` (2 new tests)

8. **`test_on_stale_task_hook_registered`**
   - Verifies `on_stale_task` is in HookRegistry

9. **`test_on_stale_task_hook_fires`**
   - Hook fires correctly when monitor detects stale tasks
   - Integrates monitor, board, and hook system

---

## Milestone Completion

All milestone criteria from `plans/sprint-04-stale-monitor.md` are met:

### ✅ Monitor starts with the server and shuts down cleanly (no `asyncio.CancelledError` leaks)

- Monitor is created in FastAPI `lifespan` before `yield`
- Monitor is cancelled after `yield` (on shutdown)
- `await monitor_task` waits for completion
- `CancelledError` is caught and handled gracefully
- No unhandled exceptions leak from monitor

**Verified by:** Manual testing (start server, verify monitor running, shutdown server, verify clean stop), all tests complete without hanging

### ✅ `find_stale` correctly identifies tasks by audit timestamp, not `created_at`

- Implementation iterates through `task.history` to find IN_PROGRESS transition
- Uses `AuditEntry.timestamp` from history, not `task.created_at`
- Correctly handles tasks with old `created_at` but recent transitions

**Verified by:** `test_find_stale_uses_audit_timestamp_not_created_at`

### ✅ `on_stale_task` hook fires for each stale task found per poll cycle

- Monitor calls `board._fire_hook("on_stale_task", task)` for each stale task
- Hook fires multiple times if task remains stale across poll cycles
- Multiple stale tasks all fire their hooks

**Verified by:** `test_stale_monitor` (hook fires for single stale task), `test_stale_monitor_handles_multiple_stale_tasks` (hooks fire for multiple stale tasks)

### ✅ A task that moves to `REVIEW` is no longer considered stale

- `find_stale` only checks tasks with `task.stage == Stage.IN_PROGRESS`
- When task moves to REVIEW, it's automatically excluded from stale checks
- Monitor stops firing hooks for that task

**Verified by:** `test_stale_monitor_respects_stage_changes`

### ✅ Tests: fast threshold + short poll, assert hook fires; assert task moving out of `IN_PROGRESS` stops triggering

- Tests use `threshold=1` or `2` seconds for fast detection
- Tests use `poll_interval=1` second for quick iteration
- Tests manually set old timestamps to simulate staleness
- Tests verify hooks fire for stale tasks
- Tests verify hooks stop when task leaves IN_PROGRESS

**Verified by:** All 7 stale task tests pass, 2 stale hook tests pass

---

## What Was Learned

**Asyncio Task Lifecycle:**
- `asyncio.create_task()` spawns background coroutines
- Tasks run independently from main event loop
- `cancel()` sends `CancelledError` to task
- Tasks must handle cancellation gracefully
- `await task` waits for task completion (or cancellation)

**FastAPI Lifespan:**
- `@asynccontextmanager` defines startup/shutdown behavior
- Code before `yield` runs on startup
- Code after `yield` runs on shutdown
- Perfect place to spawn/cleanup background tasks
- Clean separation between app and infrastructure

**Background Task Error Boundaries:**
- Background tasks need their own error handling
- Uncaught exceptions crash the task
- Use try/except to log and continue
- Consider retry logic for transient failures
- Don't let background task errors affect main app

**Audit Trail for Time Tracking:**
- Don't use `created_at` for time-based logic
- Audit trail provides accurate event timestamps
- Search backwards through history to find latest transition
- Allows tracking time in specific stages (like IN_PROGRESS)

---

## Files Modified/Created

**Created:**
- None (all changes to existing files)

**Modified:**
- `kanban/board.py`:
  - Added `find_stale` method (lines 241-266)
  - Added `stale_task_monitor` coroutine function (lines 269-376)
  - Added `import asyncio` (line 40)

- `kanban/api.py`:
  - Added imports: `asyncio`, `os`, `stale_task_monitor` (lines 25-26, 31-32)
  - Updated `lifespan` to start/cancel monitor (lines 52-72)

- `test/test_async_kanban_board.py`:
  - Added `new_board` fixture for new board class (lines 50-53)
  - Added 7 new tests for stale task functionality (lines 357-667)
  - Added imports: `AuditEntry`, `Stage as KanbanStage`, `KanbanBoard`, `stale_task_monitor` (lines 15-16)

- `test/test_hooks.py`:
  - Added 2 new tests for `on_stale_task` hook (lines 301-366)
  - Added imports for monitor testing (line 311)

---

## Usage Example

### Running the Server with Stale Monitor

```bash
# Default settings (5-minute threshold, 1-minute poll)
uvicorn kanban.api:app

# Custom settings (2-minute threshold, 30-second poll)
STALE_THRESHOLD_SECONDS=120 MONITOR_POLL_SECONDS=30 uvicorn kanban.api:app
```

### Custom Stale Hook

```python
from kanban.board import AsyncKanbanBoard

async def alert_on_stale(task):
    print(f"⚠️  Task {task.id} stuck in {task.stage.value}")
    # Could send Slack alert, email, PagerDuty, etc.

hooks = {"on_stale_task": [alert_on_stale]}
board = AsyncKanbanBoard(persist_path=None, hooks=hooks)

# Start server - monitor will alert on stale tasks
```

### Manual Stale Detection (Testing/Debugging)

```python
from kanban.board import AsyncKanbanBoard

board = AsyncKanbanBoard(persist_path=None)

# Create and start a task
task = await board.create_task("Test", "Desc")
await board.move_to_in_progress(task.id)

# Check for stale tasks (5-minute threshold)
stale = board.find_stale(threshold_seconds=300)
print(f"Found {len(stale)} stale tasks")
for t in stale:
    print(f"  - {t.id}: {t.title}")
```

---

## Key Implementation Details

### Audit Trail Timestamp vs. Created At

**Problem:** If we used `task.created_at`, a task created a week ago but moved to IN_PROGRESS today would immediately be considered stale.

**Solution:** Search `task.history` backwards to find the most recent transition to `IN_PROGRESS` and use that timestamp.

```python
for entry in reversed(task.history):
    if entry.to_stage == Stage.IN_PROGRESS:
        transition_time = datetime.fromisoformat(entry.timestamp).timestamp()
        break
```

### Graceful Shutdown Pattern

```python
# Startup
monitor_task = asyncio.create_task(stale_task_monitor(board, threshold, poll))

# Shutdown
monitor_task.cancel()  # Send cancellation signal
try:
    await monitor_task  # Wait for task to finish
except asyncio.CancelledError:
    pass  # Expected, task handled cancellation
```

This pattern ensures:
1. Monitor receives cancellation signal
2. Monitor logs shutdown message
3. We wait for cleanup to complete
4. No `CancelledError` leaks to caller

### Hook Error Isolation

Even though we added a new hook (`on_stale_task`), the existing error handling in `HookRegistry.fire()` catches and logs any errors:

```python
async def fire(self, event: str, task: Task) -> None:
    for hook in self._hooks.get(event, []):
        try:
            await hook(task)
        except Exception as e:
            logger.error(f"Hook {event} failed: {e}")
```

This means:
- Stale hook errors don't crash the monitor
- Monitor continues checking for stale tasks
- Other hooks continue to fire

---

## Next Steps

The stale task monitor provides a foundation for:
- Sprint 5: Skills system (hook-based skill learning)
- Sprint 6: Export functionality (scheduled exports via monitor)
- Future: Automatic task recovery, escalation alerts, SLA tracking

Potential enhancements:
- Add retry logic in monitor for transient failures
- Send alerts to external systems (Slack, PagerDuty, email)
- Track stale task metrics over time
- Automatic task reassignment when tasks go stale
- Configurable different thresholds per task priority
