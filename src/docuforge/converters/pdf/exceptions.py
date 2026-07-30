"""Exceptions raised by PDF converter implementations."""

from docuforge.core import DocuForgeError


class PdfProcessingError(DocuForgeError):
    """Raised when a PDF cannot be read, merged, or written."""
