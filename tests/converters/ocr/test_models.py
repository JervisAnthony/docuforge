"""Model and language contract tests."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from docuforge.converters.ocr import OcrEngineRequest, OcrEngineResult
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
