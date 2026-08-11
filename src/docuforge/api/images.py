"""Image-specific HTTP adaptation built on reusable converter APIs."""

from collections.abc import Callable, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import TypeVar

from docuforge.api.errors import ApiError
from docuforge.api.uploads import StoredUpload
from docuforge.converters import (
    ImageCompressPathRequest,
    ImageConvertPathRequest,
    ImageProcessingError,
    ImageResizePathRequest,
    ImageToPdfPathRequest,
    compress_image_path,
    convert_image_path,
    convert_images_to_pdf,
    resize_image_path,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    InvalidFormatError,
    UnsupportedConversionError,
)

RASTER_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
)
IMAGE_TO_PDF_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
)
RASTER_IMAGE_FORMATS = frozenset(
    {
        DocumentFormat.JPG,
        DocumentFormat.PNG,
        DocumentFormat.WEBP,
        DocumentFormat.BMP,
        DocumentFormat.TIFF,
    }
)
CANONICAL_IMAGE_SUFFIX = MappingProxyType(
    {
        DocumentFormat.JPG: ".jpg",
        DocumentFormat.PNG: ".png",
        DocumentFormat.WEBP: ".webp",
        DocumentFormat.BMP: ".bmp",
        DocumentFormat.TIFF: ".tiff",
    }
)
IMAGE_MEDIA_TYPE = MappingProxyType(
    {
        DocumentFormat.JPG: "image/jpeg",
        DocumentFormat.PNG: "image/png",
        DocumentFormat.WEBP: "image/webp",
        DocumentFormat.BMP: "image/bmp",
        DocumentFormat.TIFF: "image/tiff",
    }
)

_ResultT = TypeVar("_ResultT")


def parse_image_format(value: str | None) -> DocumentFormat:
    """Normalize one explicit raster target or return a stable field error."""
    try:
        image_format = DocumentFormat.normalize(value)  # type: ignore[arg-type]
    except InvalidFormatError:
        raise _field_error(
            "invalid_image_format", "A supported target image format is required."
        ) from None
    if image_format not in RASTER_IMAGE_FORMATS:
        raise _field_error(
            "invalid_image_format", "A supported target image format is required."
        )
    return image_format


def parse_optional_integer(value: str | None, *, code: str, message: str) -> int | None:
    """Parse an optional non-negative-looking multipart integer without bool coercion."""
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise _field_error(code, message)
    return int(value)


def parse_http_boolean(value: str | None) -> bool:
    """Accept only explicit case-insensitive true/false values."""
    normalized = "false" if value is None else value.lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise _field_error(
        "invalid_resize_request",
        "Resize fields must contain valid dimensions and a true or false upscale value.",
    )


def convert_uploaded_image(
    upload: StoredUpload, output_path: Path
) -> None:
    """Delegate uploaded raster conversion with image-context error translation."""
    _invoke_image_converter(
        convert_image_path,
        ImageConvertPathRequest(upload.stored_path, output_path),
    )


def resize_uploaded_image(
    upload: StoredUpload,
    output_path: Path,
    *,
    max_width: int | None,
    max_height: int | None,
    allow_upscale: bool,
) -> None:
    """Delegate uploaded raster resizing with resize-specific request errors."""
    try:
        request = ImageResizePathRequest(
            upload.stored_path,
            output_path,
            max_width=max_width,
            max_height=max_height,
            allow_upscale=allow_upscale,
        )
    except (TypeError, InvalidConversionRequestError):
        raise _field_error(
            "invalid_resize_request",
            "At least one valid positive resize dimension is required.",
        ) from None
    _invoke_image_converter(resize_image_path, request)


def compress_uploaded_image(
    upload: StoredUpload,
    output_path: Path,
    *,
    quality: int | None,
    max_bytes: int | None,
) -> None:
    """Delegate uploaded raster compression with stable field errors."""
    try:
        request = ImageCompressPathRequest(
            upload.stored_path,
            output_path,
            quality=quality,
            max_bytes=max_bytes,
        )
    except (TypeError, InvalidConversionRequestError):
        raise _field_error(
            "invalid_compression_request",
            "Exactly one valid quality or max_bytes value is required.",
        ) from None
    _invoke_image_converter(compress_image_path, request)


def uploaded_images_to_pdf(
    uploads: Sequence[StoredUpload], output_path: Path
) -> None:
    """Delegate ordered uploaded images to the existing image-to-PDF path API."""
    try:
        request = ImageToPdfPathRequest(
            tuple(upload.stored_path for upload in uploads), output_path
        )
    except (TypeError, InvalidConversionRequestError):
        raise _image_error("invalid_image_request", "The image request is invalid.") from None
    _invoke_image_converter(convert_images_to_pdf, request)


def _invoke_image_converter(function: Callable[..., _ResultT], *args: object) -> _ResultT:
    try:
        return function(*args)
    except InvalidConversionRequestError:
        raise _image_error("invalid_image_request", "The image request is invalid.") from None
    except UnsupportedConversionError:
        raise _image_error(
            "unsupported_image_conversion",
            "The image conversion is not supported.",
        ) from None
    except ImageProcessingError:
        raise ApiError(
            status_code=422,
            code="image_processing_failed",
            message="The image could not be processed.",
        ) from None


def _field_error(code: str, message: str) -> ApiError:
    return ApiError(status_code=400, code=code, message=message)


def _image_error(code: str, message: str) -> ApiError:
    return ApiError(status_code=400, code=code, message=message)
