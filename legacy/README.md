# Legacy Implementations

This directory contains reference implementations of earlier versions of the Kanban board. These are kept for historical purposes and are not used in production.

## Files

- `kanban_board.py` - Original synchronous implementation
- `async_kanban_board.py` - First asynchronous implementation (pre-package structure)
- `test_kanban_board.py` - Tests for the sync implementation
- `test_async_kanban_board.py` - Tests for the async implementation (legacy)

## Current Production Code

The modern implementation is in the `kanban/` package:
- `kanban/board.py` - Core board logic with hooks, audit log, reviewer, rejection, and stale monitor
- `kanban/api.py` - FastAPI REST API
- `kanban/domain.py` - Domain models
- `kanban/hooks.py` - Hook system
- `kanban/assistants.py` - Coding and reviewer assistants

## Tests for Current Implementation

Modern tests are in the `test/` directory:
- `test/test_api.py` - API endpoint tests
- `test/test_hooks.py` - Hook system tests
- `test/test_board.py` - Board logic tests (including stale monitor)

## Why This Exists

During development, the board evolved through several iterations:
1. **Sync Board** - Simple synchronous version
2. **Async Board (legacy)** - First async version with WIP limits
3. **Modern Board** - Packaged version with hooks, audit log, reviewer, rejection, and stale monitor

The legacy files demonstrate the evolution and can serve as reference for understanding the design decisions.
