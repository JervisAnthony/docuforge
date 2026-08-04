"""Tests for high-level path-based PDF page rotation."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.pdf as pdf_package
import docuforge.converters.pdf.rotate_path as rotate_path_module
from docuforge.converters import (
    PageRotation,
    PdfProcessingError,
    PdfRotateConverter,
    PdfRotatePathRequest,
    PdfRotatePathResult,
    PdfRotateRequest,
    rotate_pdf_pages,
)
from docuforge.core import InvalidConversionRequestError


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


def page_metadata(path: Path) -> list[tuple[float, float, int]]:
    """Return page dimensions and rotations in source order."""
    return [
        (
            float(page.mediabox.width),
            float(page.mediabox.height),
            page.rotation,
        )
        for page in PdfReader(path).pages
    ]


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_are_frozen_slotted_and_preserve_identity(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    first = PageRotation(2, 270)
    second = PageRotation(0, 90)
    rotations = (first, second)

    model = model_type(input_path, output_path, rotations)

    assert model_type.__slots__ == ("input_path", "output_path", "rotations")
    assert not hasattr(model, "__dict__")
    assert model.input_path is input_path
    assert model.output_path is output_path
    assert model.rotations is rotations
    assert model.rotations[0] is first
    assert model.rotations[1] is second
    with pytest.raises(FrozenInstanceError):
        model.input_path = Path("replacement.pdf")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        model.output_path = Path("replacement.pdf")  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        model.rotations = (PageRotation(1, 180),)  # type: ignore[misc]


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_reject_non_path_input(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    with pytest.raises(TypeError, match="input_path must be a Path object"):
        model_type(  # type: ignore[arg-type]
            "input.pdf",
            Path("output.pdf"),
            (PageRotation(0, 90),),
        )


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_reject_non_path_output(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    with pytest.raises(TypeError, match="output_path must be a Path object"):
        model_type(  # type: ignore[arg-type]
            Path("input.pdf"),
            "output.pdf",
            (PageRotation(0, 90),),
        )


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_require_rotation_tuple(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    with pytest.raises(TypeError, match="rotations must be a tuple"):
        model_type(  # type: ignore[arg-type]
            Path("input.pdf"),
            Path("output.pdf"),
            [PageRotation(0, 90)],
        )


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_reject_empty_rotations(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        model_type(Path("input.pdf"), Path("output.pdf"), ())

    assert str(exc_info.value) == "At least one rotation instruction is required."


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_reject_non_rotation_members(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    with pytest.raises(TypeError, match="rotations must contain only PageRotation"):
        model_type(  # type: ignore[arg-type]
            Path("input.pdf"),
            Path("output.pdf"),
            (PageRotation(0, 90), object()),
        )


@pytest.mark.parametrize("model_type", [PdfRotatePathRequest, PdfRotatePathResult])
def test_path_models_report_first_duplicate_in_request_order(
    model_type: type[PdfRotatePathRequest] | type[PdfRotatePathResult],
) -> None:
    rotations = (
        PageRotation(2, 90),
        PageRotation(1, 180),
        PageRotation(2, 270),
        PageRotation(1, 90),
    )

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        model_type(Path("input.pdf"), Path("output.pdf"), rotations)

    assert str(exc_info.value) == "Each page may have only one rotation instruction: 2"


def test_path_request_construction_performs_no_filesystem_access() -> None:
    input_path = Path("missing.pdf")
    output_path = Path("missing/output.pdf")
    rotations = (PageRotation(999, 90),)

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "is_file", side_effect=AssertionError("is_file called")),
        patch.object(Path, "resolve", side_effect=AssertionError("resolve called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
        patch.object(Path, "mkdir", side_effect=AssertionError("mkdir called")),
    ):
        request = PdfRotatePathRequest(input_path, output_path, rotations)

    assert request.input_path is input_path
    assert request.output_path is output_path
    assert request.rotations is rotations


def test_rotate_pdf_pages_requires_path_request() -> None:
    with pytest.raises(
        TypeError,
        match="request must be an instance of PdfRotatePathRequest",
    ):
        rotate_pdf_pages(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_input_suffixes_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    class FakeConverter:
        def convert(self, request: PdfRotateRequest) -> tuple[Path, ...]:
            return request.output_paths

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", FakeConverter)

    result = rotate_pdf_pages(
        PdfRotatePathRequest(
            Path(f"input{suffix}"),
            Path("output.pdf"),
            (PageRotation(0, 90),),
        )
    )

    assert result.output_path == Path("output.pdf")


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_output_suffixes_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    class FakeConverter:
        def convert(self, request: PdfRotateRequest) -> tuple[Path, ...]:
            return request.output_paths

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", FakeConverter)

    result = rotate_pdf_pages(
        PdfRotatePathRequest(
            Path("input.pdf"),
            Path(f"output{suffix}"),
            (PageRotation(0, 90),),
        )
    )

    assert result.output_path == Path(f"output{suffix}")


@pytest.mark.parametrize("name", ["input", "input.txt", "input.pdf.tmp", ".pdf"])
def test_invalid_input_suffix_is_rejected_before_converter_construction(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    input_path = Path(name)

    class UnexpectedConverter:
        def __init__(self) -> None:
            raise AssertionError("converter constructed")

    def unexpected_request(*args: object, **kwargs: object) -> object:
        raise AssertionError("low-level request constructed")

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", UnexpectedConverter)
    monkeypatch.setattr(rotate_path_module, "PdfRotateRequest", unexpected_request)

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                Path("output.txt"),
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == f"Input file must use the .pdf extension: {input_path}"


@pytest.mark.parametrize("name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_suffix_is_rejected_before_converter_construction(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    output_path = Path(name)

    class UnexpectedConverter:
        def __init__(self) -> None:
            raise AssertionError("converter constructed")

    def unexpected_request(*args: object, **kwargs: object) -> object:
        raise AssertionError("low-level request constructed")

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", UnexpectedConverter)
    monkeypatch.setattr(rotate_path_module, "PdfRotateRequest", unexpected_request)

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        rotate_pdf_pages(
            PdfRotatePathRequest(
                Path("input.pdf"),
                output_path,
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == (
        f"Output file must use the .pdf extension: {output_path}"
    )


def test_delegation_preserves_identity_order_and_converter_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("relative/input.pdf")
    output_path = Path("relative/output.pdf")
    converted_path = Path("library-returned.pdf")
    first = PageRotation(2, 270)
    second = PageRotation(0, 90)
    rotations = (first, second)
    constructed_arguments: list[
        tuple[tuple[Path, ...], tuple[Path, ...], tuple[PageRotation, ...]]
    ] = []
    received_request: PdfRotateRequest | None = None
    converter_count = 0
    convert_count = 0
    real_request = rotate_path_module.PdfRotateRequest

    def low_level_request(
        *,
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        rotations: tuple[PageRotation, ...],
    ) -> PdfRotateRequest:
        constructed_arguments.append((input_paths, output_paths, rotations))
        return real_request(input_paths, output_paths, rotations)

    class FakeConverter:
        def __init__(self) -> None:
            nonlocal converter_count
            converter_count += 1

        def convert(self, request: PdfRotateRequest) -> tuple[Path, ...]:
            nonlocal convert_count, received_request
            convert_count += 1
            received_request = request
            return (converted_path,)

    monkeypatch.setattr(rotate_path_module, "PdfRotateRequest", low_level_request)
    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", FakeConverter)

    result = rotate_pdf_pages(PdfRotatePathRequest(input_path, output_path, rotations))

    assert len(constructed_arguments) == 1
    constructed_inputs, constructed_outputs, constructed_rotations = constructed_arguments[0]
    assert constructed_inputs[0] is input_path
    assert constructed_outputs[0] is output_path
    assert constructed_rotations is rotations
    assert constructed_rotations[0] is first
    assert constructed_rotations[1] is second
    assert converter_count == 1
    assert convert_count == 1
    assert received_request is not None
    assert result.input_path is input_path
    assert result.output_path is converted_path
    assert result.rotations is rotations


@pytest.mark.parametrize(
    "failure",
    [PdfProcessingError("public failure"), RuntimeError("unexpected failure")],
)
def test_converter_failures_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    class FailingConverter:
        def convert(self, request: PdfRotateRequest) -> tuple[Path, ...]:
            raise failure

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", FailingConverter)

    with pytest.raises(type(failure)) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                Path("input.pdf"),
                Path("output.pdf"),
                (PageRotation(0, 90),),
            )
        )

    assert exc_info.value is failure


def test_orchestration_performs_no_filesystem_or_pdf_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("missing.pdf")
    output_path = Path("missing/output.pdf")
    rotations = (PageRotation(2, 270), PageRotation(0, 90))

    class FakeConverter:
        def convert(self, request: PdfRotateRequest) -> tuple[Path, ...]:
            return request.output_paths

    def unexpected_call(path: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("orchestration performed filesystem work")

    monkeypatch.setattr(rotate_path_module, "PdfRotateConverter", FakeConverter)
    monkeypatch.setattr(Path, "exists", unexpected_call)
    monkeypatch.setattr(Path, "is_file", unexpected_call)
    monkeypatch.setattr(Path, "resolve", unexpected_call)
    monkeypatch.setattr(Path, "open", unexpected_call)
    monkeypatch.setattr(Path, "mkdir", unexpected_call)
    monkeypatch.setattr(Path, "iterdir", unexpected_call)
    monkeypatch.setattr(Path, "glob", unexpected_call)

    result = rotate_pdf_pages(PdfRotatePathRequest(input_path, output_path, rotations))

    assert result.input_path is input_path
    assert result.output_path is output_path
    assert result.rotations is rotations
    assert result.rotations == (PageRotation(2, 270), PageRotation(0, 90))
    assert not hasattr(rotate_path_module, "PdfReader")
    assert not hasattr(rotate_path_module, "PdfWriter")


@pytest.mark.parametrize("degrees", [90, 180, 270])
def test_one_page_rotates_by_supported_degrees(
    tmp_path: Path,
    degrees: int,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    result = rotate_pdf_pages(
        PdfRotatePathRequest(
            input_path,
            output_path,
            (PageRotation(0, degrees),),
        )
    )

    assert result.input_path is input_path
    assert result.output_path is output_path
    assert page_metadata(output_path) == [(100, 200, degrees)]


def test_selected_pages_rotate_while_order_and_source_are_preserved(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (300, 400), (500, 600)))
    source_before = input_path.read_bytes()
    first = PageRotation(2, 270)
    second = PageRotation(0, 90)
    rotations = (first, second)

    result = rotate_pdf_pages(
        PdfRotatePathRequest(input_path, output_path, rotations)
    )

    assert page_metadata(output_path) == [
        (100, 200, 90),
        (300, 400, 0),
        (500, 600, 270),
    ]
    assert len(PdfReader(output_path).pages) == 3
    assert input_path.read_bytes() == source_before
    assert page_metadata(input_path) == [
        (100, 200, 0),
        (300, 400, 0),
        (500, 600, 0),
    ]
    assert result.input_path is input_path
    assert result.rotations is rotations
    assert result.rotations[0] is first
    assert result.rotations[1] is second


def test_uppercase_paths_and_existing_output_replacement(tmp_path: Path) -> None:
    input_path = tmp_path / "INPUT.PDF"
    output_path = tmp_path / "OUTPUT.PDF"
    write_pdf(input_path, ((100, 200),))
    write_pdf(output_path, ((999, 999),))

    rotate_pdf_pages(
        PdfRotatePathRequest(
            input_path,
            output_path,
            (PageRotation(0, 180),),
        )
    )

    assert page_metadata(output_path) == [(100, 200, 180)]


def test_malformed_pdf_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.pdf"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                tmp_path / "output.pdf",
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == "Unable to rotate the requested PDF document."


def test_encrypted_pdf_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "encrypted.pdf"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                tmp_path / "output.pdf",
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == f"Encrypted PDF requires a password: {input_path}."


def test_missing_input_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.pdf"

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                tmp_path / "output.pdf",
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == f"Input file does not exist: {input_path}."


def test_directory_input_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "directory.pdf"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                tmp_path / "output.pdf",
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == f"Input path is not a file: {input_path}."


def test_missing_output_parent_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    missing_parent = tmp_path / "missing"
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                missing_parent / "output.pdf",
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {missing_parent}."
    )
    assert not missing_parent.exists()


def test_input_output_collision_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    nested = tmp_path / "nested"
    nested.mkdir()
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                nested / ".." / input_path.name,
                (PageRotation(0, 90),),
            )
        )

    assert str(exc_info.value) == "Output path must not resolve to the input file."


def test_out_of_range_page_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        rotate_pdf_pages(
            PdfRotatePathRequest(
                input_path,
                output_path,
                (PageRotation(1, 90),),
            )
        )

    assert str(exc_info.value) == "Page index is out of range: 1"
    assert not output_path.exists()


def test_low_level_rotation_api_remains_independently_usable(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200),))
    output_paths = (output_path,)
    request = PdfRotateRequest(
        input_paths=(input_path,),
        output_paths=output_paths,
        rotations=(PageRotation(0, 270),),
    )

    result = PdfRotateConverter().convert(request)

    assert result is output_paths
    assert page_metadata(output_path) == [(100, 200, 270)]


def test_public_exports_include_path_api_and_preserve_low_level_api() -> None:
    for package in (pdf_package, converters_package):
        assert package.PdfRotatePathRequest is PdfRotatePathRequest
        assert package.PdfRotatePathResult is PdfRotatePathResult
        assert package.rotate_pdf_pages is rotate_pdf_pages
        assert package.PageRotation is PageRotation
        assert package.PdfRotateRequest is PdfRotateRequest
        assert package.PdfRotateConverter is PdfRotateConverter

    assert "_validate_rotate_path_fields" not in pdf_package.__all__
    assert "_validate_rotate_path_fields" not in converters_package.__all__
