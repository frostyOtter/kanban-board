# Sprint 3 Walkthrough — Reject Transition + Audit Depth

## Overview

Implemented a reject transition that returns tasks from REVIEW to BACKLOG, records the rejection reason in the audit trail, and tracks how many times a task has been rejected via a `retry_count` field. This adds non-happy-path state machine handling to the kanban board, demonstrating how audit trails earn their keep when things go backwards.

---

## What Was Implemented

### 1. Extended Domain Model with `retry_count` Field

**Changes to `kanban/domain.py`:**

- Added `retry_count: int = 0` field to `Task` dataclass
- Default value is 0 (no rejections yet)
- Updated `Task.__str__` to display retry_count when greater than 0

**File:** `kanban/domain.py:56-67, 69-75`

**Key Pattern:**
```python
@dataclass
class Task:
    title: str
    description: str
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    stage: Stage = Stage.BACKLOG
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    code_snippet: str | None = None
    depends_on: list[str] = field(default_factory=list)
    history: list[AuditEntry] = field(default_factory=list)
    review_notes: str | None = None
    retry_count: int = 0  # Tracks how many times task has been rejected
```

### 2. Added `on_rejected` Hook Event

**Changes to `kanban/hooks.py`:**

- Added `"on_rejected": []` to `_hooks` dictionary initialization
- Hook fires when a task is rejected (Review → Backlog transition)

**File:** `kanban/hooks.py:24-28`

**Key Pattern:**
```python
def __init__(self) -> None:
    self._hooks: dict[str, list[AsyncHookFn]] = {
        "on_transition": [],
        "on_done": [],
        "on_stale_task": [],
        "on_rejected": [],  # New hook for rejection events
    }
```

### 3. Implemented `reject()` Method on `AsyncKanbanBoard`

**Changes to `kanban/board.py`:**

**`reject()` Method:**
- Only valid from `Stage.REVIEW` (enforced by `_assert_stage`)
- Transitions task to `Stage.BACKLOG`
- Increments `task.retry_count`
- Records audit entry with `reason` in the `note` field
- Fires `on_rejected` hook after lock release
- Frees WIP slot (task no longer in REVIEW)

**Key Pattern:**
```python
async def reject(self, task_id: str, reason: str) -> Task:
    async with self._lock:
        task = self._get(task_id)
        self._assert_stage(task, Stage.REVIEW)
        task.stage = Stage.BACKLOG
        task.retry_count += 1
        self._record(task, from_stage=Stage.REVIEW, to_stage=Stage.BACKLOG, note=reason)
        self._save()

    logger.info("Task {} rejected → backlog (reason: {})", task_id, reason[:50])
    await self._fire_hook("on_rejected", task)
    return task
```

**File:** `kanban/board.py:191-205`

**Persistence:**
- Updated `_load` method to handle `retry_count` field when loading from JSON
- `raw.get("retry_count", 0)` safely handles missing field in old persisted files

**File:** `kanban/board.py:273`

### 4. Added Reject API Endpoint

**Changes to `kanban/api.py`:**

**New Request Schema:**
```python
class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)
```

**New Endpoint:**
```python
@app.post("/tasks/{task_id}/reject", response_model=TaskResponse)
async def reject_task(task_id: str, body: RejectRequest, board: BoardDep) -> TaskResponse:
    try:
        task = await board.reject(task_id, body.reason)
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)
```

**Updated Response Schema:**
- Added `retry_count: int` field to `TaskResponse`
- Updated `from_task` class method to include `retry_count` in serialization

**File:** `kanban/api.py:77-78, 93-116, 219-228`

### 5. Created Comprehensive Tests

**File:** `test/test_api.py` (8 new tests, all passing)

**Test Coverage:**

1. **`test_reject_task`**: Verifies basic reject functionality
   - Creates task, moves to review
   - Rejects with reason
   - Asserts task returns to backlog with retry_count = 1

2. **`test_reject_task_invalid_stage`**: Verifies stage validation
   - Attempts to reject task in backlog
   - Asserts 422 error with appropriate message

3. **`test_reject_task_multiple_times`**: Verifies retry_count increments
   - Runs task through full cycle 3 times
   - Rejects each time
   - Asserts retry_count increments correctly (1, 2, 3)

4. **`test_reject_frees_wip_slot`**: Verifies WIP slot is freed
   - Creates board with WIP limit of 1
   - Starts task 1 (fills slot)
   - Attempts to start task 2 (blocked by WIP)
   - Rejects task 1
   - Asserts task 2 can now start

5. **`test_reject_records_audit_entry`**: Verifies audit trail
   - Rejects task with reason
   - Asserts audit entry exists in history
   - Asserts note field contains rejection reason

6. **`test_reject_reason_validation`**: Verifies input validation
   - Tests empty reason (fails 422)
   - Tests reason too long (>500 chars, fails 422)

7. **`test_reject_task_not_found`**: Verifies 404 error
   - Attempts to reject non-existent task
   - Asserts 404 status code

8. **`test_board_view_shows_rejected_tasks_in_backlog`**: Verifies board view
   - Rejects task
   - Gets board snapshot
   - Asserts rejected task appears in backlog
   - Asserts retry_count is visible

**File:** `test/test_api.py:648-812`

**Schema Test Fix:**
- Updated `test_task_response_schema` to include `retry_count` parameter

---

## Milestone Completion

All milestone criteria from `plans/sprint-03-reject.md` are met:

### ✅ Rejected task lands in `Stage.BACKLOG` with correct audit entry and note

- `reject()` method transitions task to `Stage.BACKLOG`
- `_record()` adds audit entry with `from_stage=REVIEW`, `to_stage=BACKLOG`
- `reason` parameter is stored in `AuditEntry.note`
- Audit entry includes timestamp for tracking

**Verified by:** `test_reject_records_audit_entry`

### ✅ `retry_count` increments correctly across multiple rejection cycles

- `reject()` method increments `task.retry_count` by 1
- Counter persists to JSON and loads correctly
- Multiple rejections result in incremented count (1, 2, 3...)

**Verified by:** `test_reject_task_multiple_times`

### ✅ WIP count is accurate after rejection

- Task moves from `Stage.REVIEW` to `Stage.BACKLOG`
- No longer counts towards REVIEW stage
- Frees up slot for other tasks to move to REVIEW
- `_count_stage(Stage.REVIEW)` correctly excludes rejected tasks

**Verified by:** `test_reject_frees_wip_slot`

### ✅ `GET /board` shows rejected tasks in backlog correctly

- `BoardSnapshot` groups tasks by stage
- Rejected tasks appear in `backlog` array
- `retry_count` field is visible in response

**Verified by:** `test_board_view_shows_rejected_tasks_in_backlog`

### ✅ Tests: full cycle — start → review → reject → start → review → approve

- Full workflow tested across multiple test cases
- Task can cycle through: Backlog → In-Progress → Review → Backlog → In-Progress → Review → Done
- All transitions validated
- Audit trail tracks complete history

**Verified by:** `test_reject_task_multiple_times`, `test_reject_frees_wip_slot`

---

## What Was Learned

**State Machine Depth:**

- Linear flows (Backlog → In-Progress → Review → Done) are easy
- Non-linear flows (Review → Backlog) require careful handling
- Audit trails become critical when state goes "backwards"
- `retry_count` enables policy decisions (e.g., max retries before escalation)

**Audit Trail Value:**

- Each rejection is recorded with timestamp and reason
- History shows complete task lifecycle, not just final state
- Enables debugging: "Why was this task rejected?"
- Pattern: Immutable audit entries provide provenance

**Transition Validation:**

- `_assert_stage()` prevents invalid transitions
- `InvalidTransitionError` provides clear error messages
- HTTP status code 422 (Unprocessable Entity) maps to transition errors

**Hook System Extensibility:**

- `on_rejected` hook enables custom rejection handling
- Examples: Send Slack notifications, escalate to team lead, update metrics
- Board logic remains decoupled from side effects

**Input Validation:**

- Pydantic models validate request bodies
- `reason` field: min_length=1, max_length=500
- FastAPI automatically returns 422 for validation errors

---

## Files Modified/Created

**Modified:**
- `kanban/domain.py` — Added retry_count field to Task dataclass, updated __str__
- `kanban/hooks.py` — Added on_rejected to HookRegistry initialization
- `kanban/board.py` — Added reject() method, updated _load for retry_count
- `kanban/api.py` — Added RejectRequest schema, /reject endpoint, retry_count to TaskResponse
- `test/test_api.py` — Added 8 reject tests, fixed 1 schema test

---

## Usage Example

```python
from kanban.board import AsyncKanbanBoard
from kanban.api import app
from fastapi.testclient import TestClient

# Create board
board = AsyncKanbanBoard(persist_path=None)

# Create and start task
task = await board.create_task("Build Feature", "Implement new feature")
task = await board.move_to_in_progress(task.id)
task = await board.move_to_review(task.id)

# Reject task (returns to backlog, retry_count increments)
task = await board.reject(task.id, "Code needs refactoring")
assert task.stage == Stage.BACKLOG
assert task.retry_count == 1

# Task can be restarted
task = await board.move_to_in_progress(task.id)
task = await board.move_to_review(task.id)

# Approve on second try
task = await board.approve(task.id)
assert task.stage == Stage.DONE
```

**With API:**

```python
client = TestClient(app)

# Create and move task
task = client.post("/tasks", json={"title": "Fix Bug", "description": "Fix crash"}).json()
client.post(f"/tasks/{task['id']}/start")
client.post(f"/tasks/{task['id']}/review")

# Reject with reason
response = client.post(
    f"/tasks/{task['id']}/reject",
    json={"reason": "Edge case not handled"}
)
assert response.status_code == 200
data = response.json()
assert data["stage"] == "backlog"
assert data["retry_count"] == 1

# Check audit trail
task = client.get(f"/tasks/{task['id']}").json()
reject_entry = next(
    h for h in task["history"]
    if h["from_stage"] == "review" and h["to_stage"] == "backlog"
)
assert reject_entry["note"] == "Edge case not handled"
```

**With Rejection Hook:**

```python
async def notify_on_reject(task):
    print(f"Task {task.id} rejected (retry #{task.retry_count})")
    # Could send to Slack, PagerDuty, etc.

board = AsyncKanbanBoard(
    persist_path=None,
    hooks={
        "on_rejected": [notify_on_reject],
    }
)

task = await board.create_task("Test", "Desc")
await board.move_to_in_progress(task.id)
await board.move_to_review(task.id)
await board.reject(task.id, "Needs work")
# Output: Task abc12345 rejected (retry #1)
```

---

## Next Steps

The reject transition provides a foundation for:

- **Sprint 4: Stale Task Monitor** — Auto-reject tasks stuck in REVIEW too long
- **Sprint 5: Skills System** — Skill-based rejection policies
- **Sprint 6: Export** — Include rejection history and retry_count in documentation
- **Future**: Max retry policy, auto-escalation after N rejections, rejection analytics

**Potential Enhancements:**

- Max retry limit (prevent infinite loops)
- Rejection reason categorization (code quality, scope creep, etc.)
- Rejection metrics dashboard (most common reasons, teams with highest rejection rate)
- Auto-assignment escalation after N rejections
- Rejection notification templates
