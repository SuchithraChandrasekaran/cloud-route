"""
The cluster's own `kubernetes` Service (the API server, no selector) is not
part of the application and must not appear as a component to migrate.
A user-defined Service that happens to be called `kubernetes` but does select
pods is a real component and must be kept.
"""

from unittest.mock import MagicMock, patch

from agent.cluster_source import load_blueprint_from_cluster


def _service(name, selector):
    svc = MagicMock()
    svc.metadata.name = name
    svc.spec.selector = selector
    return svc


def _ids(mock_client_module, services):
    core_v1 = MagicMock()
    core_v1.list_namespaced_service.return_value.items = services
    apps_v1 = MagicMock()
    apps_v1.list_namespaced_deployment.return_value.items = []
    apps_v1.list_namespaced_stateful_set.return_value.items = []
    mock_client_module.CoreV1Api.return_value = core_v1
    mock_client_module.AppsV1Api.return_value = apps_v1
    return [c["id"] for c in load_blueprint_from_cluster(namespace="default")]


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_builtin_kubernetes_service_is_left_out(mock_client_module, mock_config):
    ids = _ids(mock_client_module, [
        _service("kubernetes", None),
        _service("web", {"app": "web"}),
    ])
    assert "service/kubernetes" not in ids
    assert "service/web" in ids


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_a_kubernetes_named_service_with_a_selector_is_kept(mock_client_module, mock_config):
    ids = _ids(mock_client_module, [_service("kubernetes", {"app": "mine"})])
    assert ids == ["service/kubernetes"]
