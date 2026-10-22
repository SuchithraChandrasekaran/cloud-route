# LLM-only baseline

Model: nvidia/nemotron-3-super-120b-a12b, no tools, temperature 0. Graphs: 55 (11 shapes, same generator as the 550-case set).

| Measure | LLM only |
|---|---|
| Reply parsed | 47/55 |
| Every component exactly once | 45/55 |
| No dependency violated | 44/55 |
| Complete and safe | 43/55 |
| Also the fewest phases | 43/55 |

Replies cut off at the token limit (30000): 8. Unparsed replies that were NOT cut off: 0.

## By shape (complete and safe)

| Shape | ok | avg components |
|---|---|---|
| chain | 5/5 | 23 |
| fan-out | 5/5 | 81 |
| fan-in | 4/5 | 108 |
| layered | 4/5 | 82 |
| diamonds | 5/5 | 79 |
| sparse random | 3/5 | 77 |
| dense random | 5/5 | 27 |
| chain with branches | 2/5 | 57 |
| isolated | 5/5 | 105 |
| hub | 1/5 | 103 |
| wide then deep | 4/5 | 85 |

Total dependency violations across all answers: 9.

The engine's result on the same generator is in RESULTS_GENERATED.md.

## Engine on the same graphs

Same graphs, same checker. The model rows exclude API errors.

| Measure | LLM only | Engine |
|---|---|---|
| Reply finished and parsed | 47/55 | n/a |
| Every component exactly once | 45/55 | 55/55 |
| Every dependency in an earlier phase | 44/55 | 55/55 |
| Complete and safe | 43/55 | 55/55 |
| Fewest possible phases | 43/55 | 55/55 |

