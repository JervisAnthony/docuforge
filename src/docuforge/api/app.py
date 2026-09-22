"""FastAPI application construction for the DocuForge HTTP adapter."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batches import BatchExecutionService
from docuforge.api.config import ApiSettings
from docuforge.api.errors import register_error_handlers
from docuforge.api.observability import REQUEST_ID_HEADER, ProductionMiddleware
from docuforge.api.ocr import OcrEngineFactory
from docuforge.api.office import OfficeEngineFactory
from docuforge.api.routes import create_api_router
from docuforge.converters.ocr import TesseractEngine
from docuforge.converters.office import LibreOfficeEngine


def create_app(
    settings: ApiSettings | None = None,
    *,
    office_engine_factory: OfficeEngineFactory = LibreOfficeEngine,
    ocr_engine_factory: OcrEngineFactory = TesseractEngine,
) -> FastAPI:
    """Create a new, independently configured DocuForge API application."""
    resolved_settings = settings if settings is not None else ApiSettings()
    docs_url = "/docs" if resolved_settings.docs_enabled else None
    redoc_url = "/redoc" if resolved_settings.docs_enabled else None
    openapi_url = "/openapi.json" if resolved_settings.docs_enabled else None
    batch_service = BatchExecutionService(
        office_engine_factory=office_engine_factory,
        max_workers=resolved_settings.batch_max_workers,
        terminal_ttl_seconds=resolved_settings.batch_terminal_ttl_seconds,
        storage_directory=resolved_settings.batch_storage_directory,
    )

    @asynccontextmanager
    async def lifespan(_application: FastAPI):
        yield
        batch_service.shutdown()

    application = FastAPI(
        title=resolved_settings.application_name,
        version=resolved_settings.version,
        docs_url=docs_url,
        redoc_url=redoc_url,
        openapi_url=openapi_url,
        lifespan=lifespan,
    )
    if resolved_settings.cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_allowed_origins),
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["Accept", "Content-Type", REQUEST_ID_HEADER, BATCH_TOKEN_HEADER],
            expose_headers=[REQUEST_ID_HEADER, BATCH_TOKEN_HEADER],
        )
    application.add_middleware(
        ProductionMiddleware,
        environment=resolved_settings.environment,
        api_prefix=resolved_settings.api_prefix,
    )
    register_error_handlers(application)
    application.include_router(
        create_api_router(
            resolved_settings, office_engine_factory=office_engine_factory,
            ocr_engine_factory=ocr_engine_factory,
            batch_service=batch_service,
        )
    )
    application.state.batch_service = batch_service
    return application


app = create_app(ApiSettings.from_environment())
