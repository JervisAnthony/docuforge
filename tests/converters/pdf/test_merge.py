"""Tests for PDF merge conversion."""

from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

from docuforge.converters import PdfMergeConverter, PdfProcessingError
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    ConverterRegistry,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def write_pdf(path: Path, page_widths: tuple[float, ...]) -> None:
    """Write a PDF whose page widths make ordering observable."""
    writer = PdfWriter()
    try:
        for width in page_widths:
            writer.add_blank_page(width=width, height=100)
        writer.write(path)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a password-protected PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=100)
        writer.encrypt("secret")
        writer.write(path)
    finally:
        writer.close()


def merge_request(input_paths: tuple[Path, ...], output_path: Path) -> ConversionRequest:
    """Create a PDF merge request."""
    return ConversionRequest(
        input_paths=input_paths,
        output_path=output_path,
        source_format=DocumentFormat.PDF,
        target_format=DocumentFormat.PDF,
        operation=ConversionOperation.MERGE,
    )


def page_widths(path: Path) -> list[float]:
    """Return page widths from a PDF."""
    return [float(page.mediabox.width) for page in PdfReader(path).pages]


def test_converter_format_pair() -> None:
    converter = PdfMergeConverter()

    assert converter.operation is ConversionOperation.MERGE
    assert converter.source_format is DocumentFormat.PDF
    assert converter.target_format is DocumentFormat.PDF


def test_merge_two_pdfs_preserves_order_and_returns_output(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "merged.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))

    result = PdfMergeConverter().convert(merge_request((first, second), output))

    assert result == output
    assert page_widths(output) == [100, 200]


def test_merge_three_pdfs_preserves_all_page_order(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    third = tmp_path / "third.pdf"
    output = tmp_path / "merged.pdf"
    write_pdf(first, (100, 110))
    write_pdf(second, (200,))
    write_pdf(third, (300, 310))

    PdfMergeConverter().convert(merge_request((first, second, third), output))

    assert page_widths(output) == [100, 110, 200, 300, 310]


def test_merge_replaces_existing_non_input_output(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "merged.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))
    write_pdf(output, (999,))

    PdfMergeConverter().convert(merge_request((first, second), output))

    assert page_widths(output) == [100, 200]


def test_merge_rejects_fewer_than_two_inputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))

    with pytest.raises(InvalidConversionRequestError):
        PdfMergeConverter().convert(merge_request((input_path,), tmp_path / "output.pdf"))


def test_merge_rejects_missing_input(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    write_pdf(first, (100,))

    with pytest.raises(InvalidConversionRequestError):
        PdfMergeConverter().convert(
            merge_request((first, tmp_path / "missing.pdf"), tmp_path / "output.pdf")
        )


def test_merge_rejects_directory_input(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    directory = tmp_path / "directory"
    write_pdf(first, (100,))
    directory.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        PdfMergeConverter().convert(merge_request((first, directory), tmp_path / "output.pdf"))


def test_merge_rejects_missing_output_parent(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))

    with pytest.raises(InvalidConversionRequestError):
        PdfMergeConverter().convert(
            merge_request((first, second), tmp_path / "missing" / "output.pdf")
        )


def test_merge_rejects_output_resolving_to_input(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    nested = tmp_path / "nested"
    write_pdf(first, (100,))
    write_pdf(second, (200,))
    nested.mkdir()
    colliding_output = nested / ".." / first.name

    with pytest.raises(InvalidConversionRequestError):
        PdfMergeConverter().convert(merge_request((first, second), colliding_output))


@pytest.mark.parametrize(
    ("source_format", "target_format"),
    [
        (DocumentFormat.TXT, DocumentFormat.PDF),
        (DocumentFormat.PDF, DocumentFormat.TXT),
    ],
)
def test_merge_rejects_non_pdf_format_pair(
    tmp_path: Path,
    source_format: DocumentFormat,
    target_format: DocumentFormat,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")
    request = ConversionRequest(
        input_paths=(first, second),
        output_path=tmp_path / "output",
        source_format=source_format,
        target_format=target_format,
    )

    with pytest.raises(UnsupportedConversionError):
        PdfMergeConverter().convert(request)


def test_merge_rejects_pdf_request_with_wrong_operation(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    request = merge_request((first, second), tmp_path / "output.pdf")
    object.__setattr__(request, "operation", ConversionOperation.CONVERT)

    with pytest.raises(UnsupportedConversionError):
        PdfMergeConverter().convert(request)


def test_merge_rejects_malformed_pdf_without_partial_output(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    malformed = tmp_path / "malformed.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    malformed.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfMergeConverter().convert(merge_request((first, malformed), output))

    assert exc_info.value.__cause__ is not None
    assert not output.exists()
    assert list(tmp_path.glob(f".{output.name}.*.tmp")) == []


def test_merge_failure_preserves_existing_output(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    malformed = tmp_path / "malformed.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    malformed.write_bytes(b"not a PDF")
    write_pdf(output, (999,))

    with pytest.raises(PdfProcessingError):
        PdfMergeConverter().convert(merge_request((first, malformed), output))

    assert page_widths(output) == [999]


def test_merge_translates_unreadable_input_error(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    write_pdf(second, (200,))

    with (
        patch.object(Path, "open", side_effect=PermissionError("access denied")),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfMergeConverter().convert(merge_request((first, second), output))

    assert isinstance(exc_info.value.__cause__, PermissionError)
    assert not output.exists()


def test_merge_rejects_encrypted_pdf(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    encrypted = tmp_path / "encrypted.pdf"
    output = tmp_path / "output.pdf"
    write_pdf(first, (100,))
    write_encrypted_pdf(encrypted)

    with pytest.raises(PdfProcessingError, match="Encrypted PDF"):
        PdfMergeConverter().convert(merge_request((first, encrypted), output))

    assert not output.exists()


def test_registry_can_register_and_find_pdf_merge_converter(tmp_path: Path) -> None:
    registry = ConverterRegistry()
    converter = PdfMergeConverter()
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    request = merge_request((first, second), tmp_path / "output.pdf")

    registry.register(converter)

    assert registry.get_converter_for(request) is converter
