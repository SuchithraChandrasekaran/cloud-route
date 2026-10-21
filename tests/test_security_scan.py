"""Deterministic security checks on workload specs."""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.security_scan import (
    format_findings, main, scan_workloads, summarize,
    workloads_from_cluster, workloads_from_manifest,
)

GOOD = {
    "name": "app",
    "image": "app:v1",
    "resources": {"limits": {"cpu": "100m", "memory": "128Mi"}},
    "securityContext": {"runAsNonRoot": True},
}

MANIFEST = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
spec:
  template:
    spec:
      containers:
      - name: api
        image: api:v1
---
apiVersion: v1
kind: Service
metadata:
  name: api
spec:
  ports:
  - port: 80
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: db
spec:
  template:
    spec:
      containers:
      - name: db
        image: db:latest
"""


def _ctr(**overrides):
    ctr = dict(GOOD)
    for key, value in overrides.items():
        if value is None:
            ctr.pop(key, None)
        else:
            ctr[key] = value
    return ctr


def _scan_ctr(ctr, pod=None):
    spec = dict(pod or {})
    spec["containers"] = [ctr]
    return scan_workloads([("deployment/app", spec)])


def _checks(findings):
    return sorted(f["check"] for f in findings)


def test_a_hardened_container_has_no_findings():
    assert _scan_ctr(_ctr()) == []


@pytest.mark.parametrize("resources, detail", [
    (None, "no cpu limit, no memory limit"),
    ({"requests": {"cpu": "50m"}}, "no cpu limit, no memory limit"),
    ({"limits": {"memory": "1Gi"}}, "no cpu limit"),
    ({"limits": {"cpu": "1"}}, "no memory limit"),
])
def test_missing_limits_says_which_are_missing(resources, detail):
    findings = _scan_ctr(_ctr(resources=resources))
    assert [(f["check"], f["detail"]) for f in findings] == [("missing-limits", detail)]


@pytest.mark.parametrize("image", [
    "nginx", "nginx:latest", "registry.example.com:5000/app", "app:latest",
])
def test_untagged_or_latest_images_are_flagged(image):
    assert _checks(_scan_ctr(_ctr(image=image))) == ["latest-image"]


@pytest.mark.parametrize("image", [
    "nginx:1.25", "app@sha256:abc123", "localhost:5000/app:v2", "bank-easy/auth:v1",
])
def test_pinned_images_pass(image):
    assert _scan_ctr(_ctr(image=image)) == []


def test_secret_variable_with_a_literal_value_is_flagged_without_the_value():
    findings = _scan_ctr(_ctr(env=[{"name": "DB_PASSWORD", "value": "hunter2-very-secret"}]))
    assert _checks(findings) == ["secret-in-env"]
    assert "DB_PASSWORD" in findings[0]["detail"]
    assert "hunter2" not in str(findings)


@pytest.mark.parametrize("name", [
    "PASSWORD", "db_password", "JWT_SECRET", "API_KEY", "apikey",
    "AUTH_TOKEN", "PRIVATE_KEY", "AWS_CREDENTIALS",
])
def test_secret_looking_names_are_flagged(name):
    assert _checks(_scan_ctr(_ctr(env=[{"name": name, "value": "x"}]))) == ["secret-in-env"]


def test_references_empty_values_and_ordinary_names_are_not_flagged():
    env = [
        {"name": "DB_PASSWORD", "valueFrom": {"secretKeyRef": {"name": "db", "key": "pw"}}},
        {"name": "API_TOKEN", "value": ""},
        {"name": "LEDGER_URL", "value": "http://account-ledger:4002"},
        {"name": "REGION"},
    ]
    assert _scan_ctr(_ctr(env=env)) == []


@pytest.mark.parametrize("privileged, expected", [
    (True, ["privileged"]), (False, []), (None, []),
])
def test_privileged_mode(privileged, expected):
    sc = {"runAsNonRoot": True}
    if privileged is not None:
        sc["privileged"] = privileged
    assert _checks(_scan_ctr(_ctr(securityContext=sc))) == expected


@pytest.mark.parametrize("pod_sc, ctr_sc, flagged", [
    ({}, None, True),
    ({"runAsNonRoot": True}, None, False),
    ({"runAsNonRoot": True}, {"runAsNonRoot": False}, True),
    ({}, {"runAsNonRoot": True}, False),
    ({}, {"runAsUser": 0}, True),
    ({"runAsNonRoot": True}, {"runAsUser": 0}, True),
    ({"runAsUser": 1000}, None, False),
])
def test_running_as_root(pod_sc, ctr_sc, flagged):
    pod = {"securityContext": pod_sc} if pod_sc else {}
    findings = _scan_ctr(_ctr(securityContext=ctr_sc), pod)
    if flagged:
        assert _checks(findings) == ["may-run-as-root"]
    else:
        assert findings == []


def test_init_containers_are_scanned():
    spec = {"containers": [dict(GOOD)],
            "initContainers": [{"name": "setup", "image": "busybox"}]}
    findings = scan_workloads([("deployment/app", spec)])
    assert {f["container"] for f in findings} == {"setup"}
    assert set(_checks(findings)) == {"latest-image", "missing-limits", "may-run-as-root"}


def test_findings_are_sorted_and_repeatable():
    spec_a = {"containers": [{"name": "a", "image": "x"}]}
    spec_b = {"containers": [{"name": "b", "image": "x"}]}
    one = scan_workloads([("deployment/zeta", spec_b), ("deployment/alpha", spec_a)])
    two = scan_workloads([("deployment/alpha", spec_a), ("deployment/zeta", spec_b)])
    assert one == two
    assert [f["component"] for f in one] == sorted(f["component"] for f in one)


def test_summary_counts_findings_by_check():
    spec = {"containers": [{"name": "a", "image": "x"},
                           {"name": "b", "image": "y:latest"}]}
    assert summarize(scan_workloads([("deployment/app", spec)])) == {
        "total": 6,
        "by_check": {"latest-image": 2, "may-run-as-root": 2, "missing-limits": 2},
        "components_with_findings": 1,
    }


def test_manifest_parsing_names_workloads_like_the_engine_and_skips_services():
    names = [component for component, _ in workloads_from_manifest(MANIFEST)]
    assert names == ["deployment/api", "statefulset/db"]


def test_manifest_scan_reads_statefulsets():
    findings = scan_workloads(workloads_from_manifest(MANIFEST))
    pairs = {(f["component"], f["check"]) for f in findings}
    assert ("statefulset/db", "latest-image") in pairs
    assert ("deployment/api", "latest-image") not in pairs


def test_the_bank_easy_manifest():
    path = Path(__file__).resolve().parent.parent / "k8s" / "bank-easy.yaml"
    workloads = workloads_from_manifest(path.read_text())
    assert len(workloads) == 7
    checks = {f["check"] for f in scan_workloads(workloads)}
    assert not checks & {"latest-image", "secret-in-env", "privileged"}


def test_cluster_workloads_come_from_deployments_and_statefulsets():
    spec_a = {"containers": [{"name": "a", "image": "a:v1"}]}
    spec_b = {"containers": [{"name": "b", "image": "b:v1"}]}
    dep = MagicMock()
    dep.metadata.name = "a"
    dep.spec.template.spec = spec_a
    sts = MagicMock()
    sts.metadata.name = "b"
    sts.spec.template.spec = spec_b
    with patch("agent.security_scan.config"), \
         patch("agent.security_scan.client") as client_mod:
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value.items = [dep]
        apps.list_namespaced_stateful_set.return_value.items = [sts]
        client_mod.AppsV1Api.return_value = apps
        client_mod.ApiClient.return_value.sanitize_for_serialization.side_effect = lambda o: o
        workloads = workloads_from_cluster()
    assert workloads == [("deployment/a", spec_a), ("statefulset/b", spec_b)]


def test_format_lists_counts_and_each_finding():
    workloads = [("deployment/app", {"containers": [{"name": "c", "image": "x"}]})]
    text = format_findings("test source", len(workloads), scan_workloads(workloads))
    assert "Source: test source" in text
    assert "Workloads scanned: 1" in text
    assert "Findings: 3" in text
    assert "deployment/app [c] missing-limits" in text
    clean = format_findings("test source", 1, [])
    assert "Findings: 0" in clean


def test_main_scans_a_manifest_file(tmp_path, capsys):
    path = tmp_path / "m.yaml"
    path.write_text(MANIFEST)
    assert main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "Workloads scanned: 2" in out
    assert "statefulset/db [db] latest-image" in out
