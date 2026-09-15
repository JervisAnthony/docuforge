"""Ordered intent and safe metadata validation for batch values."""

from dataclasses import FrozenInstanceError
from uuid import UUID

import pytest

from docuforge.batch import (
    Batch,
    BatchId,
    BatchItem,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchRequest,
    InvalidBatchDefinitionError,
)
from docuforge.jobs import OperationKey


def item(index: int, *, item_id: int | None = None, descriptor: str = " same name ") -> BatchItemRequest:
    return BatchItemRequest(UUID(int=item_id or index + 1), index, descriptor)


def request(*items: BatchItemRequest) -> BatchRequest:
    return BatchRequest(UUID(int=100), "  image.convert  ", items or (item(0), item(1), item(2)))


def test_item_request_normalizes_identity_position_and_descriptor() -> None:
    first = item(0)
    later = item(3)
    assert first.id == BatchItemId(UUID(int=1))
    assert first.position == 0
    assert later.position == 3
    assert first.descriptor == "same name"
    assert not hasattr(first, "__dict__")
    with pytest.raises(FrozenInstanceError):
        first.position = 4  # type: ignore[misc]


@pytest.mark.parametrize("position", [-1, True, False, 1.5, "0"])
def test_item_request_rejects_invalid_position(position: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError, match="position"):
        BatchItemRequest(BatchItemId.new(), position, "photo")  # type: ignore[arg-type]


@pytest.mark.parametrize("descriptor", ["", " \t ", None, 3])
def test_item_request_rejects_invalid_descriptor(descriptor: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError, match="descriptor"):
        BatchItemRequest(BatchItemId.new(), 0, descriptor)  # type: ignore[arg-type]


def test_batch_request_reuses_operation_key_and_preserves_duplicate_descriptors() -> None:
    ordered = request()
    assert ordered.id == BatchId(UUID(int=100))
    assert isinstance(ordered.operation, OperationKey)
    assert ordered.operation == "image.convert"
    assert [item.position for item in ordered.items] == [0, 1, 2]
    assert [item.descriptor for item in ordered.items] == ["same name"] * 3
    assert not hasattr(ordered, "__dict__")
    with pytest.raises(FrozenInstanceError):
        ordered.items = ()  # type: ignore[misc]


@pytest.mark.parametrize("items", [(), [], (item(0), "wrong")])
def test_batch_request_requires_nonempty_item_request_tuple(items: object) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchRequest(BatchId.new(), "image.convert", items)  # type: ignore[arg-type]


@pytest.mark.parametrize("items", [
    (item(0, item_id=1), item(1, item_id=1)),
    (item(0), item(0, item_id=2)),
    (item(0), item(2)),
    (item(1, item_id=1), item(2, item_id=2)),
    (item(0), item(2), item(1)),
])
def test_batch_request_rejects_duplicate_ids_or_noncontiguous_tuple_order(
    items: tuple[BatchItemRequest, ...],
) -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchRequest(BatchId.new(), "image.convert", items)


def test_batch_request_rejects_invalid_operation_as_batch_error() -> None:
    with pytest.raises(InvalidBatchDefinitionError, match="operation"):
        BatchRequest(BatchId.new(), "  ", (item(0),))


def test_result_and_failure_values_are_trimmed_frozen_and_slotted() -> None:
    result = BatchItemResult("  converted  ")
    failure = BatchItemFailure("  invalid_input  ", "  Unsupported image.  ")
    assert result.descriptor == "converted"
    assert failure.code == "invalid_input"
    assert failure.message == "Unsupported image."
    assert not hasattr(result, "__dict__") and not hasattr(failure, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.descriptor = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        failure.code = "changed"  # type: ignore[misc]


@pytest.mark.parametrize("value", ["", " \t ", None, 3])
def test_result_and_failure_reject_blank_or_nonstring_metadata(value: object) -> None:
    for create in (
        lambda: BatchItemResult(value),
        lambda: BatchItemFailure(value, "message"),
        lambda: BatchItemFailure("code", value),
    ):
        with pytest.raises(InvalidBatchDefinitionError):
            create()  # type: ignore[arg-type]


def test_snapshots_require_valid_requests() -> None:
    with pytest.raises(InvalidBatchDefinitionError):
        BatchItem("wrong")  # type: ignore[arg-type]
    with pytest.raises(InvalidBatchDefinitionError):
        Batch("wrong")  # type: ignore[arg-type]
