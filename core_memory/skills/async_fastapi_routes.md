---
name: Async FastAPI Routes
description: Guidelines for generating high-performance async Python backend endpoints.
trigger_keywords:
  ["api", "endpoint", "fastapi", "route", "backend", "server.py", "async"]
---

# FastAPI Backend Skill

When generating backend routes or modifying server architecture, you must:

1. Always use `async def` for endpoints.
2. Leverage Pydantic models for request/response validation.
3. Inject the `get_logger` module for comprehensive telemetry.
4. Catch all internal exceptions and return appropriate HTTP exceptions instead of crashing.
