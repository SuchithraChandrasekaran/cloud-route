# Retrieval evaluation

Method: hybrid (min score 0.45). Notes: 12. Questions: 28 (hand-written).

| Question set | n | right note first | right note in top 3 | MRR |
|---|---|---|---|---|
| Plain wording | 12 | 12/12 | 12/12 | 1.00 |
| Paraphrased | 12 | 8/12 | 9/12 | 0.71 |
| All in scope | 24 | 20/24 | 21/24 | 0.85 |

Out-of-scope questions that correctly returned nothing: 4/4.

## Misses (right note not first)

- [para] Customers wrote orders while we were duplicating the store. Will they appear?  expected ['fm-02'], got ['fm-01', 'fm-02', 'fm-11']
- [para] Our plan ordered things wrongly because one call is only set in a config value.  expected ['fm-06'], got ['fm-11', 'fm-07', 'fm-05']
- [para] Pages return errors for the first minute after a restart.  expected ['fm-08'], got ['fm-04', 'fm-12', 'fm-05']
- [para] How much do we have to undo if the auth service has to be reversed?  expected ['fm-10'], got ['fm-09', 'fm-05', 'fm-01']

Questions were written by one person; results show retrieval on these questions only.
