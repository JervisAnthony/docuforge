"""High-level orchestration for extracting selected pages from one PDF."""

from docuforge.converters.pdf.extract_pages import PdfExtractPagesConverter
from docuforge.converters.pdf.models import (
    PdfExtractPagesPathRequest,
    PdfExtractPagesPathResult,
    PdfExtractPagesRequest,
)
from docuforge.core import InvalidConversionRequestError


def extract_pdf_pages(
    request: PdfExtractPagesPathRequest,
) -> PdfExtractPagesPathResult:
    """Validate PDF suffixes and delegate to the low-level extraction converter."""
    if not isinstance(request, PdfExtractPagesPathRequest):
        raise TypeError("request must be an instance of PdfExtractPagesPathRequest")

    if request.input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Input file must use the .pdf extension: {request.input_path}"
        )
    if request.output_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Output file must use the .pdf extension: {request.output_path}"
        )

    low_level_request = PdfExtractPagesRequest(
        input_paths=(request.input_path,),
        output_paths=(request.output_path,),
        page_indices=request.page_indices,
    )
    converted_paths = PdfExtractPagesConverter().convert(low_level_request)
    converted_path = converted_paths[0]
    return PdfExtractPagesPathResult(
        input_path=request.input_path,
        output_path=converted_path,
        page_indices=request.page_indices,
    )
