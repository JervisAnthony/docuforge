"""Exception translation boundary for the DocuForge API."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from docuforge.api.schemas import ApiErrorResponse
from docuforge.converters import PdfProcessingError
from docuforge.core import InvalidConversionRequestError, UnsupportedConversionError


class ApiError(Exception):
    """An explicitly translated error safe to return to an HTTP client."""

    def __init__(self, *, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def register_error_handlers(application: FastAPI) -> None:
    """Register API-specific exception translations on one application."""

    @application.exception_handler(ApiError)
    async def handle_api_error(_request: Request, error: ApiError) -> JSONResponse:
        response = ApiErrorResponse(code=error.code, message=error.message)
        return JSONResponse(status_code=error.status_code, content=response.model_dump())

    @application.exception_handler(InvalidConversionRequestError)
    async def handle_invalid_pdf_request(
        _request: Request,
        _error: InvalidConversionRequestError,
    ) -> JSONResponse:
        response = ApiErrorResponse(
            code="invalid_pdf_request",
            message="The PDF request is invalid.",
        )
        return JSONResponse(status_code=400, content=response.model_dump())

    @application.exception_handler(UnsupportedConversionError)
    async def handle_unsupported_pdf_operation(
        _request: Request,
        _error: UnsupportedConversionError,
    ) -> JSONResponse:
        response = ApiErrorResponse(
            code="unsupported_pdf_operation",
            message="The PDF operation is not supported.",
        )
        return JSONResponse(status_code=400, content=response.model_dump())

    @application.exception_handler(PdfProcessingError)
    async def handle_pdf_processing_error(
        _request: Request,
        _error: PdfProcessingError,
    ) -> JSONResponse:
        response = ApiErrorResponse(
            code="pdf_processing_failed",
            message="The PDF document could not be processed.",
        )
        return JSONResponse(status_code=422, content=response.model_dump())
