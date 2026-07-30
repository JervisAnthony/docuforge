"""Tests for the converter abstraction."""

from pathlib import Path

import pytest

from docuforge.core import ConversionRequest, Converter, DocumentFormat


class TestConverter(Converter):
    """Minimal converter used to exercise the core contract."""

    __test__ = False

    def convert(self, request: ConversionRequest) -> Path:
        """Return the requested output path without performing file operations."""
        return request.output_path


def test_abstract_converter_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Converter(DocumentFormat.TXT, DocumentFormat.PDF)  # type: ignore[abstract]


def test_converter_exposes_normalized_read_only_formats() -> None:
    converter = TestConverter(" .TXT ", ".PDF")

    assert converter.source_format is DocumentFormat.TXT
    assert converter.target_format is DocumentFormat.PDF

    with pytest.raises(AttributeError):
        converter.source_format = DocumentFormat.JPG  # type: ignore[misc]
