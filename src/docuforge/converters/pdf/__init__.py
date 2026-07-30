"""Public PDF converter API."""

from docuforge.converters.pdf.exceptions import PdfProcessingError
from docuforge.converters.pdf.merge import PdfMergeConverter

__all__ = ["PdfMergeConverter", "PdfProcessingError"]
