"""Operation-oriented PDF HTTP routes."""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.files import create_download_response
from docuforge.api.images import parse_image_format
from docuforge.api.pdf import (
    PDF_MEDIA_TYPE,
    ZIP_MEDIA_TYPE,
    derived_download_name,
    extract_pdf_pages_from_upload,
    merge_pdfs,
    parse_page_selection,
    parse_pdf_render_dpi,
    parse_rotations,
    remove_pdf_pages_from_upload,
    render_pdf_images_archive,
    rotate_pdf,
    split_pdf,
)
from docuforge.api.schemas import ApiErrorResponse
from docuforge.api.uploads import StoredUpload, UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace

PDF_EXTENSIONS = frozenset({".pdf"})


def create_pdf_router(settings: ApiSettings) -> APIRouter:
    """Build PDF operation routes bound to immutable upload settings."""
    router = APIRouter(prefix="/pdf", tags=["PDF"])
    policy = UploadPolicy.from_settings(settings, allowed_extensions=PDF_EXTENSIONS)

    @router.post(
        "/merge",
        summary="Merge PDF documents",
        description="Merge two or more uploaded PDFs in multipart order.",
        response_class=FileResponse,
        responses=_binary_responses(PDF_MEDIA_TYPE),
    )
    async def merge(
        files: Annotated[
            list[UploadFile],
            File(description="Two or more PDF files in merge order."),
        ],
    ) -> FileResponse:
        with RequestWorkspace() as workspace:
            uploads = await store_uploads(files, workspace=workspace, policy=policy)
            if len(uploads) < 2:
                raise ApiError(
                    status_code=400,
                    code="invalid_pdf_request",
                    message="PDF merge requires at least two files.",
                )
            output_path = workspace.path / "merged.pdf"
            await run_in_threadpool(merge_pdfs, uploads, output_path)
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename="merged.pdf",
                media_type=PDF_MEDIA_TYPE,
            )

    @router.post(
        "/split",
        summary="Split a PDF document",
        description="Split every uploaded PDF page into one PDF inside a ZIP archive.",
        response_class=FileResponse,
        responses=_binary_responses(ZIP_MEDIA_TYPE),
    )
    async def split(
        file: Annotated[
            list[UploadFile],
            File(description="Exactly one PDF document to split."),
        ],
    ) -> FileResponse:
        with RequestWorkspace() as workspace:
            upload = await _store_one(file, workspace=workspace, policy=policy)
            output_path = workspace.path / "split-pages.zip"
            await run_in_threadpool(split_pdf, upload, output_path)
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename=derived_download_name(upload.original_name, "-pages.zip"),
                media_type=ZIP_MEDIA_TYPE,
            )

    @router.post(
        "/rotate",
        summary="Rotate PDF pages",
        description="Rotate selected one-based pages clockwise without reordering them.",
        response_class=FileResponse,
        responses=_binary_responses(PDF_MEDIA_TYPE),
    )
    async def rotate(
        file: Annotated[
            list[UploadFile],
            File(description="Exactly one PDF document to rotate."),
        ],
        rotate: Annotated[
            list[str] | None,
            Form(description="Repeat PAGE:DEGREES for each page rotation."),
        ] = None,
    ) -> FileResponse:
        rotations = parse_rotations(rotate)
        with RequestWorkspace() as workspace:
            upload = await _store_one(file, workspace=workspace, policy=policy)
            output_path = workspace.path / "rotated.pdf"
            await run_in_threadpool(rotate_pdf, upload, output_path, rotations)
            return _pdf_download(
                workspace,
                upload,
                output_path,
                filename_suffix="-rotated.pdf",
            )

    @router.post(
        "/remove-pages",
        summary="Remove PDF pages",
        description="Remove repeated one-based page selections from one PDF.",
        response_class=FileResponse,
        responses=_binary_responses(PDF_MEDIA_TYPE),
    )
    async def remove_pages(
        file: Annotated[
            list[UploadFile],
            File(description="Exactly one PDF document to trim."),
        ],
        page: Annotated[
            list[str] | None,
            Form(description="Repeat for every one-based page to remove."),
        ] = None,
    ) -> FileResponse:
        return await _selected_page_operation(
            file=file,
            page_values=page,
            workspace_operation=remove_pdf_pages_from_upload,
            output_name="trimmed.pdf",
            filename_suffix="-trimmed.pdf",
            policy=policy,
        )

    @router.post(
        "/extract-pages",
        summary="Extract PDF pages",
        description="Extract repeated one-based page selections in request order.",
        response_class=FileResponse,
        responses=_binary_responses(PDF_MEDIA_TYPE),
    )
    async def extract_pages(
        file: Annotated[
            list[UploadFile],
            File(description="Exactly one PDF document to extract from."),
        ],
        page: Annotated[
            list[str] | None,
            Form(description="Repeat in the desired one-based extraction order."),
        ] = None,
    ) -> FileResponse:
        return await _selected_page_operation(
            file=file,
            page_values=page,
            workspace_operation=extract_pdf_pages_from_upload,
            output_name="extracted.pdf",
            filename_suffix="-extracted.pdf",
            policy=policy,
        )

    @router.post(
        "/to-images",
        summary="Render PDF pages to images",
        description="Render every page in order and return the images in a ZIP archive.",
        response_class=FileResponse,
        responses=_binary_responses(ZIP_MEDIA_TYPE),
    )
    async def to_images(
        file: Annotated[
            list[UploadFile], File(description="Exactly one PDF document to render.")
        ],
        format: Annotated[str | None, Form(description="Target raster format.")] = None,
        dpi: Annotated[str | None, Form(description="Render DPI from 72 through 300.")] = None,
    ) -> FileResponse:
        target_format = parse_image_format(format)
        render_dpi = parse_pdf_render_dpi(dpi)
        with RequestWorkspace() as workspace:
            upload = await _store_one(
                file,
                workspace=workspace,
                policy=policy,
                error_code="invalid_pdf_render_request",
                error_message="PDF rendering requires exactly one file.",
            )
            output_path = workspace.path / "rendered-images.zip"
            await run_in_threadpool(
                render_pdf_images_archive,
                upload,
                output_path,
                output_format=target_format,
                dpi=render_dpi,
                settings=settings,
            )
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename=derived_download_name(
                    upload.original_name, "-images.zip"
                ),
                media_type=ZIP_MEDIA_TYPE,
            )

    return router


async def _store_one(
    uploads: list[UploadFile],
    *,
    workspace: RequestWorkspace,
    policy: UploadPolicy,
    error_code: str = "invalid_pdf_request",
    error_message: str = "This PDF operation requires exactly one file.",
) -> StoredUpload:
    stored_uploads = await store_uploads(uploads, workspace=workspace, policy=policy)
    if len(stored_uploads) != 1:
        raise ApiError(
            status_code=400,
            code=error_code,
            message=error_message,
        )
    return stored_uploads[0]


async def _selected_page_operation(
    *,
    file: list[UploadFile],
    page_values: list[str] | None,
    workspace_operation: Callable[[StoredUpload, Path, tuple[int, ...]], None],
    output_name: str,
    filename_suffix: str,
    policy: UploadPolicy,
) -> FileResponse:
    page_indices = parse_page_selection(page_values)
    with RequestWorkspace() as workspace:
        upload = await _store_one(file, workspace=workspace, policy=policy)
        output_path = workspace.path / output_name
        await run_in_threadpool(workspace_operation, upload, output_path, page_indices)
        return _pdf_download(
            workspace,
            upload,
            output_path,
            filename_suffix=filename_suffix,
        )


def _pdf_download(
    workspace: RequestWorkspace,
    upload: StoredUpload,
    output_path: Path,
    *,
    filename_suffix: str,
) -> FileResponse:
    return create_download_response(
        workspace=workspace,
        output_path=output_path,
        download_filename=derived_download_name(upload.original_name, filename_suffix),
        media_type=PDF_MEDIA_TYPE,
    )


def _binary_responses(media_type: str) -> dict[int | str, dict[str, object]]:
    error_responses = {
        status: {"model": ApiErrorResponse, "description": description}
        for status, description in (
            (400, "Invalid PDF operation request."),
            (413, "Upload limit exceeded."),
            (415, "Unsupported upload extension."),
            (422, "PDF processing failed."),
        )
    }
    return {
        200: {
            "description": "Generated download.",
            "content": {
                media_type: {"schema": {"type": "string", "format": "binary"}}
            },
        },
        **error_responses,
    }
