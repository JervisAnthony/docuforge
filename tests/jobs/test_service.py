"""Behavior tests for the job application service."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta

import pytest

from docuforge.jobs import (
    InMemoryJobRepository,
    InvalidJobTransitionError,
    JobFailure,
    JobManager,
    JobNotFoundError,
    JobResult,
    JobStatus,
)

CREATED_AT = datetime(2026, 9, 11, 10, 0, tzinfo=UTC)


def clock_returning(*values: datetime) -> Callable[[], datetime]:
    remaining: Iterator[datetime] = iter(values)
    return lambda: next(remaining)


def test_manager_creates_and_retrieves_a_job() -> None:
    manager = JobManager(InMemoryJobRepository(), clock=clock_returning(CREATED_AT))

    created = manager.create_job("test.operation", payload_descriptor="safe input metadata")

    assert created.status is JobStatus.PENDING
    assert created.created_at == CREATED_AT
    assert created.request.payload_descriptor == "safe input metadata"
    assert manager.get_job(created.id) is created


def test_manager_drives_a_successful_lifecycle_and_persists_each_state() -> None:
    started_at = CREATED_AT + timedelta(seconds=1)
    finished_at = started_at + timedelta(seconds=1)
    manager = JobManager(
        InMemoryJobRepository(),
        clock=clock_returning(CREATED_AT, started_at, finished_at),
    )
    pending = manager.create_job("test.operation")

    running = manager.start_job(pending.id)
    completed = manager.complete_job(pending.id, JobResult("downloadable artifact"))

    assert running.status is JobStatus.RUNNING
    assert completed.status is JobStatus.COMPLETED
    assert completed.started_at == started_at
    assert completed.finished_at == finished_at
    assert manager.get_job(pending.id) is completed


def test_manager_can_record_a_pre_execution_failure() -> None:
    failed_at = CREATED_AT + timedelta(seconds=1)
    manager = JobManager(
        InMemoryJobRepository(),
        clock=clock_returning(CREATED_AT, failed_at),
    )
    pending = manager.create_job("test.operation")

    failed = manager.fail_job(
        pending.id,
        JobFailure(code="invalid_input", message="The input is not supported."),
    )

    assert failed.status is JobStatus.FAILED
    assert manager.get_job(pending.id).failure == failed.failure


def test_manager_propagates_unknown_job_errors() -> None:
    manager = JobManager(InMemoryJobRepository())

    with pytest.raises(JobNotFoundError):
        manager.start_job("1f7dca2c-67af-4f81-a989-625cb9d77680")


def test_manager_propagates_invalid_transition_errors() -> None:
    started_at = CREATED_AT + timedelta(seconds=1)
    manager = JobManager(
        InMemoryJobRepository(),
        clock=clock_returning(CREATED_AT, started_at, started_at),
    )
    job = manager.create_job("test.operation")
    manager.start_job(job.id)

    with pytest.raises(InvalidJobTransitionError):
        manager.start_job(job.id)
