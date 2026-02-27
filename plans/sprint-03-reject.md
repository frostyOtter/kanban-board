# Sprint 3 — Reject Transition + Audit Depth

**Concept: Non-Happy-Path State Machines**
**Analogue: Craft Agents session re-open / re-queue**

---

## Goal

Review is not always approval. Add a `reject` path that returns a task to Backlog, records a reason, and tracks how many times a task has cycled.

---

## Deliverables

- `reject(task_id: str, reason: str) -> Task` on `AsyncKanbanBoard`
  - Valid from `Stage.REVIEW` only
  - Transitions: `Review → Backlog`
  - Records `reason` in `AuditEntry.note`
- `Task` gains `retry_count: int = 0` — incremented on each rejection
- WIP slot freed on rejection (same as `move_to_review`)
- `POST /tasks/{id}/reject` endpoint with `{"reason": "..."}` body
- `on_rejected` hook event

---

## Milestone Definition of Done

- [ ] Rejected task lands in `Stage.BACKLOG` with correct audit entry and note
- [ ] `retry_count` increments correctly across multiple rejection cycles
- [ ] WIP count is accurate after rejection
- [ ] `GET /board` shows rejected tasks in backlog correctly
- [ ] Tests: full cycle — start → review → reject → start → review → approve

---

## What You'll Learn

How state machines handle non-linear flows. How audit history earns its keep when things go backwards. How `retry_count` enables policy decisions (e.g. max retries before escalation).

---

## Implementation Notes

### Domain Updates

```python
# kanban/domain.py
@dataclass
class Task:
    # existing fields...
    retry_count: int = 0
```

### Board Method

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

### API Endpoint

```python
# kanban/api.py

class RejectRequest(BaseModel):
    reason: str = Field(..., min_length=1, max_length=500)

@app.post("/tasks/{task_id}/reject", response_model=TaskResponse)
async def reject_task(task_id: str, body: RejectRequest, board: BoardDep) -> TaskResponse:
    try:
        task = await board.reject(task_id, body.reason)
    except BoardError as exc:
        raise _http(exc)
    return TaskResponse.from_task(task)
```

### HTTP Exception Mapping

```python
def _http(exc: BoardError) -> HTTPException:
    # existing mappings...
    if isinstance(exc, InvalidTransitionError):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))
```

### Hook Example

```python
async def notify_on_reject(task: Task) -> None:
    logger.warning(f"Task {task.id} rejected (retry #{task.retry_count})")
    # Could send to Slack, PagerDuty, etc.
```
