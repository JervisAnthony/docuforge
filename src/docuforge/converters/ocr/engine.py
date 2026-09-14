"""Backend-neutral OCR engine boundary."""

from typing import Protocol

from docuforge.converters.ocr.models import OcrEngineRequest, OcrEngineResult


class OcrEngine(Protocol):
    """Produce one trusted OCR artifact from one raster input."""

    def recognize(self, request: OcrEngineRequest) -> OcrEngineResult: ...
