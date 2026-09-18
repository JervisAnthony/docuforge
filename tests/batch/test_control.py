"""Cancellation, recovery, progress, and terminalization domain coverage."""

from dataclasses import FrozenInstanceError

import pytest

from docuforge.batch import (
    Batch,
    BatchCancellationToken,
    BatchItemFailure,
    BatchItemResult,
    BatchItemStatus,
    BatchStatus,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from tests.batch.test_models import item, request

RESULT = BatchItemResult("output.png")
FAILURE = BatchItemFailure("failed", "The item failed.")


def make_batch(count: int = 3) -> Batch:
    return Batch(request(*(item(index) for index in range(count))))


def test_cancellation_token_is_thread_safe_one_shot_state() -> None:
    token = BatchCancellationToken()
    assert token.cancellation_requested is False
    token.request_cancellation()
    token.request_cancellation()
    assert token.cancellation_requested is True
    assert not hasattr(token, "__dict__")


def test_item_cancel_and_recover_are_immutable_validated_transitions() -> None:
    pending = make_batch(1).items[0]
    cancelled = pending.cancel()
    failed = pending.fail(FAILURE)
    recovered_cancelled = cancelled.recover()
    recovered_failed = failed.recover()
    assert cancelled.status is BatchItemStatus.CANCELLED
    assert cancelled.result is cancelled.failure is None
    assert recovered_cancelled.status is recovered_failed.status is BatchItemStatus.PENDING
    assert recovered_failed.result is recovered_failed.failure is None
    assert recovered_failed.id == pending.id and recovered_failed.position == pending.position
    assert pending.status is BatchItemStatus.PENDING
    with pytest.raises(FrozenInstanceError):
        cancelled.status = BatchItemStatus.PENDING  # type: ignore[misc]
    for terminal in (
        pending.start().complete(RESULT),
        failed,
        cancelled,
    ):
        with pytest.raises(InvalidBatchTransitionError):
            terminal.cancel()
    for unrecoverable in (pending, pending.start(), pending.start().complete(RESULT)):
        with pytest.raises(InvalidBatchTransitionError):
            unrecoverable.recover()


def test_cancel_pending_items_preserves_order_identity_and_other_outcomes() -> None:
    base = make_batch(4)
    first, second, third, fourth = (entry.id for entry in base.items)
    mixed = base.start_item(first).complete_item(first, RESULT)
    mixed = mixed.fail_item(second, FAILURE).start_item(third)
    cancelled = mixed.cancel_pending_items()
    assert [entry.id for entry in cancelled.items] == [first, second, third, fourth]
    assert [entry.status for entry in cancelled.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.FAILED,
        BatchItemStatus.RUNNING,
        BatchItemStatus.CANCELLED,
    ]
    assert cancelled.items[:3] == mixed.items[:3]
    assert cancelled.request is base.request


def test_summary_counts_cancelled_items_and_derives_integer_progress() -> None:
    base = make_batch(3)
    first, second, _third = (entry.id for entry in base.items)
    assert base.summary.progress_percent == 0
    one = base.cancel_item(first)
    assert one.summary.progress_percent == 33
    assert one.processed_count == 1 and one.remaining_count == 2
    two = one.cancel_item(second)
    assert two.summary.progress_percent == 66
    all_cancelled = two.cancel_pending_items()
    assert all_cancelled.status is BatchStatus.CANCELLED
    assert all_cancelled.cancelled_count == 3
    assert all_cancelled.summary.progress_percent == 100
    assert all_cancelled.is_terminal


def test_mixed_cancelled_terminal_outcomes_are_partial() -> None:
    base = make_batch(2)
    first, second = (entry.id for entry in base.items)
    completed = base.start_item(first).complete_item(first, RESULT).cancel_item(second)
    failed = base.fail_item(first, FAILURE).cancel_item(second)
    assert completed.status is failed.status is BatchStatus.PARTIAL
    assert completed.summary.progress_percent == failed.summary.progress_percent == 100


def test_recover_items_preserves_completed_outputs_and_prior_snapshot() -> None:
    base = make_batch(3)
    first, second, third = (entry.id for entry in base.items)
    terminal = base.start_item(first).complete_item(first, RESULT)
    terminal = terminal.fail_item(second, FAILURE).cancel_item(third)
    recovered = terminal.recover_items()
    assert recovered.request is terminal.request
    assert [entry.id for entry in recovered.items] == [first, second, third]
    assert [entry.status for entry in recovered.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.PENDING,
        BatchItemStatus.PENDING,
    ]
    assert recovered.items[0] is terminal.items[0]
    assert recovered.items[1].failure is None and recovered.items[2].result is None
    assert terminal.is_terminal and terminal.items[1].failure is FAILURE
    with pytest.raises(InvalidBatchTransitionError):
        base.recover_items()
    completed = base
    for entry in base.items:
        completed = completed.start_item(entry.id).complete_item(entry.id, RESULT)
    with pytest.raises(InvalidBatchTransitionError):
        completed.recover_items()


def test_fail_nonterminal_items_preserves_terminal_items() -> None:
    base = make_batch(4)
    first, second, third, fourth = (entry.id for entry in base.items)
    mixed = base.start_item(first).complete_item(first, RESULT)
    mixed = mixed.fail_item(second, FAILURE).cancel_item(third).start_item(fourth)
    terminal = mixed.fail_nonterminal_items(
        BatchItemFailure("batch_execution_failed", "The batch could not be completed.")
    )
    assert [entry.status for entry in terminal.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.FAILED,
        BatchItemStatus.CANCELLED,
        BatchItemStatus.FAILED,
    ]
    assert terminal.status is BatchStatus.PARTIAL
    with pytest.raises(InvalidBatchDefinitionError):
        mixed.fail_nonterminal_items("failure")  # type: ignore[arg-type]
