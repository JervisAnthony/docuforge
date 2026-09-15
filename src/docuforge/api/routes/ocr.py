"""Single-upload OCR HTTP routes."""

from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.files import create_download_response
from docuforge.api.ocr import (
    OcrEngineFactory,
    extract_uploaded_image_text,
    extract_uploaded_pdf_text,
    make_uploaded_pdf_searchable,
)
from docuforge.api.pdf import PDF_MEDIA_TYPE, derived_download_name
from docuforge.api.schemas import ApiErrorResponse
from docuforge.api.uploads import UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace
from docuforge.converters.ocr import TesseractEngine

TEXT_MEDIA_TYPE = "text/plain; charset=utf-8"
IMAGE_OCR_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"})


def create_ocr_router(
    settings: ApiSettings, *, engine_factory: OcrEngineFactory = TesseractEngine
) -> APIRouter:
    """Build OCR routes without constructing a Tesseract engine."""
    router = APIRouter(prefix="/ocr", tags=["OCR"])
    image_policy = UploadPolicy.from_settings(
        settings, allowed_extensions=IMAGE_OCR_EXTENSIONS
    )
    pdf_policy = UploadPolicy.from_settings(settings, allowed_extensions=frozenset({".pdf"}))

    async def convert_one(
        files: list[UploadFile] | None, *, kind: str
    ) -> FileResponse:
        if files is None or len(files) != 1:
            if files:
                for upload in files:
                    await upload.close()
            raise ApiError(
                status_code=400, code="invalid_ocr_request",
                message="This OCR operation requires exactly one file."
            )
        with RequestWorkspace() as workspace:
            upload = (await store_uploads(
                files, workspace=workspace,
                policy=image_policy if kind == "image-text" else pdf_policy,
            ))[0]
            if kind == "pdf-searchable":
                output_path = workspace.path / "searchable.pdf"
                await run_in_threadpool(
                    make_uploaded_pdf_searchable, upload, output_path, settings, engine_factory
                )
                filename = derived_download_name(upload.original_name, "-searchable.pdf")
                media_type = PDF_MEDIA_TYPE
            else:
                output_path = workspace.path / "extracted.txt"
                if kind == "image-text":
                    await run_in_threadpool(
                        extract_uploaded_image_text, upload, output_path, engine_factory
                    )
                else:
                    await run_in_threadpool(
                        extract_uploaded_pdf_text, upload, output_path, settings, engine_factory
                    )
                filename = derived_download_name(upload.original_name, ".txt")
                media_type = TEXT_MEDIA_TYPE
            return create_download_response(
                workspace=workspace, output_path=output_path,
                download_filename=filename, media_type=media_type,
            )

    @router.post(
        "/image-to-text", summary="Extract text from one raster image",
        response_class=FileResponse, responses=_ocr_responses(text=True),
    )
    async def image_to_text(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one raster image.")] = None,
    ) -> FileResponse:
        return await convert_one(file, kind="image-text")

    @router.post(
        "/pdf-to-text", summary="Extract text from every page of one scanned PDF",
        response_class=FileResponse, responses=_ocr_responses(text=True),
    )
    async def pdf_to_text(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one PDF document.")] = None,
    ) -> FileResponse:
        return await convert_one(file, kind="pdf-text")

    @router.post(
        "/pdf-to-searchable-pdf", summary="Make one scanned PDF searchable",
        response_class=FileResponse, responses=_ocr_responses(text=False),
    )
    async def pdf_to_searchable_pdf(
        file: Annotated[list[UploadFile] | None, File(description="Exactly one PDF document.")] = None,
    ) -> FileResponse:
        return await convert_one(file, kind="pdf-searchable")

    return router


def _ocr_responses(*, text: bool) -> dict[int | str, dict[str, object]]:
    content = (
        {"text/plain": {"schema": {"type": "string"}}}
        if text else
        {PDF_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}
    )
    descriptions = {
        400: "Invalid OCR request.", 413: "Upload limit exceeded.",
        415: "Unsupported upload extension.", 422: "OCR processing failed.",
        502: "OCR engine failed.", 503: "OCR engine unavailable.",
        504: "OCR operation timed out.",
    }
    return {
        200: {"description": "OCR output download.", "content": content},
        **{status: {"model": ApiErrorResponse, "description": description}
           for status, description in descriptions.items()},
    }
