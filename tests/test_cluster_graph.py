"""
Tests for cluster_source.py.

These use a mocked kubernetes client rather than a live K3s cluster, so
this suite runs anywhere. This tests the graph-construction LOGIC
(matching Services to workloads via label selectors, StatefulSet
governing-service dependencies) — it does not prove the code works
against a real cluster's exact API responses. That's a real gap: before
trusting this against production data, it should also be run once against
an actual local K3s cluster (`k3s` installed, real Services/Deployments
applied) as a manual integration check, not just this mocked unit suite.
"""

from unittest.mock import MagicMock, patch

from agent.cluster_source import load_blueprint_from_cluster, _parse_cpu, _parse_memory_gb


def _mock_container(cpu="500m", memory="512Mi"):
    container = MagicMock()
    container.resources.requests = {"cpu": cpu, "memory": memory}
    return container


def test_parse_cpu_handles_millicores_and_whole_cores():
    assert _parse_cpu("500m") == 0.5
    assert _parse_cpu("2") == 2.0


def test_parse_memory_handles_common_units():
    assert _parse_memory_gb("512Mi") == 0.5
    assert _parse_memory_gb("1Gi") == 1.0


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_deployment_depends_on_matching_service(mock_client_module, mock_config):
    # Set up one Service selecting app=auth, and one Deployment with that label.
    mock_service = MagicMock()
    mock_service.metadata.name = "auth-svc"
    mock_service.spec.selector = {"app": "auth"}

    mock_deployment = MagicMock()
    mock_deployment.metadata.name = "auth-deployment"
    mock_deployment.spec.template.metadata.labels = {"app": "auth"}
    mock_deployment.spec.template.spec.containers = [_mock_container()]

    mock_core_v1 = MagicMock()
    mock_core_v1.list_namespaced_service.return_value.items = [mock_service]

    mock_apps_v1 = MagicMock()
    mock_apps_v1.list_namespaced_deployment.return_value.items = [mock_deployment]
    mock_apps_v1.list_namespaced_stateful_set.return_value.items = []

    mock_client_module.CoreV1Api.return_value = mock_core_v1
    mock_client_module.AppsV1Api.return_value = mock_apps_v1

    components = load_blueprint_from_cluster(namespace="default")

    deployment_component = next(c for c in components if c["id"] == "deployment/auth-deployment")
    assert "service/auth-svc" in deployment_component["dependencies"]


@patch("agent.cluster_source.config")
@patch("agent.cluster_source.client")
def test_statefulset_depends_on_governing_service(mock_client_module, mock_config):
    mock_sts = MagicMock()
    mock_sts.metadata.name = "db"
    mock_sts.spec.template.metadata.labels = {"app": "db"}
    mock_sts.spec.template.spec.containers = [_mock_container()]
    mock_sts.spec.service_name = "db-headless"

    mock_core_v1 = MagicMock()
    mock_core_v1.list_namespaced_service.return_value.items = []

    mock_apps_v1 = MagicMock()
    mock_apps_v1.list_namespaced_deployment.return_value.items = []
    mock_apps_v1.list_namespaced_stateful_set.return_value.items = [mock_sts]

    mock_client_module.CoreV1Api.return_value = mock_core_v1
    mock_client_module.AppsV1Api.return_value = mock_apps_v1

    components = load_blueprint_from_cluster(namespace="default")

    sts_component = next(c for c in components if c["id"] == "statefulset/db")
    assert "service/db-headless" in sts_component["dependencies"]
