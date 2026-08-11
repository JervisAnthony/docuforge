"""Operation-oriented image HTTP routes."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.files import create_download_response
from docuforge.api.images import (
    CANONICAL_IMAGE_SUFFIX,
    IMAGE_MEDIA_TYPE,
    IMAGE_TO_PDF_EXTENSIONS,
    RASTER_IMAGE_EXTENSIONS,
    compress_uploaded_image,
    convert_uploaded_image,
    parse_http_boolean,
    parse_image_format,
    parse_optional_integer,
    resize_uploaded_image,
    uploaded_images_to_pdf,
)
from docuforge.api.pdf import PDF_MEDIA_TYPE, derived_download_name
from docuforge.api.schemas import ApiErrorResponse
from docuforge.api.uploads import StoredUpload, UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace


def create_image_router(settings: ApiSettings) -> APIRouter:
    """Build image workflow routes bound to immutable transport settings."""
    router = APIRouter(prefix="/images", tags=["Images"])
    raster_policy = UploadPolicy.from_settings(
        settings, allowed_extensions=RASTER_IMAGE_EXTENSIONS
    )
    to_pdf_policy = UploadPolicy.from_settings(
        settings, allowed_extensions=IMAGE_TO_PDF_EXTENSIONS
    )

    @router.post(
        "/convert",
        summary="Convert an image format",
        response_class=FileResponse,
        responses=_image_responses(),
    )
    async def convert(
        file: Annotated[list[UploadFile], File(description="Exactly one raster image.")],
        format: Annotated[str | None, Form(description="Target raster format.")] = None,
    ) -> FileResponse:
        target_format = parse_image_format(format)
        with RequestWorkspace() as workspace:
            upload = await _store_one_image(file, workspace, raster_policy)
            suffix = CANONICAL_IMAGE_SUFFIX[target_format]
            output_path = workspace.path / f"converted{suffix}"
            await run_in_threadpool(convert_uploaded_image, upload, output_path)
            return _image_download(
                workspace,
                upload,
                output_path,
                operation="converted",
                media_type=IMAGE_MEDIA_TYPE[target_format],
            )

    @router.post(
        "/resize",
        summary="Resize an image",
        response_class=FileResponse,
        responses=_image_responses(),
    )
    async def resize(
        file: Annotated[list[UploadFile], File(description="Exactly one raster image.")],
        format: Annotated[str | None, Form(description="Target raster format.")] = None,
        max_width: Annotated[str | None, Form(description="Optional maximum width.")] = None,
        max_height: Annotated[str | None, Form(description="Optional maximum height.")] = None,
        allow_upscale: Annotated[
            str | None, Form(description="Explicit true or false; defaults to false.")
        ] = None,
    ) -> FileResponse:
        target_format = parse_image_format(format)
        width = parse_optional_integer(
            max_width,
            code="invalid_resize_request",
            message="Resize dimensions must be positive integers.",
        )
        height = parse_optional_integer(
            max_height,
            code="invalid_resize_request",
            message="Resize dimensions must be positive integers.",
        )
        upscale = parse_http_boolean(allow_upscale)
        with RequestWorkspace() as workspace:
            upload = await _store_one_image(file, workspace, raster_policy)
            suffix = CANONICAL_IMAGE_SUFFIX[target_format]
            output_path = workspace.path / f"resized{suffix}"
            await run_in_threadpool(
                resize_uploaded_image,
                upload,
                output_path,
                max_width=width,
                max_height=height,
                allow_upscale=upscale,
            )
            return _image_download(
                workspace,
                upload,
                output_path,
                operation="resized",
                media_type=IMAGE_MEDIA_TYPE[target_format],
            )

    @router.post(
        "/compress",
        summary="Compress an image",
        response_class=FileResponse,
        responses=_image_responses(),
    )
    async def compress(
        file: Annotated[list[UploadFile], File(description="Exactly one raster image.")],
        format: Annotated[str | None, Form(description="Target raster format.")] = None,
        quality: Annotated[str | None, Form(description="JPEG/WebP quality 1 through 95.")] = None,
        max_bytes: Annotated[
            str | None, Form(description="Strict maximum encoded output bytes.")
        ] = None,
    ) -> FileResponse:
        target_format = parse_image_format(format)
        parsed_quality = parse_optional_integer(
            quality,
            code="invalid_compression_request",
            message="Compression fields must be positive integers.",
        )
        parsed_max_bytes = parse_optional_integer(
            max_bytes,
            code="invalid_compression_request",
            message="Compression fields must be positive integers.",
        )
        with RequestWorkspace() as workspace:
            upload = await _store_one_image(file, workspace, raster_policy)
            suffix = CANONICAL_IMAGE_SUFFIX[target_format]
            output_path = workspace.path / f"compressed{suffix}"
            await run_in_threadpool(
                compress_uploaded_image,
                upload,
                output_path,
                quality=parsed_quality,
                max_bytes=parsed_max_bytes,
            )
            return _image_download(
                workspace,
                upload,
                output_path,
                operation="compressed",
                media_type=IMAGE_MEDIA_TYPE[target_format],
            )

    @router.post(
        "/to-pdf",
        summary="Convert ordered images to PDF",
        response_class=FileResponse,
        responses=_image_responses(PDF_MEDIA_TYPE),
    )
    async def to_pdf(
        files: Annotated[
            list[UploadFile], File(description="One or more images in PDF page order.")
        ],
    ) -> FileResponse:
        with RequestWorkspace() as workspace:
            uploads = await store_uploads(files, workspace=workspace, policy=to_pdf_policy)
            if not uploads:
                raise ApiError(
                    status_code=400,
                    code="invalid_image_request",
                    message="At least one image is required.",
                )
            output_path = workspace.path / "images.pdf"
            await run_in_threadpool(uploaded_images_to_pdf, uploads, output_path)
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename="images.pdf",
                media_type=PDF_MEDIA_TYPE,
            )

    return router


async def _store_one_image(
    uploads: list[UploadFile],
    workspace: RequestWorkspace,
    policy: UploadPolicy,
) -> StoredUpload:
    stored = await store_uploads(uploads, workspace=workspace, policy=policy)
    if len(stored) != 1:
        raise ApiError(
            status_code=400,
            code="invalid_image_request",
            message="This image operation requires exactly one file.",
        )
    return stored[0]


def _image_download(
    workspace: RequestWorkspace,
    upload: StoredUpload,
    output_path: Path,
    *,
    operation: str,
    media_type: str,
) -> FileResponse:
    return create_download_response(
        workspace=workspace,
        output_path=output_path,
        download_filename=derived_download_name(
            upload.original_name, f"-{operation}{output_path.suffix}"
        ),
        media_type=media_type,
    )


def _image_responses(media_type: str = "image/*") -> dict[int | str, dict[str, object]]:
    return {
        200: {
            "description": "Generated download.",
            "content": {media_type: {"schema": {"type": "string", "format": "binary"}}},
        },
        400: {"model": ApiErrorResponse, "description": "Invalid image request."},
        413: {"model": ApiErrorResponse, "description": "Upload limit exceeded."},
        415: {"model": ApiErrorResponse, "description": "Unsupported upload extension."},
        422: {"model": ApiErrorResponse, "description": "Image processing failed."},
    }
