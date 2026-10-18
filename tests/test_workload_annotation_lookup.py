"""depends-on resolves names to the real workload kind, on Deployments and StatefulSets."""
from unittest.mock import MagicMock, patch

from agent.cluster_source import load_blueprint_from_cluster

ANN = "cloud-route/depends-on"


def _container():
    c = MagicMock()
    c.resources.requests = {"cpu": "500m", "memory": "512Mi"}
    return c


def _workload(name, annotations=None):
    w = MagicMock()
    w.metadata.name = name
    w.metadata.annotations = annotations
    w.spec.template.metadata.labels = {"app": name}
    w.spec.template.spec.containers = [_container()]
    w.spec.service_name = None
    return w


def _load(deployments, statefulsets):
    with patch("agent.cluster_source.config"), \
         patch("agent.cluster_source.client") as client_mod:
        core = MagicMock()
        core.list_namespaced_service.return_value.items = []
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value.items = deployments
        apps.list_namespaced_stateful_set.return_value.items = statefulsets
        client_mod.CoreV1Api.return_value = core
        client_mod.AppsV1Api.return_value = apps
        return load_blueprint_from_cluster(namespace="default")


def _deps(components, component_id):
    return next(c for c in components if c["id"] == component_id)["dependencies"]


def test_statefulset_reads_depends_on_annotation():
    comps = _load(
        [_workload("cache")],
        [_workload("db"), _workload("web", {ANN: "db, cache"})],
    )
    deps = _deps(comps, "statefulset/web")
    assert "statefulset/db" in deps
    assert "deployment/cache" in deps


def test_deployment_depends_on_statefulset_by_name():
    comps = _load([_workload("api", {ANN: "db"})], [_workload("db")])
    deps = _deps(comps, "deployment/api")
    assert "statefulset/db" in deps
    assert "deployment/db" not in deps


def test_unknown_name_stays_a_deployment_id_so_the_engine_reports_it():
    comps = _load([_workload("api", {ANN: "ghost"})], [])
    assert _deps(comps, "deployment/api") == ["deployment/ghost"]


def test_deployment_wins_when_a_deployment_and_statefulset_share_a_name():
    comps = _load(
        [_workload("db")],
        [_workload("db"), _workload("web", {ANN: "db"})],
    )
    assert _deps(comps, "statefulset/web") == ["deployment/db"]
