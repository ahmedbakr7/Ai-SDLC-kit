---
id: ADR-0001
title: Stack for the example product
status: accepted
date: 2026-10-01
source: spec-042
supersedes: none
---

# ADR-0001: Python stdlib HTTP server

## Context

The example has to run anywhere the kit runs, with nothing to install.

## Decision

- Python 3.11+ standard library only: `http.server` for HTTP, `unittest` for tests.
- JSON error envelope: `{"error": {"code": "<snake_case>", "message": "<text>"}}`.
- Routes are registered in one table in `app/server.py`; `tools/routes.py` prints it for the gate.

## Consequences

- No framework router: every route is explicit and greppable.
- Tests call handlers directly (unit) and over real HTTP (integration).

## Not decided

Nothing.
