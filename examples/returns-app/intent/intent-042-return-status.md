---
id: intent-042
title: Show return status on the order page
status: accepted
author: lead
---

# Intent 042: return status

## Problem

Shoppers with an open return cannot see its state and call support to ask. Support handles about 300 of these calls a week.

## Outcome

The order page shows each return on the order and its current state, so a shopper can answer "where is my return?" without calling.

## Users and systems

- Shoppers viewing their own order.
- Returns service (source of return states); read-only from this slice.

## Constraints

- Read-only. No new tables: returns already exist in the `returns` projection.

## Out of scope

- Starting a return, refund amounts, carrier tracking links.

## Open questions

None.
