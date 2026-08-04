"""Tests for high-level path-based PDF page removal."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.pdf as pdf_package
import docuforge.converters.pdf.remove_pages_path as remove_pages_path_module
from docuforge.converters.pdf import (
    PdfProcessingError,
    PdfRemovePagesConverter,
    PdfRemovePagesPathRequest,
    PdfRemovePagesPathResult,
    PdfRemovePagesRequest,
    remove_pdf_pages,
)
from docuforge.core import InvalidConversionRequestError

PathModel = type[PdfRemovePagesPathRequest] | type[PdfRemovePagesPathResult]


def write_pdf(path: Path, dimensions: tuple[tuple[int, int], ...]) -> None:
    """Write a PDF with pages identifiable by their dimensions."""
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
    """Return the dimensions of every page in source order."""
    reader = PdfReader(path, strict=True)
    return [
        (int(page.mediabox.width), int(page.mediabox.height))
        for page in reader.pages
    ]


@pytest.mark.parametrize(
    "model_type",
    [PdfRemovePagesPathRequest, PdfRemovePagesPathResult],
)
def test_path_models_are_frozen_slotted_and_preserve_identity(
    model_type: PathModel,
) -> None:
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    page_indices = (3, 1)

    model = model_type(input_path, output_path, page_indices)

    assert not hasattr(model, "__dict__")
    assert model.input_path is input_path
    assert model.output_path is output_path
    assert model.page_indices is page_indices
    with pytest.raises(FrozenInstanceError):
        model.output_path = Path("other.pdf")  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field", "value", "error_type", "message"),
    [
        ("input_path", "input.pdf", TypeError, "input_path must be a Path object"),
        ("output_path", "output.pdf", TypeError, "output_path must be a Path object"),
        (
            "page_indices",
            [0],
            TypeError,
            "page_indices must be a tuple of integers",
        ),
        (
            "page_indices",
            (),
            InvalidConversionRequestError,
            "At least one page index is required",
        ),
        (
            "page_indices",
            ("0",),
            TypeError,
            "page_indices must contain only integers",
        ),
        (
            "page_indices",
            (True,),
            TypeError,
            "page_indices must contain only integers",
        ),
        (
            "page_indices",
            (2, -1),
            InvalidConversionRequestError,
            "Page indices must be non-negative",
        ),
        (
            "page_indices",
            (2, 2),
            InvalidConversionRequestError,
            "Each page may be removed only once: 2",
        ),
    ],
)
@pytest.mark.parametrize(
    "model_type",
    [PdfRemovePagesPathRequest, PdfRemovePagesPathResult],
)
def test_path_models_reject_invalid_structure(
    model_type: PathModel,
    field: str,
    value: object,
    error_type: type[Exception],
    message: str,
) -> None:
    values: dict[str, object] = {
        "input_path": Path("input.pdf"),
        "output_path": Path("output.pdf"),
        "page_indices": (0,),
    }
    values[field] = value

    with pytest.raises(error_type, match=message):
        model_type(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "model_type",
    [PdfRemovePagesPathRequest, PdfRemovePagesPathResult],
)
def test_path_models_report_first_duplicate_in_request_order(
    model_type: PathModel,
) -> None:
    page_indices = (3, 1, 3, 1)

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        model_type(Path("input.pdf"), Path("output.pdf"), page_indices)

    assert str(exc_info.value) == "Each page may be removed only once: 3"


@pytest.mark.parametrize(
    "model_type",
    [PdfRemovePagesPathRequest, PdfRemovePagesPathResult],
)
def test_path_models_preserve_unsorted_indices_without_filesystem_access(
    model_type: PathModel,
) -> None:
    input_path = Path("missing.pdf")
    output_path = Path("missing/output.pdf")
    page_indices = (4, 1, 3)

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "is_file", side_effect=AssertionError("is_file called")),
        patch.object(Path, "resolve", side_effect=AssertionError("resolve called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
        patch.object(Path, "mkdir", side_effect=AssertionError("mkdir called")),
    ):
        model = model_type(input_path, output_path, page_indices)

    assert model.input_path is input_path
    assert model.output_path is output_path
    assert model.page_indices is page_indices


def test_remove_pdf_pages_requires_path_request() -> None:
    with pytest.raises(
        TypeError,
        match="request must be an instance of PdfRemovePagesPathRequest",
    ):
        remove_pdf_pages(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_input_suffixes_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    class FakeConverter:
        def convert(self, request: PdfRemovePagesRequest) -> tuple[Path, ...]:
            return request.output_paths

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        FakeConverter,
    )

    result = remove_pdf_pages(
        PdfRemovePagesPathRequest(
            Path(f"input{suffix}"),
            Path("output.pdf"),
            (0,),
        )
    )

    assert result.output_path == Path("output.pdf")


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_output_suffixes_are_accepted(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
) -> None:
    class FakeConverter:
        def convert(self, request: PdfRemovePagesRequest) -> tuple[Path, ...]:
            return request.output_paths

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        FakeConverter,
    )

    result = remove_pdf_pages(
        PdfRemovePagesPathRequest(
            Path("input.pdf"),
            Path(f"output{suffix}"),
            (0,),
        )
    )

    assert result.output_path == Path(f"output{suffix}")


@pytest.mark.parametrize("name", ["input", "input.txt", "input.pdf.tmp", ".pdf"])
def test_invalid_input_suffix_is_rejected_before_low_level_construction(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    input_path = Path(name)

    class UnexpectedConverter:
        def __init__(self) -> None:
            raise AssertionError("converter constructed")

    def unexpected_request(*args: object, **kwargs: object) -> object:
        raise AssertionError("low-level request constructed")

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        UnexpectedConverter,
    )
    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesRequest",
        unexpected_request,
    )

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                Path("output.txt"),
                (0,),
            )
        )

    assert str(exc_info.value) == f"Input file must use the .pdf extension: {input_path}"


@pytest.mark.parametrize("name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_suffix_is_rejected_before_low_level_construction(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    output_path = Path(name)

    class UnexpectedConverter:
        def __init__(self) -> None:
            raise AssertionError("converter constructed")

    def unexpected_request(*args: object, **kwargs: object) -> object:
        raise AssertionError("low-level request constructed")

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        UnexpectedConverter,
    )
    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesRequest",
        unexpected_request,
    )

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                Path("input.pdf"),
                output_path,
                (0,),
            )
        )

    assert str(exc_info.value) == (
        f"Output file must use the .pdf extension: {output_path}"
    )


def test_delegation_preserves_identity_and_exact_converter_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("relative/input.pdf")
    output_path = Path("relative/output.pdf")
    converted_path = Path("library-returned.pdf")
    page_indices = (3, 1)
    constructed_arguments: list[
        tuple[tuple[Path, ...], tuple[Path, ...], tuple[int, ...]]
    ] = []
    received_request: PdfRemovePagesRequest | None = None
    converter_count = 0
    convert_count = 0
    real_request = remove_pages_path_module.PdfRemovePagesRequest

    def low_level_request(
        *,
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        page_indices: tuple[int, ...],
    ) -> PdfRemovePagesRequest:
        constructed_arguments.append((input_paths, output_paths, page_indices))
        return real_request(input_paths, output_paths, page_indices)

    class FakeConverter:
        def __init__(self) -> None:
            nonlocal converter_count
            converter_count += 1

        def convert(self, request: PdfRemovePagesRequest) -> tuple[Path, ...]:
            nonlocal convert_count, received_request
            convert_count += 1
            received_request = request
            return (converted_path,)

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesRequest",
        low_level_request,
    )
    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        FakeConverter,
    )

    result = remove_pdf_pages(
        PdfRemovePagesPathRequest(input_path, output_path, page_indices)
    )

    assert len(constructed_arguments) == 1
    constructed_inputs, constructed_outputs, constructed_indices = (
        constructed_arguments[0]
    )
    assert constructed_inputs[0] is input_path
    assert constructed_outputs[0] is output_path
    assert constructed_indices is page_indices
    assert converter_count == 1
    assert convert_count == 1
    assert received_request is not None
    assert result.input_path is input_path
    assert result.output_path is converted_path
    assert result.page_indices is page_indices


@pytest.mark.parametrize(
    "failure",
    [PdfProcessingError("public failure"), RuntimeError("unexpected failure")],
)
def test_converter_failures_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    class FailingConverter:
        def convert(self, request: PdfRemovePagesRequest) -> tuple[Path, ...]:
            raise failure

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        FailingConverter,
    )

    with pytest.raises(type(failure)) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                Path("input.pdf"),
                Path("output.pdf"),
                (0,),
            )
        )

    assert exc_info.value is failure


def test_orchestration_performs_no_filesystem_or_pdf_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("missing.pdf")
    output_path = Path("missing/output.pdf")
    page_indices = (4, 1, 3)

    class FakeConverter:
        def convert(self, request: PdfRemovePagesRequest) -> tuple[Path, ...]:
            return request.output_paths

    def unexpected_call(path: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("orchestration performed filesystem work")

    monkeypatch.setattr(
        remove_pages_path_module,
        "PdfRemovePagesConverter",
        FakeConverter,
    )
    for method_name in (
        "exists",
        "is_file",
        "is_dir",
        "resolve",
        "open",
        "mkdir",
        "iterdir",
        "glob",
    ):
        monkeypatch.setattr(Path, method_name, unexpected_call)

    result = remove_pdf_pages(
        PdfRemovePagesPathRequest(input_path, output_path, page_indices)
    )

    assert result.input_path is input_path
    assert result.output_path is output_path
    assert result.page_indices is page_indices
    assert result.page_indices == (4, 1, 3)
    assert not hasattr(remove_pages_path_module, "PdfReader")
    assert not hasattr(remove_pages_path_module, "PdfWriter")
    assert not hasattr(remove_pages_path_module, "os")


@pytest.mark.parametrize(
    ("page_indices", "expected"),
    [
        ((0,), [(200, 300), (300, 400), (400, 500)]),
        ((1,), [(100, 200), (300, 400), (400, 500)]),
        ((3,), [(100, 200), (200, 300), (300, 400)]),
        ((3, 1), [(100, 200), (300, 400)]),
        ((1, 3), [(100, 200), (300, 400)]),
    ],
)
def test_integration_removes_selected_pages_and_preserves_source_order(
    tmp_path: Path,
    page_indices: tuple[int, ...],
    expected: list[tuple[int, int]],
) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    source_dimensions = ((100, 200), (200, 300), (300, 400), (400, 500))
    write_pdf(input_path, source_dimensions)
    source_before = input_path.read_bytes()

    result = remove_pdf_pages(
        PdfRemovePagesPathRequest(input_path, output_path, page_indices)
    )

    assert result.input_path is input_path
    assert result.output_path is output_path
    assert result.page_indices is page_indices
    assert page_dimensions(output_path) == expected
    assert len(PdfReader(output_path, strict=True).pages) == (
        len(source_dimensions) - len(page_indices)
    )
    assert input_path.read_bytes() == source_before
    assert page_dimensions(input_path) == list(source_dimensions)


def test_uppercase_paths_replace_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "INPUT.PDF"
    output_path = tmp_path / "OUTPUT.PDF"
    write_pdf(input_path, ((100, 200), (200, 300)))
    write_pdf(output_path, ((999, 999),))

    remove_pdf_pages(PdfRemovePagesPathRequest(input_path, output_path, (0,)))

    assert page_dimensions(output_path) == [(200, 300)]


def test_malformed_pdf_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.pdf"
    input_path.write_bytes(b"not a PDF")

    with pytest.raises(PdfProcessingError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (0,),
            )
        )

    assert str(exc_info.value) == (
        "Unable to remove pages from the requested PDF document."
    )


def test_encrypted_pdf_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "encrypted.pdf"
    write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (0,),
            )
        )

    assert str(exc_info.value) == f"Encrypted PDF requires a password: {input_path}."


def test_missing_input_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.pdf"

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (0,),
            )
        )

    assert str(exc_info.value) == f"Input file does not exist: {input_path}."


def test_directory_input_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "directory.pdf"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (0,),
            )
        )

    assert str(exc_info.value) == f"Input path is not a file: {input_path}."


def test_missing_output_parent_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    missing_parent = tmp_path / "missing"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                missing_parent / "output.pdf",
                (0,),
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
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                nested / ".." / input_path.name,
                (0,),
            )
        )

    assert str(exc_info.value) == "Output path must not resolve to the input file."


def test_out_of_range_page_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (2,),
            )
        )

    assert str(exc_info.value) == "Page index is out of range: 2"


def test_total_removal_failure_propagates_from_low_level_converter(
    tmp_path: Path,
) -> None:
    input_path = tmp_path / "input.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        remove_pdf_pages(
            PdfRemovePagesPathRequest(
                input_path,
                tmp_path / "output.pdf",
                (1, 0),
            )
        )

    assert str(exc_info.value) == "At least one PDF page must remain after removal."


def test_low_level_removal_api_remains_independently_usable(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))
    output_paths = (output_path,)
    request = PdfRemovePagesRequest((input_path,), output_paths, (0,))

    result = PdfRemovePagesConverter().convert(request)

    assert result is output_paths
    assert page_dimensions(output_path) == [(200, 300)]


def test_public_exports_include_path_api_and_preserve_low_level_api() -> None:
    for package in (pdf_package, converters_package):
        assert package.PdfRemovePagesPathRequest is PdfRemovePagesPathRequest
        assert package.PdfRemovePagesPathResult is PdfRemovePagesPathResult
        assert package.remove_pdf_pages is remove_pdf_pages
        assert package.PdfRemovePagesRequest is PdfRemovePagesRequest
        assert package.PdfRemovePagesConverter is PdfRemovePagesConverter

    assert "_validate_remove_pages_path_fields" not in pdf_package.__all__
    assert "_validate_remove_pages_path_fields" not in converters_package.__all__
