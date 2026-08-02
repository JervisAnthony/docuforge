"""High-level orchestration for converting ordered image paths to PDF."""

from collections.abc import Mapping
from types import MappingProxyType

from docuforge.converters.image.models import (
    ImageInput,
    ImageToPdfPathRequest,
    ImageToPdfPathResult,
    ImageToPdfRequest,
)
from docuforge.converters.image.to_pdf import ImageToPdfConverter
from docuforge.core import DocumentFormat, InvalidConversionRequestError

_IMAGE_FORMAT_BY_SUFFIX: Mapping[str, DocumentFormat] = MappingProxyType(
    {
        ".jpg": DocumentFormat.JPG,
        ".jpeg": DocumentFormat.JPG,
        ".png": DocumentFormat.PNG,
        ".bmp": DocumentFormat.BMP,
        ".tif": DocumentFormat.TIFF,
        ".tiff": DocumentFormat.TIFF,
    }
)

_INPUT_EXTENSION_ERROR = "Input file must use .jpg, .jpeg, .png, .bmp, .tif, or .tiff"


def convert_images_to_pdf(
    request: ImageToPdfPathRequest,
) -> ImageToPdfPathResult:
    """Infer ordered image formats and delegate conversion to the existing converter."""
    if not isinstance(request, ImageToPdfPathRequest):
        raise TypeError("request must be an instance of ImageToPdfPathRequest")

    inferred_formats: list[DocumentFormat] = []
    for input_path in request.input_paths:
        inferred_format = _IMAGE_FORMAT_BY_SUFFIX.get(input_path.suffix.lower())
        if inferred_format is None:
            raise InvalidConversionRequestError(
                f"{_INPUT_EXTENSION_ERROR}: {input_path}"
            )
        inferred_formats.append(inferred_format)

    if request.output_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Output file must use the .pdf extension: {request.output_path}"
        )

    image_inputs = tuple(
        ImageInput(path=input_path, format=inferred_format)
        for input_path, inferred_format in zip(
            request.input_paths,
            inferred_formats,
            strict=True,
        )
    )
    low_level_request = ImageToPdfRequest(
        images=image_inputs,
        output_path=request.output_path,
    )
    converted_path = ImageToPdfConverter(inferred_formats[0]).convert(low_level_request)
    return ImageToPdfPathResult(
        input_paths=request.input_paths,
        output_path=converted_path,
    )
