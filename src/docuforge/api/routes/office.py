"""Multipart Office-to-PDF HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.files import create_download_response
from docuforge.api.office import OfficeEngineFactory, convert_uploaded_office
from docuforge.api.pdf import PDF_MEDIA_TYPE, derived_download_name
from docuforge.api.schemas import ApiErrorResponse
from docuforge.api.uploads import UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace
from docuforge.converters.office import LibreOfficeEngine
from docuforge.core import DocumentFormat


def create_office_router(
    settings: ApiSettings,
    *,
    engine_factory: OfficeEngineFactory = LibreOfficeEngine,
) -> APIRouter:
    """Build Office routes without resolving the engine until an Office POST."""
    router = APIRouter(prefix="/office", tags=["Office"])
    policies = {
        source_format: UploadPolicy.from_settings(
            settings, allowed_extensions=frozenset({f".{source_format.value}"})
        )
        for source_format in (DocumentFormat.DOCX, DocumentFormat.PPTX, DocumentFormat.XLSX)
    }

    async def convert_one(
        files: list[UploadFile] | None, source_format: DocumentFormat
    ) -> FileResponse:
        if files is None or len(files) != 1:
            if files:
                for upload in files:
                    await upload.close()
            raise ApiError(
                status_code=400,
                code="invalid_office_request",
                message="This Office conversion requires exactly one file.",
            )
        with RequestWorkspace() as workspace:
            upload = (await store_uploads(files, workspace=workspace, policy=policies[source_format]))[0]
            output_path = workspace.path / "converted.pdf"
            await run_in_threadpool(
                convert_uploaded_office,
                upload,
                output_path,
                source_format,
                engine_factory,
            )
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename=derived_download_name(upload.original_name, ".pdf"),
                media_type=PDF_MEDIA_TYPE,
            )

    @router.post(
        "/docx-to-pdf",
        summary="Convert a Word document to PDF",
        response_class=FileResponse,
        responses=_office_responses(),
    )
    async def docx_to_pdf(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one DOCX document.")] = None,
    ) -> FileResponse:
        return await convert_one(file, DocumentFormat.DOCX)

    @router.post(
        "/pptx-to-pdf",
        summary="Convert a PowerPoint presentation to PDF",
        response_class=FileResponse,
        responses=_office_responses(),
    )
    async def pptx_to_pdf(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one PPTX presentation.")] = None,
    ) -> FileResponse:
        return await convert_one(file, DocumentFormat.PPTX)

    @router.post(
        "/xlsx-to-pdf",
        summary="Convert an Excel workbook to PDF",
        response_class=FileResponse,
        responses=_office_responses(),
    )
    async def xlsx_to_pdf(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one XLSX workbook.")] = None,
    ) -> FileResponse:
        return await convert_one(file, DocumentFormat.XLSX)

    return router


def _office_responses() -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": "Converted PDF download.",
            "content": {PDF_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
        },
        400: {"model": ApiErrorResponse, "description": "Invalid Office request."},
        413: {"model": ApiErrorResponse, "description": "Upload limit exceeded."},
        415: {"model": ApiErrorResponse, "description": "Unsupported upload extension."},
        422: {"model": ApiErrorResponse, "description": "Office conversion failed."},
        502: {"model": ApiErrorResponse, "description": "Office engine failed."},
        503: {"model": ApiErrorResponse, "description": "Office engine unavailable."},
        504: {"model": ApiErrorResponse, "description": "Office conversion timed out."},
    }
