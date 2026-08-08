"""Tests for low-level PDF page extraction."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.pdf as pdf_package
from docuforge.converters.pdf import (
    PdfExtractPagesConverter,
    PdfExtractPagesRequest,
    PdfProcessingError,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def write_pdf(path: Path, dimensions: tuple[tuple[int, int], ...]) -> None:
    """Write a PDF whose page dimensions identify source-page order."""
    writer = PdfWriter()
    try:
        for width, height in dimensions:
            writer.add_blank_page(width=width, height=height)
        with path.open("wb") as output_stream:
            writer.write(output_stream)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a one-page encrypted PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=200)
        writer.encrypt("secret")
        with path.open("wb") as output_stream:
            writer.write(output_stream)
    finally:
        writer.close()


def page_dimensions(path: Path) -> list[tuple[int, int]]:
    """Return integer dimensions for every page in a PDF."""
    reader = PdfReader(path, strict=True)
    return [
        (int(page.mediabox.width), int(page.mediabox.height))
        for page in reader.pages
    ]


def extraction_request(
    input_path: Path,
    output_path: Path,
    page_indices: tuple[int, ...] = (0,),
) -> PdfExtractPagesRequest:
    """Build a low-level page-extraction request."""
    return PdfExtractPagesRequest(
        input_paths=(input_path,),
        output_paths=(output_path,),
        page_indices=page_indices,
    )


def temporary_outputs(directory: Path) -> list[Path]:
    """Return hidden temporary PDF outputs created by the converter."""
    return list(directory.glob(".*.tmp"))


def test_request_is_frozen_slotted_and_preserves_all_identities() -> None:
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    input_paths = (input_path,)
    output_paths = (output_path,)
    page_indices = (3, 1)

    request = PdfExtractPagesRequest(input_paths, output_paths, page_indices)

    assert not hasattr(request, "__dict__")
    assert request.input_paths is input_paths
    assert request.output_paths is output_paths
    assert request.page_indices is page_indices
    assert request.input_paths[0] is input_path
    assert request.output_paths[0] is output_path
    with pytest.raises(FrozenInstanceError):
        request.page_indices = (0,)  # type: ignore[misc]


@pytest.mark.parametrize("input_paths", [(), (Path("a.pdf"), Path("b.pdf"))])
def test_request_requires_exactly_one_input(input_paths: tuple[Path, ...]) -> None:
    with pytest.raises(
        InvalidConversionRequestError,
        match="PDF page extraction requires exactly one input path",
    ):
        PdfExtractPagesRequest(input_paths, (Path("output.pdf"),), (0,))


@pytest.mark.parametrize("output_paths", [(), (Path("a.pdf"), Path("b.pdf"))])
def test_request_requires_exactly_one_output(output_paths: tuple[Path, ...]) -> None:
    with pytest.raises(
        InvalidConversionRequestError,
        match="PDF page extraction requires exactly one output path",
    ):
        PdfExtractPagesRequest((Path("input.pdf"),), output_paths, (0,))


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("input_paths", [Path("input.pdf")], "input_paths must be a tuple"),
        ("input_paths", ("input.pdf",), "input_paths must contain only Path"),
        ("output_paths", [Path("output.pdf")], "output_paths must be a tuple"),
        ("output_paths", ("output.pdf",), "output_paths must contain only Path"),
        ("page_indices", [0], "page_indices must be a tuple of integers"),
        ("page_indices", ("0",), "page_indices must contain only integers"),
        ("page_indices", (True,), "page_indices must contain only integers"),
    ],
)
def test_request_rejects_incorrect_python_types(
    field: str,
    value: object,
    message: str,
) -> None:
    values: dict[str, object] = {
        "input_paths": (Path("input.pdf"),),
        "output_paths": (Path("output.pdf"),),
        "page_indices": (0,),
    }
    values[field] = value

    with pytest.raises(TypeError, match=message):
        PdfExtractPagesRequest(**values)  # type: ignore[arg-type]


def test_request_rejects_empty_indices() -> None:
    with pytest.raises(
        InvalidConversionRequestError,
        match="At least one page index is required",
    ):
        PdfExtractPagesRequest((Path("input.pdf"),), (Path("output.pdf"),), ())


def test_request_rejects_negative_indices() -> None:
    with pytest.raises(
        InvalidConversionRequestError,
        match="Page indices must be non-negative",
    ):
        PdfExtractPagesRequest((Path("input.pdf"),), (Path("output.pdf"),), (2, -1))


@pytest.mark.parametrize(
    ("page_indices", "duplicate"),
    [((1, 1, 2, 2), 1), ((3, 1, 3, 1), 3)],
)
def test_request_reports_first_duplicate_in_request_order(
    page_indices: tuple[int, ...],
    duplicate: int,
) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesRequest(
            (Path("input.pdf"),),
            (Path("output.pdf"),),
            page_indices,
        )

    assert str(exc_info.value) == f"Each page may be extracted only once: {duplicate}"


def test_request_preserves_unsorted_indices_without_filesystem_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> object:
        raise AssertionError("request construction performed filesystem access")

    for method_name in ("exists", "is_file", "is_dir", "resolve", "open"):
        monkeypatch.setattr(Path, method_name, unexpected_call)
    indices = (4, 1, 3)

    request = PdfExtractPagesRequest(
        (Path("input.pdf"),),
        (Path("output.pdf"),),
        indices,
    )

    assert request.page_indices is indices


def test_converter_identity_is_pdf_to_pdf_split_operation() -> None:
    converter = PdfExtractPagesConverter()

    assert converter.operation is ConversionOperation.SPLIT
    assert converter.source_format is DocumentFormat.PDF
    assert converter.target_format is DocumentFormat.PDF


def test_converter_rejects_non_conversion_request() -> None:
    with pytest.raises(TypeError, match="request must be an instance"):
        PdfExtractPagesConverter().convert(object())  # type: ignore[arg-type]


def test_converter_rejects_wrong_operation_identity() -> None:
    request = ConversionRequest(
        input_paths=(Path("input.txt"),),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.TXT,
        target_format=DocumentFormat.PDF,
    )

    with pytest.raises(UnsupportedConversionError):
        PdfExtractPagesConverter().convert(request)


def test_converter_rejects_generic_compatible_request() -> None:
    request = ConversionRequest(
        input_paths=(Path("input.pdf"),),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.PDF,
        target_format=DocumentFormat.PDF,
        operation=ConversionOperation.SPLIT,
    )

    with pytest.raises(
        InvalidConversionRequestError,
        match="PDF page extraction requires a PdfExtractPagesRequest",
    ):
        PdfExtractPagesConverter().convert(request)


@pytest.mark.parametrize("bad_name", ["input", "input.txt", "input.pdf.tmp", ".pdf"])
def test_invalid_input_extension_is_rejected_before_io(
    monkeypatch: pytest.MonkeyPatch,
    bad_name: str,
) -> None:
    def unexpected_exists(path: Path) -> bool:
        raise AssertionError("filesystem inspected before extension validation")

    monkeypatch.setattr(Path, "exists", unexpected_exists)

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(Path(bad_name), Path("output.pdf"))
        )

    assert str(exc_info.value) == f"Input file must use the .pdf extension: {bad_name}"


@pytest.mark.parametrize("bad_name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_extension_is_rejected_before_input_io(bad_name: str) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(Path("missing.pdf"), Path(bad_name))
        )

    assert str(exc_info.value) == f"Output file must use the .pdf extension: {bad_name}"


def test_missing_input_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.pdf"

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input file does not exist: {input_path}."


def test_directory_input_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "directory.pdf"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input path is not a file: {input_path}."


def test_missing_output_parent_is_rejected_without_creation(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    missing_parent = tmp_path / "missing"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, missing_parent / "output.pdf")
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {missing_parent}."
    )
    assert not missing_parent.exists()


def test_non_directory_output_parent_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_parent = tmp_path / "parent"
    write_pdf(input_path, ((100, 200), (200, 300)))
    output_parent.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, output_parent / "output.pdf")
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {output_parent}."
    )


def test_output_directory_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))
    output_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(extraction_request(input_path, output_path))

    assert str(exc_info.value) == f"Output path is a directory: {output_path}."


def test_resolved_input_output_collision_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    nested = tmp_path / "nested"
    nested.mkdir()
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, nested / ".." / input_path.name)
        )

    assert str(exc_info.value) == "Output path must not resolve to the input file."


def test_malformed_pdf_uses_public_processing_boundary(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.pdf"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == "Unable to extract the requested PDF pages."


def test_encrypted_pdf_is_rejected(tmp_path: Path) -> None:
    input_path = tmp_path / "encrypted.pdf"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Encrypted PDF requires a password: {input_path}."


def test_reader_uses_strict_pdf_parsing(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    with patch(
        "docuforge.converters.pdf.extract_pages.PdfReader",
        wraps=PdfReader,
    ) as reader:
        PdfExtractPagesConverter().convert(extraction_request(input_path, output_path))

    assert reader.call_args.kwargs["strict"] is True


@pytest.mark.parametrize("page_indices", [(2,), (5,), (1, 4, 3)])
def test_first_out_of_range_index_is_rejected_before_writing(
    tmp_path: Path,
    page_indices: tuple[int, ...],
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfExtractPagesConverter().convert(
            extraction_request(input_path, output_path, page_indices)
        )

    invalid_index = next(index for index in page_indices if index >= 2)
    assert str(exc_info.value) == f"Page index is out of range: {invalid_index}"
    assert not output_path.exists()
    assert temporary_outputs(tmp_path) == []


@pytest.mark.parametrize(
    ("page_indices", "expected"),
    [
        ((0,), [(100, 200)]),
        ((1,), [(200, 300)]),
        ((4,), [(500, 600)]),
        ((0, 2, 4), [(100, 200), (300, 400), (500, 600)]),
        ((3, 1), [(400, 500), (200, 300)]),
        ((3, 1, 4), [(400, 500), (200, 300), (500, 600)]),
    ],
)
def test_extraction_preserves_request_order_and_source(
    tmp_path: Path,
    page_indices: tuple[int, ...],
    expected: list[tuple[int, int]],
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    source_dimensions = (
        (100, 200),
        (200, 300),
        (300, 400),
        (400, 500),
        (500, 600),
    )
    write_pdf(input_path, source_dimensions)
    source_before = input_path.read_bytes()

    PdfExtractPagesConverter().convert(
        extraction_request(input_path, output_path, page_indices)
    )

    assert page_dimensions(output_path) == expected
    assert len(PdfReader(output_path, strict=True).pages) == len(page_indices)
    assert input_path.read_bytes() == source_before
    assert page_dimensions(input_path) == list(source_dimensions)
    assert temporary_outputs(tmp_path) == []


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_case_insensitive_pdf_suffixes_succeed(tmp_path: Path, suffix: str) -> None:
    input_path = tmp_path / f"input{suffix}"
    output_path = tmp_path / f"output{suffix}"
    write_pdf(input_path, ((100, 200), (200, 300)))

    PdfExtractPagesConverter().convert(
        extraction_request(input_path, output_path, (1,))
    )

    assert page_dimensions(output_path) == [(200, 300)]


def test_converter_replaces_output_preserves_unrelated_file_and_returns_tuple(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    unrelated = tmp_path / "unrelated.txt"
    write_pdf(input_path, ((100, 200), (200, 300)))
    write_pdf(output_path, ((999, 999),))
    unrelated.write_text("keep", encoding="utf-8")
    output_paths = (output_path,)
    request = PdfExtractPagesRequest((input_path,), output_paths, (1,))

    result = PdfExtractPagesConverter().convert(request)

    assert result is output_paths
    assert page_dimensions(output_path) == [(200, 300)]
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert temporary_outputs(tmp_path) == []


def test_writer_failure_preserves_existing_output_and_cleans_temp(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    unrelated = tmp_path / "unrelated.txt"
    write_pdf(input_path, ((100, 200), (200, 300)))
    write_pdf(output_path, ((999, 999),))
    unrelated.write_text("keep", encoding="utf-8")
    failure = OSError("write failed")

    with (
        patch.object(PdfWriter, "write", autospec=True, side_effect=failure),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfExtractPagesConverter().convert(extraction_request(input_path, output_path))

    assert exc_info.value.__cause__ is failure
    assert page_dimensions(output_path) == [(999, 999)]
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert temporary_outputs(tmp_path) == []


def test_replace_failure_preserves_existing_output_and_cleans_temp(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))
    write_pdf(output_path, ((999, 999),))
    failure = OSError("replace failed")

    with (
        patch("docuforge.converters.pdf.extract_pages.os.replace", side_effect=failure),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfExtractPagesConverter().convert(extraction_request(input_path, output_path))

    assert exc_info.value.__cause__ is failure
    assert page_dimensions(output_path) == [(999, 999)]
    assert temporary_outputs(tmp_path) == []


def test_unexpected_page_addition_failure_remains_visible(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))
    failure = RuntimeError("unexpected add-page failure")

    with (
        patch.object(PdfWriter, "add_page", side_effect=failure),
        pytest.raises(RuntimeError) as exc_info,
    ):
        PdfExtractPagesConverter().convert(extraction_request(input_path, output_path))

    assert exc_info.value is failure
    assert not output_path.exists()
    assert temporary_outputs(tmp_path) == []


def test_public_exports_include_only_public_page_extraction_api() -> None:
    for package in (pdf_package, converters_package):
        assert package.PdfExtractPagesRequest is PdfExtractPagesRequest
        assert package.PdfExtractPagesConverter is PdfExtractPagesConverter
        assert "PdfExtractPagesRequest" in package.__all__
        assert "PdfExtractPagesConverter" in package.__all__

    assert "_validate_page_indices" not in pdf_package.__all__
    assert "_validate_page_indices" not in converters_package.__all__
