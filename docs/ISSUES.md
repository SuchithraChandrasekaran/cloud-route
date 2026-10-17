# Known issues from live runs

Found on Oct 17, 2026, running all four Nemotron modes against the live K3s cluster.

1. **Misleading arrows in explain.** Components in the same phase are listed with arrows, which suggests a dependency chain. They are independent; order within a phase is only a cheapest-first tiebreak.
2. **Replan has nothing to adjust.** The engine exposes no parameters, so "prioritize downtime over cost" correctly changes nothing. Needs one real engine option.
3. **Propose-infra is generic.** It ignores the actual services in the cluster and names tools (Datadog, CloudWatch) the engine never returned.
4. **Annotation code is untested.** The cloud-route/depends-on handling in cluster_source.py has no unit test yet.
