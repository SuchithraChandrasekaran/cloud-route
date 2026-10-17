
"""
Tests for the explicit `cloud-route/depends-on` annotation in cluster_source.py.

A Deployment can declare dependencies that Kubernetes' object graph doesn't
express (for example a hardcoded URL), as a comma-separated list of other
Deployment names:

    metadata:
      annotations:
        cloud-route/depends-on: credit-scoring,account-ledger

These use a mocked kubernetes client, like test_cluster_graph.py, so they run
anywhere. They check the graph-construction logic, not a live cluster.
"""

from unittest.mock import MagicMock, patch

from agent.cluster_source import load_blueprint_from_cluster

ANNOTATION = "cloud-route/depends-on"


def _container():
    container = MagicMock()
    container.resources.requests = {"cpu": "100m", "memory": "128Mi"}
    return container


def _deployment(name, annotations=None, labels=None):
    dep = MagicMock()
    dep.metadata.name = name
    dep.metadata.annotations = annotations
    dep.spec.template.metadata.labels = labels or {"app": name}
    dep.spec.template.spec.containers = [_container()]
    return dep


def _service(name, selector):
    svc = MagicMock()
    svc.metadata.name = name
    svc.spec.selector = selector
    return svc


def _load(mock_client_module, deployments, services=()):
    core_v1 = MagicMock()
    core_v1.list_namespaced_service.return_value.items = list(services)
    apps_v1 = MagicMock()
    apps_v1.list_namespaced_deployment.return_value.items = list(deployments)
    apps_v1.list_namespaced_stateful_set.return_value.items = []
    mock_client_module.CoreV1Api.return_value = core_v1
    mock_client_module.AppsV1Api.return_value = apps_v1
    return {c["id"]: c for c in load_blueprint_from_cluster(namespace="default")}


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_annotation_adds_each_declared_dependency(mock_client_module, mock_config):
    components = _load(mock_client_module, [
        _deployment("loan", {ANNOTATION: "credit-scoring,account-ledger"}),
        _deployment("credit-scoring"),
        _deployment("account-ledger"),
    ])
    deps = components["deployment/loan"]["dependencies"]
    assert "deployment/credit-scoring" in deps
    assert "deployment/account-ledger" in deps


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_annotation_tolerates_spaces_around_names(mock_client_module, mock_config):
    components = _load(mock_client_module, [
        _deployment("loan", {ANNOTATION: "  credit-scoring ,  account-ledger  "}),
    ])
    deps = components["deployment/loan"]["dependencies"]
    assert deps == ["deployment/credit-scoring", "deployment/account-ledger"]


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_missing_annotation_adds_no_declared_dependencies(mock_client_module, mock_config):
    components = _load(mock_client_module, [
        _deployment("plain", annotations=None),
        _deployment("other", annotations={"unrelated/key": "value"}),
    ])
    assert components["deployment/plain"]["dependencies"] == []
    assert components["deployment/other"]["dependencies"] == []


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_blank_annotation_values_are_ignored(mock_client_module, mock_config):
    components = _load(mock_client_module, [
        _deployment("empty", {ANNOTATION: ""}),
        _deployment("commas", {ANNOTATION: " , ,, "}),
    ])
    assert components["deployment/empty"]["dependencies"] == []
    assert components["deployment/commas"]["dependencies"] == []


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_annotation_combines_with_service_selector_dependencies(mock_client_module, mock_config):
    components = _load(
        mock_client_module,
        [
            _deployment("loan", {ANNOTATION: "credit-scoring"}, labels={"app": "loan"}),
            _deployment("credit-scoring"),
        ],
        services=[_service("loan-svc", {"app": "loan"})],
    )
    deps = components["deployment/loan"]["dependencies"]
    assert "service/loan-svc" in deps          # inferred from the label selector
    assert "deployment/credit-scoring" in deps  # declared by annotation
    assert len(deps) == 2


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_annotation_does_not_change_other_deployments(mock_client_module, mock_config):
    components = _load(mock_client_module, [
        _deployment("loan", {ANNOTATION: "credit-scoring"}),
        _deployment("credit-scoring"),
    ])
    assert components["deployment/credit-scoring"]["dependencies"] == []
