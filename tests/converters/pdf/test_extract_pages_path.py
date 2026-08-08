"""Tests for path-based PDF page extraction."""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.pdf as pdf_package
import docuforge.converters.pdf.extract_pages_path as path_module
from docuforge.converters.pdf import (
    PdfExtractPagesConverter,
    PdfExtractPagesPathRequest,
    PdfExtractPagesPathResult,
    PdfExtractPagesRequest,
    PdfProcessingError,
    extract_pdf_pages,
)
from docuforge.core import InvalidConversionRequestError

PathModel = type[PdfExtractPagesPathRequest] | type[PdfExtractPagesPathResult]


def write_pdf(path: Path, dimensions: tuple[tuple[int, int], ...]) -> None:
    """Write a PDF whose page dimensions identify source-page order."""
    writer = PdfWriter()
    try:
        for width, height in dimensions:
            writer.add_blank_page(width=width, height=height)
        writer.write(path)
    finally:
        writer.close()


def write_encrypted_pdf(path: Path) -> None:
    """Write a one-page encrypted PDF."""
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=100, height=200)
        writer.encrypt("secret")
        writer.write(path)
    finally:
        writer.close()


def page_dimensions(path: Path) -> list[tuple[int, int]]:
    """Return integer dimensions for every page in a PDF."""
    return [
        (int(page.mediabox.width), int(page.mediabox.height))
        for page in PdfReader(path, strict=True).pages
    ]


def path_request(
    input_path: Path,
    output_path: Path,
    page_indices: tuple[int, ...] = (0,),
) -> PdfExtractPagesPathRequest:
    """Build a path extraction request."""
    return PdfExtractPagesPathRequest(input_path, output_path, page_indices)


@pytest.mark.parametrize(
    "model_type",
    [PdfExtractPagesPathRequest, PdfExtractPagesPathResult],
)
def test_path_models_are_frozen_slotted_and_preserve_identity(
    model_type: PathModel,
) -> None:
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    page_indices = (3, 1, 4)

    model = model_type(input_path, output_path, page_indices)

    assert not hasattr(model, "__dict__")
    assert model.input_path is input_path
    assert model.output_path is output_path
    assert model.page_indices is page_indices
    with pytest.raises(FrozenInstanceError):
        model.page_indices = (0,)  # type: ignore[misc]


@pytest.mark.parametrize(
    ("model_type", "field", "value", "exception_type", "message"),
    [
        *[
            (model_type, "input_path", "input.pdf", TypeError, "input_path must be a Path")
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (model_type, "output_path", "output.pdf", TypeError, "output_path must be a Path")
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (
                model_type,
                "page_indices",
                [0],
                TypeError,
                "page_indices must be a tuple of integers",
            )
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (
                model_type,
                "page_indices",
                (),
                InvalidConversionRequestError,
                "At least one page index is required",
            )
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (
                model_type,
                "page_indices",
                ("0",),
                TypeError,
                "page_indices must contain only integers",
            )
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (
                model_type,
                "page_indices",
                (True,),
                TypeError,
                "page_indices must contain only integers",
            )
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
        *[
            (
                model_type,
                "page_indices",
                (1, -1),
                InvalidConversionRequestError,
                "Page indices must be non-negative",
            )
            for model_type in (PdfExtractPagesPathRequest, PdfExtractPagesPathResult)
        ],
    ],
)
def test_path_models_reject_invalid_structure(
    model_type: PathModel,
    field: str,
    value: object,
    exception_type: type[Exception],
    message: str,
) -> None:
    values: dict[str, object] = {
        "input_path": Path("input.pdf"),
        "output_path": Path("output.pdf"),
        "page_indices": (0,),
    }
    values[field] = value

    with pytest.raises(exception_type, match=message):
        model_type(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "model_type",
    [PdfExtractPagesPathRequest, PdfExtractPagesPathResult],
)
@pytest.mark.parametrize(
    ("page_indices", "duplicate"),
    [((1, 1, 2, 2), 1), ((3, 1, 3, 1), 3)],
)
def test_path_models_report_first_duplicate_in_request_order(
    model_type: PathModel,
    page_indices: tuple[int, ...],
    duplicate: int,
) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        model_type(Path("input.pdf"), Path("output.pdf"), page_indices)

    assert str(exc_info.value) == f"Each page may be extracted only once: {duplicate}"


@pytest.mark.parametrize(
    "model_type",
    [PdfExtractPagesPathRequest, PdfExtractPagesPathResult],
)
def test_path_models_preserve_unsorted_indices_without_filesystem_access(
    model_type: PathModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_access(*args: object, **kwargs: object) -> object:
        raise AssertionError("path model construction accessed the filesystem")

    for method_name in ("exists", "is_file", "is_dir", "resolve", "open"):
        monkeypatch.setattr(Path, method_name, unexpected_access)
    input_path = Path("input.pdf")
    output_path = Path("output.pdf")
    page_indices = (4, 1, 3)

    model = model_type(input_path, output_path, page_indices)

    assert model.input_path is input_path
    assert model.output_path is output_path
    assert model.page_indices is page_indices


def test_extract_pdf_pages_requires_path_request() -> None:
    with pytest.raises(
        TypeError,
        match="request must be an instance of PdfExtractPagesPathRequest",
    ):
        extract_pdf_pages(object())  # type: ignore[arg-type]


def install_successful_converter(
    monkeypatch: pytest.MonkeyPatch,
    returned_path: Path,
) -> None:
    """Replace the converter with a no-I/O successful implementation."""
    class SuccessfulConverter:
        def convert(self, request: PdfExtractPagesRequest) -> tuple[Path, ...]:
            return (returned_path,)

    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", SuccessfulConverter)


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_input_suffixes_are_accepted(
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returned_path = Path("returned.pdf")
    install_successful_converter(monkeypatch, returned_path)
    request = path_request(Path(f"input{suffix}"), Path("output.pdf"), (3, 1))

    result = extract_pdf_pages(request)

    assert result.output_path is returned_path
    assert result.page_indices is request.page_indices


@pytest.mark.parametrize("suffix", [".pdf", ".PDF", ".Pdf"])
def test_supported_output_suffixes_are_accepted(
    suffix: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    returned_path = Path(f"returned{suffix}")
    install_successful_converter(monkeypatch, returned_path)
    request = path_request(Path("input.pdf"), Path(f"output{suffix}"), (1, 0))

    result = extract_pdf_pages(request)

    assert result.output_path is returned_path
    assert result.page_indices is request.page_indices


@pytest.mark.parametrize("name", ["input", "input.txt", "input.pdf.tmp", ".pdf"])
def test_invalid_input_suffix_is_rejected_before_low_level_construction(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False
    instantiated = False

    def unexpected_request(*args: object, **kwargs: object) -> object:
        nonlocal constructed
        constructed = True
        raise AssertionError("low-level request was constructed")

    class UnexpectedConverter:
        def __init__(self) -> None:
            nonlocal instantiated
            instantiated = True

    monkeypatch.setattr(path_module, "PdfExtractPagesRequest", unexpected_request)
    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", UnexpectedConverter)

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        extract_pdf_pages(path_request(Path(name), Path("output.txt")))

    assert str(exc_info.value) == f"Input file must use the .pdf extension: {name}"
    assert constructed is False
    assert instantiated is False


@pytest.mark.parametrize("name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_suffix_is_rejected_before_low_level_construction(
    name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    constructed = False
    instantiated = False

    def unexpected_request(*args: object, **kwargs: object) -> object:
        nonlocal constructed
        constructed = True
        raise AssertionError("low-level request was constructed")

    class UnexpectedConverter:
        def __init__(self) -> None:
            nonlocal instantiated
            instantiated = True

    monkeypatch.setattr(path_module, "PdfExtractPagesRequest", unexpected_request)
    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", UnexpectedConverter)

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        extract_pdf_pages(path_request(Path("input.pdf"), Path(name)))

    assert str(exc_info.value) == f"Output file must use the .pdf extension: {name}"
    assert constructed is False
    assert instantiated is False


def test_delegation_preserves_identity_and_exact_converter_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_path = Path("relative/input.pdf")
    requested_output = Path("relative/requested.pdf")
    returned_output = Path("converter/returned.pdf")
    page_indices = (3, 1, 4)
    request = path_request(input_path, requested_output, page_indices)
    constructed_requests: list[PdfExtractPagesRequest] = []
    converted_requests: list[PdfExtractPagesRequest] = []
    instance_count = 0
    real_request_type = PdfExtractPagesRequest

    def construct_request(
        input_paths: tuple[Path, ...],
        output_paths: tuple[Path, ...],
        page_indices: tuple[int, ...],
    ) -> PdfExtractPagesRequest:
        low_level_request = real_request_type(input_paths, output_paths, page_indices)
        constructed_requests.append(low_level_request)
        return low_level_request

    class ObservedConverter:
        def __init__(self) -> None:
            nonlocal instance_count
            instance_count += 1

        def convert(self, low_level_request: PdfExtractPagesRequest) -> tuple[Path, ...]:
            converted_requests.append(low_level_request)
            return (returned_output,)

    monkeypatch.setattr(path_module, "PdfExtractPagesRequest", construct_request)
    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", ObservedConverter)

    result = extract_pdf_pages(request)

    assert instance_count == 1
    assert len(constructed_requests) == 1
    assert converted_requests == constructed_requests
    low_level_request = constructed_requests[0]
    assert low_level_request.input_paths[0] is input_path
    assert low_level_request.output_paths[0] is requested_output
    assert low_level_request.page_indices is page_indices
    assert result.input_path is input_path
    assert result.output_path is returned_output
    assert result.output_path is not requested_output
    assert result.page_indices is page_indices


@pytest.mark.parametrize(
    "failure",
    [PdfProcessingError("expected failure"), RuntimeError("unexpected failure")],
)
def test_converter_failures_propagate_unchanged(
    failure: Exception,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingConverter:
        def convert(self, request: PdfExtractPagesRequest) -> tuple[Path, ...]:
            raise failure

    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", FailingConverter)

    with pytest.raises(type(failure)) as exc_info:
        extract_pdf_pages(path_request(Path("input.pdf"), Path("output.pdf")))

    assert exc_info.value is failure


def test_orchestration_performs_no_filesystem_or_pdf_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = path_request(
        Path("relative/input.pdf"),
        Path("relative/output.pdf"),
        (999, 3, 1),
    )
    returned_output = Path("returned.pdf")
    received_request: PdfExtractPagesRequest | None = None

    class SuccessfulConverter:
        def convert(self, low_level_request: PdfExtractPagesRequest) -> tuple[Path, ...]:
            nonlocal received_request
            received_request = low_level_request
            return (returned_output,)

    def unexpected_work(*args: object, **kwargs: object) -> object:
        raise AssertionError("high-level extraction performed filesystem or PDF work")

    monkeypatch.setattr(path_module, "PdfExtractPagesConverter", SuccessfulConverter)
    for method_name in ("exists", "is_file", "is_dir", "resolve", "open", "mkdir", "glob"):
        monkeypatch.setattr(Path, method_name, unexpected_work)

    result = extract_pdf_pages(request)

    assert received_request is not None
    assert received_request.page_indices is request.page_indices
    assert result.output_path is returned_output
    assert "PdfReader" not in vars(path_module)
    assert "PdfWriter" not in vars(path_module)


@pytest.mark.parametrize(
    ("page_indices", "expected"),
    [
        ((0,), [(100, 200)]),
        ((2,), [(300, 400)]),
        ((4,), [(500, 600)]),
        ((0, 2, 4), [(100, 200), (300, 400), (500, 600)]),
        ((3, 1, 4), [(400, 500), (200, 300), (500, 600)]),
    ],
)
def test_integration_extracts_selected_pages_in_request_order(
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
    indices = page_indices
    request = path_request(input_path, output_path, indices)

    result = extract_pdf_pages(request)

    assert result.input_path is input_path
    assert result.page_indices is indices
    assert page_dimensions(result.output_path) == expected
    assert len(PdfReader(result.output_path, strict=True).pages) == len(indices)
    assert input_path.read_bytes() == source_before
    assert page_dimensions(input_path) == list(source_dimensions)


def test_uppercase_paths_replace_existing_output(tmp_path: Path) -> None:
    input_path = tmp_path / "INPUT.PDF"
    output_path = tmp_path / "OUTPUT.PDF"
    write_pdf(input_path, ((100, 200), (200, 300)))
    write_pdf(output_path, ((999, 999),))

    result = extract_pdf_pages(path_request(input_path, output_path, (1,)))

    assert result.output_path is output_path
    assert page_dimensions(output_path) == [(200, 300)]


@pytest.mark.parametrize("kind", ["malformed", "encrypted"])
def test_pdf_processing_failures_propagate(tmp_path: Path, kind: str) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    if kind == "malformed":
        input_path.write_bytes(b"not a PDF")
    else:
        write_encrypted_pdf(input_path)

    with pytest.raises(PdfProcessingError):
        extract_pdf_pages(path_request(input_path, output_path))

    assert not output_path.exists()


@pytest.mark.parametrize("kind", ["missing", "directory", "missing-parent", "collision"])
def test_path_validation_failures_propagate(tmp_path: Path, kind: str) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    if kind == "directory":
        input_path.mkdir()
    elif kind != "missing":
        write_pdf(input_path, ((100, 200), (200, 300)))
    if kind == "missing-parent":
        output_path = tmp_path / "missing" / "output.pdf"
    elif kind == "collision":
        output_path = input_path

    with pytest.raises(InvalidConversionRequestError):
        extract_pdf_pages(path_request(input_path, output_path))

    if kind == "missing-parent":
        assert not output_path.parent.exists()


def test_out_of_range_page_failure_propagates(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300)))

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        extract_pdf_pages(path_request(input_path, output_path, (1, 4, 3)))

    assert str(exc_info.value) == "Page index is out of range: 4"
    assert not output_path.exists()


def test_low_level_extraction_api_remains_independently_usable(tmp_path: Path) -> None:
    input_path = tmp_path / "input.pdf"
    output_path = tmp_path / "output.pdf"
    write_pdf(input_path, ((100, 200), (200, 300), (300, 400)))
    output_paths = (output_path,)
    request = PdfExtractPagesRequest((input_path,), output_paths, (2, 0))

    result = PdfExtractPagesConverter().convert(request)

    assert result is output_paths
    assert page_dimensions(output_path) == [(300, 400), (100, 200)]


def test_public_exports_include_path_api_and_preserve_low_level_api() -> None:
    for package in (pdf_package, converters_package):
        assert package.PdfExtractPagesPathRequest is PdfExtractPagesPathRequest
        assert package.PdfExtractPagesPathResult is PdfExtractPagesPathResult
        assert package.extract_pdf_pages is extract_pdf_pages
        assert package.PdfExtractPagesRequest is PdfExtractPagesRequest
        assert package.PdfExtractPagesConverter is PdfExtractPagesConverter
        for name in (
            "PdfExtractPagesPathRequest",
            "PdfExtractPagesPathResult",
            "extract_pdf_pages",
            "PdfExtractPagesRequest",
            "PdfExtractPagesConverter",
        ):
            assert name in package.__all__

    assert "_validate_extract_pages_path_fields" not in pdf_package.__all__
    assert "_validate_extract_pages_path_fields" not in converters_package.__all__
