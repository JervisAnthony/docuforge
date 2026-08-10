"""FastAPI application construction for the DocuForge HTTP adapter."""

from fastapi import FastAPI

from docuforge.api.config import ApiSettings
from docuforge.api.errors import register_error_handlers
from docuforge.api.routes import create_api_router


def create_app(settings: ApiSettings | None = None) -> FastAPI:
    """Create a new, independently configured DocuForge API application."""
    resolved_settings = settings if settings is not None else ApiSettings()
    docs_url = "/docs" if resolved_settings.docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.docs_enabled else None

    application = FastAPI(
        title=resolved_settings.application_name,
        version=resolved_settings.version,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
    )
    register_error_handlers(application)
    application.include_router(create_api_router(resolved_settings))
    return application


app = create_app()
