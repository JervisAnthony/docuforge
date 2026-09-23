from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER


def test_settings_load_production_environment(monkeypatch) -> None:
    monkeypatch.setenv("DOCUFORGE_ENVIRONMENT", "production")
    monkeypatch.setenv("DOCUFORGE_DOCS_ENABLED", "false")
    monkeypatch.setenv(
        "DOCUFORGE_CORS_ALLOWED_ORIGINS",
        "https://app.example.com, https://preview.example.com/",
    )

    settings = ApiSettings.from_environment()

    assert settings.environment == "production"
    assert settings.docs_enabled is False
    assert settings.cors_allowed_origins == (
        "https://app.example.com",
        "https://preview.example.com",
    )


def test_configured_cors_allows_known_frontend_origin() -> None:
    application = create_app(
        ApiSettings(cors_allowed_origins=("https://app.example.com",))
    )
    response = TestClient(application).options(
        "/api/v1/health",
        headers={
            "Origin": "https://app.example.com",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": f"X-Request-ID, {BATCH_TOKEN_HEADER}",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    assert "X-Request-ID" in response.headers["access-control-allow-headers"]
    assert BATCH_TOKEN_HEADER in response.headers["access-control-allow-headers"]
    assert "DELETE" in response.headers["access-control-allow-methods"]
    assert response.headers["access-control-allow-headers"] != "*"


def test_configured_cors_exposes_request_id_to_known_frontend_origin() -> None:
    application = create_app(
        ApiSettings(cors_allowed_origins=("https://app.example.com",))
    )
    response = TestClient(application).get(
        "/api/v1/health",
        headers={"Origin": "https://app.example.com"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://app.example.com"
    exposed = response.headers["access-control-expose-headers"]
    assert "X-Request-ID" in exposed
    assert BATCH_TOKEN_HEADER in exposed
    assert response.headers["x-request-id"]


def test_unconfigured_origin_is_not_reflected() -> None:
    application = create_app(
        ApiSettings(cors_allowed_origins=("https://app.example.com",))
    )
    response = TestClient(application).options(
        "/api/v1/health",
        headers={
            "Origin": "https://unknown.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.headers.get("access-control-allow-origin") is None
