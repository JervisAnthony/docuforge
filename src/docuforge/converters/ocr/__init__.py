"""Backend-neutral OCR engine contract and local Tesseract adapter."""

from docuforge.converters.ocr.engine import OcrEngine
from docuforge.converters.ocr.exceptions import (
    OcrEngineExecutionError,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrError,
    OcrOutputError,
)
from docuforge.converters.ocr.image_to_text import ImageToTextConverter, extract_text_from_image
from docuforge.converters.ocr.models import (
    ImageToTextRequest,
    ImageToTextResult,
    OcrEngineRequest,
    OcrEngineResult,
    ScannedPdfToSearchablePdfRequest,
    ScannedPdfToSearchablePdfResult,
    ScannedPdfToTextRequest,
    ScannedPdfToTextResult,
)
from docuforge.converters.ocr.scanned_pdf import (
    ScannedPdfToSearchablePdfConverter,
    ScannedPdfToTextConverter,
    extract_text_from_scanned_pdf,
    make_scanned_pdf_searchable,
)
from docuforge.converters.ocr.tesseract import DEFAULT_OCR_TIMEOUT_SECONDS, TesseractEngine

__all__ = [
    "DEFAULT_OCR_TIMEOUT_SECONDS",
    "ImageToTextConverter",
    "ImageToTextRequest",
    "ImageToTextResult",
    "OcrEngine",
    "OcrEngineExecutionError",
    "OcrEngineRequest",
    "OcrEngineResult",
    "OcrEngineTimeoutError",
    "OcrEngineUnavailableError",
    "OcrError",
    "OcrOutputError",
    "ScannedPdfToSearchablePdfConverter",
    "ScannedPdfToSearchablePdfRequest",
    "ScannedPdfToSearchablePdfResult",
    "ScannedPdfToTextConverter",
    "ScannedPdfToTextRequest",
    "ScannedPdfToTextResult",
    "TesseractEngine",
    "extract_text_from_image",
    "extract_text_from_scanned_pdf",
    "make_scanned_pdf_searchable",
]
