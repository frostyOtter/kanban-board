# Sprint 2 Walkthrough — Reviewer Assistant (LLM Chaining)

## Overview

Implemented a second LLM call (reviewer assistant) that runs when a task is moved to REVIEW stage. The reviewer reads the task description and generated code snippet to produce a structured review checklist with flags, risks, and suggestions. This demonstrates LLM chaining — multiple LLM calls working together in a workflow.

---

## What Was Implemented

### 1. Extended `kanban/assistants.py` with Reviewer Types

**New Components:**

- **`AsyncReviewerAssistant` type**: Type alias for `Callable[[str, str], Coroutine[Any, Any, str]]`
  - Takes task description AND code snippet as input
  - Returns review notes as a string

- **`async_mock_reviewer` function**: Mock reviewer for testing
  - Simulates network latency (0.05s sleep)
  - Checks for common code smells:
    - "TODO" markers
    - Bare "pass" statements
  - Returns structured checklist or clean review

**File:** `kanban/assistants.py:21-73`

**Key Pattern:**
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
        return "Review Checklist:\n" + "\n".join(issues)
    else:
        return f"✓ Code reviewed for: {description[:50]}...\nIssues: None"
```

### 2. Updated Domain Model with `review_notes` Field

**Changes to `kanban/domain.py`:**

- Added `review_notes: str | None` field to `Task` dataclass
- Default value is `None` (no review yet)
- Persists to JSON like other fields

**File:** `kanban/domain.py:56-67`

### 3. Updated API Response Schema

**Changes to `kanban/api.py`:**

- Added `review_notes: str | None` field to `TaskResponse`
- Updated `from_task` class method to include `review_notes` in serialization
- `GET /tasks/{id}` now returns review notes when available

**File:** `kanban/api.py:93-114`

### 4. Integrated Reviewer into `AsyncKanbanBoard`

**Changes to `kanban/board.py`:**

**Constructor:**
- Added `reviewer: AsyncReviewerAssistant | None = None` parameter
- Stored as `self._reviewer` instance variable

**`move_to_review` Method:**
- Runs reviewer **after** stage transition and hook firing
- Executes **outside the lock** (same pattern as coding assistant)
- Updates `task.review_notes` with reviewer output
- Saves state after reviewer completes

**Key Pattern:**
```python
async def move_to_review(self, task_id: str) -> Task:
    async with self._lock:
        task = self._get(task_id)
        self._assert_stage(task, Stage.IN_PROGRESS)
        task.stage = Stage.REVIEW
        self._record(task, from_stage=Stage.IN_PROGRESS, to_stage=Stage.REVIEW)
        self._save()

    await self._fire_hook("on_transition", task)

    # Run reviewer OUTSIDE the lock — pure I/O, no shared state mutation
    if self._reviewer:
        logger.info("Reviewer analysing task {}…", task_id)
        notes = await self._reviewer(task.description, task.code_snippet or "")

        async with self._lock:
            task.review_notes = notes
            self._save()

        logger.success("Reviewer done for task {}", task_id)

    return task
```

**Persistence:**
- Updated `_load` method to handle `review_notes` field when loading from JSON
- `raw.get("review_notes")` safely handles missing field in old persisted files

**File:** `kanban/board.py:49-68, 150-177, 242-255`

### 5. Created Comprehensive Tests

**File:** `test/test_api.py` (4 new tests, all passing)

**Test Coverage:**

1. **`test_reviewer_sets_review_notes`**: Verifies reviewer populates review_notes after transition
   - Creates board with reviewer
   - Moves task through full workflow
   - Asserts review_notes is not None
   - Asserts GET /tasks/{id} returns review_notes

2. **`test_reviewer_concurrent_with_board_operations`**: Verifies reviewer runs concurrently
   - Uses slow reviewer (0.1s delay)
   - Starts reviewer on one task
   - While reviewer runs, performs GET request on another task
   - Asserts request completes quickly (doesn't wait for reviewer)

3. **`test_no_reviewer_no_review_notes`**: Verifies optional reviewer behavior
   - Creates board without reviewer
   - Moves task to review
   - Asserts review_notes remains None

4. **`test_reviewer_persists_to_disk`**: Verifies persistence of review notes
   - Creates board with reviewer, completes review
   - Creates new board with same persist path (no reviewer)
   - Asserts review_notes loaded correctly from disk

**File:** `test/test_api.py:491-612`

**Schema Test Fix:**
- Updated `test_task_response_schema` to include `history` and `review_notes` parameters

---

## Milestone Completion

All milestone criteria from `plans/sprint-02-reviewer.md` are met:

### ✅ `move_to_review` populates `task.review_notes` when a reviewer is configured

- `move_to_review` checks if `self._reviewer` is set
- If configured, calls reviewer with `task.description` and `task.code_snippet`
- Updates `task.review_notes` with reviewer output
- Saves state to disk

**Verified by:** `test_reviewer_sets_review_notes`, `test_reviewer_persists_to_disk`

### ✅ Reviewer runs **concurrently** with other board operations (outside lock)

- Reviewer executes after lock release (same pattern as coding assistant)
- Other operations can access board while reviewer runs
- Reviewer's lock acquisition only occurs when saving final result

**Verified by:** `test_reviewer_concurrent_with_board_operations`

### ✅ `GET /tasks/{id}` returns `review_notes`

- `TaskResponse` schema includes `review_notes` field
- `from_task` method copies `task.review_notes` to response
- API returns `review_notes` when populated, `null` when not

**Verified by:** `test_reviewer_sets_review_notes`

### ✅ Tests: assert review notes are set after transition; assert board remains usable while reviewer runs

- `test_reviewer_sets_review_notes` asserts review notes populated after `move_to_review`
- `test_reviewer_concurrent_with_board_operations` proves board remains usable during reviewer execution
- All 4 reviewer tests pass (4/4), plus 82 existing tests still pass (86 total)

**Verified by:** All tests in `test/test_api.py:491-612`

---

## What Was Learned

**LLM Chaining in Practice:**

- First LLM call (coding assistant) generates code from description
- Second LLM call (reviewer) analyzes both description AND code
- Sequential LLM calls enable more sophisticated workflows
- Each call builds on previous output — the essence of agent chaining

**Latency/Cost Tradeoffs:**

- Running reviewer adds 0.05s per task (mock) or real API latency
- Running outside lock minimizes impact on board responsiveness
- Reviewer is optional — board works without it for cost-sensitive deployments
- Demonstrates the tension between code quality (review) and throughput (latency)

**Context Window Management:**

- Reviewer receives both description and code snippet
- More context = better review, but higher token usage
- Pattern: prompt design significantly affects LLM output quality

**Async Concurrency Patterns:**

- Reviewer follows same pattern as coding assistant (outside lock)
- Enables multiple reviewers to run simultaneously on different tasks
- Lock held briefly only to save final result, not during reviewer execution

---

## Files Modified/Created

**Modified:**
- `kanban/assistants.py` — Added AsyncReviewerAssistant type and async_mock_reviewer function
- `kanban/domain.py` — Added review_notes field to Task dataclass
- `kanban/api.py` — Added review_notes to TaskResponse schema
- `kanban/board.py` — Added reviewer parameter, updated move_to_review, updated _load
- `test/test_api.py` — Added 4 reviewer tests, fixed 1 schema test

---

## Usage Example

```python
from kanban.board import AsyncKanbanBoard
from kanban.assistants import async_mock_reviewer

# Board with reviewer
board = AsyncKanbanBoard(
    persist_path=None,
    reviewer=async_mock_reviewer,
)

# Create and start task
task = await board.create_task("Fix Bug", "Fix crash on null input")
task = await board.move_to_in_progress(task.id)
print(f"Generated code:\n{task.code_snippet}")

# Move to review — reviewer runs automatically
task = await board.move_to_review(task.id)
print(f"Review notes:\n{task.review_notes}")
# Output:
# Review Checklist:
# - Contains TODO markers
# - Uses bare pass statements

# Approve task
task = await board.approve(task.id)
print(f"Task complete: {task.stage}")
```

**With Real LLM Reviewer:**

```python
from anthropic import AsyncAnthropic
from kanban.board import AsyncKanbanBoard

async def real_reviewer(description: str, snippet: str) -> str:
    """Uses Claude to review the generated code."""
    client = AsyncAnthropic()
    message = await client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        messages=[
            {
                "role": "user",
                "content": (
                    "You are a code reviewer. Review the following task and code.\n\n"
                    f"Task: {description}\n\n"
                    f"Code:\n{snippet}\n\n"
                    "Return a structured review with:\n"
                    "- Flags (critical issues)\n"
                    "- Risks (potential problems)\n"
                    "- Suggestions (improvements)\n"
                ),
            }
        ],
    )
    return message.content[0].text

board = AsyncKanbanBoard(
    persist_path=None,
    reviewer=real_reviewer,
)
```

---

## Next Steps

The reviewer system provides a foundation for:

- **Sprint 3: Reject Transition** — Use review notes to inform rejection decisions
- **Sprint 5: Skills System** — Skill-based reviewers for different task types
- **Sprint 6: Export** — Include review notes in session documentation

**Potential Enhancements:**

- Multi-stage review (security, performance, style)
- Reviewer confidence scoring
- Integration with code quality tools (linters, static analysis)
- Reviewer metrics (average review time, common issues)