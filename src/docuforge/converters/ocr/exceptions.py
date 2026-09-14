"""Safe, structured failures from OCR engines."""

from docuforge.core import DocuForgeError


class OcrError(DocuForgeError):
    """Base class for OCR engine failures."""


class OcrEngineUnavailableError(OcrError):
    """No usable OCR executable was found."""


class OcrEngineTimeoutError(OcrError):
    """The OCR process exceeded its finite timeout."""


class OcrEngineExecutionError(OcrError):
    """The OCR process could not start or exited unsuccessfully."""


class OcrOutputError(OcrError):
    """The OCR artifact or its workspace could not be trusted or published."""
