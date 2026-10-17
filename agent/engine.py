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
            )
            for dep in comp.get("dependencies", []):
                self.graph.add_edge(dep, comp["id"])

    def calculate_cost_optimized_sequence(self) -> Tuple[List[List[str]], float]:
        """
        Groups components into safe topological generations (each generation
        is only reachable once everything in prior generations is done), then
        orders components inside each generation cheapest-first so the most
        expensive components spend the least possible time double-billed
        across old and new environments.

        Returns ([] , 0.0) if the graph isn't a valid DAG — that's the signal
        the caller should treat as "unsafe to sequence, resolve the cycle first."
        """
        if not nx.is_directed_acyclic_graph(self.graph):
            return [], 0.0

        raw_generations = list(nx.topological_generations(self.graph))
        optimized_phases = []
        projected_parallel_overhead = 0.0

        for i, generation in enumerate(raw_generations):
            sorted_gen = sorted(generation, key=lambda node: self.graph.nodes[node]["daily_cost"])
            optimized_phases.append(sorted_gen)

            # Heuristic proxy only — see module docstring.
            generation_cost = sum(self.graph.nodes[node]["daily_cost"] for node in sorted_gen)
            projected_parallel_overhead += generation_cost * (len(raw_generations) - i)

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
