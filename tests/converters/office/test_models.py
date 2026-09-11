"""Tests for Office conversion request and result models."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from docuforge.converters.office import OfficeConversionRequest, OfficeConversionResult
from docuforge.core import DocumentFormat, InvalidConversionRequestError


def test_office_request_is_an_immutable_path_value() -> None:
    request = OfficeConversionRequest(Path("source.docx"), Path("output"))

    with pytest.raises(FrozenInstanceError):
        request.input_path = Path("other.docx")  # type: ignore[misc]


def test_office_request_requires_path_objects() -> None:
    with pytest.raises(TypeError):
        OfficeConversionRequest("source.docx", Path("output"))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "source_format",
    [DocumentFormat.DOCX, DocumentFormat.PPTX, DocumentFormat.XLSX],
)
def test_office_result_accepts_supported_sources(source_format: DocumentFormat) -> None:
    result = OfficeConversionResult(
        input_path=Path(f"source.{source_format.value}"),
        output_path=Path("source.pdf"),
        source_format=source_format,
    )

    assert result.source_format is source_format
    assert result.target_format is DocumentFormat.PDF


def test_office_result_rejects_non_pdf_target() -> None:
    with pytest.raises(InvalidConversionRequestError):
        OfficeConversionResult(
            input_path=Path("source.docx"),
            output_path=Path("source.png"),
            source_format=DocumentFormat.DOCX,
            target_format=DocumentFormat.PNG,
        )
