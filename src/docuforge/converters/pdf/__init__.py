"""Public PDF converter API."""

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.merge import PdfMergeConverter
from docuforge.converters.pdf.models import (
    PageGroup,
    PageRotation,
    PdfRotateRequest,
    PdfSplitDirectoryRequest,
    PdfSplitDirectoryResult,
    PdfSplitRequest,
)
from docuforge.converters.pdf.rotate import PdfRotateConverter
from docuforge.converters.pdf.split import PdfSplitConverter
from docuforge.converters.pdf.split_directory import split_pdf_to_directory

__all__ = [
    "PageGroup",
    "PageRotation",
    "PdfMergeConverter",
    "PdfProcessingError",
    "PdfRotateConverter",
    "PdfRotateRequest",
    "PdfSplitConverter",
    "PdfSplitDirectoryRequest",
    "PdfSplitDirectoryResult",
    "PdfSplitRequest",
    "split_pdf_to_directory",
]
