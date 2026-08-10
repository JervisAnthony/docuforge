"""System-level routes for API metadata and liveness."""

from fastapi import APIRouter

from docuforge.api.config import ApiSettings
from docuforge.api.schemas import ApiMetadataResponse, HealthResponse


def create_system_router(settings: ApiSettings, *, metadata_path: str = "") -> APIRouter:
    """Build system routes bound to immutable application settings."""
    router = APIRouter()

    @router.get(metadata_path, response_model=ApiMetadataResponse)
    async def api_metadata() -> ApiMetadataResponse:
        return ApiMetadataResponse(
            name=settings.application_name,
            version=settings.application_version,
            status="available",
        )

    @router.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            service="docuforge",
            version=settings.application_version,
        )

    return router
