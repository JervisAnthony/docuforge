"""Low-level Office-to-PDF conversion engine API."""

from docuforge.converters.office.engine import OfficeConversionEngine
from docuforge.converters.office.exceptions import (
    OfficeConversionError,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
)
from docuforge.converters.office.libreoffice import (
    DEFAULT_OFFICE_TIMEOUT_SECONDS,
    LibreOfficeEngine,
)
from docuforge.converters.office.models import (
    SUPPORTED_OFFICE_SOURCE_FORMATS,
    OfficeConversionRequest,
    OfficeConversionResult,
)

__all__ = [
    "DEFAULT_OFFICE_TIMEOUT_SECONDS",
    "SUPPORTED_OFFICE_SOURCE_FORMATS",
    "LibreOfficeEngine",
    "OfficeConversionEngine",
    "OfficeConversionError",
    "OfficeConversionRequest",
    "OfficeConversionResult",
    "OfficeEngineExecutionError",
    "OfficeEngineTimeoutError",
    "OfficeEngineUnavailableError",
]
