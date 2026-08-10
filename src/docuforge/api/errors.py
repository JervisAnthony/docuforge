"""Exception translation boundary for the DocuForge API."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from docuforge.api.schemas import ApiErrorResponse


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
