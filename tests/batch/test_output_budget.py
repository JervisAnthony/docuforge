"""Exact publication accounting across converters and selective recovery."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

import docuforge.batch.document as document_module
import docuforge.batch.image as image_module
from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageResizeRequest,
    BatchItemStatus,
    InvalidBatchDefinitionError,
    batch_compress_images,
    batch_convert_documents,
    batch_convert_images,
    batch_resize_images,
)
from docuforge.batch.output_budget import PublishedOutputBudget
from tests.batch.test_document import RecordingEngine, write_office


def image_request(tmp_path, widths=(1, 2, 1)):
    items = []
    for i, width in enumerate(widths):
        source = tmp_path / f"{i}.png"
        Image.new("RGB", (width, 1), "blue").save(source)
        items.append(BatchImageInput(source))
    output = tmp_path / "out"
    output.mkdir()
    return BatchImageConvertRequest(tuple(items), output, "bmp")


def states(result):
    return [item.status for item in result.batch.items]


C = BatchItemStatus.COMPLETED
F = BatchItemStatus.FAILED


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "100"])
def test_optional_limit_validation(tmp_path, value):
    request = image_request(tmp_path)
    with pytest.raises(InvalidBatchDefinitionError):
        batch_convert_images(request, max_published_output_bytes=value)
    with pytest.raises(InvalidBatchDefinitionError):
        PublishedOutputBudget(value)


@pytest.mark.parametrize("limit,expected", [(116, [C, F, C]), (115, [C, F, F]), (58, [C, F, F])])
def test_image_cumulative_exact_and_one_byte_over(tmp_path, limit, expected):
    # BMP sizes are 58, 62, 58 bytes: valid raster artifacts, measured from disk.
    request = image_request(tmp_path)
    with patch.object(image_module.os, "replace", wraps=os.replace) as publish:
        result = batch_convert_images(request, max_published_output_bytes=limit)
    assert states(result) == expected
    assert sum(
        Path(call.args[1]).parent == request.output_directory for call in publish.call_args_list
    ) == expected.count(C)
    assert sum(o.output_path.lstat().st_size for o in result.outputs) <= limit
    assert len(list(request.output_directory.iterdir())) == len(result.outputs)
    for item in result.batch.items:
        if item.status is F:
            assert item.failure.code == "batch_output_limit_exceeded"
            assert item.failure.message == "The batch output limit was exceeded."


def test_oversized_first_then_smaller_and_unlimited_default(tmp_path):
    request = image_request(tmp_path, (20, 1))
    result = batch_convert_images(request, max_published_output_bytes=100)
    assert states(result) == [F, C]
    recovered = batch_convert_images(request, recover_from=result)
    assert states(recovered) == [C, C]


@pytest.mark.parametrize("operation", ["resize", "compress"])
def test_other_image_operations(tmp_path, operation):
    request = image_request(tmp_path, (1,))
    if operation == "resize":
        request = BatchImageResizeRequest(
            request.items, request.output_directory, "bmp", max_width=1
        )
        convert = batch_resize_images
    else:
        request = BatchImageCompressRequest(
            request.items, request.output_directory, "jpg", quality=80
        )
        convert = batch_compress_images
    result = convert(request, max_published_output_bytes=1)
    assert states(result) == [F]
    assert not list(request.output_directory.iterdir())


@pytest.mark.parametrize("failure", ["publish", "inspection", "invalid"])
def test_failure_consumes_zero_budget(tmp_path, failure):
    request = image_request(tmp_path, (1, 1))
    real_replace = os.replace
    if failure == "publish":

        def replace(source, target):
            if target.name.startswith("0001"):
                raise OSError("private")
            return real_replace(source, target)

        seam = patch.object(image_module.os, "replace", side_effect=replace)
    elif failure == "inspection":
        real_size = PublishedOutputBudget.candidate_size

        def size(self, path):
            if path.name.startswith("0001"):
                raise OSError("private")
            return real_size(self, path)

        seam = patch.object(PublishedOutputBudget, "candidate_size", size)
    else:
        real_validate = image_module._valid_staged_result

        def validate(*args, **kwargs):
            return not kwargs["staged_output"].name.startswith("0001") and real_validate(
                *args, **kwargs
            )

        seam = patch.object(image_module, "_valid_staged_result", side_effect=validate)
    with seam:
        result = batch_convert_images(request, max_published_output_bytes=58)
    assert states(result) == [F, C]
    assert len(list(request.output_directory.iterdir())) == 1


@pytest.mark.parametrize("limit,expected", [(116, [C, F, C]), (1, [C, F, F]), (178, [C, C, C])])
def test_recovery_counts_preserved_actual_sizes(tmp_path, limit, expected):
    request = image_request(tmp_path)
    previous = batch_convert_images(request, max_published_output_bytes=58)
    preserved = previous.outputs[0].output_path
    original = preserved.read_bytes()
    with patch.object(
        image_module, "convert_image_path", wraps=image_module.convert_image_path
    ) as convert:
        recovered = batch_convert_images(
            request, recover_from=previous, max_published_output_bytes=limit
        )
    assert convert.call_count == 2
    assert states(recovered) == expected
    assert preserved.read_bytes() == original


class SizedEngine(RecordingEngine):
    def convert_to_pdf(self, request):
        result = super().convert_to_pdf(request)
        size = int(request.input_path.stem)
        result.output_path.write_bytes(b"%PDF-" + b"x" * (size - 5))
        return result


def document_request(tmp_path, sizes):
    items = []
    for i, size in enumerate(sizes):
        directory = tmp_path / str(i)
        directory.mkdir()
        source = directory / f"{size}.docx"
        write_office(source)
        items.append(BatchDocumentInput(source))
    output = tmp_path / "out"
    output.mkdir()
    return BatchDocumentConvertRequest(tuple(items), output)


@pytest.mark.parametrize(
    "limit,expected", [(100, [C, F, C]), (90, [C, F, C]), (89, [C, F, F]), (1, [F, F, F])]
)
def test_document_cumulative_boundary(tmp_path, limit, expected):
    request = document_request(tmp_path, (60, 50, 30))
    with patch.object(document_module.os, "replace", wraps=os.replace) as publish:
        result = batch_convert_documents(
            request, engine=SizedEngine(), max_published_output_bytes=limit
        )
    assert states(result) == expected
    assert sum(
        Path(call.args[1]).parent == request.output_directory for call in publish.call_args_list
    ) == expected.count(C)
    assert len(list(request.output_directory.iterdir())) == len(result.outputs)


@pytest.mark.parametrize("limit,expected", [(100, [C, F]), (110, [C, C]), (1, [C, F])])
def test_document_preserved_recovery(tmp_path, limit, expected):
    request = document_request(tmp_path, (70, 40))
    previous = batch_convert_documents(
        request, engine=SizedEngine(), max_published_output_bytes=100
    )
    engine = SizedEngine()
    result = batch_convert_documents(
        request, engine=engine, recover_from=previous, max_published_output_bytes=limit
    )
    assert states(result) == expected
    assert len(engine.requests) == 1
    assert previous.outputs[0].output_path.lstat().st_size == 70


@pytest.mark.parametrize(
    "convert,request_type",
    [
        (batch_resize_images, BatchImageResizeRequest),
        (batch_compress_images, BatchImageCompressRequest),
        (batch_convert_documents, BatchDocumentConvertRequest),
    ],
)
@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "100"])
def test_all_function_arguments_validate(tmp_path, convert, request_type, value):
    if request_type is BatchDocumentConvertRequest:
        request = document_request(tmp_path, (60,))
        kwargs = {"engine": SizedEngine()}
    else:
        base = image_request(tmp_path, (1,))
        kwargs = {}
        request = request_type(
            base.items,
            base.output_directory,
            "jpg",
            **({"max_width": 1} if request_type is BatchImageResizeRequest else {"quality": 80}),
        )
    with pytest.raises(InvalidBatchDefinitionError):
        convert(request, max_published_output_bytes=value, **kwargs)


def test_shared_utility_uses_actual_file_and_rejects_nonregular(tmp_path):
    path = tmp_path / "artifact"
    path.write_bytes(b"x" * 70)
    budget = PublishedOutputBudget(100)
    budget.track_existing(path)
    assert budget.can_publish(30)
    assert not budget.can_publish(31)
    with pytest.raises(OSError):
        budget.candidate_size(tmp_path)
    with pytest.raises(OSError):
        budget.candidate_size(tmp_path / "missing")
