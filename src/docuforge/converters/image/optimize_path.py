"""Safe path-based raster resizing and compression."""

import math
import os
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, UnidentifiedImageError

from docuforge.converters.image.convert_path import (
    _PILLOW_NAME_BY_FORMAT,
    _load_oriented_image,
    _prepare_for_target,
    _target_format,
    _validate_encoded_output,
    _validate_paths,
)
from docuforge.converters.image.exceptions import ImageProcessingError
from docuforge.converters.image.models import (
    ImageCompressPathRequest,
    ImageCompressPathResult,
    ImageResizePathRequest,
    ImageResizePathResult,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)

_QUALITY_FORMATS = frozenset({DocumentFormat.JPG, DocumentFormat.WEBP})
_MIN_SEARCH_QUALITY = 20
_MAX_SEARCH_QUALITY = 95
_MAX_DIMENSION_ATTEMPTS = 16
_SHRINK_SAFETY_FACTOR = 0.9


def resize_image_path(request: ImageResizePathRequest) -> ImageResizePathResult:
    """Resize one raster into its suffix-selected format and install it atomically."""
    if not isinstance(request, ImageResizePathRequest):
        raise TypeError("request must be an instance of ImageResizePathRequest")

    target_format = _target_format(request.output_path)
    _validate_paths(request.input_path, request.output_path)
    try:
        image, source_format = _load_oriented_image(
            request.input_path,
            multiframe_error="Raster optimization supports only single-frame images.",
        )
        try:
            input_dimensions = image.size
            output_dimensions = _bounded_dimensions(
                input_dimensions,
                request.max_width,
                request.max_height,
                request.allow_upscale,
            )
            resized = _resize(image, output_dimensions)
            try:
                encoded = _encode(resized, target_format)
            finally:
                if resized is not image:
                    resized.close()
            _install_output(encoded, request.output_path, target_format)
        finally:
            image.close()
    except (InvalidConversionRequestError, UnsupportedConversionError, ImageProcessingError):
        raise
    except _PILLOW_ERRORS as error:
        raise ImageProcessingError("Unable to resize the requested raster image.") from error

    return ImageResizePathResult(
        input_path=request.input_path,
        output_path=request.output_path,
        source_format=source_format,
        target_format=target_format,
        input_dimensions=input_dimensions,
        output_dimensions=output_dimensions,
        output_size_bytes=len(encoded),
    )


def compress_image_path(request: ImageCompressPathRequest) -> ImageCompressPathResult:
    """Compress one raster at fixed quality or to a maximum encoded size."""
    if not isinstance(request, ImageCompressPathRequest):
        raise TypeError("request must be an instance of ImageCompressPathRequest")

    target_format = _target_format(request.output_path)
    _validate_paths(request.input_path, request.output_path)
    if request.quality is not None and target_format not in _QUALITY_FORMATS:
        raise UnsupportedConversionError(
            "Fixed quality is supported only for JPEG and WebP output."
        )

    try:
        image, source_format = _load_oriented_image(
            request.input_path,
            multiframe_error="Raster optimization supports only single-frame images.",
        )
        try:
            input_dimensions = image.size
            if request.quality is not None:
                encoded = _encode(image, target_format, quality=request.quality)
                output_dimensions = image.size
                quality_used = request.quality
            else:
                assert request.max_bytes is not None
                encoded, output_dimensions, quality_used = _encode_to_size(
                    image, target_format, request.max_bytes
                )
            _install_output(encoded, request.output_path, target_format)
        finally:
            image.close()
    except (InvalidConversionRequestError, UnsupportedConversionError, ImageProcessingError):
        raise
    except _PILLOW_ERRORS as error:
        raise ImageProcessingError(
            "Unable to compress the requested raster image."
        ) from error

    return ImageCompressPathResult(
        input_path=request.input_path,
        output_path=request.output_path,
        source_format=source_format,
        target_format=target_format,
        input_dimensions=input_dimensions,
        output_dimensions=output_dimensions,
        output_size_bytes=len(encoded),
        quality_used=quality_used,
    )


_PILLOW_ERRORS = (
    OSError,
    ValueError,
    UnidentifiedImageError,
    Image.DecompressionBombError,
    Image.DecompressionBombWarning,
)


def _bounded_dimensions(
    dimensions: tuple[int, int],
    max_width: int | None,
    max_height: int | None,
    allow_upscale: bool,
) -> tuple[int, int]:
    width, height = dimensions
    scales = []
    if max_width is not None:
        scales.append(max_width / width)
    if max_height is not None:
        scales.append(max_height / height)
    scale = min(scales)
    if not allow_upscale:
        scale = min(scale, 1.0)
    # Flooring is deterministic and guarantees neither requested bound is exceeded.
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def _resize(image: Image.Image, dimensions: tuple[int, int]) -> Image.Image:
    if dimensions == image.size:
        return image
    return image.resize(dimensions, Image.Resampling.LANCZOS)


def _encode(
    image: Image.Image,
    target_format: DocumentFormat,
    *,
    quality: int | None = None,
    size_mode: bool = False,
) -> bytes:
    prepared = _prepare_for_target(image, target_format)
    try:
        options: dict[str, int | bool] = {}
        if quality is not None:
            options["quality"] = quality
            if target_format is DocumentFormat.JPG:
                options["optimize"] = True
        elif size_mode and target_format is DocumentFormat.PNG:
            options.update(optimize=True, compress_level=9)
        stream = BytesIO()
        prepared.save(
            stream,
            format=_PILLOW_NAME_BY_FORMAT[target_format],
            **options,
        )
        return stream.getvalue()
    finally:
        prepared.close()


def _encode_to_size(
    image: Image.Image,
    target_format: DocumentFormat,
    max_bytes: int,
) -> tuple[bytes, tuple[int, int], int | None]:
    current = image
    try:
        for _ in range(_MAX_DIMENSION_ATTEMPTS):
            if target_format in _QUALITY_FORMATS:
                candidate, quality = _quality_candidate(current, target_format, max_bytes)
            else:
                candidate = _encode(current, target_format, size_mode=True)
                quality = None
            if len(candidate) <= max_bytes:
                return candidate, current.size, quality
            if current.size == (1, 1):
                break
            next_dimensions = _smaller_dimensions(current.size, max_bytes, len(candidate))
            smaller = _resize(current, next_dimensions)
            if current is not image:
                current.close()
            current = smaller
    finally:
        if current is not image:
            current.close()
    raise InvalidConversionRequestError(
        "max_bytes is too small for a valid image in the requested format."
    )


def _quality_candidate(
    image: Image.Image,
    target_format: DocumentFormat,
    max_bytes: int,
) -> tuple[bytes, int]:
    floor_candidate = _encode(image, target_format, quality=_MIN_SEARCH_QUALITY)
    if len(floor_candidate) > max_bytes:
        return floor_candidate, _MIN_SEARCH_QUALITY
    # A bounded descending scan handles encoder-size non-monotonicity and returns
    # the highest quality whose actual encoded bytes satisfy the requested limit.
    for quality in range(_MAX_SEARCH_QUALITY, _MIN_SEARCH_QUALITY, -1):
        candidate = _encode(image, target_format, quality=quality)
        if len(candidate) <= max_bytes:
            return candidate, quality
    return floor_candidate, _MIN_SEARCH_QUALITY


def _smaller_dimensions(
    dimensions: tuple[int, int], max_bytes: int, current_bytes: int
) -> tuple[int, int]:
    width, height = dimensions
    scale = min(
        _SHRINK_SAFETY_FACTOR,
        math.sqrt(max_bytes / current_bytes) * _SHRINK_SAFETY_FACTOR,
    )
    new_width = max(1, math.floor(width * scale))
    new_height = max(1, math.floor(height * scale))
    if (new_width, new_height) == dimensions:
        if width >= height and width > 1:
            new_width -= 1
        elif height > 1:
            new_height -= 1
    return new_width, new_height


def _install_output(
    encoded: bytes, output_path: Path, target_format: DocumentFormat
) -> None:
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w+b",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=output_path.suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(encoded)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        _validate_encoded_output(temporary_path, target_format)
        os.replace(temporary_path, output_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)
