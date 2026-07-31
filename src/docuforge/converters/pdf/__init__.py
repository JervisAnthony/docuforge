"""Public PDF converter API."""

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.merge import PdfMergeConverter
from docuforge.converters.pdf.models import PageGroup, PdfSplitRequest
from docuforge.converters.pdf.split import PdfSplitConverter

__all__ = [
    "PageGroup",
    "PdfMergeConverter",
    "PdfProcessingError",
    "PdfSplitConverter",
    "PdfSplitRequest",
]
