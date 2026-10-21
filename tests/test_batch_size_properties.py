"""
What is and is not true about max_batch_size and the overhead heuristic.

True on every graph tested: the phase count never falls as the cap shrinks,
every capped plan scores at least the uncapped plan, and cap 1 scores at least
every other cap. NOT true: that each smaller cap scores strictly higher. The
hand-made graph below is a counterexample, found by the generated test set.
"""

from agent.engine import CloudRouteOptimizer
from agent.evaluate_generated import SHAPES, generate_case

CAPS = (None, 5, 3, 2, 1)


def _plan(components, cap):
    engine = CloudRouteOptimizer()
    engine.load_blueprint(components)
    return engine.calculate_cost_optimized_sequence(cap)


def test_a_smaller_cap_can_score_lower_than_a_larger_one():
    # A root and four dependents, every cost 1. Caps 3 and 2 both give 3 phases:
    #   cap 3: [root] [x1 x2 x3] [x4]  -> 1*3 + 3*2 + 1*1 = 10
    #   cap 2: [root] [x1 x2] [x3 x4]  -> 1*3 + 2*2 + 2*1 = 9
    comps = [{"id": "root", "daily_cost": 1.0, "dependencies": []}] + [
        {"id": f"x{i}", "daily_cost": 1.0, "dependencies": ["root"]} for i in range(1, 5)
    ]
    phases3, overhead3 = _plan(comps, 3)
    phases2, overhead2 = _plan(comps, 2)
    assert len(phases3) == len(phases2) == 3
    assert overhead3 == 10.0
    assert overhead2 == 9.0
    assert overhead3 > overhead2


def test_the_relations_that_do_hold_on_generated_graphs():
    for shape in SHAPES:
        for seed in range(1000, 1010):
            comps = generate_case(shape, seed)
            runs = [_plan(comps, cap) for cap in CAPS]
            counts = [len(p) for p, _ in runs]
            overheads = [o for _, o in runs]
            assert counts == sorted(counts), (shape, seed)
            assert all(o >= overheads[0] - 1e-9 for o in overheads), (shape, seed)
            assert all(o <= overheads[-1] + 1e-9 for o in overheads), (shape, seed)
