"""Bounded, transactional PDF page rendering into raster images."""

import math
import os
import shutil
from contextlib import suppress
from pathlib import Path
from tempfile import mkdtemp
from types import MappingProxyType

import pypdfium2 as pdfium

from docuforge.converters.image.convert_path import (
    _PILLOW_NAME_BY_FORMAT,
    _prepare_for_target,
    _validate_encoded_output,
)
from docuforge.converters.image.exceptions import ImageProcessingError
from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.models import (
    PdfToImagesPathRequest,
    PdfToImagesPathResult,
)
from docuforge.core import InvalidConversionRequestError, UnsupportedConversionError

_CANONICAL_SUFFIX = MappingProxyType(
    {
        "jpg": ".jpg",
        "png": ".png",
        "webp": ".webp",
        "bmp": ".bmp",
        "tiff": ".tiff",
    }
)


def pdf_to_images_path(request: PdfToImagesPathRequest) -> PdfToImagesPathResult:
    """Render every PDF page in source order and install one complete directory."""
    if not isinstance(request, PdfToImagesPathRequest):
        raise TypeError("request must be an instance of PdfToImagesPathRequest")

    _validate_paths(request.input_path, request.output_directory)
    temporary_directory: Path | None = None
    try:
        temporary_directory = Path(
            mkdtemp(
                dir=request.output_directory.parent,
                prefix=f".{request.output_directory.name}.",
                suffix=".tmp",
            )
        )
        with pdfium.PdfDocument(request.input_path) as document:
            page_count = len(document)
            if page_count == 0:
                raise InvalidConversionRequestError(
                    "PDF rendering requires at least one page."
                )
            if page_count > request.max_pages:
                raise InvalidConversionRequestError(
                    "PDF page count exceeds the configured rendering limit."
                )

            scale = request.dpi / 72
            _validate_page_dimensions(
                document,
                scale=scale,
                max_pixels_per_page=request.max_pixels_per_page,
            )
            suffix = _CANONICAL_SUFFIX[request.output_format.value]
            for page_index in range(page_count):
                output_path = temporary_directory / f"page-{page_index + 1:04d}{suffix}"
                _render_page(document, page_index, scale, output_path, request)

        os.replace(temporary_directory, request.output_directory)
        temporary_directory = None
        output_paths = tuple(
            request.output_directory / f"page-{page_number:04d}{suffix}"
            for page_number in range(1, page_count + 1)
        )
        return PdfToImagesPathResult(
            input_path=request.input_path,
            output_directory=request.output_directory,
            output_format=request.output_format,
            dpi=request.dpi,
            page_count=page_count,
            output_paths=output_paths,
        )
    except (InvalidConversionRequestError, UnsupportedConversionError, PdfProcessingError):
        raise
    except (OSError, ValueError, pdfium.PdfiumError, ImageProcessingError) as error:
        raise PdfProcessingError("Unable to render the requested PDF document.") from error
    finally:
        if temporary_directory is not None:
            with suppress(OSError):
                shutil.rmtree(temporary_directory)


def _validate_paths(input_path: Path, output_directory: Path) -> None:
    if input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError("Input file must use the .pdf extension.")
    if not input_path.exists():
        raise InvalidConversionRequestError("Input file does not exist.")
    if not input_path.is_file():
        raise InvalidConversionRequestError("Input path is not a file.")
    if output_directory.exists():
        raise InvalidConversionRequestError("Output directory must not already exist.")
    output_parent = output_directory.parent
    if not output_parent.exists() or not output_parent.is_dir():
        raise InvalidConversionRequestError("Output parent directory does not exist.")
    try:
        input_path.resolve(strict=True)
        output_directory.resolve(strict=False)
    except OSError as error:
        raise InvalidConversionRequestError("Unable to resolve render paths.") from error


def _validate_page_dimensions(
    document: pdfium.PdfDocument,
    *,
    scale: float,
    max_pixels_per_page: int,
) -> None:
    for page_index in range(len(document)):
        page = document[page_index]
        try:
            width, height = page.get_size()
        finally:
            page.close()
        if not math.isfinite(width) or not math.isfinite(height):
            raise InvalidConversionRequestError("PDF page dimensions are invalid.")
        pixel_width = math.ceil(width * scale)
        pixel_height = math.ceil(height * scale)
        if pixel_width <= 0 or pixel_height <= 0:
            raise InvalidConversionRequestError("PDF page dimensions are invalid.")
        if pixel_width * pixel_height > max_pixels_per_page:
            raise InvalidConversionRequestError(
                "PDF page exceeds the configured pixel rendering limit."
            )


def _render_page(
    document: pdfium.PdfDocument,
    page_index: int,
    scale: float,
    output_path: Path,
    request: PdfToImagesPathRequest,
) -> None:
    rendered_image = None
    page = document[page_index]
    try:
        bitmap = page.render(
            scale=scale,
            fill_color=(255, 255, 255, 255),
            rev_byteorder=True,
        )
        try:
            borrowed_image = bitmap.to_pil()
            try:
                rendered_image = borrowed_image.copy()
            finally:
                borrowed_image.close()
        finally:
            bitmap.close()
    finally:
        page.close()

    assert rendered_image is not None
    try:
        prepared = _prepare_for_target(rendered_image, request.output_format)
        try:
            prepared.save(
                output_path,
                format=_PILLOW_NAME_BY_FORMAT[request.output_format],
            )
        finally:
            prepared.close()
        _validate_encoded_output(output_path, request.output_format)
    finally:
        rendered_image.close()
