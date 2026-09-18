"""Cooperative progress, cancellation, and selective recovery workflow coverage."""

from pathlib import Path

import pytest

from docuforge.batch import (
    BatchCancellationToken,
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchItemStatus,
    BatchStatus,
    InvalidBatchDefinitionError,
    batch_convert_documents,
    batch_convert_images,
)
from docuforge.core import DocumentFormat
from tests.batch.test_document import RecordingEngine, write_office
from tests.batch.test_image_processing import write_image


def test_image_progress_and_cancellation_before_first_item(tmp_path: Path) -> None:
    sources = (tmp_path / "one.png", tmp_path / "two.png")
    for source in sources:
        write_image(source)
    output = tmp_path / "output"
    output.mkdir()
    token = BatchCancellationToken()
    token.request_cancellation()
    snapshots = []
    result = batch_convert_images(
        BatchImageConvertRequest(tuple(map(BatchImageInput, sources)), output, "jpg"),
        cancellation=token,
        on_progress=snapshots.append,
    )
    assert [snapshot.status for snapshot in snapshots] == [
        BatchStatus.PENDING,
        BatchStatus.CANCELLED,
    ]
    assert result.batch.status is BatchStatus.CANCELLED
    assert result.outputs == ()
    assert all(item.status is BatchItemStatus.CANCELLED for item in result.batch.items)


def test_image_running_item_finishes_then_remaining_items_cancel(tmp_path: Path) -> None:
    sources = tuple(tmp_path / f"{name}.png" for name in ("one", "two", "three"))
    for source in sources:
        write_image(source)
    output = tmp_path / "output"
    output.mkdir()
    token = BatchCancellationToken()
    snapshots = []

    def observe(batch: object) -> None:
        snapshots.append(batch)
        if batch.completed_count == 1:  # type: ignore[attr-defined]
            token.request_cancellation()

    result = batch_convert_images(
        BatchImageConvertRequest(tuple(map(BatchImageInput, sources)), output, "webp"),
        cancellation=token,
        on_progress=observe,
    )
    assert [item.status for item in result.batch.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.CANCELLED,
        BatchItemStatus.CANCELLED,
    ]
    assert result.batch.status is BatchStatus.PARTIAL
    assert [entry.position for entry in result.outputs] == [0]
    assert any(snapshot.running_count == 1 for snapshot in snapshots)
    assert snapshots[-1].summary.progress_percent == 100


def test_image_recovery_retries_only_failed_item_and_restores_order(tmp_path: Path) -> None:
    missing = tmp_path / "first.png"
    second = tmp_path / "second.png"
    write_image(second)
    output = tmp_path / "output"
    output.mkdir()
    items = (BatchImageInput(missing), BatchImageInput(second))
    request = BatchImageConvertRequest(items, output, DocumentFormat.JPG)
    first = batch_convert_images(request)
    preserved = first.outputs[0].output_path.read_bytes()
    assert first.outputs[0].position == 1
    write_image(missing)
    recovered = batch_convert_images(request, recover_from=first)
    assert recovered.batch.status is BatchStatus.COMPLETED
    assert [entry.position for entry in recovered.outputs] == [0, 1]
    assert recovered.outputs[1] is first.outputs[0]
    assert recovered.outputs[1].output_path.read_bytes() == preserved
    assert first.batch.status is BatchStatus.PARTIAL


def test_image_recovery_rejects_mismatch_or_untrusted_preserved_output(tmp_path: Path) -> None:
    missing = tmp_path / "missing.png"
    good = tmp_path / "good.png"
    write_image(good)
    output = tmp_path / "output"
    output.mkdir()
    request = BatchImageConvertRequest(
        (BatchImageInput(missing), BatchImageInput(good)), output, "png"
    )
    result = batch_convert_images(request)
    with pytest.raises(InvalidBatchDefinitionError):
        batch_convert_images(
            BatchImageConvertRequest(request.items, output, "png"), recover_from=result
        )
    result.outputs[0].output_path.unlink()
    with pytest.raises(InvalidBatchDefinitionError, match="not trustworthy"):
        batch_convert_images(request, recover_from=result)


def test_document_cancellation_and_selective_recovery(tmp_path: Path) -> None:
    first = tmp_path / "first.docx"
    second = tmp_path / "second.pptx"
    write_office(first)
    output = tmp_path / "output"
    output.mkdir()
    items = (BatchDocumentInput(first), BatchDocumentInput(second))
    request = BatchDocumentConvertRequest(items, output)
    token = BatchCancellationToken()

    def cancel_after_first(batch: object) -> None:
        if batch.completed_count == 1:  # type: ignore[attr-defined]
            token.request_cancellation()

    initial = batch_convert_documents(
        request,
        engine=RecordingEngine(),
        cancellation=token,
        on_progress=cancel_after_first,
    )
    assert [item.status for item in initial.batch.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.CANCELLED,
    ]
    write_office(second)
    engine = RecordingEngine()
    recovered = batch_convert_documents(request, engine=engine, recover_from=initial)
    assert recovered.batch.status is BatchStatus.COMPLETED
    assert [entry.position for entry in recovered.outputs] == [0, 1]
    assert [call.input_path for call in engine.requests] == [second]


def test_progress_observer_programming_error_propagates_and_cleans_workspace(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.png"
    write_image(source)
    output = tmp_path / "output"
    output.mkdir()

    def broken_observer(_batch: object) -> None:
        raise RuntimeError("observer bug")

    with pytest.raises(RuntimeError, match="observer bug"):
        batch_convert_images(
            BatchImageConvertRequest((BatchImageInput(source),), output, "png"),
            on_progress=broken_observer,
        )
    assert list(output.glob(".docuforge-batch-images-*")) == []
