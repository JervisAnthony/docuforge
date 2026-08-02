"""Tests for high-level path-based image-to-PDF conversion."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

import docuforge.converters as converters_package
import docuforge.converters.image as image_package
import docuforge.converters.image.paths_to_pdf as paths_module
from docuforge.converters import (
    ImageInput,
    ImageProcessingError,
    ImageToPdfConverter,
    ImageToPdfPathRequest,
    ImageToPdfPathResult,
    ImageToPdfRequest,
    convert_images_to_pdf,
)
from docuforge.core import DocumentFormat, InvalidConversionRequestError


def write_image(
    path: Path,
    size: tuple[int, int],
    image_format: str,
) -> None:
    """Write a distinguishable RGB image in a declared Pillow format."""
    image = Image.new("RGB", size, "white")
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def page_sizes(path: Path) -> list[tuple[float, float]]:
    """Return PDF page dimensions in output order."""
    return [
        (float(page.mediabox.width), float(page.mediabox.height))
        for page in PdfReader(path).pages
    ]


def test_path_request_is_frozen_slotted_and_preserves_identity() -> None:
    first = Path("first.jpg")
    second = Path("second.png")
    input_paths = (first, second)
    output_path = Path("output.pdf")

    request = ImageToPdfPathRequest(input_paths, output_path)

    assert ImageToPdfPathRequest.__slots__ == ("input_paths", "output_path")
    assert not hasattr(request, "__dict__")
    assert request.input_paths is input_paths
    assert request.input_paths[0] is first
    assert request.input_paths[1] is second
    assert request.output_path is output_path
    with pytest.raises(FrozenInstanceError):
        request.input_paths = (Path("replacement.jpg"),)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        request.output_path = Path("replacement.pdf")  # type: ignore[misc]


def test_path_result_is_frozen_slotted_and_preserves_identity() -> None:
    first = Path("first.jpg")
    second = Path("second.png")
    input_paths = (first, second)
    output_path = Path("output.pdf")

    result = ImageToPdfPathResult(input_paths, output_path)

    assert ImageToPdfPathResult.__slots__ == ("input_paths", "output_path")
    assert not hasattr(result, "__dict__")
    assert result.input_paths is input_paths
    assert result.input_paths[0] is first
    assert result.input_paths[1] is second
    assert result.output_path is output_path
    with pytest.raises(FrozenInstanceError):
        result.input_paths = (Path("replacement.jpg"),)  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        result.output_path = Path("replacement.pdf")  # type: ignore[misc]


@pytest.mark.parametrize("model_type", [ImageToPdfPathRequest, ImageToPdfPathResult])
def test_path_models_reject_non_tuple_inputs(model_type: type[object]) -> None:
    with pytest.raises(TypeError, match="input_paths must be a tuple of Path objects"):
        model_type([Path("input.jpg")], Path("output.pdf"))  # type: ignore[call-arg]


@pytest.mark.parametrize("model_type", [ImageToPdfPathRequest, ImageToPdfPathResult])
def test_path_models_reject_empty_inputs(model_type: type[object]) -> None:
    with pytest.raises(InvalidConversionRequestError) as exc_info:
        model_type((), Path("output.pdf"))  # type: ignore[call-arg]

    assert str(exc_info.value) == "At least one input path is required."


@pytest.mark.parametrize("model_type", [ImageToPdfPathRequest, ImageToPdfPathResult])
def test_path_models_reject_non_path_input_members(model_type: type[object]) -> None:
    with pytest.raises(TypeError, match="input_paths must contain only Path objects"):
        model_type((Path("first.jpg"), "second.png"), Path("output.pdf"))  # type: ignore[call-arg]


@pytest.mark.parametrize("model_type", [ImageToPdfPathRequest, ImageToPdfPathResult])
def test_path_models_reject_non_path_output(model_type: type[object]) -> None:
    with pytest.raises(TypeError, match="output_path must be a Path object"):
        model_type((Path("input.jpg"),), "output.pdf")  # type: ignore[call-arg]


def test_path_request_construction_performs_no_filesystem_operations() -> None:
    input_path = Path("missing.jpg")
    output_path = Path("missing/output.pdf")

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "is_file", side_effect=AssertionError("is_file called")),
        patch.object(Path, "resolve", side_effect=AssertionError("resolve called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
        patch.object(Path, "mkdir", side_effect=AssertionError("mkdir called")),
    ):
        request = ImageToPdfPathRequest((input_path,), output_path)

    assert request.input_paths[0] is input_path
    assert request.output_path is output_path


def test_convert_requires_path_request() -> None:
    with pytest.raises(
        TypeError,
        match="request must be an instance of ImageToPdfPathRequest",
    ):
        convert_images_to_pdf(object())  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("suffix", "expected_format"),
    [
        (".jpg", DocumentFormat.JPG),
        (".jpeg", DocumentFormat.JPG),
        (".png", DocumentFormat.PNG),
        (".bmp", DocumentFormat.BMP),
        (".tif", DocumentFormat.TIFF),
        (".tiff", DocumentFormat.TIFF),
        (".JPG", DocumentFormat.JPG),
        (".JpEg", DocumentFormat.JPG),
        (".PNG", DocumentFormat.PNG),
        (".BmP", DocumentFormat.BMP),
        (".TIF", DocumentFormat.TIFF),
        (".TiFf", DocumentFormat.TIFF),
    ],
)
def test_supported_suffix_inference(
    monkeypatch: pytest.MonkeyPatch,
    suffix: str,
    expected_format: DocumentFormat,
) -> None:
    captured_format: DocumentFormat | None = None

    class FakeConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            nonlocal captured_format
            captured_format = source_format

        def convert(self, request: ImageToPdfRequest) -> Path:
            return request.output_path

    monkeypatch.setattr(paths_module, "ImageToPdfConverter", FakeConverter)

    convert_images_to_pdf(
        ImageToPdfPathRequest((Path(f"input{suffix}"),), Path("output.PDF"))
    )

    assert captured_format is expected_format


@pytest.mark.parametrize(
    "name",
    ["animation.gif", "image.webp", "document.pdf", "image", "image.jpg.tmp", ".jpg"],
)
def test_unsupported_input_suffix_is_rejected_before_filesystem_or_converter(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    input_path = Path(name)

    class UnexpectedConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            raise AssertionError("converter constructed")

    monkeypatch.setattr(paths_module, "ImageToPdfConverter", UnexpectedConverter)

    with (
        patch.object(Path, "exists", side_effect=AssertionError("exists called")),
        patch.object(Path, "open", side_effect=AssertionError("open called")),
        pytest.raises(InvalidConversionRequestError) as exc_info,
    ):
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), Path("output.pdf"))
        )

    assert str(exc_info.value) == (
        "Input file must use .jpg, .jpeg, .png, .bmp, .tif, or .tiff: "
        f"{input_path}"
    )


def test_first_unsupported_input_is_reported_in_request_order() -> None:
    first_invalid = Path("first.gif")
    second_invalid = Path("second.webp")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest(
                (Path("valid.jpg"), first_invalid, second_invalid),
                Path("output.pdf"),
            )
        )

    assert str(exc_info.value).endswith(f": {first_invalid}")


@pytest.mark.parametrize("name", ["output", "output.txt", "output.pdf.tmp", ".pdf"])
def test_invalid_output_suffix_is_rejected_before_converter(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
) -> None:
    output_path = Path(name)

    class UnexpectedConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            raise AssertionError("converter constructed")

    monkeypatch.setattr(paths_module, "ImageToPdfConverter", UnexpectedConverter)

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((Path("input.jpg"),), output_path)
        )

    assert str(exc_info.value) == (
        f"Output file must use the .pdf extension: {output_path}"
    )


def test_delegation_preserves_order_identity_and_exact_converter_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_paths = (
        Path("first.png"),
        Path("second.jpg"),
        Path("third.tiff"),
    )
    output_path = Path("output.pdf")
    converted_path = Path("converter-returned.pdf")
    constructed_inputs: list[tuple[Path, DocumentFormat]] = []
    received_output_path: Path | None = None
    received_request: ImageToPdfRequest | None = None
    converter_formats: list[DocumentFormat] = []
    convert_count = 0
    real_image_input = paths_module.ImageInput
    real_request = paths_module.ImageToPdfRequest

    def image_input(*, path: Path, format: DocumentFormat) -> ImageInput:
        constructed_inputs.append((path, format))
        return real_image_input(path=path, format=format)

    def low_level_request(
        *,
        images: tuple[ImageInput, ...],
        output_path: Path,
    ) -> ImageToPdfRequest:
        nonlocal received_output_path
        received_output_path = output_path
        return real_request(images=images, output_path=output_path)

    class FakeConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            converter_formats.append(source_format)

        def convert(self, request: ImageToPdfRequest) -> Path:
            nonlocal convert_count, received_request
            convert_count += 1
            received_request = request
            return converted_path

    monkeypatch.setattr(paths_module, "ImageInput", image_input)
    monkeypatch.setattr(paths_module, "ImageToPdfRequest", low_level_request)
    monkeypatch.setattr(paths_module, "ImageToPdfConverter", FakeConverter)

    result = convert_images_to_pdf(ImageToPdfPathRequest(input_paths, output_path))

    assert [path for path, _ in constructed_inputs] == list(input_paths)
    assert all(
        constructed_path is original_path
        for (constructed_path, _), original_path in zip(
            constructed_inputs,
            input_paths,
            strict=True,
        )
    )
    assert [image_format for _, image_format in constructed_inputs] == [
        DocumentFormat.PNG,
        DocumentFormat.JPG,
        DocumentFormat.TIFF,
    ]
    assert received_output_path is output_path
    assert converter_formats == [DocumentFormat.PNG]
    assert convert_count == 1
    assert isinstance(received_request, ImageToPdfRequest)
    assert result.input_paths is input_paths
    assert result.output_path is converted_path


def test_orchestration_does_not_scan_or_create_output_parent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            pass

        def convert(self, request: ImageToPdfRequest) -> Path:
            return request.output_path

    def unexpected_call(path: Path, *args: object, **kwargs: object) -> object:
        raise AssertionError("orchestration performed filesystem work")

    monkeypatch.setattr(paths_module, "ImageToPdfConverter", FakeConverter)
    monkeypatch.setattr(Path, "iterdir", unexpected_call)
    monkeypatch.setattr(Path, "glob", unexpected_call)
    monkeypatch.setattr(Path, "mkdir", unexpected_call)

    result = convert_images_to_pdf(
        ImageToPdfPathRequest((Path("input.jpg"),), Path("missing/output.pdf"))
    )

    assert result.output_path == Path("missing/output.pdf")


@pytest.mark.parametrize(
    "failure",
    [ImageProcessingError("public failure"), RuntimeError("unexpected failure")],
)
def test_converter_failures_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    class FailingConverter:
        def __init__(self, source_format: DocumentFormat) -> None:
            pass

        def convert(self, request: ImageToPdfRequest) -> Path:
            raise failure

    monkeypatch.setattr(paths_module, "ImageToPdfConverter", FailingConverter)

    with pytest.raises(type(failure)) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((Path("input.jpg"),), Path("output.pdf"))
        )

    assert exc_info.value is failure


def test_one_jpg_converts_to_one_page_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    output_path = tmp_path / "output.pdf"
    write_image(input_path, (10, 20), "JPEG")

    result = convert_images_to_pdf(ImageToPdfPathRequest((input_path,), output_path))

    assert result.output_path == output_path
    assert page_sizes(output_path) == [(10, 20)]


def test_mixed_supported_images_preserve_order(tmp_path: Path) -> None:
    input_paths = (
        tmp_path / "first.jpg",
        tmp_path / "second.png",
        tmp_path / "third.bmp",
        tmp_path / "fourth.tiff",
    )
    output_path = tmp_path / "output.pdf"
    write_image(input_paths[0], (10, 20), "JPEG")
    write_image(input_paths[1], (30, 40), "PNG")
    write_image(input_paths[2], (50, 60), "BMP")
    write_image(input_paths[3], (70, 80), "TIFF")

    result = convert_images_to_pdf(ImageToPdfPathRequest(input_paths, output_path))

    assert result.input_paths is input_paths
    assert page_sizes(output_path) == [(10, 20), (30, 40), (50, 60), (70, 80)]


def test_uppercase_alias_suffixes_and_output_convert_in_order(tmp_path: Path) -> None:
    input_paths = (
        tmp_path / "FIRST.JPEG",
        tmp_path / "SECOND.PNG",
        tmp_path / "THIRD.TIF",
    )
    output_path = tmp_path / "OUTPUT.PDF"
    write_image(input_paths[0], (10, 20), "JPEG")
    write_image(input_paths[1], (30, 40), "PNG")
    write_image(input_paths[2], (50, 60), "TIFF")

    convert_images_to_pdf(ImageToPdfPathRequest(input_paths, output_path))

    assert page_sizes(output_path) == [(10, 20), (30, 40), (50, 60)]


def test_existing_output_is_replaced(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpeg"
    output_path = tmp_path / "output.Pdf"
    write_image(input_path, (10, 20), "JPEG")
    writer = PdfWriter()
    try:
        writer.add_blank_page(width=999, height=999)
        writer.write(output_path)
    finally:
        writer.close()

    convert_images_to_pdf(ImageToPdfPathRequest((input_path,), output_path))

    assert page_sizes(output_path) == [(10, 20)]


def test_malformed_supported_image_propagates_processing_error(tmp_path: Path) -> None:
    input_path = tmp_path / "malformed.jpg"
    input_path.write_bytes(b"not an image")

    with pytest.raises(ImageProcessingError):
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), tmp_path / "output.pdf")
        )


def test_content_suffix_mismatch_propagates_low_level_error(tmp_path: Path) -> None:
    input_path = tmp_path / "mismatch.jpg"
    write_image(input_path, (10, 20), "PNG")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Image format does not match its declaration: {input_path}."


def test_missing_supported_input_propagates_low_level_error(tmp_path: Path) -> None:
    input_path = tmp_path / "missing.jpg"

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input file does not exist: {input_path}."


def test_supported_suffix_directory_propagates_low_level_error(tmp_path: Path) -> None:
    input_path = tmp_path / "directory.png"
    input_path.mkdir()

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), tmp_path / "output.pdf")
        )

    assert str(exc_info.value) == f"Input path is not a file: {input_path}."


def test_resolved_duplicate_inputs_are_rejected_by_low_level_layer(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    nested = tmp_path / "nested"
    nested.mkdir()
    write_image(input_path, (10, 20), "JPEG")
    alias = nested / ".." / input_path.name

    with pytest.raises(InvalidConversionRequestError, match="resolve to the same"):
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path, alias), tmp_path / "output.pdf")
        )


def test_missing_output_parent_is_not_created(tmp_path: Path) -> None:
    input_path = tmp_path / "input.jpg"
    missing_parent = tmp_path / "missing"
    write_image(input_path, (10, 20), "JPEG")

    with pytest.raises(InvalidConversionRequestError) as exc_info:
        convert_images_to_pdf(
            ImageToPdfPathRequest((input_path,), missing_parent / "output.pdf")
        )

    assert str(exc_info.value) == (
        f"Output parent directory does not exist: {missing_parent}."
    )
    assert not missing_parent.exists()


def test_new_public_exports_and_existing_exports_remain_available() -> None:
    for package in (image_package, converters_package):
        assert package.ImageToPdfPathRequest is ImageToPdfPathRequest
        assert package.ImageToPdfPathResult is ImageToPdfPathResult
        assert package.convert_images_to_pdf is convert_images_to_pdf
        assert package.ImageInput is ImageInput
        assert package.ImageToPdfRequest is ImageToPdfRequest
        assert package.ImageToPdfConverter is ImageToPdfConverter

    assert "_IMAGE_FORMAT_BY_SUFFIX" not in image_package.__all__
    assert "_IMAGE_FORMAT_BY_SUFFIX" not in converters_package.__all__
