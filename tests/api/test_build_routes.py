import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from docuforge.api import ApiSettings, create_app
from docuforge.api.schemas import BuildIdentityResponse


def test_build_schema_does_not_coerce_boolean_schema_version():
    with pytest.raises(ValidationError):
        BuildIdentityResponse(
            schema_version=True,
            service="docuforge",
            version="0.1.0",
            revision=None,
        )


@pytest.mark.parametrize("prefix", ["/api/v1", "/custom"])
@pytest.mark.parametrize("revision", [None, "a" * 40])
def test_build_contract_and_prefix(monkeypatch, prefix, revision):
    from docuforge import build_identity
    from docuforge.api.routes import system

    stamp = build_identity.identity("0.1.0", revision)
    monkeypatch.setattr(system, "read_identity", lambda: stamp)
    client = TestClient(create_app(ApiSettings(api_prefix=prefix)))
    response = client.get(prefix + "/build")
    assert response.status_code == 200
    assert response.json() == stamp
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"] == "application/json"
    assert client.get(prefix + "/ready").json() == {
        "status": "ready",
        "service": "docuforge",
        "version": "0.1.0",
    }
    assert client.get(prefix + "/health").json() == {
        "status": "ok",
        "service": "docuforge",
        "version": "0.1.0",
    }
    if prefix != "/api/v1":
        assert client.get("/api/v1/build").status_code == 404
