"""cloud-route/region on Services, Deployments and StatefulSets reaches the engine."""
from unittest.mock import MagicMock, patch

from agent.cluster_source import load_blueprint_from_cluster
from agent.engine import CloudRouteOptimizer

REGION = "cloud-route/region"
DEPENDS = "cloud-route/depends-on"


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


def _service(name, annotations=None):
    s = MagicMock()
    s.metadata.name = name
    s.metadata.annotations = annotations
    s.spec.selector = {"app": name}
    return s


def _load(deployments=(), statefulsets=(), services=()):
    with patch("agent.cluster_source.config"), \
         patch("agent.cluster_source.client") as client_mod:
        core = MagicMock()
        core.list_namespaced_service.return_value.items = list(services)
        apps = MagicMock()
        apps.list_namespaced_deployment.return_value.items = list(deployments)
        apps.list_namespaced_stateful_set.return_value.items = list(statefulsets)
        client_mod.CoreV1Api.return_value = core
        client_mod.AppsV1Api.return_value = apps
        return load_blueprint_from_cluster(namespace="default")


def _get(components, component_id):
    return next(c for c in components if c["id"] == component_id)


def test_deployment_region_is_read():
    comps = _load(deployments=[_workload("api", {REGION: "eu-west-1"})])
    assert _get(comps, "deployment/api")["region"] == "eu-west-1"


def test_statefulset_region_is_read():
    comps = _load(statefulsets=[_workload("db", {REGION: "us-east-1"})])
    assert _get(comps, "statefulset/db")["region"] == "us-east-1"


def test_service_region_is_read():
    comps = _load(services=[_service("api", {REGION: "eu-west-1"})])
    assert _get(comps, "service/api")["region"] == "eu-west-1"


def test_no_annotation_means_no_region_key():
    comps = _load(deployments=[_workload("api")],
                  services=[_service("api", {"other": "x"})])
    assert "region" not in _get(comps, "deployment/api")
    assert "region" not in _get(comps, "service/api")


def test_blank_region_is_ignored():
    comps = _load(deployments=[_workload("api", {REGION: "   "})])
    assert "region" not in _get(comps, "deployment/api")


def test_region_value_is_trimmed():
    comps = _load(deployments=[_workload("api", {REGION: " eu-west-1 "})])
    assert _get(comps, "deployment/api")["region"] == "eu-west-1"


def test_cluster_regions_feed_the_engines_residency_check():
    comps = _load(deployments=[
        _workload("db", {REGION: "eu-west-1"}),
        _workload("api", {REGION: "us-east-1", DEPENDS: "db"}),
    ])
    opt = CloudRouteOptimizer()
    opt.load_blueprint(comps)
    result = opt.check_residency(["eu-west-1"])
    assert result["out_of_policy"] == ["deployment/api"]
    assert result["cross_region_dependencies"] == [["deployment/db", "deployment/api"]]
