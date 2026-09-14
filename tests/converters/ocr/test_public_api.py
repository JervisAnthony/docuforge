"""OCR exports remain importable through both converter namespaces."""

from docuforge import converters
from docuforge.converters import ocr


def test_public_exports_match():
    names = (
        "OcrEngine", "OcrEngineRequest", "OcrEngineResult", "OcrError",
        "OcrEngineUnavailableError", "OcrEngineTimeoutError",
        "OcrEngineExecutionError", "OcrOutputError", "TesseractEngine",
    )
    for name in names:
        assert getattr(converters, name) is getattr(ocr, name)
        assert name in converters.__all__
        assert name in ocr.__all__
