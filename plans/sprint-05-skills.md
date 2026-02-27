# Sprint 5 — Skills / Prompt Templates

**Concept: Configuration-Driven Behaviour / Externalised Prompts**
**Analogue: Craft Agents Skills system (YAML + `@mention`)**

---

## Goal

Move LLM prompts out of Python and into YAML skill files. The board selects a skill based on a `task_type` field on `Task`. Changing assistant behaviour requires no code change.

---

## Deliverables

- `Task` gains `task_type: str = "default"` field
- `skills/` directory with YAML skill files:
  ```
  skills/
    default.yaml
    backend.yaml
    frontend.yaml
    data.yaml
  ```
- Each skill file:
  ```yaml
  name: backend
  description: Python backend tasks
  prompt: |
    You are a backend engineer assistant.
    Generate a minimal Python skeleton with type hints and docstring.
    Task: {description}
  ```
- `SkillLoader` — loads and caches skills from disk, renders `{description}` template
- `async_claude_assistant` accepts a `Skill` and uses its prompt
- `POST /tasks` accepts optional `task_type` field

---

## Milestone Definition of Done

- [ ] Skills load from YAML at startup; missing skill falls back to `default`
- [ ] Correct prompt is sent to LLM per `task_type`
- [ ] Adding a new skill requires **zero Python changes** — YAML only
- [ ] Tests: assert correct prompt rendered per skill; assert fallback works

---

## What You'll Learn

Why prompt engineering belongs in config, not code. The separation between behaviour definition (YAML) and behaviour execution (Python). How `{template}` rendering scales to complex multi-variable prompts.

---

## Implementation Notes

### Domain Updates

```python
# kanban/domain.py
@dataclass
class Task:
    # existing fields...
    task_type: str = "default"
```

### Skill Definition

```python
# kanban/skills.py (new file)

from dataclasses import dataclass
from pathlib import Path
import yaml

@dataclass
class Skill:
    name: str
    description: str
    prompt: str
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1024

    def render(self, **variables: str) -> str:
        """Render the prompt template with provided variables."""
        return self.prompt.format(**variables)


class SkillLoader:
    def __init__(self, skills_dir: Path) -> None:
        self._skills_dir = skills_dir
        self._skills: dict[str, Skill] = {}
        self._load_all()

    def _load_all(self) -> None:
        """Load all YAML skill files from directory."""
        if not self._skills_dir.exists():
            logger.warning(f"Skills directory {self._skills_dir} not found")
            return

        for path in self._skills_dir.glob("*.yaml"):
            data = yaml.safe_load(path.read_text())
            skill = Skill(**data)
            self._skills[skill.name] = skill
            logger.info(f"Loaded skill: {skill.name}")

    def get(self, skill_name: str) -> Skill:
        """Get a skill by name, falling back to 'default'."""
        if skill_name in self._skills:
            return self._skills[skill_name]
        if "default" in self._skills:
            logger.warning(f"Skill '{skill_name}' not found, using 'default'")
            return self._skills["default"]
        raise ValueError(f"Skill '{skill_name}' not found and no default available")

    def list_skills(self) -> list[str]:
        """Return list of available skill names."""
        return list(self._skills.keys())
```

### Example Skill Files

```yaml
# skills/default.yaml
name: default
description: General purpose coding assistant
prompt: |
  Generate a minimal code snippet for the following task:
  
  Task: {description}
  
  Requirements:
  - Keep it simple and clear
  - Add comments for complex logic
system_prompt: "You are a helpful coding assistant."
temperature: 0.7
max_tokens: 512
```

```yaml
# skills/backend.yaml
name: backend
description: Python backend tasks
prompt: |
  You are a backend engineer assistant.
  Generate a minimal Python skeleton with type hints and docstring.
  
  Task: {description}
  
  Requirements:
  - Use type hints for all function parameters and return values
  - Include a descriptive docstring
  - Follow PEP 8 style
  - Return only the code, no explanation
system_prompt: "You are a senior backend engineer who values type safety and documentation."
temperature: 0.3
max_tokens: 512
```

```yaml
# skills/frontend.yaml
name: frontend
description: React/TypeScript frontend tasks
prompt: |
  You are a frontend engineer assistant.
  Generate a React component with TypeScript.
  
  Task: {description}
  
  Requirements:
  - Use functional components with hooks
  - Define proper TypeScript interfaces for props
  - Include basic styling with CSS modules or styled-components
  - Return only the component code, no explanation
system_prompt: "You are a senior frontend engineer specializing in React and TypeScript."
temperature: 0.5
max_tokens: 1024
```

```yaml
# skills/docs.yaml
name: docs
description: Documentation and markdown tasks
prompt: |
  You are a technical writer assistant.
  Generate clear, concise documentation for the following task:
  
  Task: {description}
  
  Requirements:
  - Use GitHub Flavored Markdown
  - Include code examples with syntax highlighting
  - Structure with clear headings (##, ###)
  - Keep explanations brief but complete
system_prompt: "You are a technical writer who values clarity and brevity."
temperature: 0.5
max_tokens: 2048
```

### Board Integration

```python
# kanban/board.py

class AsyncKanbanBoard:
    def __init__(
        self,
        skills_dir: Path | None = None,
        # ... other params
    ) -> None:
        # ... existing init
        self._skill_loader = SkillLoader(
            skills_dir or Path("skills")
        )

    async def create_task(
        self,
        title: str,
        description: str,
        task_type: str = "default",
        depends_on: list[str] | None = None,
    ) -> Task:
        deps = depends_on or []
        async with self._lock:
            # Validate skill exists
            try:
                self._skill_loader.get(task_type)
            except ValueError as e:
                raise ValueError(str(e))

            task = Task(
                title=title,
                description=description,
                task_type=task_type,
                depends_on=deps,
            )
            self._record(task, from_stage=None, to_stage=Stage.BACKLOG, note="created")
            self._tasks[task.id] = task
            self._save()

        return task

    async def move_to_in_progress(self, task_id: str) -> Task:
        # ... existing validation logic
        async with self._lock:
            task = self._get(task_id)
            self._assert_stage(task, Stage.BACKLOG)
            self._check_dependencies(task)

            wip_count = self._count_stage(Stage.IN_PROGRESS)
            if wip_count >= self._wip_limit:
                raise WIPLimitError(current=wip_count, limit=self._wip_limit)

            task.stage = Stage.IN_PROGRESS
            self._record(task, from_stage=Stage.BACKLOG, to_stage=Stage.IN_PROGRESS)
            self._save()

        await self._fire_hook("on_transition", task)

        # Get skill and render prompt
        skill = self._skill_loader.get(task.task_type)
        prompt = skill.render(description=task.description)

        logger.info("Using skill '{}' for task {}", skill.name, task_id)
        snippet = await self._assistant(prompt)

        async with self._lock:
            task.code_snippet = snippet
            self._save()

        return task
```

### API Updates

```python
# kanban/api.py

class CreateTaskRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=1)
    task_type: str = "default"
    depends_on: list[str] = Field(default_factory=list)

@app.get("/skills", response_model=list[str])
def list_skills(board: BoardDep) -> list[str]:
    """List available skill types."""
    return board._skill_loader.list_skills()
```

### Testing

```python
@pytest.mark.asyncio
async def test_skill_loading():
    loader = SkillLoader(Path("skills"))
    skills = loader.list_skills()
    assert "backend" in skills
    assert "frontend" in skills

@pytest.mark.asyncio
async def test_task_uses_correct_skill():
    board = AsyncKanbanBoard(skills_dir=Path("skills"))
    task = await board.create_task("Test", "Desc", task_type="backend")
    assert task.task_type == "backend"

    # Verify the rendered prompt contains backend-specific content
    await board.move_to_in_progress(task.id)
    # Check code_snippet has type hints (backend-specific)
    snippet = board.get_task(task.id).code_snippet
    assert snippet is not None
```
