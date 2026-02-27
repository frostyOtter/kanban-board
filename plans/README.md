# Kanban Board — Project Roadmap

> Milestone-based sprints. Each sprint ships independently and teaches a distinct engineering concept.
> Inspired by patterns from [Craft Agents OSS](https://github.com/lukilabs/craft-agents-oss).

---

## Overview

Each sprint is self-contained — ship it, test it, then move on. Start with Sprint 1, as every subsequent sprint depends on hooks existing.

---

## Sprint Summary

| Sprint | Concept | Craft Agents Analogue | Key Deliverable | Status |
|--------|---------|----------------------|-----------------|--------|
| 1 | Observer / Event-Driven | Hooks system | `HookRegistry` + `on_transition` | 🔵 To Do |
| 2 | LLM Chaining | `call_llm` tool | `reviewer_assistant` + `review_notes` | 🔵 To Do |
| 3 | State Machine Depth | Session re-open | `reject()` + `retry_count` | 🔵 To Do |
| 4 | Background Scheduler | Cron scheduling | `stale_task_monitor` in lifespan | 🔵 To Do |
| 5 | Config-Driven Behaviour | Skills system | YAML skills + `SkillLoader` | 🔵 To Do |
| 6 | Docs as Output | Session sharing | `/export` endpoint + `TaskExporter` | 🔵 To Do |

---

## Sprint Dependencies

```
Sprint 1: Hooks System
    ├─> Sprint 2: Reviewer Assistant (uses hooks)
    ├─> Sprint 3: Reject Transition (uses hooks)
    └─> Sprint 4: Stale Monitor (uses hooks)

Sprint 5: Skills System (uses hooks)
    └─> Sprint 2: Reviewer Assistant (optional: skill-based reviewer)

Sprint 6: Export (depends on Sprints 2, 3, 5 features)
    ├─> Reviewer Assistant (review_notes)
    ├─> Reject Transition (retry_count, audit trail)
    └─> Skills System (task_type)
```

---

## Recommended Sequence

1. **Sprint 1** — Must start here. Foundation for all future work.
2. **Sprint 2** — Adds LLM chaining, builds on hooks.
3. **Sprint 3** — Adds non-happy path flow, builds on hooks.
4. **Sprint 4** — Adds background automation, builds on hooks.
5. **Sprint 5** — Adds config-driven behaviour, builds on hooks.
6. **Sprint 6** — Adds documentation output, integrates all previous features.

---

## Learning Progression

| Sprint | Core Concept | Engineering Value |
|--------|--------------|-------------------|
| 1 | Observer/Event-driven | Decouple side effects from core logic |
| 2 | LLM Chaining | Multi-stage agent workflows, latency/cost tradeoffs |
| 3 | State Machine Depth | Handle non-linear flows, audit trails for debugging |
| 4 | Background Async | Long-running agent monitoring, graceful shutdown |
| 5 | Config-Driven | Swappable behaviour without code changes |
| 6 | Documentation as Output | Agent work as shareable artifacts |

---

## Getting Started

### Prerequisites

- Python 3.14+
- FastAPI, pytest, pytest-asyncio, loguru
- Understanding of asyncio, FastAPI lifespan

### Workflow

1. Read the sprint document (`plans/sprint-XX-feature.md`)
2. Implement the deliverables
3. Write tests for each milestone
4. Verify all DoD items are checked
5. Move to the next sprint

---

## Sprint Documents

- [Sprint 1: Hooks System](./sprint-01-hooks.md)
- [Sprint 2: Reviewer Assistant](./sprint-02-reviewer.md)
- [Sprint 3: Reject Transition](./sprint-03-reject.md)
- [Sprint 4: Stale Task Monitor](./sprint-04-stale-monitor.md)
- [Sprint 5: Skills System](./sprint-05-skills.md)
- [Sprint 6: Session Export](./sprint-06-export.md)

---

## Questions?

Refer to each sprint's implementation notes for detailed guidance, testing strategies, and examples.
