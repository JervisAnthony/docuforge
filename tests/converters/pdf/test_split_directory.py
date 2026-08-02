"""Tests for high-level PDF splitting into a directory."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

from docuforge.converters import (
    PdfProcessingError,
    PdfSplitConverter,
    PdfSplitDirectoryRequest,
    PdfSplitDirectoryResult,
    PdfSplitRequest,
    split_pdf_to_directory,
)
from docuforge.core import InvalidConversionRequestError


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


def page_widths(path: Path) -> list[float]:
    """Return page widths from a PDF."""
    return [float(page.mediabox.width) for page in PdfReader(path).pages]


def test_directory_request_preserves_path_identity() -> None:
    input_path = Path("input.pdf")
    output_directory = Path("pages")

    request = PdfSplitDirectoryRequest(input_path, output_directory)

    assert request.input_path is input_path
    assert request.output_directory is output_directory


def test_directory_request_is_frozen_and_uses_slots() -> None:
    request = PdfSplitDirectoryRequest(Path("input.pdf"), Path("pages"))

    assert PdfSplitDirectoryRequest.__slots__ == ("input_path", "output_directory")
    assert not hasattr(request, "__dict__")
    for field_name, value in (
        ("input_path", Path("replacement.pdf")),
        ("output_directory", Path("replacement-pages")),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(request, field_name, value)


def test_directory_result_is_frozen_slotted_and_uses_an_immutable_tuple() -> None:
    input_path = Path("input.pdf")
    output_directory = Path("pages")
    output_paths = (Path("page-0001.pdf"),)
    result = PdfSplitDirectoryResult(input_path, output_directory, output_paths)

    assert PdfSplitDirectoryResult.__slots__ == (
        "input_path",
        "output_directory",
        "output_paths",
    )
    assert not hasattr(result, "__dict__")
    assert isinstance(result.output_paths, tuple)
    for field_name, value in (
        ("input_path", Path("replacement.pdf")),
        ("output_directory", Path("replacement-pages")),
        ("output_paths", (Path("replacement-page.pdf"),)),
    ):
        with pytest.raises(FrozenInstanceError):
            setattr(result, field_name, value)


def test_split_to_directory_creates_one_ordered_output_per_page(tmp_path: Path) -> None:
    input_path = tmp_path / "report.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100, 200, 300))

    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(input_path, output_directory)
    )

    expected_paths = tuple(
        output_directory / f"report-page-{number:04d}.pdf"
        for number in range(1, 4)
    )
    assert result == PdfSplitDirectoryResult(
        input_path=input_path,
        output_directory=output_directory,
        output_paths=expected_paths,
    )
    assert [page_widths(path) for path in result.output_paths] == [
        [100],
        [200],
        [300],
    ]


def test_split_to_directory_preserves_all_but_final_input_suffix(tmp_path: Path) -> None:
    input_path = tmp_path / "report.final.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100,))

    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(input_path, output_directory)
    )

    assert result.output_paths == (
        output_directory / "report.final-page-0001.pdf",
    )


def test_split_to_directory_creates_missing_parent_directories(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "nested" / "pages"
    write_pdf(input_path, (100,))

    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(input_path, output_directory)
    )

    assert output_directory.is_dir()
    assert result.output_paths[0].is_file()


def test_split_to_directory_uses_existing_output_directory(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    unrelated = output_directory / "keep.txt"
    output_directory.mkdir()
    unrelated.write_text("keep", encoding="utf-8")
    write_pdf(input_path, (100,))

    split_pdf_to_directory(PdfSplitDirectoryRequest(input_path, output_directory))

    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_split_to_directory_preserves_low_level_replacement_behavior(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    output_directory.mkdir()
    existing_output = output_directory / "input-page-0001.pdf"
    write_pdf(input_path, (100,))
    write_pdf(existing_output, (999,))

    split_pdf_to_directory(PdfSplitDirectoryRequest(input_path, output_directory))

    assert page_widths(existing_output) == [100]


def test_split_to_directory_builds_zero_based_page_groups_and_uses_converter_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100, 200, 300))
    returned_paths = (
        Path("canonical-first.pdf"),
        Path("canonical-second.pdf"),
        Path("canonical-third.pdf"),
    )
    received_request: PdfSplitRequest | None = None

    def convert(
        converter: PdfSplitConverter,
        request: PdfSplitRequest,
    ) -> tuple[Path, ...]:
        nonlocal received_request
        received_request = request
        return returned_paths

    monkeypatch.setattr(PdfSplitConverter, "convert", convert)

    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(input_path, output_directory)
    )

    assert received_request is not None
    assert received_request.input_paths == (input_path,)
    assert received_request.output_paths == tuple(
        output_directory / f"input-page-{number:04d}.pdf"
        for number in range(1, 4)
    )
    assert tuple(group.page_indices for group in received_request.page_groups) == (
        (0,),
        (1,),
        (2,),
    )
    assert result.input_path is input_path
    assert result.output_directory is output_directory
    assert result.output_paths is returned_paths
    assert len(result.output_paths) == len(received_request.output_paths)
    assert len(result.output_paths) == len(received_request.page_groups)
    assert result.output_paths[0] is returned_paths[0]
    assert result.output_paths[1] is returned_paths[1]
    assert result.output_paths[2] is returned_paths[2]


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_split_to_directory_accepts_case_insensitive_pdf_extensions(
    tmp_path: Path,
    suffix: str,
) -> None:
    input_path = tmp_path / f"input{suffix}"
    write_pdf(input_path, (100,))

    result = split_pdf_to_directory(
        PdfSplitDirectoryRequest(input_path, tmp_path / "pages")
    )

    assert len(result.output_paths) == 1


@pytest.mark.parametrize("name", ["input.txt", "input", "input.pdf.tmp"])
def test_split_to_directory_rejects_invalid_extension_before_io(
    tmp_path: Path,
    name: str,
) -> None:
    input_path = tmp_path / name
    output_directory = tmp_path / "pages"

    with (
        patch.object(Path, "open") as open_mock,
        patch.object(Path, "mkdir") as mkdir_mock,
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, output_directory)
        )

    assert str(exc_info.value) == (
        f"Input file must use the .pdf extension: {input_path}"
    )
    open_mock.assert_not_called()
    mkdir_mock.assert_not_called()


def test_split_to_directory_rejects_missing_input_without_creating_directory(
    tmp_path: Path,
) -> None:
    output_directory = tmp_path / "pages"

    with pytest.raises(InvalidConversionRequestError, match="Input file does not exist"):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(tmp_path / "missing.pdf", output_directory)
        )

    assert not output_directory.exists()


def test_split_to_directory_rejects_directory_input(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError, match="Input path is not a file"):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, tmp_path / "pages")
        )


def test_split_to_directory_rejects_existing_non_directory_output(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "pages"
    write_pdf(input_path, (100,))
    output_path.write_text("not a directory", encoding="utf-8")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        split_pdf_to_directory(PdfSplitDirectoryRequest(input_path, output_path))

    assert str(exc_info.value) == f"Output path is not a directory: {output_path}."


def test_split_to_directory_rejects_malformed_pdf_without_outputs(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, output_directory)
        )

    assert str(exc_info.value) == "Unable to inspect the requested PDF document."
    assert exc_info.value.__cause__ is not None
    assert capsys.readouterr().err == ""
    assert not output_directory.exists()


def test_split_to_directory_rejects_encrypted_pdf_without_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError, match="Encrypted PDF requires a password"):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, output_directory)
        )

    assert not output_directory.exists()


def test_split_to_directory_rejects_empty_pdf_without_outputs(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, ())

    with pytest.raises(InvalidConversionRequestError, match="at least one page"):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, output_directory)
        )

    assert not output_directory.exists()


def test_split_to_directory_translates_input_read_failure(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))

    with (
        patch.object(Path, "open", side_effect=PermissionError("access denied")),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, tmp_path / "pages")
        )

    assert isinstance(exc_info.value.__cause__, PermissionError)


def test_split_to_directory_translates_output_directory_creation_failure(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_directory = tmp_path / "pages"
    write_pdf(input_path, (100,))
    mkdir_error = PermissionError("access denied")

    with (
        patch.object(Path, "mkdir", side_effect=mkdir_error),
        pytest.raises(PdfProcessingError) as exc_info,
    ):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, output_directory)
        )

    assert str(exc_info.value) == f"Unable to create output directory: {output_directory}."
    assert exc_info.value.__cause__ is mkdir_error


def test_split_to_directory_propagates_low_level_public_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))
    failure = PdfProcessingError("simulated split failure")

    def fail_conversion(
        converter: PdfSplitConverter,
        request: PdfSplitRequest,
    ) -> tuple[Path, ...]:
        raise failure

    monkeypatch.setattr(PdfSplitConverter, "convert", fail_conversion)

    with pytest.raises(PdfProcessingError) as exc_info:
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, tmp_path / "pages")
        )

    assert exc_info.value is failure


def test_split_to_directory_does_not_catch_unexpected_converter_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, (100,))

    def fail_conversion(
        converter: PdfSplitConverter,
        request: PdfSplitRequest,
    ) -> tuple[Path, ...]:
        raise RuntimeError("unexpected failure")

    monkeypatch.setattr(PdfSplitConverter, "convert", fail_conversion)

    with pytest.raises(RuntimeError, match="unexpected failure"):
        split_pdf_to_directory(
            PdfSplitDirectoryRequest(input_path, tmp_path / "pages")
        )


def test_split_to_directory_requires_public_request_type() -> None:
    with pytest.raises(TypeError, match="PdfSplitDirectoryRequest"):
        split_pdf_to_directory(object())  # type: ignore[arg-type]
