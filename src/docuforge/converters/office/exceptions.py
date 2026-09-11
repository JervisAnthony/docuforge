"""Exceptions raised by Office conversion engines."""

from docuforge.core import DocuForgeError


class OfficeConversionError(DocuForgeError):
    """Raised when an Office document cannot produce a valid PDF artifact."""


class OfficeEngineUnavailableError(OfficeConversionError):
    """Raised when no usable LibreOffice executable can be found."""


class OfficeEngineTimeoutError(OfficeConversionError):
    """Raised when an Office conversion exceeds its configured time limit."""


class OfficeEngineExecutionError(OfficeConversionError):
    """Raised when the LibreOffice process cannot run successfully."""
