"""HTTP adaptation for the existing Office-to-PDF core workflows."""

from collections.abc import Callable
from pathlib import Path

from docuforge.api.errors import ApiError
from docuforge.api.uploads import StoredUpload
from docuforge.converters.office import (
    DocxToPdfConverter,
    DocxToPdfRequest,
    OfficeConversionEngine,
    OfficeConversionError,
    OfficeEngineExecutionError,
    OfficeEngineTimeoutError,
    OfficeEngineUnavailableError,
    PptxToPdfConverter,
    PptxToPdfRequest,
    XlsxToPdfConverter,
    XlsxToPdfRequest,
)
from docuforge.core import (
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)

OfficeEngineFactory = Callable[[], OfficeConversionEngine]


def convert_uploaded_office(
    upload: StoredUpload,
    output_path: Path,
    source_format: DocumentFormat,
    engine_factory: OfficeEngineFactory,
) -> None:
    """Resolve an engine lazily and delegate to the matching core converter."""
    try:
        engine = engine_factory()
        if source_format is DocumentFormat.DOCX:
            DocxToPdfConverter(engine).convert(DocxToPdfRequest(upload.stored_path, output_path))
        elif source_format is DocumentFormat.PPTX:
            PptxToPdfConverter(engine).convert(PptxToPdfRequest(upload.stored_path, output_path))
        elif source_format is DocumentFormat.XLSX:
            XlsxToPdfConverter(engine).convert(XlsxToPdfRequest(upload.stored_path, output_path))
        else:
            raise UnsupportedConversionError("Unsupported Office source format.")
    except OfficeEngineUnavailableError:
        raise ApiError(
            status_code=503,
            code="office_engine_unavailable",
            message="Office conversion is temporarily unavailable.",
        ) from None
    except OfficeEngineTimeoutError:
        raise ApiError(
            status_code=504,
            code="office_conversion_timeout",
            message="The Office conversion timed out.",
        ) from None
    except OfficeEngineExecutionError:
        raise ApiError(
            status_code=502,
            code="office_engine_failed",
            message="The Office conversion engine failed.",
        ) from None
    except (InvalidConversionRequestError, UnsupportedConversionError, TypeError):
        raise ApiError(
            status_code=400,
            code="invalid_office_request",
            message="The Office conversion request is invalid.",
        ) from None
    except OfficeConversionError:
        raise ApiError(
            status_code=422,
            code="office_conversion_failed",
            message="The Office document could not be converted.",
        ) from None
