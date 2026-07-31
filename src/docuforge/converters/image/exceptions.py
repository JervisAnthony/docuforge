"""Exceptions raised by image converter implementations."""

from docuforge.core import DocuForgeError


class ImageProcessingError(DocuForgeError):
    """Raised when an image cannot be read or converted to PDF."""
