"""High-level orchestration for removing selected pages from one PDF."""

from docuforge.converters.pdf.models import (
    PdfRemovePagesPathRequest,
    PdfRemovePagesPathResult,
    PdfRemovePagesRequest,
)
from docuforge.converters.pdf.remove_pages import PdfRemovePagesConverter
from docuforge.core import InvalidConversionRequestError


def remove_pdf_pages(
    request: PdfRemovePagesPathRequest,
) -> PdfRemovePagesPathResult:
    """Validate PDF suffixes and delegate to the low-level removal converter."""
    if not isinstance(request, PdfRemovePagesPathRequest):
        raise TypeError("request must be an instance of PdfRemovePagesPathRequest")

    if request.input_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Input file must use the .pdf extension: {request.input_path}"
        )
    if request.output_path.suffix.lower() != ".pdf":
        raise InvalidConversionRequestError(
            f"Output file must use the .pdf extension: {request.output_path}"
        )

    low_level_request = PdfRemovePagesRequest(
        input_paths=(request.input_path,),
        output_paths=(request.output_path,),
        page_indices=request.page_indices,
    )
    converted_paths = PdfRemovePagesConverter().convert(low_level_request)
    converted_path = converted_paths[0]
    return PdfRemovePagesPathResult(
        input_path=request.input_path,
        output_path=converted_path,
        page_indices=request.page_indices,
    )
