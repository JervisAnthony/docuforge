import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.observability import REQUEST_LOGGER_NAME
from docuforge.version import package_version


def test_readiness_endpoint_reports_service_ready() -> None:
    response = TestClient(create_app()).get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "service": "docuforge",
        "version": package_version(),
    }


def test_generated_request_id_is_returned_and_logged(caplog) -> None:
    client = TestClient(create_app())

    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        response = client.get("/api/v1/health")

    request_id = response.headers["x-request-id"]
    UUID(request_id)

    records = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == REQUEST_LOGGER_NAME
    ]
    assert records[-1]["event"] == "http_request"
    assert records[-1]["request_id"] == request_id
    assert records[-1]["method"] == "GET"
    assert records[-1]["path"] == "/api/v1/health"
    assert records[-1]["status_code"] == 200
    assert records[-1]["outcome"] == "completed"
    assert records[-1]["duration_ms"] >= 0


def test_valid_client_request_id_is_preserved() -> None:
    response = TestClient(create_app()).get(
        "/api/v1/health",
        headers={"X-Request-ID": "browser-trace_123:abc"},
    )

    assert response.headers["x-request-id"] == "browser-trace_123:abc"


def test_invalid_client_request_id_is_replaced() -> None:
    response = TestClient(create_app()).get(
        "/api/v1/health",
        headers={"X-Request-ID": "contains spaces"},
    )

    request_id = response.headers["x-request-id"]
    assert request_id != "contains spaces"
    UUID(request_id)


def test_security_headers_are_applied_to_api_responses() -> None:
    response = TestClient(create_app()).get("/api/v1/health")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"


def test_hsts_is_applied_only_in_production() -> None:
    production_response = TestClient(
        create_app(ApiSettings(environment="production"))
    ).get("/api/v1/health")
    local_response = TestClient(create_app(ApiSettings(environment="local"))).get(
        "/api/v1/health"
    )

    assert production_response.headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in local_response.headers
