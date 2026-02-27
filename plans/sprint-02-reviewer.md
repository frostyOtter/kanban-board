# Sprint 2 — Reviewer Assistant (LLM Chaining)

**Concept: Chaining LLM Calls / Prompt Design**
**Analogue: Craft Agents `call_llm` secondary tool**

---

## Goal

Add a second LLM call that runs on `move_to_review`. It reads the task description *and* the generated snippet and produces a structured review checklist — flags, risks, suggestions.

---

## Deliverables

- `async_reviewer_assistant(description: str, snippet: str) -> str`
- `AsyncKanbanBoard` accepts `reviewer: AsyncReviewerAssistant | None = None`
- `move_to_review` runs the reviewer outside the lock (same pattern as the coding assistant)
- `Task` gains `review_notes: str | None` field
- `TaskResponse` exposes `review_notes` in the API

---

## Milestone Definition of Done

- [ ] `move_to_review` populates `task.review_notes` when a reviewer is configured
- [ ] Reviewer runs **concurrently** with other board operations (outside lock)
- [ ] `GET /tasks/{id}` returns `review_notes`
- [ ] Tests: assert review notes are set after transition; assert board remains usable while reviewer runs

---

## What You'll Learn

How to chain LLM calls. Why prompt context matters (description + snippet vs description alone). The latency/cost tension that shapes every real agent system.

---

## Implementation Notes

### Type Definition

```python
from typing import Callable, Coroutine, Any

AsyncReviewerAssistant = Callable[[str, str], Coroutine[Any, Any, str]]
```

### Mock Reviewer

```python
async def async_mock_reviewer(description: str, snippet: str) -> str:
    """Simulates a reviewer that checks the generated code."""
    await asyncio.sleep(0.05)  # simulate I/O
    issues = []
    if "TODO" in snippet:
        issues.append("- Contains TODO markers")
    if "pass" in snippet:
        issues.append("- Uses bare pass statements")

    if issues:
        return f"Review Checklist:\n" + "\n".join(issues)
    else:
        return f"✓ Code reviewed for: {description[:50]}...\nIssues: None"
```

### Board Integration

```python
async def move_to_review(self, task_id: str) -> Task:
    async with self._lock:
        task = self._get(task_id)
        self._assert_stage(task, Stage.IN_PROGRESS)
        task.stage = Stage.REVIEW
        self._record(task, from_stage=Stage.IN_PROGRESS, to_stage=Stage.REVIEW)
        self._save()

    await self._fire_hook("on_transition", task)

    # Run reviewer outside lock
    if self._reviewer:
        logger.info("Reviewer analysing task {}…", task_id)
        notes = await self._reviewer(task.description, task.code_snippet or "")

        async with self._lock:
            task.review_notes = notes
            self._save()

        logger.success("Reviewer done for task {}", task_id)

    return task
```

### Schema Updates

```python
# kanban/domain.py
@dataclass
class Task:
    # existing fields...
    review_notes: str | None = None

# kanban/api.py
class TaskResponse(BaseModel):
    # existing fields...
    review_notes: str | None = None
```
