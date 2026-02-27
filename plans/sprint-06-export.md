# Sprint 6 — Session Export / Sharing

**Concept: Documentation as a First-Class Output**
**Analogue: Craft Agents session sharing, attachment to Linear/GitHub**

---

## Goal

Make a task's full lifecycle exportable as a human-readable Markdown document — decision trail, generated code, review notes, rejection reasons — so it can be attached to a PR, issue, or shared with a teammate.

---

## Deliverables

- `GET /tasks/{id}/export?format=markdown` endpoint
- Rendered output includes:
  - Task metadata (title, description, type, created at)
  - Generated code snippet (fenced code block)
  - Review notes (if present)
  - Full audit trail (stage transitions, timestamps, rejection reasons)
  - `retry_count` if > 0
- `TaskExporter` — pure function, `(Task) -> str`, no I/O, easily testable
- Optional: `format=json` returns structured export for programmatic use

---

## Milestone Definition of Done

- [ ] Export renders correctly for tasks in every stage
- [ ] Rejected tasks include rejection reasons in the audit section
- [ ] Export for a task with no snippet or review notes renders gracefully (no empty sections)
- [ ] Tests: snapshot-style assertions on rendered Markdown output

---

## What You'll Learn

How to think of agent sessions as documents, not just side effects. How audit history design compounds in value over time. The difference between operational data (board state) and archival data (export).

---

## Implementation Notes

### Exporter Module

```python
# kanban/exporter.py (new file)

from datetime import datetime

def export_task_markdown(task: Task) -> str:
    """Export a task as a human-readable Markdown document."""
    lines = [
        f"# {task.title}",
        "",
    ]

    # Metadata
    lines.extend([
        "## Metadata",
        "",
        f"- **ID:** `{task.id}`",
        f"- **Type:** `{task.task_type}`",
        f"- **Stage:** `{task.stage.value}`",
        f"- **Created:** {task.created_at}",
        f"- **Retry Count:** {task.retry_count}",
    ])

    if task.depends_on:
        deps_str = ", ".join(f"`{dep}`" for dep in task.depends_on)
        lines.append(f"- **Depends On:** {deps_str}")

    lines.append("")

    # Dependencies status
    if task.depends_on:
        lines.extend([
            "### Dependencies",
            "",
        ])
        lines.extend([
            f"- `{dep}`" for dep in task.depends_on
        ])
        lines.append("")

    # Description
    lines.extend([
        "## Description",
        "",
        task.description,
        "",
    ])

    # Code snippet
    if task.code_snippet:
        lines.extend([
            "## Generated Code",
            "",
            "```python",
            task.code_snippet,
            "```",
            "",
        ])

    # Review notes
    if task.review_notes:
        lines.extend([
            "## Review Notes",
            "",
            task.review_notes,
            "",
        ])

    # Audit trail
    lines.extend([
        "## Audit Trail",
        "",
        "| From | To | Timestamp | Note |",
        "|------|-----|-----------|------|",
    ])

    for entry in task.history:
        from_stage = entry.from_stage.value if entry.from_stage else "Created"
        to_stage = entry.to_stage.value
        note = entry.note or ""
        timestamp = _format_timestamp(entry.timestamp)
        lines.append(f"| `{from_stage}` | `{to_stage}` | {timestamp} | {note} |")

    lines.append("")

    return "\n".join(lines)


def export_task_json(task: Task) -> dict:
    """Export a task as structured JSON for programmatic use."""
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "stage": task.stage.value,
        "created_at": task.created_at,
        "retry_count": task.retry_count,
        "depends_on": task.depends_on,
        "code_snippet": task.code_snippet,
        "review_notes": task.review_notes,
        "history": [
            {
                "from_stage": entry.from_stage.value if entry.from_stage else None,
                "to_stage": entry.to_stage.value,
                "timestamp": entry.timestamp,
                "note": entry.note,
            }
            for entry in task.history
        ],
    }


def _format_timestamp(iso_timestamp: str) -> str:
    """Format ISO timestamp for display."""
    try:
        dt = datetime.fromisoformat(iso_timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (ValueError, AttributeError):
        return iso_timestamp
```

### Board Integration

```python
# kanban/board.py

from kanban.exporter import export_task_markdown, export_task_json

class AsyncKanbanBoard:
    # ... existing methods

    def export_task(self, task_id: str, format: str = "markdown") -> str | dict:
        """Export a task in the specified format."""
        task = self._get(task_id)
        
        if format == "json":
            return export_task_json(task)
        else:
            return export_task_markdown(task)
```

### API Endpoint

```python
# kanban/api.py

from fastapi import Query
from fastapi.responses import Response

@app.get("/tasks/{task_id}/export")
def export_task(
    task_id: str,
    board: BoardDep,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
) -> Response | dict:
    """Export a task as Markdown or JSON."""
    try:
        if format == "json":
            data = board.export_task(task_id, format="json")
            return data
        else:
            markdown = board.export_task(task_id, format="markdown")
            return Response(content=markdown, media_type="text/markdown; charset=utf-8")
    except TaskNotFoundError as exc:
        raise _http(exc)
```

### Example Output

**Markdown Export:**

```markdown
# CSV Parser

## Metadata

- **ID:** `abc12345`
- **Type:** `backend`
- **Stage:** `done`
- **Created:** 2024-01-15T10:30:00Z
- **Retry Count:** 1

### Dependencies

- `dep00123`

## Description

Write a function that reads a CSV file and returns a list of dicts.

## Generated Code

```python
from typing import List, Dict, Any
import csv


def read_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    Read a CSV file and return its contents as a list of dictionaries.

    Args:
        file_path: Path to the CSV file.

    Returns:
        A list of dictionaries, where each dictionary represents a row.
    """
    with open(file_path, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return list(reader)
```

## Review Notes

✓ Code reviewed for: Write a function that reads a CSV...
Issues: None

## Audit Trail

| From | To | Timestamp | Note |
|------|-----|-----------|------|
| Created | backlog | 2024-01-15 10:30:00 UTC | created |
| backlog | in_progress | 2024-01-15 10:35:00 UTC |  |
| in_progress | review | 2024-01-15 10:40:00 UTC |  |
| review | backlog | 2024-01-15 10:45:00 UTC | Missing error handling |
| backlog | in_progress | 2024-01-15 10:50:00 UTC |  |
| in_progress | review | 2024-01-15 10:55:00 UTC |  |
| review | done | 2024-01-15 11:00:00 UTC |  |
```

### Testing

```python
@pytest.mark.asyncio
async def test_export_markdown(board):
    task = await board.create_task("Test", "Description")
    await board.move_to_in_progress(task.id)
    await board.move_to_review(task.id)

    markdown = board.export_task(task.id, format="markdown")

    assert "# Test" in markdown
    assert "## Metadata" in markdown
    assert "## Generated Code" in markdown
    assert task.code_snippet in markdown
    assert "## Audit Trail" in markdown


@pytest.mark.asyncio
async def test_export_json(board):
    task = await board.create_task("Test", "Description")
    await board.move_to_in_progress(task.id)

    data = board.export_task(task.id, format="json")

    assert data["id"] == task.id
    assert data["title"] == "Test"
    assert data["stage"] == "in_progress"
    assert data["code_snippet"] == task.code_snippet
    assert isinstance(data["history"], list)


def test_export_endpoint(client):
    resp = client.post("/tasks", json={"title": "Export Me", "description": "Test"})
    task_id = resp.json()["id"]

    # Markdown export
    md_resp = client.get(f"/tasks/{task_id}/export?format=markdown")
    assert md_resp.status_code == 200
    assert md_resp.headers["content-type"].startswith("text/markdown")
    assert "# Export Me" in md_resp.text

    # JSON export
    json_resp = client.get(f"/tasks/{task_id}/export?format=json")
    assert json_resp.status_code == 200
    assert json_resp.json()["id"] == task_id
```

### Snapshot Testing

For more robust testing of Markdown output, consider using snapshot testing:

```python
# test/test_export_snapshots.py

import pytest
from pathlib import Path

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


@pytest.mark.asyncio
async def test_export_snapshot(board, snapshot):
    task = await board.create_task(
        title="Snapshot Test",
        description="Test snapshot functionality",
        task_type="backend",
    )
    await board.move_to_in_progress(task.id)
    await board.move_to_review(task.id)
    await board.approve(task.id)

    markdown = board.export_task(task.id, format="markdown")
    snapshot.assert_match(markdown)
```

Run with: `pytest --snapshot-update` to create/update snapshots.
