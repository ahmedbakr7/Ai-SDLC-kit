# CONTRACTS.md

The only routes, pages, tables and events that may exist. The gate compares the
fenced blocks below with the code on every PR. Change this file in an architect
PR first; code follows.

## Conventions

- JSON over HTTP. Errors use one envelope: `{"error": {"code": "<snake_case>", "message": "<text>"}}`.
- Unknown resource: `404` + envelope with `code: "not_found"`.

## Routes

```routes
GET /api/orders/{id}/returns  owner=T-042-01  sample=/api/orders/ord_1/returns
```

### GET /api/orders/{id}/returns

Response `200`:

```json
{ "order_id": "ord_1", "returns": [ { "id": "ret_1", "state": "requested" } ] }
```

- `state`: `requested` | `approved` | `rejected` | `received` | `refunded`
- No returns: `{ "order_id": "ord_2", "returns": [] }`
- Unknown order: `404` `not_found`

## Pages

```pages
/orders/{id}  owner=T-042-02  sample=/orders/ord_1
```

### /orders/{id}

Server-rendered HTML. See `design/pages/order.md`.

## Tables

```tables
returns  read-only projection owned by the returns service
```

## Events

None.
