"""Tests for document-format normalization."""

import pytest

from docuforge.core import DocumentFormat, InvalidFormatError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("pdf", DocumentFormat.PDF),
        ("docx", DocumentFormat.DOCX),
        ("jpg", DocumentFormat.JPG),
        ("png", DocumentFormat.PNG),
        ("gif", DocumentFormat.GIF),
        ("bmp", DocumentFormat.BMP),
        ("tiff", DocumentFormat.TIFF),
        ("webp", DocumentFormat.WEBP),
        ("txt", DocumentFormat.TXT),
    ],
)
def test_normalize_supported_formats(value: str, expected: DocumentFormat) -> None:
    assert DocumentFormat.normalize(value) is expected


def test_normalize_is_case_insensitive() -> None:
    assert DocumentFormat.normalize("PdF") is DocumentFormat.PDF


def test_normalize_accepts_a_leading_dot() -> None:
    assert DocumentFormat.normalize(".png") is DocumentFormat.PNG


def test_normalize_trims_surrounding_whitespace() -> None:
    assert DocumentFormat.normalize("  .PDF  ") is DocumentFormat.PDF


def test_normalize_maps_jpeg_alias_to_jpg() -> None:
    assert DocumentFormat.normalize("jpeg") is DocumentFormat.JPG


def test_normalize_maps_tif_alias_to_tiff() -> None:
    assert DocumentFormat.normalize("tif") is DocumentFormat.TIFF


def test_enum_constructor_normalizes_values() -> None:
    assert DocumentFormat(".JPEG") is DocumentFormat.JPG


@pytest.mark.parametrize("value", ["", "   ", ".", "svg"])
def test_normalize_rejects_invalid_strings(value: str) -> None:
    with pytest.raises(InvalidFormatError):
        DocumentFormat.normalize(value)


def test_normalize_rejects_non_string_values() -> None:
    with pytest.raises(InvalidFormatError):
        DocumentFormat.normalize(None)  # type: ignore[arg-type]
