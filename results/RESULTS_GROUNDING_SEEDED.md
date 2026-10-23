# Planted-fault test of the grounding scan

Base: 43 real responses the scan did not flag. One planted sentence per response and kind.

| Planted sentence | Built for | Original scan | With extra checks |
|---|---|---|---|
| invented service, capitalized hyphenated | yes (per its docstring) | 43/43 | 43/43 |
| same, with a typographic hyphen | yes (per its docstring) | 43/43 | 43/43 |
| invented service, lowercase hyphenated | no | 0/43 | 43/43 |
| invented service, single capitalized word | no | 0/43 | 0/43 |
| invented cost for a real service | no | 0/43 | 43/43 |
| invented dependency | no | 0/43 | 43/43 |
| wrong phase count | no | 0/43 | 43/43 |
| phrase on the scan's list | yes (per its docstring) | 43/43 | 43/43 |
| claim not on the list | no | 0/43 | 0/43 |
| note id the tool never returned | yes (per its docstring) | 43/43 | 43/43 |
| control: true restatement | harmless control | 0/43 | 0/43 |
| control: negated listed phrase | harmless control | 0/43 | 0/43 |

False alarms of the extra checks on all 48 real responses (no planted sentence): 0 distinct flag(s).


The sentences were written by one person and are not a sample of what a model would say. The table shows what the scan does and does not notice for these kinds of fault only.
