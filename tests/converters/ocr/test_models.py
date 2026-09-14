"""Model and language contract tests."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from docuforge.converters.ocr import (
    ImageToTextRequest,
    ImageToTextResult,
    OcrEngineRequest,
    OcrEngineResult,
    ScannedPdfToSearchablePdfRequest,
    ScannedPdfToSearchablePdfResult,
    ScannedPdfToTextRequest,
    ScannedPdfToTextResult,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError


@pytest.mark.parametrize("format_value", [DocumentFormat.TXT, "TXT", DocumentFormat.PDF, "pdf"])
def test_request_and_result_normalize_supported_formats(format_value):
    request = OcrEngineRequest(Path("a.png"), Path("out"), format_value)
    result = OcrEngineResult(Path("a.png"), Path("out/a.txt"), format_value, "eng")
    assert request.output_format is DocumentFormat.normalize(format_value)
    assert result.output_format is request.output_format
    assert request.language == "eng"
    assert not hasattr(request, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.language = "deu"
    with pytest.raises(FrozenInstanceError):
        result.language = "deu"


@pytest.mark.parametrize("value", ["jpg", "gif", "", "not-a-format", 4])
def test_models_reject_unsupported_outputs(value):
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineRequest(Path("a.png"), Path("out"), value)
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineResult(Path("a.png"), Path("out/a.txt"), value, "eng")


@pytest.mark.parametrize("field", ["input_path", "output_directory"])
def test_request_requires_path_objects(field):
    values = {"input_path": Path("a.png"), "output_directory": Path("out")}
    values[field] = "not-a-path"
    with pytest.raises(TypeError):
        OcrEngineRequest(**values, output_format=DocumentFormat.TXT)


@pytest.mark.parametrize("field", ["input_path", "output_path"])
def test_result_requires_path_objects(field):
    values = {"input_path": Path("a.png"), "output_path": Path("out/a.txt")}
    values[field] = "not-a-path"
    with pytest.raises(TypeError):
        OcrEngineResult(**values, output_format=DocumentFormat.TXT, language="eng")


@pytest.mark.parametrize("language", ["eng", "deu", "eng+deu", "pt_BR", "zh-Hans"])
def test_language_accepts_conservative_selectors(language):
    assert OcrEngineRequest(Path("a.png"), Path("out"), "txt", language).language == language
    assert OcrEngineResult(Path("a.png"), Path("out/a.txt"), "txt", language).language == language


@pytest.mark.parametrize(
    "language",
    ["", " ", "eng deu", "eng\n", "-l", "--psm", "../eng", "eng\\x", "eng+", "+eng", "eng++deu", "a" * 129, None],
)
def test_language_rejects_unsafe_selectors(language):
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineRequest(Path("a.png"), Path("out"), "txt", language)
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineResult(Path("a.png"), Path("out/a.txt"), "txt", language)


def test_image_to_text_models_are_frozen_and_slotted():
    request = ImageToTextRequest(Path("a.png"), Path("out/custom.txt"))
    result = ImageToTextResult(Path("a.png"), Path("out/custom.txt"), "Hello", "PNG", "deu")
    assert request.language == "eng"
    assert result.source_format is DocumentFormat.PNG
    assert result.language == "deu"
    assert not hasattr(request, "__dict__")
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        request.language = "deu"
    with pytest.raises(FrozenInstanceError):
        result.text = "changed"


@pytest.mark.parametrize("field", ["input_path", "output_path"])
def test_image_to_text_models_require_paths(field):
    values = {"input_path": Path("a.png"), "output_path": Path("out/a.txt")}
    values[field] = "not-a-path"
    with pytest.raises(TypeError):
        ImageToTextRequest(**values)
    with pytest.raises(TypeError):
        ImageToTextResult(**values, text="", source_format=DocumentFormat.PNG, language="eng")


@pytest.mark.parametrize("source_format", ["jpg", "png", "webp", "bmp", "tiff"])
def test_image_to_text_result_accepts_raster_formats(source_format):
    result = ImageToTextResult(Path("a.png"), Path("a.txt"), "", source_format, "eng")
    assert result.source_format is DocumentFormat.normalize(source_format)


@pytest.mark.parametrize("source_format", ["gif", "pdf", "txt", "unknown"])
def test_image_to_text_result_rejects_non_raster_formats(source_format):
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextResult(Path("a.png"), Path("a.txt"), "", source_format, "eng")


def test_image_to_text_models_validate_text_and_language():
    with pytest.raises(TypeError):
        ImageToTextResult(Path("a.png"), Path("a.txt"), b"text", "png", "eng")
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextRequest(Path("a.png"), Path("a.txt"), "--unsafe")
    with pytest.raises(InvalidConversionRequestError):
        ImageToTextResult(Path("a.png"), Path("a.txt"), "", "png", "eng deu")


@pytest.mark.parametrize("model", [OcrEngineRequest, OcrEngineResult])
def test_engine_dpi_is_optional_and_backward_compatible(model):
    args = (Path("a.png"), Path("out"), "txt", "eng")
    assert model(*args).dpi is None
    assert model(*args, dpi=300).dpi == 300


@pytest.mark.parametrize("dpi", [True, False, 0, -1, 1.5, "300"])
def test_engine_models_reject_invalid_dpi(dpi):
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineRequest(Path("a.png"), Path("out"), "txt", dpi=dpi)
    with pytest.raises(InvalidConversionRequestError):
        OcrEngineResult(Path("a.png"), Path("out/a.txt"), "txt", "eng", dpi)


@pytest.mark.parametrize("model", [ScannedPdfToTextRequest, ScannedPdfToSearchablePdfRequest])
def test_scanned_requests_are_frozen_slotted_and_default_bounded(model):
    item = model(Path("scan.pdf"), Path("out.txt"))
    assert (item.language, item.dpi, item.max_pages, item.max_pixels_per_page) == (
        "eng", 300, 100, 40_000_000
    )
    assert not hasattr(item, "__dict__")
    with pytest.raises(FrozenInstanceError):
        item.dpi = 72


@pytest.mark.parametrize("dpi", [72, 150, 300, 600])
def test_scanned_requests_accept_valid_dpi(dpi):
    assert ScannedPdfToTextRequest(Path("a.pdf"), Path("a.txt"), dpi=dpi).dpi == dpi


@pytest.mark.parametrize("dpi", [True, False, 0, -1, 601, 1.5, "300"])
def test_scanned_requests_reject_invalid_dpi(dpi):
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToTextRequest(Path("a.pdf"), Path("a.txt"), dpi=dpi)


@pytest.mark.parametrize("field", ["max_pages", "max_pixels_per_page"])
@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "100"])
def test_scanned_requests_reject_invalid_limits(field, value):
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToSearchablePdfRequest(Path("a.pdf"), Path("a.pdf"), **{field: value})


def test_scanned_result_contracts():
    text = ScannedPdfToTextResult(Path("a.pdf"), Path("a.txt"), "x\fy", ("x", "y"), 2, "eng", 300)
    pdf = ScannedPdfToSearchablePdfResult(Path("a.pdf"), Path("b.pdf"), 2, "eng", 300)
    assert not hasattr(text, "__dict__")
    assert not hasattr(pdf, "__dict__")
    with pytest.raises(FrozenInstanceError):
        text.text = "changed"
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToTextResult(Path("a.pdf"), Path("a.txt"), "x", ("x",), 2, "eng", 300)
    with pytest.raises(TypeError):
        ScannedPdfToTextResult(Path("a.pdf"), Path("a.txt"), "x", ["x"], 1, "eng", 300)
    with pytest.raises(InvalidConversionRequestError):
        ScannedPdfToSearchablePdfResult(Path("a.pdf"), Path("b.pdf"), 0, "eng", 300)
