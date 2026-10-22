"""The security scan evaluator: passes on the real scan, and catches every broken copy."""
from agent import evaluate_security_scan as ev
from agent import security_scan


def test_real_scan_passes_every_check():
    for name, passed, total, _ in ev.run_checks(security_scan.scan_workloads):
        assert passed == total, name


def test_every_broken_copy_is_caught():
    for flaw in ev.FLAWS:
        res = ev.run_checks(ev.flawed_scan(flaw))
        assert any(p != t for _, p, t, _ in res), flaw


def test_the_flawless_copy_matches_the_real_scan():
    flawless = ev.flawed_scan(None)
    rng_cases = ev._cases()[:300]
    for wl, _, _ in rng_cases:
        assert ev.triples(flawless(wl)) == ev.triples(security_scan.scan_workloads(wl))


def test_expected_root_matches_known_cases():
    A = ev.ABSENT
    assert ev.expected_root(A, A, A, A) is True        # nothing set: may run as root
    assert ev.expected_root(True, A, A, A) is False    # runAsNonRoot true
    assert ev.expected_root(A, 0, A, A) is True        # user 0
    assert ev.expected_root(True, 0, A, A) is True     # user 0 wins over runAsNonRoot
    assert ev.expected_root(A, A, A, 1000) is False    # pod gives a non-zero user
    assert ev.expected_root(A, 1000, A, 0) is False    # container overrides the pod
