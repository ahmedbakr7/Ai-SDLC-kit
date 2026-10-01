---
name: frontend-patterns
description: Locked page patterns for the returns example (server-rendered HTML, escaping, tokens). Load on every frontend ticket.
---

# Frontend patterns (locked by ADR-0001)

Change only with a superseding ADR.

| Concern | Pattern | Where |
|---|---|---|
| Pages | pure function `render_<page>(...) -> str`, registered in `ROUTES` with kind `page` | `app/pages.py`, `app/server.py` |
| Data | pages call `app.returns`; never the HTTP API of the same process | `app/returns.py` |
| Escaping | every interpolated value goes through `html.escape` | `app/pages.py` |
| Styling | CSS variables from `design/DESIGN.md` only | inline `<style>` |
| States | every page handles the states in its `design/pages/*.md` table | |

## Rules

- Unknown values render a safe fallback (e.g. "Unknown"); a page never answers 500 for bad data.
- Unit tests call the render function and assert on visible text, not on markup internals.
