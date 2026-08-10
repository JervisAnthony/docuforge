"""Route composition for the DocuForge API."""

from fastapi import APIRouter

from docuforge.api.config import ApiSettings
from docuforge.api.routes.system import create_system_router


def create_api_router(settings: ApiSettings) -> APIRouter:
    """Build the versioned router tree for one application instance."""
    router = APIRouter()
    if settings.api_prefix == "/":
        router.include_router(create_system_router(settings, metadata_path="/"))
    else:
        router.include_router(create_system_router(settings), prefix=settings.api_prefix)
    return router
