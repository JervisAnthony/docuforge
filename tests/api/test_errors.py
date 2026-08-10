from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.errors import ApiError
from docuforge.api.schemas import ApiErrorResponse
from docuforge.converters import PdfProcessingError
from docuforge.core import InvalidConversionRequestError, UnsupportedConversionError


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


def test_pdf_domain_errors_are_translated_without_raw_messages() -> None:
    application = create_app()

    @application.get("/invalid-pdf")
    async def invalid_pdf() -> None:
        raise InvalidConversionRequestError("C:\\private\\invalid.pdf")

    @application.get("/unsupported-pdf")
    async def unsupported_pdf() -> None:
        raise UnsupportedConversionError("internal implementation detail")

    @application.get("/broken-pdf")
    async def broken_pdf() -> None:
        raise PdfProcessingError("temporary path: C:\\temp\\uuid.pdf")

    client = TestClient(application)
    expected = {
        "/invalid-pdf": (400, "invalid_pdf_request", "The PDF request is invalid."),
        "/unsupported-pdf": (
            400,
            "unsupported_pdf_operation",
            "The PDF operation is not supported.",
        ),
        "/broken-pdf": (
            422,
            "pdf_processing_failed",
            "The PDF document could not be processed.",
        ),
    }
    for path, (status, code, message) in expected.items():
        response = client.get(path)
        assert response.status_code == status
        assert response.json() == {"code": code, "message": message}
        assert "private" not in response.text
        assert "uuid" not in response.text
