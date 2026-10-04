---
sdlc: approval
ticket: T-042-02
commit: {commit}
verdict: approve
role: review
reviewer: fake-reviewer
---


# Review T-042-02: Order page returns section

## Gate

Build evidence `evidence/T-042-02.build.json`: pass at `{commit}`, every required check green, all 3 AC proven.

## Acceptance criteria

| AC | Proof | What the test actually asserts |
|---|---|---|
| AC-1 | `app/test_pages.py::test_lists_returns_with_labels` (passed) | real dispatch of `/orders/ord_1`; visible labels "Requested", "Refunded" |
| AC-2 | `app/test_pages.py::test_no_returns_no_heading` (passed) | rendered page for an order with no returns has no "Returns" text |
| AC-3 | `app/test_pages.py::test_unknown_state_renders_unknown` (passed) | unknown state renders "Unknown" and the page answers 200 |

## Findings

None.

## Checklist

- Contract: `/orders/{id}` matches CONTRACTS `pages`; no new route, table or event.
- Patterns: data comes from `app.returns`; output escaped with `html.escape`.
- Duplication: no copied logic; labels live in one table.
- Tests exercise behaviour through `dispatch`, not source text.
