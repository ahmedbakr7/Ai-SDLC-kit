# CONTRACTS.md — slice 042

## HTTP

### GET /v1/orders/{id}/returns

Authz: buyer of `{id}` or support role.

Response `200`:

```json
{
  "order_id": "ord_…",
  "returns": [
    { "id": "ret_…", "state": "requested" }
  ]
}
```

`state` enum: `requested` | `approved` | `rejected` | `received` | `refunded`

Empty: `{ "order_id": "…", "returns": [] }`

Errors: `404` order not found; `403` not allowed.

## Events

None in this slice.

## Tables

None new in this slice (reads existing `returns` projection).
