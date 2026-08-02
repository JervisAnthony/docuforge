"""Tests for PDF split conversion."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

from docuforge.converters import (
    PageGroup,
    PdfMergeConverter,
    PdfProcessingError,
    PdfSplitConverter,
    PdfSplitRequest,
)
from docuforge.core import (
    ConversionOperation,
    ConverterRegistry,
    DocumentFormat,
    InvalidConversionRequestError,
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


def split_request(
    input_path: Path,
    output_paths: tuple[Path, ...],
    page_groups: tuple[tuple[int, ...], ...],
) -> PdfSplitRequest:
    """Create a PDF split request from page-index tuples."""
    return PdfSplitRequest(
        input_path=input_path,
        output_paths=output_paths,
        page_groups=tuple(PageGroup(indices) for indices in page_groups),
    )


def page_widths(path: Path) -> list[float]:
    """Return page widths from a PDF."""
    return [float(page.mediabox.width) for page in PdfReader(path).pages]


def test_converter_identity() -> None:
    converter = PdfSplitConverter()

    assert converter.operation is ConversionOperation.SPLIT
    assert converter.source_format is DocumentFormat.PDF
    assert converter.target_format is DocumentFormat.PDF


def test_split_one_page_into_one_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output = tmp_path / "page.pdf"
    write_pdf(input_path, (100, 200))

    result = PdfSplitConverter().convert(split_request(input_path, (output,), ((1,),)))

    assert result == (output,)
    assert page_widths(output) == [200]


def test_split_multiple_pages_preserves_requested_order_and_repetitions(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output = tmp_path / "pages.pdf"
    write_pdf(input_path, (100, 200, 300))

    PdfSplitConverter().convert(split_request(input_path, (output,), ((2, 0, 2),)))

    assert page_widths(output) == [300, 100, 300]


def test_split_multiple_groups_returns_outputs_in_request_order(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    third_output = tmp_path / "third.pdf"
    write_pdf(input_path, (100, 200, 300))
    outputs = (first_output, second_output, third_output)

    result = PdfSplitConverter().convert(
        split_request(input_path, outputs, ((2,), (0, 1), (1,)))
    )

    assert result == outputs
    assert page_widths(first_output) == [300]
    assert page_widths(second_output) == [100, 200]
    assert page_widths(third_output) == [200]


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_split_accepts_case_insensitive_input_extensions(
    tmp_path: Path,
    suffix: str,
) -> None:
    input_path = tmp_path / f"input{suffix}"
    output = tmp_path / "output.pdf"
    write_pdf(input_path, (100,))

    PdfSplitConverter().convert(split_request(input_path, (output,), ((0,),)))

    assert page_widths(output) == [100]


@pytest.mark.parametrize("name", ["input.txt", "input", "input.pdf.tmp"])
def test_split_rejects_invalid_input_extension_before_opening_pdf(
    tmp_path: Path,
    name: str,
) -> None:
    input_path = tmp_path / name
    output = tmp_path / "output.pdf"

    with (
        patch.object(Path, "open") as open_mock,
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        PdfSplitConverter().convert(split_request(input_path, (output,), ((0,),)))

    assert str(exc_info.value) == (
        f"Input file must use the .pdf extension: {input_path}"
    )
    open_mock.assert_not_called()
    assert not output.exists()


def test_split_replaces_existing_outputs_on_success(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    write_pdf(input_path, (100, 200))
    write_pdf(first_output, (999,))
    write_pdf(second_output, (999,))

    PdfSplitConverter().convert(
        split_request(input_path, (first_output, second_output), ((0,), (1,)))
    )

    assert page_widths(first_output) == [100]
    assert page_widths(second_output) == [200]


def test_split_request_rejects_no_outputs(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        split_request(tmp_path / "input.pdf", (), ())


def test_split_request_rejects_duplicate_outputs(tmp_path: Path) -> None:
    output = tmp_path / "output.pdf"

    with pytest.raises(InvalidConversionRequestError):
        split_request(tmp_path / "input.pdf", (output, output), ((0,), (1,)))


def test_split_request_rejects_output_count_mismatch(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        split_request(
            tmp_path / "input.pdf",
            (tmp_path / "output.pdf",),
            ((0,), (1,)),
        )


def test_page_group_rejects_empty_indices() -> None:
    with pytest.raises(InvalidConversionRequestError):
        PageGroup(())


def test_page_group_rejects_negative_index() -> None:
    with pytest.raises(InvalidConversionRequestError):
        PageGroup((0, -1))


def test_split_rejects_out_of_range_page_index(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_path, (tmp_path / "output.pdf",), ((1,),))
        )


def test_split_rejects_missing_input(tmp_path: Path) -> None:
    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(
                tmp_path / "missing.pdf",
                (tmp_path / "output.pdf",),
                ((0,),),
            )
        )


def test_split_rejects_directory_input(tmp_path: Path) -> None:
    input_directory = tmp_path / "input"
    input_directory.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_directory, (tmp_path / "output.pdf",), ((0,),))
        )


def test_split_rejects_missing_output_parent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_path, (tmp_path / "missing" / "output.pdf",), ((0,),))
        )


def test_split_rejects_output_resolving_to_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    nested = tmp_path / "nested"
    write_pdf(input_path, (100,))
    nested.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_path, (nested / ".." / input_path.name,), ((0,),))
        )


def test_split_rejects_outputs_resolving_to_same_path(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    nested = tmp_path / "nested"
    output = tmp_path / "output.pdf"
    write_pdf(input_path, (100, 200))
    nested.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_path, (output, nested / ".." / output.name), ((0,), (1,)))
        )


def test_split_rejects_directory_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "output"
    write_pdf(input_path, (100,))
    output_directory.mkdir()

    with pytest.raises(InvalidConversionRequestError):
        PdfSplitConverter().convert(
            split_request(input_path, (output_directory,), ((0,),))
        )


def test_split_rejects_malformed_pdf_without_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output = tmp_path / "output.pdf"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfSplitConverter().convert(split_request(input_path, (output,), ((0,),)))

    assert exc_info.value.__cause__ is not None
    assert not output.exists()


def test_split_rejects_encrypted_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output = tmp_path / "output.pdf"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError, match="Encrypted PDF"):
        PdfSplitConverter().convert(split_request(input_path, (output,), ((0,),)))

    assert not output.exists()


def test_writer_failure_leaves_no_outputs_or_temporary_files(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    write_pdf(input_path, (100, 200))
    write_error = OSError("second output write failed")
    real_write = PdfWriter.write
    write_count = 0

    def fail_second_write(writer: PdfWriter, stream: object) -> object:
        nonlocal write_count
        write_count += 1
        if write_count == 2:
            raise write_error
        return real_write(writer, stream)  # type: ignore[arg-type]

    with (
        patch.object(PdfWriter, "write", autospec=True, side_effect=fail_second_write),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfSplitConverter().convert(
            split_request(input_path, (first_output, second_output), ((0,), (1,)))
        )

    assert exc_info.value.__cause__ is write_error
    assert not first_output.exists()
    assert not second_output.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_first_replace_failure_preserves_all_existing_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    write_pdf(input_path, (100, 200))
    write_pdf(first_output, (999,))
    write_pdf(second_output, (998,))
    replace_error = OSError("first output replace failed")

    with (
        patch("docuforge.converters.pdf.split.os.replace", side_effect=replace_error),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfSplitConverter().convert(
            split_request(input_path, (first_output, second_output), ((0,), (1,)))
        )

    assert exc_info.value.__cause__ is replace_error
    assert page_widths(first_output) == [999]
    assert page_widths(second_output) == [998]
    assert list(tmp_path.glob(".*.tmp")) == []


def test_later_replace_failure_keeps_prior_update_and_preserves_remaining_outputs(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    first_output = tmp_path / "first.pdf"
    second_output = tmp_path / "second.pdf"
    third_output = tmp_path / "third.pdf"
    write_pdf(input_path, (100, 200, 300))
    write_pdf(first_output, (999,))
    write_pdf(second_output, (998,))
    write_pdf(third_output, (997,))
    replace_error = OSError("second output replace failed")
    real_replace = os.replace
    replace_count = 0

    def fail_second_replace(source: Path, destination: Path) -> None:
        nonlocal replace_count
        replace_count += 1
        if replace_count == 2:
            raise replace_error
        real_replace(source, destination)

    with (
        patch("docuforge.converters.pdf.split.os.replace", side_effect=fail_second_replace),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfSplitConverter().convert(
            split_request(
                input_path,
                (first_output, second_output, third_output),
                ((0,), (1,), (2,)),
            )
        )

    assert exc_info.value.__cause__ is replace_error
    assert page_widths(first_output) == [100]
    assert page_widths(second_output) == [998]
    assert page_widths(third_output) == [997]
    assert list(tmp_path.glob(".*.tmp")) == []


def test_registry_can_hold_merge_and_split_for_pdf_pair(tmp_path: Path) -> None:
    registry = ConverterRegistry()
    merge_converter = PdfMergeConverter()
    split_converter = PdfSplitConverter()
    request = split_request(
        tmp_path / "input.pdf",
        (tmp_path / "output.pdf",),
        ((0,),),
    )

    registry.register(merge_converter)
    registry.register(split_converter)

    assert registry.get_converter_for(request) is split_converter
    assert registry.supported_conversions() == (
        (ConversionOperation.MERGE, DocumentFormat.PDF, DocumentFormat.PDF),
        (ConversionOperation.SPLIT, DocumentFormat.PDF, DocumentFormat.PDF),
    )
