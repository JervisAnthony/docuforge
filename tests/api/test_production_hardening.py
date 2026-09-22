import json
import logging
from uuid import UUID

from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.observability import REQUEST_LOGGER_NAME
from docuforge.version import package_version
from tests.api.image_test_support import make_image


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


def test_private_batch_cache_policy_does_not_apply_to_unrelated_routes() -> None:
    client = TestClient(create_app(ApiSettings(api_prefix="/custom")))

    for path in ("/custom/health", "/other/batches/unknown", "/custom/batches"):
        response = client.get(path)
        assert "cache-control" not in response.headers


def test_hsts_is_applied_only_in_production() -> None:
    production_response = TestClient(
        create_app(ApiSettings(environment="production"))
    ).get("/api/v1/health")
    local_response = TestClient(create_app(ApiSettings(environment="local"))).get(
        "/api/v1/health"
    )

    assert production_response.headers["strict-transport-security"] == "max-age=31536000"
    assert "strict-transport-security" not in local_response.headers


def test_batch_request_paths_are_redacted_without_rewriting_unrelated_uuids(
    caplog,
) -> None:
    batch_id = "550e8400-e29b-41d4-a716-446655440000"
    client = TestClient(create_app(ApiSettings(api_prefix="/custom")))

    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        for method, path in [
            (client.get, f"/custom/batches/{batch_id}"),
            (client.post, f"/custom/batches/{batch_id}/cancel"),
            (client.post, f"/custom/batches/{batch_id}/recover"),
            (client.get, f"/custom/batches/{batch_id}/download"),
            (client.get, f"/other/{batch_id}"),
            (client.post, "/custom/batches/images/convert"),
        ]:
            method(path)

    paths = [
        json.loads(record.message)["path"]
        for record in caplog.records
        if record.name == REQUEST_LOGGER_NAME
    ]
    assert paths[-6:] == [
        "/custom/batches/{batch_id}",
        "/custom/batches/{batch_id}/cancel",
        "/custom/batches/{batch_id}/recover",
        "/custom/batches/{batch_id}/download",
        f"/other/{batch_id}",
        "/custom/batches/images/convert",
    ]


def test_access_capability_and_hash_are_absent_from_request_logs(caplog) -> None:
    application = create_app()
    client = TestClient(application)
    accepted = client.post(
        "/api/v1/batches/images/convert",
        files=[
            ("file", ("one.png", make_image(), "image/png")),
            ("format", (None, "jpeg")),
        ],
    )
    token = accepted.headers[BATCH_TOKEN_HEADER]
    batch_id = accepted.json()["id"]
    digest = application.state.batch_service._sessions[batch_id].access_token_hash
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=REQUEST_LOGGER_NAME):
        client.get(
            accepted.headers["location"],
            headers={BATCH_TOKEN_HEADER: token},
        )
    serialized = "\n".join(record.message for record in caplog.records)
    assert accepted.status_code == 202
    assert token not in serialized
    assert digest not in serialized
    assert batch_id not in serialized
