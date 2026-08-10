from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.errors import ApiError
from docuforge.api.schemas import ApiErrorResponse


def test_api_error_is_translated_to_stable_safe_response() -> None:
    application = create_app()

    @application.get("/test-error")
    async def raise_api_error() -> None:
        try:
            raise RuntimeError("internal path: C:\\private\\document.pdf")
        except RuntimeError as internal_error:
            raise ApiError(
                status_code=409,
                code="test_conflict",
                message="A safe message.",
            ) from internal_error

    response = TestClient(application).get("/test-error")

    assert response.status_code == 409
    assert ApiErrorResponse.model_validate(response.json()) == ApiErrorResponse(
        code="test_conflict",
        message="A safe message.",
    )
    assert "private" not in response.text
    assert "RuntimeError" not in response.text
