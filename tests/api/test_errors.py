from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.errors import ApiError


def test_api_error_is_translated_to_stable_response() -> None:
    application = create_app()

    @application.get("/test-error")
    async def raise_api_error() -> None:
        raise ApiError(status_code=409, code="test_conflict", message="A safe message.")

    response = TestClient(application).get("/test-error")

    assert response.status_code == 409
    assert response.json() == {
        "code": "test_conflict",
        "message": "A safe message.",
    }
