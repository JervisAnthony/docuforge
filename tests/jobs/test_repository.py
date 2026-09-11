"""Behavior tests for process-local job storage."""

from datetime import UTC, datetime

import pytest

from docuforge.jobs import (
    DuplicateJobError,
    InMemoryJobRepository,
    Job,
    JobId,
    JobNotFoundError,
    JobRequest,
    JobStatus,
    OperationKey,
)


def make_job(*, job_id: JobId | None = None) -> Job:
    return Job(
        JobRequest(
            id=job_id or JobId.new(),
            operation=OperationKey("test.operation"),
            created_at=datetime(2026, 9, 11, tzinfo=UTC),
        )
    )


def test_repository_adds_and_retrieves_a_job() -> None:
    repository = InMemoryJobRepository()
    job = make_job()

    repository.add(job)

    assert repository.get(job.id) is job
    assert repository.get(str(job.id)) is job


def test_repository_rejects_duplicate_job_ids() -> None:
    repository = InMemoryJobRepository()
    job_id = JobId.new()
    repository.add(make_job(job_id=job_id))

    with pytest.raises(DuplicateJobError):
        repository.add(make_job(job_id=job_id))


def test_repository_reports_an_unknown_job_id() -> None:
    repository = InMemoryJobRepository()

    with pytest.raises(JobNotFoundError):
        repository.get(JobId.new())


def test_repository_saves_an_updated_job_snapshot() -> None:
    repository = InMemoryJobRepository()
    job = make_job()
    repository.add(job)

    running = job.start(at=job.created_at)
    repository.save(running)

    assert repository.get(job.id).status is JobStatus.RUNNING


def test_repository_cannot_save_an_unknown_job() -> None:
    repository = InMemoryJobRepository()

    with pytest.raises(JobNotFoundError):
        repository.save(make_job())
