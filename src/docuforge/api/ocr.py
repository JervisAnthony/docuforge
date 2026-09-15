"""HTTP adaptation for the existing OCR core workflows."""

from collections.abc import Callable
from pathlib import Path

from docuforge.api.config import ApiSettings
from docuforge.api.errors import ApiError
from docuforge.api.uploads import StoredUpload
from docuforge.converters.ocr import (
    ImageToTextConverter,
    ImageToTextRequest,
    OcrEngine,
    OcrEngineExecutionError,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrError,
    OcrOutputError,
    ScannedPdfToSearchablePdfConverter,
    ScannedPdfToSearchablePdfRequest,
    ScannedPdfToTextConverter,
    ScannedPdfToTextRequest,
)
from docuforge.core import InvalidConversionRequestError, UnsupportedConversionError

OcrEngineFactory = Callable[[], OcrEngine]


def extract_uploaded_image_text(
    upload: StoredUpload, output_path: Path, engine_factory: OcrEngineFactory
) -> None:
    """Resolve the engine during an OCR request and use image core validation."""
    _run_ocr(
        engine_factory,
        lambda engine: ImageToTextConverter(engine).convert(
            ImageToTextRequest(upload.stored_path, output_path)
        ),
    )


def extract_uploaded_pdf_text(
    upload: StoredUpload, output_path: Path, settings: ApiSettings,
    engine_factory: OcrEngineFactory,
) -> None:
    """OCR a bounded uploaded PDF using the core text workflow."""
    _run_ocr(
        engine_factory,
        lambda engine: ScannedPdfToTextConverter(engine).convert(
            ScannedPdfToTextRequest(
                upload.stored_path, output_path, dpi=300,
                max_pages=settings.max_pdf_render_pages,
                max_pixels_per_page=settings.max_pdf_render_pixels_per_page,
            )
        ),
    )


def make_uploaded_pdf_searchable(
    upload: StoredUpload, output_path: Path, settings: ApiSettings,
    engine_factory: OcrEngineFactory,
) -> None:
    """OCR a bounded uploaded PDF using the core searchable workflow."""
    _run_ocr(
        engine_factory,
        lambda engine: ScannedPdfToSearchablePdfConverter(engine).convert(
            ScannedPdfToSearchablePdfRequest(
                upload.stored_path, output_path, dpi=300,
                max_pages=settings.max_pdf_render_pages,
                max_pixels_per_page=settings.max_pdf_render_pixels_per_page,
            )
        ),
    )


def _run_ocr(engine_factory: OcrEngineFactory, operation: Callable[[OcrEngine], object]) -> None:
    try:
        operation(engine_factory())
    except OcrEngineUnavailableError:
        raise ApiError(status_code=503, code="ocr_engine_unavailable", message="OCR is temporarily unavailable.") from None
    except OcrEngineTimeoutError:
        raise ApiError(status_code=504, code="ocr_timeout", message="The OCR operation timed out.") from None
    except OcrEngineExecutionError:
        raise ApiError(status_code=502, code="ocr_engine_failed", message="The OCR engine failed.") from None
    except (InvalidConversionRequestError, UnsupportedConversionError, TypeError):
        raise ApiError(status_code=400, code="invalid_ocr_request", message="The OCR request is invalid.") from None
    except OcrOutputError:
        raise ApiError(
            status_code=422, code="ocr_processing_failed",
            message="The document could not be processed with OCR."
        ) from None
    except OcrError:
        raise ApiError(
            status_code=422, code="ocr_processing_failed",
            message="The document could not be processed with OCR."
        ) from None
