from fastapi.testclient import TestClient

from docuforge.api import create_app


def test_health_endpoint_returns_liveness_contract() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "service": "docuforge",
        "version": "0.1.0.dev0",
    }


def test_metadata_endpoint_returns_api_contract() -> None:
    response = TestClient(create_app()).get("/api/v1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "DocuForge API",
        "version": "0.1.0.dev0",
        "status": "available",
    }
