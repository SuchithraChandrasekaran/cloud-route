# Plain topological sort against the engine

Graphs: 550 (11 shapes). The baseline is Kahn's algorithm with ids in plain order; the engine sorts each generation cheapest-first.

| Cap | Graphs | Same phases as the engine | Engine overhead matches our formula | Engine <= plain | Engine strictly lower | Mean reduction when lower |
|---|---|---|---|---|---|---|
| none | 550 | 550/550 | 550/550 | 550/550 | 0/550 | 0.0% |
| 2 | 550 | 71/550 | 550/550 | 550/550 | 479/550 | 12.4% |
| 3 | 550 | 89/550 | 550/550 | 550/550 | 461/550 | 12.0% |

With no cap the two give the same phases and the same overhead, because the overhead depends only on each phase's total cost. A cap makes the order inside a generation matter.
The overhead is the engine's own heuristic, not a measured cost. Rollback sets, residency, right-sizing and the security scan have no counterpart in a plain sort.
