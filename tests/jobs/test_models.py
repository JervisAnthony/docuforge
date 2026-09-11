"""Behavior tests for the job lifecycle domain."""

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from docuforge.jobs import (
    InvalidJobDefinitionError,
    InvalidJobTransitionError,
    Job,
    JobFailure,
    JobId,
    JobRequest,
    JobResult,
    JobStatus,
    OperationKey,
)

CREATED_AT = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)
STARTED_AT = CREATED_AT + timedelta(seconds=1)
FINISHED_AT = STARTED_AT + timedelta(seconds=2)


def make_job() -> Job:
    return Job(
        JobRequest(
            id=JobId.new(),
            operation=OperationKey("test.operation"),
            created_at=CREATED_AT,
            payload_descriptor="two non-sensitive inputs",
        )
    )


def test_job_ids_are_unique_and_string_serializable() -> None:
    first = JobId.new()
    second = JobId.new()

    assert first != second
    assert JobId(str(first)) == first
    assert json.loads(json.dumps({"job_id": first})) == {"job_id": str(first)}


def test_new_job_is_an_immutable_pending_snapshot() -> None:
    job = make_job()

    assert job.status is JobStatus.PENDING
    assert job.created_at == CREATED_AT
    assert job.created_at.tzinfo is UTC
    assert job.started_at is None
    assert job.finished_at is None
    assert job.result is None
    assert job.failure is None

    with pytest.raises(FrozenInstanceError):
        job.status = JobStatus.RUNNING  # type: ignore[misc]


def test_pending_job_can_start() -> None:
    pending = make_job()

    running = pending.start(at=STARTED_AT)

    assert pending.status is JobStatus.PENDING
    assert running.status is JobStatus.RUNNING
    assert running.started_at == STARTED_AT
    assert running.finished_at is None


def test_running_job_can_complete_with_a_result() -> None:
    running = make_job().start(at=STARTED_AT)
    result = JobResult(descriptor="one downloadable artifact")

    completed = running.complete(result, at=FINISHED_AT)

    assert completed.status is JobStatus.COMPLETED
    assert completed.started_at == STARTED_AT
    assert completed.finished_at == FINISHED_AT
    assert completed.result is result
    assert completed.failure is None


def test_running_job_can_fail_with_safe_failure_information() -> None:
    running = make_job().start(at=STARTED_AT)
    failure = JobFailure(code="processing_failed", message="The document could not be processed.")

    failed = running.fail(failure, at=FINISHED_AT)

    assert failed.status is JobStatus.FAILED
    assert failed.started_at == STARTED_AT
    assert failed.finished_at == FINISHED_AT
    assert failed.failure is failure
    assert failed.result is None


def test_pending_job_can_fail_before_execution() -> None:
    failure = JobFailure(code="invalid_input", message="The input is not supported.")

    failed = make_job().fail(failure, at=STARTED_AT)

    assert failed.status is JobStatus.FAILED
    assert failed.started_at is None
    assert failed.finished_at == STARTED_AT


def test_pending_job_cannot_complete_directly() -> None:
    with pytest.raises(InvalidJobTransitionError):
        make_job().complete(JobResult("result"), at=FINISHED_AT)


@pytest.mark.parametrize("terminal_status", [JobStatus.COMPLETED, JobStatus.FAILED])
def test_terminal_job_cannot_transition_again(terminal_status: JobStatus) -> None:
    running = make_job().start(at=STARTED_AT)
    terminal = (
        running.complete(JobResult("result"), at=FINISHED_AT)
        if terminal_status is JobStatus.COMPLETED
        else running.fail(JobFailure("failed", "Processing failed."), at=FINISHED_AT)
    )
    later = FINISHED_AT + timedelta(seconds=1)

    with pytest.raises(InvalidJobTransitionError):
        terminal.start(at=later)
    with pytest.raises(InvalidJobTransitionError):
        terminal.complete(JobResult("another result"), at=later)
    with pytest.raises(InvalidJobTransitionError):
        terminal.fail(JobFailure("failed_again", "Processing failed again."), at=later)


def test_repeated_start_is_rejected() -> None:
    running = make_job().start(at=STARTED_AT)

    with pytest.raises(InvalidJobTransitionError):
        running.start(at=FINISHED_AT)


def test_lifecycle_timestamps_are_normalized_to_utc_and_ordered() -> None:
    non_utc_start = STARTED_AT.astimezone(timezone(timedelta(hours=5, minutes=30)))
    running = make_job().start(at=non_utc_start)

    assert running.started_at == STARTED_AT
    assert running.started_at is not None
    assert running.started_at.tzinfo is UTC

    with pytest.raises(InvalidJobDefinitionError):
        running.complete(JobResult("result"), at=CREATED_AT)


def test_naive_creation_timestamp_is_rejected() -> None:
    with pytest.raises(InvalidJobDefinitionError):
        JobRequest(
            id=JobId.new(),
            operation=OperationKey("test.operation"),
            created_at=CREATED_AT.replace(tzinfo=None),
        )
