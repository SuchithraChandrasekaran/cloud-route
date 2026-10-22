"""Independent evaluation of agent/security_scan.py.

Pod specs are built at random from a PLAN (this container has no memory limit, that
variable holds a literal secret, ...). The expected findings come from the plan, not
from reading the scan's code. Besides the random cases there are two exhaustive tables
(every runAsNonRoot/runAsUser combination, and a list of awkward image strings) and
property checks (no secret value in any finding, order independence, input untouched).
Then deliberately broken copies of the scan must each fail at least one check.

Limits, stated plainly: one author wrote the scan and this evaluator, and the expected
values for the root and image rules restate the rules in a different form. The plan
vocabulary covers the five rules; it says nothing about what the scan does not check.

Run:  python -m agent.evaluate_security_scan [--write RESULTS_SECURITY_SCAN.md]
"""
import copy
import itertools
import random
import re
import sys
from collections import Counter

from agent import security_scan as real

CASES = 2000
SEED = 20261022
ABSENT = object()

# --------------------------------------------------------------------------
# Plan vocabulary
# --------------------------------------------------------------------------
IMAGES = [  # (image, flagged as unpinned/latest)
    ("registry.io/app:1.4.2", False), ("app:latest", True), ("app", True),
    ("localhost:5000/app", True), ("localhost:5000/app:2.0", False),
    ("repo/app@sha256:abc123", False), ("repo/app:v1@sha256:abc123", False),
    ("repo/app:Latest", False), ("", True), (None, True),
]
SECRET_NAMES = ["DB_PASSWORD", "passwd", "API_KEY", "apikey", "api-key", "PRIVATE_KEY",
                "privatekey", "SECRET_TOKEN", "JWT_TOKEN", "aws_credential", "MySecret"]
PLAIN_NAMES = ["PORT", "LOG_LEVEL", "DB_HOST", "NODE_ENV", "TIMEOUT", "SERVICE_URL", "KEYSPACE"]
ROOT_CHOICES = (ABSENT, True, False)
USER_CHOICES = (ABSENT, 0, 1000)
PRIV_CHOICES = (ABSENT, True, False, "true", 1)


def expected_root(c_nr, c_user, p_nr, p_user):
    user = c_user if c_user is not ABSENT else p_user
    nr = c_nr if c_nr is not ABSENT else p_nr
    if user is not ABSENT and user == 0:
        return True
    if user is not ABSENT:
        return False
    return nr is not True


def _ctx(nr, user, priv=ABSENT):
    d = {}
    if nr is not ABSENT: d["runAsNonRoot"] = nr
    if user is not ABSENT: d["runAsUser"] = user
    if priv is not ABSENT: d["privileged"] = priv
    return d


def make_workload(rng, k, secret_values):
    comp = f"svc-{k}"
    pod_nr, pod_user = rng.choice(ROOT_CHOICES), rng.choice(USER_CHOICES)
    pod = {}
    if rng.random() < 0.7:
        ctx = _ctx(pod_nr, pod_user)
        if ctx or rng.random() < 0.3: pod["securityContext"] = ctx
    else:
        pod_nr = pod_user = ABSENT
    expected = []
    containers, inits = [], []
    for idx in range(rng.randint(1, 3)):
        is_init = rng.random() < 0.3
        name = f"c{idx}" if rng.random() < 0.9 else None
        c = {}
        if name is not None: c["name"] = name
        shown = name if name is not None else "?"
        # limits
        cpu, mem = rng.random() < 0.5, rng.random() < 0.5
        lim = {}
        if cpu: lim["cpu"] = "500m"
        elif rng.random() < 0.2: lim["cpu"] = ""
        if mem: lim["memory"] = "256Mi"
        elif rng.random() < 0.2: lim["memory"] = ""
        form = rng.choice(["none", "empty", "limits"])
        if form == "limits" or (cpu or mem):
            c["resources"] = {"limits": lim} if rng.random() < 0.8 else {"limits": lim, "requests": {"cpu": "1m"}}
        elif form == "empty":
            c["resources"] = {}
        if not (cpu and mem): expected.append((comp, shown, "missing-limits"))
        # image
        img, flagged = rng.choice(IMAGES)
        if img is not None: c["image"] = img
        if flagged: expected.append((comp, shown, "latest-image"))
        # env
        env = []
        for _ in range(rng.randint(0, 4)):
            secretish = rng.random() < 0.5
            nm = rng.choice(SECRET_NAMES if secretish else PLAIN_NAMES)
            nm = rng.choice([nm, nm.upper(), nm.lower()])
            kind = rng.choice(["literal", "literal", "empty", "none", "from", "both"])
            e = {"name": nm}
            if kind == "literal":
                v = f"VAL-{rng.getrandbits(48):012x}"; e["value"] = v; secret_values.append(v)
            elif kind == "empty": e["value"] = ""
            elif kind == "from": e["valueFrom"] = {"secretKeyRef": {"name": "s", "key": "k"}}
            elif kind == "both":   # not valid Kubernetes, but the scan has a guard for it
                v = f"VAL-{rng.getrandbits(48):012x}"; e["value"] = v; e["valueFrom"] = {"secretKeyRef": {"name": "s", "key": "k"}}; secret_values.append(v)
            env.append(e)
            if secretish and kind == "literal": expected.append((comp, shown, "secret-in-env"))
        if env or rng.random() < 0.3: c["env"] = env
        # security context
        priv = rng.choice(PRIV_CHOICES)
        c_nr, c_user = rng.choice(ROOT_CHOICES), rng.choice(USER_CHOICES)
        ctx = _ctx(c_nr, c_user, priv)
        if ctx or rng.random() < 0.3: c["securityContext"] = ctx
        if priv is True: expected.append((comp, shown, "privileged"))
        if expected_root(c_nr, c_user, pod_nr, pod_user): expected.append((comp, shown, "may-run-as-root"))
        (inits if is_init else containers).append(c)
    if containers or rng.random() < 0.9: pod["containers"] = containers
    if inits: pod["initContainers"] = inits
    return (comp, pod), expected


def make_case(rng):
    wl, exp, secrets = [], [], []
    for k in range(rng.randint(1, 5)):
        w, e = make_workload(rng, k, secrets)
        wl.append(w); exp.extend(e)
    return wl, Counter(exp), secrets


def triples(findings):
    return Counter((f["component"], f["container"], f["check"]) for f in findings)


# --------------------------------------------------------------------------
# Checks. Each takes a scan function and returns (passed, total, first failures).
# --------------------------------------------------------------------------

def _cases():
    rng = random.Random(SEED)
    return [make_case(rng) for _ in range(CASES)]


def check_random(scan, cases):
    ok, bad = 0, []
    for wl, exp, _ in cases:
        got = triples(scan(copy.deepcopy(wl)))
        if got == exp: ok += 1
        elif len(bad) < 3: bad.append((dict(exp - got), dict(got - exp)))
    return ok, len(cases), bad


def check_no_secret_values(scan, cases):
    ok = 0
    for wl, _, secrets in cases:
        text = repr(scan(copy.deepcopy(wl)))
        ok += all(v not in text for v in secrets)
    return ok, len(cases), []


def check_order_independent(scan, cases):
    rng = random.Random(SEED + 1); ok = 0
    for wl, _, _ in cases:
        a = scan(copy.deepcopy(wl)); sh = copy.deepcopy(wl); rng.shuffle(sh)
        ok += a == scan(sh)
    return ok, len(cases), []


def check_input_untouched(scan, cases):
    ok = 0
    for wl, _, _ in cases:
        before = copy.deepcopy(wl); scan(wl); ok += wl == before
    return ok, len(cases), []


def check_fields(scan, cases):
    ok = 0
    for wl, _, _ in cases:
        fs = scan(copy.deepcopy(wl))
        ok += all(set(f) == {"component", "container", "check", "detail"}
                  and f["check"] in real.CHECK_DEFINITIONS for f in fs)
    return ok, len(cases), []


def check_root_table(scan, _cases_unused=None):
    ok = total = 0; bad = []
    for c_nr, c_user, p_nr, p_user in itertools.product(ROOT_CHOICES, USER_CHOICES, repeat=2):
        pod = {"securityContext": _ctx(p_nr, p_user), "containers": [{
            "name": "c", "image": "a:1", "securityContext": _ctx(c_nr, c_user),
            "resources": {"limits": {"cpu": "1", "memory": "1"}}}]}
        got = any(f["check"] == "may-run-as-root" for f in scan([("s", pod)]))
        want = expected_root(c_nr, c_user, p_nr, p_user)
        total += 1; ok += got == want
        if got != want and len(bad) < 3: bad.append(((c_nr, c_user, p_nr, p_user), want, got))
    return ok, total, bad


def check_image_table(scan, _cases_unused=None):
    ok = 0
    for img, want in IMAGES:
        c = {"name": "c", "securityContext": {"runAsNonRoot": True},
             "resources": {"limits": {"cpu": "1", "memory": "1"}}}
        if img is not None: c["image"] = img
        got = any(f["check"] == "latest-image" for f in scan([("s", {"containers": [c]})]))
        ok += got == want
    return ok, len(IMAGES), []


CHECKS = [
    ("Findings equal the planted faults (random pods)", check_random, True),
    ("No secret value appears in any finding", check_no_secret_values, True),
    ("Same result whatever the workload order", check_order_independent, True),
    ("The input is left unchanged", check_input_untouched, True),
    ("Every finding has the four fields and a known check", check_fields, True),
    ("Every runAsNonRoot / runAsUser combination (81)", check_root_table, False),
    ("Image strings: tags, digests, registry ports (10)", check_image_table, False),
]


def run_checks(scan):
    cases = _cases()
    return [(name, *fn(scan, cases)) for name, fn, _ in CHECKS]


# --------------------------------------------------------------------------
# Broken copies of the scan: the real rules with ONE flaw switched on.
# --------------------------------------------------------------------------
FLAWS = [
    "ignores init containers", "never flags a missing tag", "ignores the latest tag",
    "secret match is case-sensitive", "flags secrets that use valueFrom",
    "flags an empty secret value", "counts the string 'true' as privileged",
    "ignores runAsUser 0", "ignores the pod-level security context",
    "checks only the memory limit", "puts the secret value in the finding",
    "treats a digest as unpinned", "accepts runAsNonRoot false as safe",
]


def flawed_scan(flaw):
    secret = re.compile(real._SECRET_NAME.pattern) if flaw == "secret match is case-sensitive" else real._SECRET_NAME

    def unpinned(image):
        last = image.rsplit("/", 1)[-1]
        if "@" in last: return flaw == "treats a digest as unpinned"
        if ":" not in last: return flaw != "never flags a missing tag"
        return last.split(":", 1)[1] == "latest" and flaw != "ignores the latest tag"

    def container(comp, c, pod):
        name = c.get("name", "?"); found = []
        limits = (c.get("resources") or {}).get("limits") or {}
        need = ("memory",) if flaw == "checks only the memory limit" else ("cpu", "memory")
        if any(not limits.get(r) for r in need):
            found.append(real._finding(comp, name, "missing-limits", "x"))
        if unpinned(c.get("image") or ""):
            found.append(real._finding(comp, name, "latest-image", "x"))
        for e in c.get("env") or []:
            var = e.get("name") or ""; val = e.get("value")
            empty_ok = (val is not None) if flaw == "flags an empty secret value" else (val not in (None, ""))
            from_ok = True if flaw == "flags secrets that use valueFrom" else not e.get("valueFrom")
            if secret.search(var) and empty_ok and from_ok:
                found.append(real._finding(comp, name, "secret-in-env",
                                           f"{var}={val}" if flaw == "puts the secret value in the finding" else var))
        sc = c.get("securityContext") or {}
        pod_sc = {} if flaw == "ignores the pod-level security context" else (pod.get("securityContext") or {})
        priv = sc.get("privileged")
        if priv is True or (flaw == "counts the string 'true' as privileged" and priv == "true"):
            found.append(real._finding(comp, name, "privileged", "x"))
        nr = sc["runAsNonRoot"] if "runAsNonRoot" in sc else pod_sc.get("runAsNonRoot")
        user = sc["runAsUser"] if "runAsUser" in sc else pod_sc.get("runAsUser")
        if flaw == "accepts runAsNonRoot false as safe" and nr is False:
            return found
        if real._is_zero_int(user):
            if flaw != "ignores runAsUser 0": found.append(real._finding(comp, name, "may-run-as-root", "x"))
        elif nr is not True and not real._is_nonzero_int(user):
            found.append(real._finding(comp, name, "may-run-as-root", "x"))
        return found

    def scan(workloads):
        out = []
        for comp, pod in workloads:
            pod = pod or {}
            cs = ([] if flaw == "ignores init containers" else list(pod.get("initContainers") or [])) + list(pod.get("containers") or [])
            for c in cs: out.extend(container(comp, c, pod))
        return sorted(out, key=lambda f: (f["component"], f["container"], f["check"]))
    return scan


def run_all():
    base = run_checks(real.scan_workloads)
    cases = _cases()
    faithful = sum(triples(flawed_scan(None)(copy.deepcopy(w))) == triples(real.scan_workloads(copy.deepcopy(w)))
                   for w, _, _ in cases)
    caught = []
    for fl in FLAWS:
        res = run_checks(flawed_scan(fl))
        failed = [n for n, p, t, _ in res if p != t]
        caught.append((fl, failed))
    return base, faithful, len(cases), caught


def render(base, faithful, n, caught):
    L = ["# Security scan evaluation", "",
         f"Seed {SEED}; {CASES} random pods plus two exhaustive tables. Expected findings come from the plan used to build each pod.", "",
         "| Check | Passed |", "|---|---|"]
    L += [f"| {name} | {p}/{t} |" for name, p, t, _ in base]
    L += ["", f"Broken copies of the scan caught: {sum(1 for _, f in caught if f)}/{len(caught)}.",
          f"The copy with no flaw reproduces the real scan on {faithful}/{n} cases (it must, or the copies prove nothing).", "",
          "| Flaw | Caught by |", "|---|---|"]
    L += [f"| {fl} | {', '.join(f) if f else '**NOT CAUGHT**'} |" for fl, f in caught]
    L += ["", "One author wrote the scan and this evaluator, and the root and image expectations restate the rules in another form. "
          "It checks the five rules only.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    text = render(*run_all())
    print(text)
    if "--write" in sys.argv:
        open(sys.argv[sys.argv.index("--write") + 1], "w").write(text); print("wrote")
