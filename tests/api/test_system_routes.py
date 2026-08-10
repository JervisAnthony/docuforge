from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app


def test_health_endpoint_returns_liveness_contract() -> None:
    settings = ApiSettings()
    response = TestClient(create_app(settings)).get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "service": "docuforge",
        "version": settings.version,
    }


def test_metadata_endpoint_returns_api_contract() -> None:
    settings = ApiSettings()
    response = TestClient(create_app(settings)).get("/api/v1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "DocuForge API",
        "version": settings.version,
        "status": "available",
    }
