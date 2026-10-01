# CONTRACTS.md

The only routes, pages, tables and events that may exist. `sdlc gate` compares the
fenced blocks below with the code on every PR: a route in code that is not here
fails, and a client call to a path no route here serves fails. Change this file in
an architect PR; code follows.

## Conventions

- Base path: <e.g. /api/v1>. Write paths exactly as the router serves them.
- Error envelope: `{"error": {"code": "<snake_case>", "message": "<text>"}}`.
- Auth: <session cookie / bearer>; unauthenticated -> <401 | 404>.
- Authz order: <who may see what; what a non-member gets>.

## Routes

One line per route: `METHOD /path key=value...`. `owner=` is the ticket that builds
it; `sample=` is a concrete path the smoke probe calls.

```routes
GET /api/v1/things/{id}  owner=T-001-03  sample=/api/v1/things/demo
```

### GET /api/v1/things/{id}

Request: <params, body schema>
Response `200`: <schema, with an example>
Errors: `404 not_found` <when>; `403 forbidden` <when>

## Pages

```pages
/things/{id}  owner=T-001-05  sample=/things/demo
```

## Tables

```tables
things  id uuid pk, name text not null, created_at timestamptz
```

## Events

```events
thing.created  {id, name}
```
