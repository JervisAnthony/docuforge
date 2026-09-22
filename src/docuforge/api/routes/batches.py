"""Batch creation, polling, cancellation, recovery, and download routes."""

from typing import Annotated

from fastapi import APIRouter, File, Form, Header, Response, UploadFile
from fastapi.responses import FileResponse

from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batches import (
    BatchExecutionService,
    BatchExecutionSnapshot,
    BatchSessionGrant,
)
from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.images import (
    RASTER_IMAGE_EXTENSIONS,
    parse_http_boolean,
    parse_image_format,
    parse_optional_integer,
)
from docuforge.api.schemas import (
    ApiErrorResponse,
    BatchItemFailureResponse,
    BatchItemStatusResponse,
    BatchSessionErrorResponse,
    BatchStatusResponse,
    BatchSummaryResponse,
)
from docuforge.api.uploads import UploadPolicy, store_batch_uploads
from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageResizeRequest,
    InvalidBatchDefinitionError,
)

_OFFICE_EXTENSIONS = frozenset({".docx", ".pptx", ".xlsx"})


def create_batch_router(
    settings: ApiSettings, *, service: BatchExecutionService
) -> APIRouter:
    """Build routes bound to one application-owned execution service."""
    router = APIRouter(prefix="/batches", tags=["Batches"])
    image_policy = UploadPolicy.from_settings(
        settings, allowed_extensions=RASTER_IMAGE_EXTENSIONS
    )
    office_policy = UploadPolicy.from_settings(
        settings, allowed_extensions=_OFFICE_EXTENSIONS
    )

    @router.post(
        "/images/convert",
        status_code=202,
        response_model=BatchStatusResponse,
        responses=_batch_responses(),
    )
    async def create_image_convert(
        response: Response,
        file: Annotated[list[UploadFile], File(description="Ordered raster images.")],
        format: Annotated[str | None, Form()] = None,
    ) -> BatchStatusResponse:
        target = parse_image_format(format)
        return await _create_image_session(
            response,
            file,
            policy=image_policy,
            service=service,
            settings=settings,
            request_factory=lambda items, output, batch_id: BatchImageConvertRequest(
                items, output, target, batch_id
            ),
        )

    @router.post(
        "/images/resize",
        status_code=202,
        response_model=BatchStatusResponse,
        responses=_batch_responses(),
    )
    async def create_image_resize(
        response: Response,
        file: Annotated[list[UploadFile], File(description="Ordered raster images.")],
        format: Annotated[str | None, Form()] = None,
        max_width: Annotated[str | None, Form()] = None,
        max_height: Annotated[str | None, Form()] = None,
        allow_upscale: Annotated[str | None, Form()] = None,
    ) -> BatchStatusResponse:
        target = parse_image_format(format)
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
        return await _create_image_session(
            response,
            file,
            policy=image_policy,
            service=service,
            settings=settings,
            request_factory=lambda items, output, batch_id: BatchImageResizeRequest(
                items,
                output,
                target,
                max_width=width,
                max_height=height,
                allow_upscale=upscale,
                batch_id=batch_id,
            ),
        )

    @router.post(
        "/images/compress",
        status_code=202,
        response_model=BatchStatusResponse,
        responses=_batch_responses(),
    )
    async def create_image_compress(
        response: Response,
        file: Annotated[list[UploadFile], File(description="Ordered raster images.")],
        format: Annotated[str | None, Form()] = None,
        quality: Annotated[str | None, Form()] = None,
        max_bytes: Annotated[str | None, Form()] = None,
    ) -> BatchStatusResponse:
        target = parse_image_format(format)
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
        return await _create_image_session(
            response,
            file,
            policy=image_policy,
            service=service,
            settings=settings,
            request_factory=lambda items, output, batch_id: BatchImageCompressRequest(
                items,
                output,
                target,
                quality=parsed_quality,
                max_bytes=parsed_max_bytes,
                batch_id=batch_id,
            ),
        )

    @router.post(
        "/office/to-pdf",
        status_code=202,
        response_model=BatchStatusResponse,
        responses=_batch_responses(),
    )
    async def create_office_batch(
        response: Response,
        file: Annotated[list[UploadFile], File(description="Ordered Office documents.")],
    ) -> BatchStatusResponse:
        workspace = service.create_workspace()
        try:
            uploads = await store_batch_uploads(
                file, input_directory=workspace.inputs_directory, policy=office_policy
            )
            request = BatchDocumentConvertRequest(
                tuple(
                    BatchDocumentInput(upload.stored_path, descriptor=upload.original_name)
                    for upload in uploads
                ),
                workspace.output_directory,
                workspace.batch_id,
            )
            grant = service.create_session(request, workspace)
        except InvalidBatchDefinitionError:
            workspace.cleanup()
            raise ApiError(
                status_code=400,
                code="invalid_batch_request",
                message="The batch request is invalid.",
            ) from None
        except BaseException:
            workspace.cleanup()
            raise
        _set_creation_headers(response, settings, grant)
        return _response(grant.snapshot)

    @router.get("/{batch_id}", response_model=BatchStatusResponse)
    def get_status(
        response: Response,
        batch_id: str,
        access_token: Annotated[str | None, Header(alias=BATCH_TOKEN_HEADER)] = None,
    ) -> BatchStatusResponse:
        _set_private_cache_control(response)
        return _response(service.get(batch_id, access_token))

    @router.delete("/{batch_id}", status_code=204)
    def delete_batch(
        batch_id: str,
        access_token: Annotated[str | None, Header(alias=BATCH_TOKEN_HEADER)] = None,
    ) -> None:
        service.delete_session(batch_id, access_token)

    @router.post("/{batch_id}/cancel", status_code=202, response_model=BatchStatusResponse)
    def cancel(
        response: Response,
        batch_id: str,
        access_token: Annotated[str | None, Header(alias=BATCH_TOKEN_HEADER)] = None,
    ) -> BatchStatusResponse:
        _set_private_cache_control(response)
        return _response(service.cancel(batch_id, access_token))

    @router.post("/{batch_id}/recover", status_code=202, response_model=BatchStatusResponse)
    def recover(
        response: Response,
        batch_id: str,
        access_token: Annotated[str | None, Header(alias=BATCH_TOKEN_HEADER)] = None,
    ) -> BatchStatusResponse:
        _set_private_cache_control(response)
        return _response(service.recover(batch_id, access_token))

    @router.get(
        "/{batch_id}/download",
        response_class=FileResponse,
        responses={
            200: {
                "description": "ZIP containing successful outputs.",
                "content": {"application/zip": {"schema": {"type": "string", "format": "binary"}}},
            },
            404: {"model": ApiErrorResponse},
            409: {"model": ApiErrorResponse},
        },
    )
    def download(
        batch_id: str,
        access_token: Annotated[str | None, Header(alias=BATCH_TOKEN_HEADER)] = None,
    ) -> FileResponse:
        path = service.download_path(batch_id, access_token)
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"docuforge-batch-{batch_id}.zip",
            headers={"Cache-Control": "no-store"},
        )

    return router


async def _create_image_session(
    response: Response,
    uploads: list[UploadFile],
    *,
    policy: UploadPolicy,
    service: BatchExecutionService,
    settings: ApiSettings,
    request_factory: object,
) -> BatchStatusResponse:
    workspace = service.create_workspace()
    try:
        stored = await store_batch_uploads(
            uploads, input_directory=workspace.inputs_directory, policy=policy
        )
        items = tuple(
            BatchImageInput(upload.stored_path, descriptor=upload.original_name)
            for upload in stored
        )
        request = request_factory(  # type: ignore[operator]
            items, workspace.output_directory, workspace.batch_id
        )
        grant = service.create_session(request, workspace)
    except InvalidBatchDefinitionError:
        workspace.cleanup()
        raise ApiError(
            status_code=400,
            code="invalid_batch_request",
            message="The batch request is invalid.",
        ) from None
    except BaseException:
        workspace.cleanup()
        raise
    _set_creation_headers(response, settings, grant)
    return _response(grant.snapshot)


def _set_creation_headers(
    response: Response, settings: ApiSettings, grant: BatchSessionGrant
) -> None:
    prefix = "" if settings.api_prefix == "/" else settings.api_prefix
    response.headers["Location"] = f"{prefix}/batches/{grant.snapshot.batch.id}"
    response.headers[BATCH_TOKEN_HEADER] = grant.access_token
    _set_private_cache_control(response)


def _set_private_cache_control(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _response(snapshot: BatchExecutionSnapshot) -> BatchStatusResponse:
    batch = snapshot.batch
    summary = batch.summary
    return BatchStatusResponse(
        id=str(batch.id),
        operation=str(batch.operation),
        attempt=snapshot.attempt,
        phase=snapshot.phase.value,
        status=batch.status.value,
        progress_percent=summary.progress_percent,
        cancellation_requested=snapshot.cancellation_requested,
        summary=BatchSummaryResponse(
            total=summary.total_count,
            pending=summary.pending_count,
            running=summary.running_count,
            completed=summary.completed_count,
            failed=summary.failed_count,
            cancelled=summary.cancelled_count,
            processed=summary.processed_count,
            remaining=summary.remaining_count,
        ),
        items=[
            BatchItemStatusResponse(
                id=str(item.id),
                position=item.position,
                descriptor=item.descriptor,
                status=item.status.value,
                result_descriptor=item.result.descriptor if item.result else None,
                failure=(
                    BatchItemFailureResponse(
                        code=item.failure.code, message=item.failure.message
                    )
                    if item.failure
                    else None
                ),
            )
            for item in batch.items
        ],
        session_error=(
            BatchSessionErrorResponse(
                code=snapshot.session_error.code,
                message=snapshot.session_error.message,
            )
            if snapshot.session_error
            else None
        ),
        can_cancel=snapshot.can_cancel,
        can_recover=snapshot.can_recover,
        can_download=snapshot.can_download,
    )


def _batch_responses() -> dict[int | str, dict[str, object]]:
    return {
        202: {
            "model": BatchStatusResponse,
            "description": "Batch accepted; the access capability is returned once in the response header.",
            "headers": {
                BATCH_TOKEN_HEADER: {
                    "description": "Capability required for later access to this batch.",
                    "schema": {"type": "string"},
                }
            },
        },
        400: {"model": ApiErrorResponse, "description": "Invalid batch request."},
        413: {"model": ApiErrorResponse, "description": "Upload limit exceeded."},
        415: {"model": ApiErrorResponse, "description": "Unsupported upload extension."},
    }
