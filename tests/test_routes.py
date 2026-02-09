from unittest.mock import patch

from flask.testing import FlaskClient

from app.services.watchdog_service import WatchdogService


class TestRoutes:
    def test_root(self, client: FlaskClient) -> None:
        """Test root endpoint returns service info"""
        response = client.get("/")
        assert response.status_code == 200
        data = response.get_json()
        assert data["service"] == "Alertmanager Watchdog Service"
        assert "endpoints" in data

    def test_watchdog_post_success(self, client: FlaskClient, service: WatchdogService) -> None:
        """Test successful watchdog alert processing"""
        payload = {"alerts": [{"labels": {"alertname": "Watchdog"}}]}

        with patch.object(service, "process_watchdog_alert", return_value=(True, "Watchdog alert processed")):
            response = client.post("/watchdog", json=payload)
            assert response.status_code == 200
            data = response.get_json()
            assert data["status"] == "success"
            assert "processed" in data["message"]

    def test_watchdog_post_invalid_json(self, client: FlaskClient) -> None:
        """Test watchdog with invalid JSON"""
        response = client.post("/watchdog", data="not json", content_type="application/json")
        # request.get_json(silent=True) returns None for invalid JSON
        # routes.py: if watchdog_service.process_watchdog_alert fails and payload is None it returns 400
        assert response.status_code == 400
        data = response.get_json()
        assert data["status"] == "error"

    def test_health_check_ok(self, client: FlaskClient, service: WatchdogService) -> None:
        """Test health check when service is healthy"""
        with patch.object(service, "get_health_status", return_value={"is_healthy": True, "status": "ok"}):
            response = client.get("/health")
            assert response.status_code == 200
            data = response.get_json()
            assert data["is_healthy"] is True

    def test_health_check_unhealthy(self, client: FlaskClient, service: WatchdogService) -> None:
        """Test health check when service is unhealthy"""
        # Not initializing and not healthy
        with patch.object(service, "get_health_status", return_value={"is_healthy": False, "status": "alert"}):
            response = client.get("/health")
            assert response.status_code == 503

    def test_status_endpoint(self, client: FlaskClient, service: WatchdogService) -> None:
        """Test detailed status endpoint"""
        mock_status = {"status": "ok", "total_received": 5}
        with patch.object(service, "get_detailed_status", return_value=mock_status):
            response = client.get("/status")
            assert response.status_code == 200
            data = response.get_json()
            assert data["total_received"] == 5

    def test_liveness_probe(self, client: FlaskClient) -> None:
        """Test liveness probe endpoint"""
        response = client.get("/probe/liveness")
        assert response.status_code == 200
        data = response.get_json()
        assert data["status"] == "alive"

    def test_readiness_probe_not_ready(self, client: FlaskClient) -> None:
        """Test readiness probe during startup grace period"""
        # KubernetesProbes is initialized in init_routes, we need to bypass grace period to test success
        # but by default it should be in grace period (30s)
        response = client.get("/probe/readiness")
        assert response.status_code == 503
        data = response.get_json()
        assert data["status"] == "not_ready"

    def test_routes_not_initialized(self, client: FlaskClient) -> None:
        """Test routes when service/probes are None"""
        from app.web import routes

        original_service = routes.watchdog_service
        original_probes = routes.kubernetes_probes

        try:
            routes.watchdog_service = None
            routes.kubernetes_probes = None

            assert client.post("/watchdog").status_code == 500
            assert client.get("/health").status_code == 500
            assert client.get("/probe/liveness").status_code == 500
            assert client.get("/probe/readiness").status_code == 500
            assert client.get("/status").status_code == 500
        finally:
            routes.watchdog_service = original_service
            routes.kubernetes_probes = original_probes

    def test_watchdog_exception(self, client: FlaskClient, service: WatchdogService) -> None:
        """Test watchdog endpoint exception handling"""
        with patch.object(service, "process_watchdog_alert", side_effect=Exception("Unexpected error")):
            response = client.post("/watchdog", json={})
            assert response.status_code == 500
            assert "Unexpected error" in response.get_json()["message"]
