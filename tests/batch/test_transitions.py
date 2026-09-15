"""Immutable item transitions, aggregate status, exact counts, and lookup."""

from dataclasses import FrozenInstanceError, replace
from uuid import UUID

import pytest

from docuforge.batch import (
    Batch,
    BatchItem,
    BatchItemFailure,
    BatchItemId,
    BatchItemNotFoundError,
    BatchItemResult,
    BatchItemStatus,
    BatchStatus,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from tests.batch.test_models import item, request

RESULT = BatchItemResult("converted")
FAILURE = BatchItemFailure("failed", "Could not process the item.")


def make_batch(count: int = 3) -> Batch:
    return Batch(request(*(item(index) for index in range(count))))


def assert_counts(batch: Batch, expected: tuple[int, int, int, int]) -> None:
    pending, running, completed, failed = expected
    summary = batch.summary
    assert summary.total_count == batch.total_count == sum(expected)
    assert summary.pending_count == batch.pending_count == pending
    assert summary.running_count == batch.running_count == running
    assert summary.completed_count == batch.completed_count == completed
    assert summary.failed_count == batch.failed_count == failed
    assert summary.processed_count == batch.processed_count == completed + failed
    assert summary.remaining_count == batch.remaining_count == pending + running
    assert summary.processed_count + summary.remaining_count == summary.total_count


def test_item_snapshot_lifecycle_is_immutable_and_carries_one_outcome() -> None:
    pending = BatchItem(item(0))
    running = pending.start()
    completed = running.complete(RESULT)
    prefailed = pending.fail(FAILURE)
    failed = running.fail(FAILURE)
    assert pending.status is BatchItemStatus.PENDING
    assert pending.result is pending.failure is None
    assert running.status is BatchItemStatus.RUNNING
    assert running.result is running.failure is None
    assert completed.status is BatchItemStatus.COMPLETED
    assert completed.result is RESULT and completed.failure is None
    assert prefailed.status is failed.status is BatchItemStatus.FAILED
    assert prefailed.failure is failed.failure is FAILURE
    assert failed.result is None
    assert [snapshot.id for snapshot in (pending, running, completed, failed)] == [pending.id] * 4
    assert pending.position == 0 and pending.descriptor == "same name"
    assert not hasattr(completed, "__dict__")
    with pytest.raises(FrozenInstanceError):
        completed.status = BatchItemStatus.RUNNING  # type: ignore[misc]


def test_invalid_item_transitions_and_outcome_types_raise_structured_errors() -> None:
    pending = BatchItem(item(0))
    running = pending.start()
    completed = running.complete(RESULT)
    failed = pending.fail(FAILURE)
    for snapshot, method, args in (
        (pending, "complete", (RESULT,)),
        (running, "start", ()),
        (completed, "start", ()), (completed, "complete", (RESULT,)),
        (completed, "fail", (FAILURE,)),
        (failed, "start", ()), (failed, "complete", (RESULT,)),
        (failed, "fail", (FAILURE,)),
    ):
        with pytest.raises(InvalidBatchTransitionError):
            getattr(snapshot, method)(*args)
    with pytest.raises(InvalidBatchDefinitionError):
        running.complete("raw")  # type: ignore[arg-type]
    with pytest.raises(InvalidBatchDefinitionError):
        pending.fail("raw")  # type: ignore[arg-type]
    assert pending.status is BatchItemStatus.PENDING
    assert running.status is BatchItemStatus.RUNNING


def test_initial_batch_preserves_order_and_exact_pending_counts() -> None:
    batch = make_batch()
    assert [entry.id for entry in batch.items] == [entry.id for entry in batch.request.items]
    assert batch.status is BatchStatus.PENDING
    assert_counts(batch, (3, 0, 0, 0))
    assert batch.is_terminal is False
    assert not hasattr(batch, "__dict__")
    with pytest.raises(FrozenInstanceError):
        batch.items = ()  # type: ignore[misc]


def test_batch_aggregate_states_are_derived_from_item_snapshots() -> None:
    base = make_batch()
    ids = [entry.id for entry in base.items]
    one_running = base.start_item(ids[0])
    two_running = one_running.start_item(ids[1])
    one_completed = one_running.complete_item(ids[0], RESULT)
    one_failed = base.fail_item(ids[0], FAILURE)
    mixed_with_pending = one_completed.fail_item(ids[1], FAILURE)
    mixed_with_running = mixed_with_pending.start_item(ids[2])
    all_completed = one_completed.start_item(ids[1]).complete_item(ids[1], RESULT).start_item(ids[2]).complete_item(ids[2], RESULT)
    all_failed = one_failed.fail_item(ids[1], FAILURE).fail_item(ids[2], FAILURE)
    partial = mixed_with_pending.fail_item(ids[2], FAILURE)
    for snapshot in (
        one_running, two_running, one_completed, one_failed,
        mixed_with_pending, mixed_with_running,
    ):
        assert snapshot.status is BatchStatus.RUNNING
        assert snapshot.is_terminal is False
    assert all_completed.status is BatchStatus.COMPLETED
    assert all_failed.status is BatchStatus.FAILED
    assert partial.status is BatchStatus.PARTIAL
    assert all(snapshot.is_terminal for snapshot in (all_completed, all_failed, partial))
    assert_counts(two_running, (1, 2, 0, 0))
    assert_counts(mixed_with_pending, (1, 0, 1, 1))
    assert_counts(mixed_with_running, (0, 1, 1, 1))
    assert_counts(all_completed, (0, 0, 3, 0))
    assert_counts(all_failed, (0, 0, 0, 3))
    assert_counts(partial, (0, 0, 1, 2))
    assert base.status is BatchStatus.PENDING


def test_batch_transitions_replace_only_one_item_and_keep_old_summaries() -> None:
    base = make_batch()
    first, second, third = (entry.id for entry in base.items)
    old_summary = base.summary
    running = base.start_item(second)
    completed = running.complete_item(second, RESULT)
    failed = completed.fail_item(first, FAILURE)
    assert base.items[1].status is BatchItemStatus.PENDING
    assert running.items[1].status is BatchItemStatus.RUNNING
    assert completed.items[1].status is BatchItemStatus.COMPLETED
    assert failed.items[0].status is BatchItemStatus.FAILED
    assert failed.items[2] is base.items[2]
    assert failed.request is base.request
    assert failed.id == base.id and failed.operation == base.operation
    assert [entry.id for entry in failed.items] == [first, second, third]
    assert old_summary.status is BatchStatus.PENDING
    assert base.summary == old_summary and base.summary is not old_summary
    assert_counts(failed, (1, 0, 1, 1))


def test_lookup_uses_stable_identity_even_with_duplicate_descriptors() -> None:
    batch = make_batch()
    for index, entry in enumerate(batch.items):
        assert batch.get_item(entry.id) is entry
        assert batch.get_item(str(entry.id).upper()) is entry
        assert entry.position == index
    with pytest.raises(BatchItemNotFoundError):
        batch.get_item(BatchItemId(UUID(int=999)))
    with pytest.raises(InvalidBatchDefinitionError):
        batch.get_item("invalid")


def test_summary_rejects_invalid_counts_and_status() -> None:
    summary = make_batch().summary
    assert not hasattr(summary, "__dict__")
    with pytest.raises(FrozenInstanceError):
        summary.total_count = 2  # type: ignore[misc]
    for changes in (
        {"total_count": 0}, {"pending_count": -1}, {"pending_count": True},
        {"processed_count": 1}, {"remaining_count": 2},
        {"status": BatchStatus.COMPLETED}, {"status": "pending"},
    ):
        with pytest.raises(InvalidBatchDefinitionError):
            replace(summary, **changes)
