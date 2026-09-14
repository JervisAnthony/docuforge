"""Backend-neutral OCR engine contract and local Tesseract adapter."""

from docuforge.converters.ocr.engine import OcrEngine
from docuforge.converters.ocr.exceptions import (
    OcrEngineExecutionError,
    OcrEngineTimeoutError,
    OcrEngineUnavailableError,
    OcrError,
    OcrOutputError,
)
from docuforge.converters.ocr.models import OcrEngineRequest, OcrEngineResult
from docuforge.converters.ocr.tesseract import DEFAULT_OCR_TIMEOUT_SECONDS, TesseractEngine

__all__ = [
    "DEFAULT_OCR_TIMEOUT_SECONDS",
    "OcrEngine",
    "OcrEngineExecutionError",
    "OcrEngineRequest",
    "OcrEngineResult",
    "OcrEngineTimeoutError",
    "OcrEngineUnavailableError",
    "OcrError",
    "OcrOutputError",
    "TesseractEngine",
]
