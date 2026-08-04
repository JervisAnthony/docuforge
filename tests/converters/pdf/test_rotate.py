"""Tests for low-level PDF page rotation."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.pdf as pdf_package
import docuforge.converters.pdf.rotate as rotate_module
from docuforge.converters import (
    PageRotation,
    PdfProcessingError,
    PdfRotateConverter,
    PdfRotateRequest,
)
from docuforge.core import (
    ConversionOperation,
    ConversionRequest,
    DocumentFormat,
    InvalidConversionRequestError,
    UnsupportedConversionError,
)


def write_pdf(path: Path, page_sizes: tuple[tuple[float, float], ...]) -> None:
    """Write a PDF with distinguishable page dimensions."""
    writer = PdfWriter()
    try:
        for width, height in page_sizes:
            writer.add_blank_page(width=width, height=height)
        writer.write(path)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a password-protected PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=200)
        writer.encrypt("secret")
        writer.write(path)
    finally:
        writer.close()


def rotate_request(
    input_path: Path,
    output_path: Path,
    rotations: tuple[tuple[int, int], ...] = ((0, 90),),
) -> PdfRotateRequest:
    """Construct a public rotation request from index/degree pairs."""
    return PdfRotateRequest(
        input_paths=(input_path,),
        output_paths=(output_path,),
        rotations=tuple(PageRotation(index, degrees) for index, degrees in rotations),
    )


def page_metadata(path: Path) -> list[tuple[float, float, int]]:
    """Return dimensions and rotation for every page in source order."""
    return [
        (
            float(page.mediabox.width),
            float(page.mediabox.height),
            page.rotation,
        )
        for page in PdfReader(path).pages
    ]


def test_page_rotation_is_frozen_slotted_and_has_no_dict() -> None:
    rotation = PageRotation(0, 90)

    assert PageRotation.__slots__ == ("page_index", "degrees")
    assert not hasattr(rotation, "__dict__")
    with pytest.raises(FrozenInstanceError):
        rotation.page_index = 1  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        rotation.degrees = 180  # type: ignore[misc]


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_page_rotation_accepts_supported_degrees(degrees: int) -> None:
    rotation = PageRotation(0, degrees)

    assert rotation.degrees == degrees


@pytest.mark.parametrize("page_index", [True, False, 1.5, "1", None])
def test_page_rotation_rejects_non_integer_indices(page_index: object) -> None:
    with pytest.raises(TypeError, match="page_index must be an integer"):
        PageRotation(page_index, 90)  # type: ignore[arg-type]


def test_page_rotation_rejects_negative_index() -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PageRotation(-1, 90)

    assert str(exc_info.value) == "page_index must be non-negative"


@pytest.mark.parametrize("degrees", [True, False, 90.0, "90", None])
def test_page_rotation_rejects_non_integer_degrees(degrees: object) -> None:
    with pytest.raises(TypeError, match="degrees must be an integer"):
        PageRotation(0, degrees)  # type: ignore[arg-type]


@pytest.mark.parametrize("degrees", [0, 360, -90, 450])
def test_page_rotation_rejects_unsupported_degrees(degrees: int) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PageRotation(0, degrees)

    assert str(exc_info.value) == "degrees must be one of 90, 180, or 270"


def test_rotate_request_is_frozen_slotted_and_preserves_identity() -> None:
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    first_rotation = PageRotation(2, 270)
    second_rotation = PageRotation(0, 90)
    input_paths = (input_path,)
    output_paths = (output_path,)
    rotations = (first_rotation, second_rotation)

    request = PdfRotateRequest(input_paths, output_paths, rotations)

    assert not hasattr(request, "__dict__")
    assert request.input_paths is input_paths
    assert request.output_paths is output_paths
    assert request.rotations is rotations
    assert request.input_paths[0] is input_path
    assert request.output_paths[0] is output_path
    assert request.output_path is output_path
    assert request.rotations[0] is first_rotation
    assert request.rotations[1] is second_rotation
    with pytest.raises(FrozenInstanceError):
        request.rotations = (PageRotation(1, 180),)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("input_paths", "message"),
    [
        ((), "PDF rotation requires exactly one input path."),
        ((Path("first.pdf"), Path("second.pdf")), "PDF rotation requires exactly one input path."),
    ],
)
def test_rotate_request_requires_exactly_one_input(
    input_paths: tuple[Path, ...],
    message: str,
) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateRequest(
            input_paths,
            (Path("output.pdf"),),
            (PageRotation(0, 90),),
        )

    assert str(exc_info.value) == message


@pytest.mark.parametrize(
    "output_paths",
    [(), (Path("first.pdf"), Path("second.pdf"))],
)
def test_rotate_request_requires_exactly_one_output(
    output_paths: tuple[Path, ...],
) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateRequest(
            (Path("input.pdf"),),
            output_paths,
            (PageRotation(0, 90),),
        )

    assert str(exc_info.value) == "PDF rotation requires exactly one output path."


@pytest.mark.parametrize(
    ("input_paths", "output_paths", "message"),
    [
        ([Path("input.pdf")], (Path("output.pdf"),), "input_paths must be a tuple"),
        ((Path("input.pdf"),), [Path("output.pdf")], "output_paths must be a tuple"),
        (("input.pdf",), (Path("output.pdf"),), "input_paths must contain only Path"),
        ((Path("input.pdf"),), ("output.pdf",), "output_paths must contain only Path"),
    ],
)
def test_rotate_request_rejects_invalid_path_structure(
    input_paths: object,
    output_paths: object,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        PdfRotateRequest(  # type: ignore[arg-type]
            input_paths,
            output_paths,
            (PageRotation(0, 90),),
        )


def test_rotate_request_rejects_empty_rotations() -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateRequest((Path("input.pdf"),), (Path("output.pdf"),), ())

    assert str(exc_info.value) == "At least one page rotation is required."


def test_rotate_request_requires_rotation_tuple() -> None:
    with pytest.raises(TypeError, match="rotations must be a tuple"):
        PdfRotateRequest(
            (Path("input.pdf"),),
            (Path("output.pdf"),),
            [PageRotation(0, 90)],  # type: ignore[arg-type]
        )


def test_rotate_request_rejects_non_rotation_members() -> None:
    with pytest.raises(TypeError, match="rotations must contain only PageRotation"):
        PdfRotateRequest(
            (Path("input.pdf"),),
            (Path("output.pdf"),),
            (PageRotation(0, 90), object()),  # type: ignore[arg-type]
        )


def test_rotate_request_reports_first_duplicate_in_request_order() -> None:
    rotations = (
        PageRotation(2, 90),
        PageRotation(1, 180),
        PageRotation(2, 270),
        PageRotation(1, 90),
    )

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateRequest(
            (Path("input.pdf"),),
            (Path("output.pdf"),),
            rotations,
        )

    assert str(exc_info.value) == "Each page may have only one rotation instruction: 2"


def test_rotate_request_construction_performs_no_filesystem_access() -> None:
    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "is_file", side_effect=AssertionError("is_file called")),
        patch.object(Path, "resolve", side_effect=AssertionError("resolve called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
    ):
        request = rotate_request(Path("missing.pdf"), Path("missing/output.pdf"))

    assert request.input_paths == (Path("missing.pdf"),)


def test_converter_identity() -> None:
    converter = PdfRotateConverter()

    assert converter.operation is ConversionOperation.SPLIT
    assert converter.source_format is DocumentFormat.PDF
    assert converter.target_format is DocumentFormat.PDF


def test_converter_rejects_incorrect_request_type() -> None:
    with pytest.raises(TypeError, match="request must be an instance of ConversionRequest"):
        PdfRotateConverter().convert(object())  # type: ignore[arg-type]


def test_converter_rejects_non_rotation_conversion_request() -> None:
    request = ConversionRequest(
        input_paths=(Path("first.pdf"), Path("second.pdf")),
        output_path=Path("output.pdf"),
        source_format=DocumentFormat.PDF,
        target_format=DocumentFormat.PDF,
        operation=ConversionOperation.MERGE,
    )

    with pytest.raises(UnsupportedConversionError):
        PdfRotateConverter().convert(request)


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_converter_accepts_case_insensitive_extensions(
    tmp_path: Path,
    suffix: str,
) -> None:
    input_path = tmp_path / f"input{suffix}"
    output_path = tmp_path / f"output{suffix}"
    write_pdf(input_path, ((100, 200),))

    PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert page_metadata(output_path) == [(100, 200, 90)]


@pytest.mark.parametrize("name", ["input", "input.txt", "input.pdf.tmp", ".pdf"])
def test_invalid_input_extension_is_rejected_before_io(
    tmp_path: Path,
    name: str,
) -> None:
    input_path = tmp_path / name

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        PdfRotateConverter().convert(
            rotate_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input file must use the .pdf extension: {input_path}"


@pytest.mark.parametrize("name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_extension_is_rejected_before_pdf_parsing(
    tmp_path: Path,
    name: str,
) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, ((100, 200),))

    with (
        patch.object(rotate_module, "PdfReader", side_effect=AssertionError("reader called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        PdfRotateConverter().convert(
            rotate_request(input_path, tmp_path / name)
        )

    assert str(exc_info.value) == (
        f"Output file must use the .pdf extension: {tmp_path / name}"
    )


def test_converter_rejects_missing_input() -> None:
    input_path = Path("missing.pdf")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(rotate_request(input_path, Path("output.pdf")))

    assert str(exc_info.value) == f"Input file does not exist: {input_path}."


def test_converter_rejects_directory_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input path is not a file: {input_path}."


def test_converter_rejects_missing_output_parent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_parent = tmp_path / "missing"
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, output_parent / "output.pdf")
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {output_parent}."
    )
    assert not output_parent.exists()


def test_converter_rejects_non_directory_output_parent(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_parent = tmp_path / "not-a-directory"
    write_pdf(input_path, ((100, 200),))
    output_parent.write_text("file", encoding="utf-8")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, output_parent / "output.pdf")
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {output_parent}."
    )


def test_converter_rejects_output_resolving_to_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    nested = tmp_path / "nested"
    nested.mkdir()
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, nested / ".." / input_path.name)
        )

    assert str(exc_info.value) == "Output path must not resolve to the input file."


def test_converter_rejects_malformed_pdf_without_output(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.pdf"
    output_path = tmp_path / "output.pdf"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert str(exc_info.value) == "Unable to rotate the requested PDF document."
    assert exc_info.value.__cause__ is not None
    assert not output_path.exists()


def test_converter_rejects_encrypted_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "encrypted.pdf"
    output_path = tmp_path / "output.pdf"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError) as exc_info:
        PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert str(exc_info.value) == f"Encrypted PDF requires a password: {input_path}."
    assert not output_path.exists()


def test_converter_uses_strict_pdf_parsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))
    real_reader = rotate_module.PdfReader
    strict_values: list[bool] = []

    def reader(stream: object, *, strict: bool) -> PdfReader:
        strict_values.append(strict)
        return real_reader(stream, strict=strict)  # type: ignore[arg-type]

    monkeypatch.setattr(rotate_module, "PdfReader", reader)

    PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert strict_values == [True]


@pytest.mark.parametrize("page_index", [1, 2, 99])
def test_converter_rejects_out_of_range_page_index(
    tmp_path: Path,
    page_index: int,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, output_path, ((page_index, 90),))
        )

    assert str(exc_info.value) == f"Page index is out of range: {page_index}"
    assert not output_path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_converter_reports_first_invalid_index_in_request_order(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (300, 400)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        PdfRotateConverter().convert(
            rotate_request(input_path, output_path, ((8, 90), (7, 180)))
        )

    assert str(exc_info.value) == "Page index is out of range: 8"
    assert not output_path.exists()


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_converter_rotates_one_page_by_supported_degrees(
    tmp_path: Path,
    degrees: int,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    PdfRotateConverter().convert(
        rotate_request(input_path, output_path, ((0, degrees),))
    )

    assert page_metadata(output_path) == [(100, 200, degrees)]


def test_converter_preserves_pages_order_and_rotates_only_selected_pages(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    source_metadata = [(100, 200, 0), (300, 400, 0), (500, 600, 0)]
    write_pdf(input_path, tuple((width, height) for width, height, _ in source_metadata))
    input_before = input_path.read_bytes()
    output_paths = (output_path,)
    request = PdfRotateRequest(
        input_paths=(input_path,),
        output_paths=output_paths,
        rotations=(PageRotation(2, 270), PageRotation(0, 90)),
    )

    result = PdfRotateConverter().convert(request)

    assert result is output_paths
    assert result is request.output_paths
    assert page_metadata(output_path) == [
        (100, 200, 90),
        (300, 400, 0),
        (500, 600, 270),
    ]
    assert len(PdfReader(output_path).pages) == 3
    assert input_path.read_bytes() == input_before
    assert page_metadata(input_path) == source_metadata


def test_unsorted_rotation_instructions_do_not_reorder_pages(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (300, 400), (500, 600)))

    PdfRotateConverter().convert(
        rotate_request(input_path, output_path, ((2, 90), (0, 180), (1, 270)))
    )

    assert page_metadata(output_path) == [
        (100, 200, 180),
        (300, 400, 270),
        (500, 600, 90),
    ]


def test_converter_replaces_existing_output_and_preserves_unrelated_files(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    unrelated = tmp_path / "unrelated.txt"
    write_pdf(input_path, ((100, 200),))
    write_pdf(output_path, ((999, 999),))
    unrelated.write_text("keep", encoding="utf-8")

    PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert page_metadata(output_path) == [(100, 200, 90)]
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert list(tmp_path.glob(".*.tmp")) == []


def test_writer_failure_preserves_existing_output_and_cleans_temporary_file(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))
    write_pdf(output_path, ((999, 999),))
    write_error = OSError("write failed")

    with (
        patch.object(PdfWriter, "write", autospec=True, side_effect=write_error),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert exc_info.value.__cause__ is write_error
    assert page_metadata(output_path) == [(999, 999, 0)]
    assert list(tmp_path.glob(".*.tmp")) == []


def test_replace_failure_preserves_existing_output_and_cleans_temporary_file(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))
    write_pdf(output_path, ((999, 999),))
    replace_error = OSError("replace failed")

    with (
        patch("docuforge.converters.pdf.rotate.os.replace", side_effect=replace_error),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert exc_info.value.__cause__ is replace_error
    assert page_metadata(output_path) == [(999, 999, 0)]
    assert list(tmp_path.glob(".*.tmp")) == []


def test_unexpected_writer_setup_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))
    failure = RuntimeError("unexpected add-page failure")

    with (
        patch.object(PdfWriter, "add_page", side_effect=failure),
        pytest.raises(RuntimeError) as exc_info,
    ):
        PdfRotateConverter().convert(rotate_request(input_path, output_path))

    assert exc_info.value is failure
    assert not output_path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_public_exports_include_rotation_api() -> None:
    for package in (pdf_package, converters_package):
        assert package.PageRotation is PageRotation
        assert package.PdfRotateRequest is PdfRotateRequest
        assert package.PdfRotateConverter is PdfRotateConverter
