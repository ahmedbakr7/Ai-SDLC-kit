# Page: /orders/{id}

Requirements: F-042-5, F-042-6, N-042-1.

| State | Shows |
|---|---|
| loaded, has returns | heading "Returns", one row per return: id + state label |
| loaded, no returns | no returns heading or empty box |
| unknown order | 404 page |
| unknown state value | label "Unknown" |

State labels: requested -> "Requested", approved -> "Approved", rejected -> "Rejected", received -> "Received", refunded -> "Refunded".
