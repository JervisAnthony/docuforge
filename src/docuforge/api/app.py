"""FastAPI application construction for the DocuForge HTTP adapter."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docuforge.api.config import ApiSettings
from docuforge.api.errors import register_error_handlers
from docuforge.api.observability import REQUEST_ID_HEADER, ProductionMiddleware
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
    if resolved_settings.cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_allowed_origins),
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Accept", "Content-Type", REQUEST_ID_HEADER],
            expose_headers=[REQUEST_ID_HEADER],
        )
    application.add_middleware(
        ProductionMiddleware,
        environment=resolved_settings.environment,
    )
    register_error_handlers(application)
    application.include_router(create_api_router(resolved_settings))
    return application


app = create_app(ApiSettings.from_environment())
