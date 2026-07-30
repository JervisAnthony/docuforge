"""Exceptions raised by the DocuForge domain layer."""


class DocuForgeError(Exception):
    """Base exception for expected DocuForge errors."""


class InvalidFormatError(DocuForgeError):
    """Raised when a document format value cannot be normalized."""


class InvalidConversionRequestError(DocuForgeError):
    """Raised when a conversion request violates domain constraints."""


class UnsupportedConversionError(DocuForgeError):
    """Raised when conversion between two formats is unsupported."""


class ConverterNotFoundError(DocuForgeError):
    """Raised when no converter is available for a conversion request."""
