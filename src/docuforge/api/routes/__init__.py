"""Route composition for the DocuForge API."""

from fastapi import APIRouter

from docuforge.api.batches import BatchExecutionService
from docuforge.api.config import ApiSettings
from docuforge.api.ocr import OcrEngineFactory
from docuforge.api.office import OfficeEngineFactory
from docuforge.api.routes.batches import create_batch_router
from docuforge.api.routes.images import create_image_router
from docuforge.api.routes.ocr import create_ocr_router
from docuforge.api.routes.office import create_office_router
from docuforge.api.routes.pdf import create_pdf_router
from docuforge.api.routes.system import create_system_router
from docuforge.converters.ocr import TesseractEngine
from docuforge.converters.office import LibreOfficeEngine


def create_api_router(
    settings: ApiSettings,
    *,
    office_engine_factory: OfficeEngineFactory = LibreOfficeEngine,
    ocr_engine_factory: OcrEngineFactory = TesseractEngine,
    batch_service: BatchExecutionService,
) -> APIRouter:
    """Build the versioned router tree for one application instance."""
    router = APIRouter()
    if settings.api_prefix == "/":
        router.include_router(create_system_router(
            settings,
            office_engine_factory=office_engine_factory,
            ocr_engine_factory=ocr_engine_factory,
            metadata_path="/",
        ))
        router.include_router(create_pdf_router(settings))
        router.include_router(create_image_router(settings))
        router.include_router(create_office_router(settings, engine_factory=office_engine_factory))
        router.include_router(create_ocr_router(settings, engine_factory=ocr_engine_factory))
        router.include_router(create_batch_router(settings, service=batch_service))
    else:
        router.include_router(create_system_router(
            settings,
            office_engine_factory=office_engine_factory,
            ocr_engine_factory=ocr_engine_factory,
        ), prefix=settings.api_prefix)
        router.include_router(create_pdf_router(settings), prefix=settings.api_prefix)
        router.include_router(create_image_router(settings), prefix=settings.api_prefix)
        router.include_router(
            create_office_router(settings, engine_factory=office_engine_factory),
            prefix=settings.api_prefix,
        )
        router.include_router(
            create_ocr_router(settings, engine_factory=ocr_engine_factory),
            prefix=settings.api_prefix,
        )
        router.include_router(
            create_batch_router(settings, service=batch_service),
            prefix=settings.api_prefix,
        )
    return router
