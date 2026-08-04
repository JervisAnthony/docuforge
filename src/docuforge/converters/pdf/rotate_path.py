"""High-level orchestration for rotating selected pages in one PDF."""

from docuforge.converters.pdf.models import (
    PdfRotatePathRequest,
    PdfRotatePathResult,
    PdfRotateRequest,
)
from docuforge.converters.pdf.rotate import PdfRotateConverter
from docuforge.core import InvalidConversionRequestError


def rotate_pdf_pages(request: PdfRotatePathRequest) -> PdfRotatePathResult:
    """Validate PDF suffixes and delegate to the low-level rotation converter."""
    if not isinstance(request, PdfRotatePathRequest):
        raise TypeError("request must be an instance of PdfRotatePathRequest")

    if request.input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Input file must use the .pdf extension: {request.input_path}"
        )
    if request.output_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Output file must use the .pdf extension: {request.output_path}"
        )

    low_level_request = PdfRotateRequest(
        input_paths=(request.input_path,),
        output_paths=(request.output_path,),
        rotations=request.rotations,
    )
    converted_paths = PdfRotateConverter().convert(low_level_request)
    converted_path = converted_paths[0]
    return PdfRotatePathResult(
        input_path=request.input_path,
        output_path=converted_path,
        rotations=request.rotations,
    )
