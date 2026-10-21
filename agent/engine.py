"""
Core dependency-graph engine for cloud-route.

Two responsibilities:
  1. Compute a safe migration order (topological generations) and, within
     each safe layer, sequence components to reduce dual-billing overlap
     between old and new environments.
  2. Given a failed component, compute the minimal "blast radius" of
     downstream components that need to be rolled back — not a full reset.

The cost-overhead figure returned below is a heuristic proxy, not a
validated cost model. Treat it as a relative comparison signal between
sequencing strategies, not an absolute dollar prediction, until it's been
checked against real phase-duration data.
"""

import networkx as nx
from typing import List, Dict, Any, Tuple


class CloudRouteOptimizer:
    def __init__(self):
        self.graph = nx.DiGraph()

    def load_blueprint(self, components: List[Dict[str, Any]]) -> None:
        """Loads infrastructure components, pairing topology with daily run-costs."""
        known_ids = {comp["id"] for comp in components}
        for comp in components:
            for dep in comp.get("dependencies", []):
                if dep not in known_ids and dep not in self.graph:
                    raise ValueError(
                        f"{comp['id']} depends on unknown component {dep}. "
                        f"Check the name (for example a typo in a "
                        f"cloud-route/depends-on annotation)."
                    )

        for comp in components:
            self.graph.add_node(
                comp["id"],
                type=comp.get("type", "VM"),
                daily_cost=float(comp.get("daily_cost", 0.0)),
                region=comp.get("region"),
            )
            for dep in comp.get("dependencies", []):
                self.graph.add_edge(dep, comp["id"])

    def calculate_cost_optimized_sequence(
        self, max_batch_size: int | None = None
    ) -> Tuple[List[List[str]], float]:
        """
        Groups components into safe topological generations (each generation
        is only reachable once everything in prior generations is done), then
        orders components inside each generation cheapest-first so the most
        expensive components spend the least possible time double-billed
        across old and new environments.

        max_batch_size (optional) caps how many components migrate in the
        same phase. A generation larger than the cap is split into
        consecutive smaller phases, keeping the cheapest-first order. This
        never breaks dependency order, because components in one generation
        do not depend on each other. None means no cap.

        Returns ([] , 0.0) if the graph isn't a valid DAG - that's the signal
        the caller should treat as "unsafe to sequence, resolve the cycle first."
        """
        if max_batch_size is not None and (
            isinstance(max_batch_size, bool)
            or not isinstance(max_batch_size, int)
            or max_batch_size < 1
        ):
            raise ValueError("max_batch_size must be a positive integer or None")

        if not nx.is_directed_acyclic_graph(self.graph):
            return [], 0.0

        optimized_phases: List[List[str]] = []
        for generation in nx.topological_generations(self.graph):
            sorted_gen = sorted(
                generation, key=lambda node: self.graph.nodes[node]["daily_cost"]
            )
            if max_batch_size is None:
                optimized_phases.append(sorted_gen)
            else:
                for start in range(0, len(sorted_gen), max_batch_size):
                    optimized_phases.append(sorted_gen[start:start + max_batch_size])

        # Heuristic proxy only - see module docstring. Phase cost is weighted
        # by how many phases remain, so more (smaller) phases score higher.
        total_phases = len(optimized_phases)
        projected_parallel_overhead = 0.0
        for i, phase in enumerate(optimized_phases):
            phase_cost = sum(self.graph.nodes[node]["daily_cost"] for node in phase)
            projected_parallel_overhead += phase_cost * (total_phases - i)

        return optimized_phases, projected_parallel_overhead

    def compute_blast_radius_rollback(self, failed_component: str) -> List[str]:
        """
        Given a component that failed mid-migration, returns only the
        components that structurally depend on it (its descendants in the
        graph) — not every component in the system. The failed component
        itself is listed first since it's the root cause to address.
        """
        if failed_component not in self.graph:
            return []

        affected_nodes = nx.descendants(self.graph, failed_component)
        blast_radius = list(affected_nodes)
        blast_radius.insert(0, failed_component)

        return blast_radius

    def check_residency(self, allowed_regions=None) -> Dict[str, Any]:
        """
        Data-residency check. A plain graph fact, like the phases.

        Each component may carry a "region". Returns:
          out_of_policy: components whose region is not in allowed_regions
              (always empty when allowed_regions is None).
          cross_region_dependencies: [dependency, dependent] pairs whose two
              regions are both known and different.
          unassigned: components with no region. They are reported, never
              assumed compliant.
        """
        if isinstance(allowed_regions, str):
            raise ValueError("allowed_regions must be a list of region names, not a string")
        allowed = None if allowed_regions is None else set(allowed_regions)

        def region(node):
            return self.graph.nodes[node].get("region")

        out_of_policy = []
        unassigned = []
        for node in self.graph.nodes:
            r = region(node)
            if r is None:
                unassigned.append(node)
            elif allowed is not None and r not in allowed:
                out_of_policy.append(node)

        cross = [
            [dep, node]
            for dep, node in self.graph.edges
            if region(dep) is not None
            and region(node) is not None
            and region(dep) != region(node)
        ]
        return {
            "out_of_policy": sorted(out_of_policy),
            "cross_region_dependencies": sorted(cross),
            "unassigned": sorted(unassigned),
        }
