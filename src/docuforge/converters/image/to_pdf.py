"""Image-to-PDF converter implementation."""

import os
from contextlib import suppress
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image, ImageOps, UnidentifiedImageError

from docuforge.converters.image.exceptions import ImageProcessingError
from docuforge.converters.image.models import (
    SUPPORTED_IMAGE_FORMATS,
    ImageInput,
    ImageToPdfRequest,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    Converter,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)

PILLOW_FORMATS = {
    "BMP": DocumentFormat.BMP,
    "JPEG": DocumentFormat.JPG,
    "PNG": DocumentFormat.PNG,
    "TIFF": DocumentFormat.TIFF,
}


class ImageToPdfConverter(Converter):
    """Convert ordered image inputs into one PDF document."""

    def __init__(self, source_format: DocumentFormat = DocumentFormat.JPG) -> None:
        """Initialize a converter for one supported leading image format."""
        normalized_source = DocumentFormat.normalize(source_format)
        if normalized_source not in SUPPORTED_IMAGE_FORMATS:
            raise UnsupportedConversionError(
                f"Unsupported image-to-PDF source format: {normalized_source.value}."
            )
        super().__init__(
            ConversionOperation.CONVERT,
            normalized_source,
            DocumentFormat.PDF,
        )

    def convert(self, request: ConversionRequest) -> Path:
        """Convert image inputs in order and atomically replace the PDF output."""
        self._validate_request(request)
        assert isinstance(request, ImageToPdfRequest)

        pages: list[Image.Image] = []
        temporary_path: Path | None = None
        try:
            for image_input in request.images:
                pages.append(self._load_page(image_input))

            with NamedTemporaryFile(
                mode="w+b",
                dir=request.output_path.parent,
                prefix=f".{request.output_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                pages[0].save(
                    temporary_file,
                    format="PDF",
                    save_all=True,
                    append_images=pages[1:],
                )
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            os.replace(temporary_path, request.output_path)
            temporary_path = None
            return request.output_path
        except ImageProcessingError:
            raise
        except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise ImageProcessingError("Unable to convert the requested images to PDF.") from error
        finally:
            for page in pages:
                page.close()
            if temporary_path is not None:
                with suppress(OSError):
                    temporary_path.unlink(missing_ok=True)

    def _validate_request(self, request: ConversionRequest) -> None:
        """Validate converter identity and all filesystem paths."""
        if not isinstance(request, ConversionRequest):
            raise TypeError("request must be an instance of ConversionRequest")
        if (
            request.operation is not ConversionOperation.CONVERT
            or request.source_format is not self.source_format
            or request.target_format is not DocumentFormat.PDF
        ):
            raise UnsupportedConversionError(
                "ImageToPdfConverter does not support the requested conversion identity."
            )
        if not isinstance(request, ImageToPdfRequest):
            raise InvalidConversionRequestError(
                "Image-to-PDF conversion requires an ImageToPdfRequest."
            )

        resolved_inputs: set[Path] = set()
        for image_input in request.images:
            input_path = image_input.path
            if not input_path.exists():
                raise InvalidConversionRequestError(f"Input file does not exist: {input_path}.")
            if not input_path.is_file():
                raise InvalidConversionRequestError(f"Input path is not a file: {input_path}.")
            try:
                resolved_input = input_path.resolve(strict=True)
            except OSError as error:
                raise InvalidConversionRequestError(
                    f"Unable to resolve input file: {input_path}."
                ) from error
            if resolved_input in resolved_inputs:
                raise InvalidConversionRequestError(
                    "Input paths must not resolve to the same file."
                )
            resolved_inputs.add(resolved_input)

        output_parent = request.output_path.parent
        if not output_parent.exists() or not output_parent.is_dir():
            raise InvalidConversionRequestError(
                f"Output parent directory does not exist: {output_parent}."
            )
        if request.output_path.exists() and request.output_path.is_dir():
            raise InvalidConversionRequestError(
                f"Output path is a directory: {request.output_path}."
            )
        try:
            resolved_output = request.output_path.resolve(strict=False)
        except OSError as error:
            raise InvalidConversionRequestError(
                f"Unable to resolve output path: {request.output_path}."
            ) from error
        if resolved_output in resolved_inputs:
            raise InvalidConversionRequestError("Output path must not resolve to an input file.")

    @staticmethod
    def _load_page(image_input: ImageInput) -> Image.Image:
        """Load, orient, validate, and convert one image to opaque RGB."""
        with Image.open(image_input.path) as source:
            source.load()
            actual_format = PILLOW_FORMATS.get(source.format or "")
            if actual_format is None or actual_format is not image_input.format:
                raise InvalidConversionRequestError(
                    f"Image format does not match its declaration: {image_input.path}."
                )

            oriented = ImageOps.exif_transpose(source)
            try:
                if oriented.mode in {"LA", "RGBA"} or (
                    oriented.mode == "P" and "transparency" in oriented.info
                ):
                    rgba = oriented.convert("RGBA")
                    try:
                        background = Image.new("RGB", oriented.size, "white")
                        background.paste(rgba, mask=rgba.getchannel("A"))
                        return background
                    finally:
                        rgba.close()
                return oriented.convert("RGB")
            finally:
                if oriented is not source:
                    oriented.close()
