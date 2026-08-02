"""Public PDF converter API."""

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.merge import PdfMergeConverter
from docuforge.converters.pdf.models import (
    PageGroup,
    PdfSplitDirectoryRequest,
    PdfSplitDirectoryResult,
    PdfSplitRequest,
)
from docuforge.converters.pdf.split import PdfSplitConverter
from docuforge.converters.pdf.split_directory import split_pdf_to_directory

__all__ = [
    "PageGroup",
    "PdfMergeConverter",
    "PdfProcessingError",
    "PdfSplitConverter",
    "PdfSplitDirectoryRequest",
    "PdfSplitDirectoryResult",
    "PdfSplitRequest",
    "split_pdf_to_directory",
]
