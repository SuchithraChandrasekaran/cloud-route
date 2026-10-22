# Security scan evaluation

Seed 20261022; 2000 random pods plus two exhaustive tables. Expected findings come from the plan used to build each pod.

| Check | Passed |
|---|---|
| Findings equal the planted faults (random pods) | 2000/2000 |
| No secret value appears in any finding | 2000/2000 |
| Same result whatever the workload order | 2000/2000 |
| The input is left unchanged | 2000/2000 |
| Every finding has the four fields and a known check | 2000/2000 |
| Every runAsNonRoot / runAsUser combination (81) | 81/81 |
| Image strings: tags, digests, registry ports (10) | 10/10 |

Broken copies of the scan caught: 13/13.
The copy with no flaw reproduces the real scan on 2000/2000 cases (it must, or the copies prove nothing).

| Flaw | Caught by |
|---|---|
| ignores init containers | Findings equal the planted faults (random pods) |
| never flags a missing tag | Findings equal the planted faults (random pods), Image strings: tags, digests, registry ports (10) |
| ignores the latest tag | Findings equal the planted faults (random pods), Image strings: tags, digests, registry ports (10) |
| secret match is case-sensitive | Findings equal the planted faults (random pods) |
| flags secrets that use valueFrom | Findings equal the planted faults (random pods) |
| flags an empty secret value | Findings equal the planted faults (random pods) |
| counts the string 'true' as privileged | Findings equal the planted faults (random pods) |
| ignores runAsUser 0 | Findings equal the planted faults (random pods), Every runAsNonRoot / runAsUser combination (81) |
| ignores the pod-level security context | Findings equal the planted faults (random pods), Every runAsNonRoot / runAsUser combination (81) |
| checks only the memory limit | Findings equal the planted faults (random pods) |
| puts the secret value in the finding | No secret value appears in any finding |
| treats a digest as unpinned | Findings equal the planted faults (random pods), Image strings: tags, digests, registry ports (10) |
| accepts runAsNonRoot false as safe | Findings equal the planted faults (random pods), Every runAsNonRoot / runAsUser combination (81) |

One author wrote the scan and this evaluator, and the root and image expectations restate the rules in another form. It checks the five rules only.
