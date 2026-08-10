"""Safe path-based raster image format conversion."""

import os
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile
from types import MappingProxyType

from PIL import Image, ImageOps, UnidentifiedImageError

from docuforge.converters.image.exceptions import ImageProcessingError
from docuforge.converters.image.models import (
    SUPPORTED_RASTER_FORMATS,
    ImageConvertPathRequest,
    ImageConvertPathResult,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)

_FORMAT_BY_SUFFIX: Mapping[str, DocumentFormat] = MappingProxyType(
    {
        ".jpg": DocumentFormat.JPG,
        ".jpeg": DocumentFormat.JPG,
        ".png": DocumentFormat.PNG,
        ".webp": DocumentFormat.WEBP,
        ".bmp": DocumentFormat.BMP,
        ".tif": DocumentFormat.TIFF,
        ".tiff": DocumentFormat.TIFF,
    }
)

_FORMAT_BY_PILLOW_NAME: Mapping[str, DocumentFormat] = MappingProxyType(
    {
        "JPEG": DocumentFormat.JPG,
        "PNG": DocumentFormat.PNG,
        "WEBP": DocumentFormat.WEBP,
        "BMP": DocumentFormat.BMP,
        "TIFF": DocumentFormat.TIFF,
    }
)

_PILLOW_NAME_BY_FORMAT: Mapping[DocumentFormat, str] = MappingProxyType(
    {image_format: pillow_name for pillow_name, image_format in _FORMAT_BY_PILLOW_NAME.items()}
)


def convert_image_path(request: ImageConvertPathRequest) -> ImageConvertPathResult:
    """Decode one supported raster image and atomically re-encode its target format."""
    if not isinstance(request, ImageConvertPathRequest):
        raise TypeError("request must be an instance of ImageConvertPathRequest")

    target_format = _target_format(request.output_path)
    _validate_paths(request.input_path, request.output_path)

    prepared: Image.Image | None = None
    temporary_path: Path | None = None
    try:
        with Image.open(request.input_path) as source:
            source_format = _source_format(source)
            if getattr(source, "n_frames", 1) != 1:
                raise UnsupportedConversionError(
                    "Raster format conversion supports only single-frame images."
                )
            source.load()
            oriented = ImageOps.exif_transpose(source)
            try:
                oriented.load()
                prepared = _prepare_for_target(oriented, target_format)
            finally:
                if oriented is not source:
                    oriented.close()

        with NamedTemporaryFile(
            mode="w+b",
            dir=request.output_path.parent,
            prefix=f".{request.output_path.name}.",
            suffix=request.output_path.suffix,
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)

        prepared.save(
            temporary_path,
            format=_PILLOW_NAME_BY_FORMAT[target_format],
        )
        with temporary_path.open("r+b") as output_stream:
            output_stream.flush()
            os.fsync(output_stream.fileno())
        _validate_encoded_output(temporary_path, target_format)
        os.replace(temporary_path, request.output_path)
        temporary_path = None
        return ImageConvertPathResult(
            input_path=request.input_path,
            output_path=request.output_path,
            source_format=source_format,
            target_format=target_format,
        )
    except (InvalidConversionRequestError, UnsupportedConversionError, ImageProcessingError):
        raise
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ImageProcessingError(
            "Unable to convert the requested raster image."
        ) from error
    finally:
        if prepared is not None:
            prepared.close()
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _target_format(output_path: Path) -> DocumentFormat:
    target_format = _FORMAT_BY_SUFFIX.get(output_path.suffix.lower())
    if target_format is None:
        raise UnsupportedConversionError(
            "Output file must use .jpg, .jpeg, .png, .webp, .bmp, .tif, or .tiff."
        )
    return target_format


def _source_format(source: Image.Image) -> DocumentFormat:
    source_format = _FORMAT_BY_PILLOW_NAME.get(source.format or "")
    if source_format is None or source_format not in SUPPORTED_RASTER_FORMATS:
        raise UnsupportedConversionError(
            "The decoded source image format is not supported."
        )
    return source_format


def _validate_paths(input_path: Path, output_path: Path) -> None:
    if not input_path.exists():
        raise InvalidConversionRequestError(f"Input file does not exist: {input_path}.")
    if not input_path.is_file():
        raise InvalidConversionRequestError(f"Input path is not a file: {input_path}.")

    output_parent = output_path.parent
    if not output_parent.exists() or not output_parent.is_dir():
        raise InvalidConversionRequestError(
            f"Output parent directory does not exist: {output_parent}."
        )
    if output_path.exists() and output_path.is_dir():
        raise InvalidConversionRequestError(f"Output path is a directory: {output_path}.")

    try:
        resolved_input = input_path.resolve(strict=True)
    except OSError as error:
        raise InvalidConversionRequestError(
            f"Unable to resolve input file: {input_path}."
        ) from error
    try:
        resolved_output = output_path.resolve(strict=False)
    except OSError as error:
        raise InvalidConversionRequestError(
            f"Unable to resolve output path: {output_path}."
        ) from error
    if resolved_input == resolved_output:
        raise InvalidConversionRequestError(
            "Output path must not resolve to the input file."
        )


def _prepare_for_target(image: Image.Image, target_format: DocumentFormat) -> Image.Image:
    if target_format in {DocumentFormat.JPG, DocumentFormat.BMP}:
        return _flatten_to_white_rgb(image)
    if target_format is DocumentFormat.WEBP:
        return image.convert("RGBA" if _has_transparency(image) else "RGB")
    if target_format is DocumentFormat.PNG:
        if _has_transparency(image) and image.mode == "P":
            return image.convert("RGBA")
        if image.mode in {"1", "L", "LA", "P", "RGB", "RGBA", "I", "I;16"}:
            return image.copy()
        return image.convert("RGBA" if _has_transparency(image) else "RGB")
    if target_format is DocumentFormat.TIFF:
        return image.copy()
    raise UnsupportedConversionError("The requested raster target is not supported.")


def _has_transparency(image: Image.Image) -> bool:
    return "A" in image.getbands() or (
        image.mode == "P" and "transparency" in image.info
    )


def _flatten_to_white_rgb(image: Image.Image) -> Image.Image:
    if not _has_transparency(image):
        return image.convert("RGB")

    rgba = image.convert("RGBA")
    try:
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    finally:
        rgba.close()


def _validate_encoded_output(output_path: Path, target_format: DocumentFormat) -> None:
    try:
        with Image.open(output_path) as encoded:
            encoded.load()
            actual_format = _FORMAT_BY_PILLOW_NAME.get(encoded.format or "")
    except (
        OSError,
        ValueError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as error:
        raise ImageProcessingError(
            "Unable to validate the converted raster image."
        ) from error
    if actual_format is not target_format:
        raise ImageProcessingError("Converted raster image format validation failed.")
