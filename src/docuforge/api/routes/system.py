"""System-level routes for API metadata, liveness, and readiness."""

from fastapi import APIRouter

from docuforge.api.capabilities import probe_runtime_capabilities
from docuforge.api.config import ApiSettings
from docuforge.api.ocr import OcrEngineFactory
from docuforge.api.office import OfficeEngineFactory
from docuforge.api.schemas import (
    ApiMetadataResponse,
    HealthResponse,
    ReadinessResponse,
    RuntimeCapabilitiesResponse,
)


def create_system_router(
    settings: ApiSettings,
    *,
    office_engine_factory: OfficeEngineFactory,
    ocr_engine_factory: OcrEngineFactory,
    metadata_path: str = "",
) -> APIRouter:
    """Build system routes bound to immutable application settings."""
    router = APIRouter()

    @router.get(metadata_path, response_model=ApiMetadataResponse)
    async def api_metadata() -> ApiMetadataResponse:
        return ApiMetadataResponse(
            name=settings.application_name,
            version=settings.version,
            status="available",
        )

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="docuforge",
            version=settings.version,
        )

    @router.get("/ready", response_model=ReadinessResponse)
    async def readiness() -> ReadinessResponse:
        return ReadinessResponse(
            status="ready",
            service="docuforge",
            version=settings.version,
        )

    @router.get("/capabilities", response_model=RuntimeCapabilitiesResponse)
    def capabilities() -> RuntimeCapabilitiesResponse:
        probed = probe_runtime_capabilities(
            office_engine_factory=office_engine_factory,
            ocr_engine_factory=ocr_engine_factory,
        )
        return RuntimeCapabilitiesResponse.model_validate(probed, from_attributes=True)

    return router
