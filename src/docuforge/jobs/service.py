"""Application service for creating and advancing jobs."""

from collections.abc import Callable
from datetime import UTC, datetime

from docuforge.jobs.models import Job, JobFailure, JobId, JobRequest, JobResult, OperationKey
from docuforge.jobs.repository import JobRepository

Clock = Callable[[], datetime]


class JobManager:
    """Coordinate job lifecycle changes through an injected repository."""

    def __init__(self, repository: JobRepository, *, clock: Clock | None = None) -> None:
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(UTC))

    def create_job(
        self,
        operation: OperationKey | str,
        *,
        payload_descriptor: str | None = None,
        job_id: JobId | None = None,
    ) -> Job:
        request = JobRequest(
            id=job_id or JobId.new(),
            operation=OperationKey(operation),
            created_at=self._clock(),
            payload_descriptor=payload_descriptor,
        )
        job = Job(request)
        self._repository.add(job)
        return job

    def get_job(self, job_id: JobId | str) -> Job:
        return self._repository.get(job_id)

    def start_job(self, job_id: JobId | str) -> Job:
        job = self._repository.get(job_id).start(at=self._clock())
        self._repository.save(job)
        return job

    def complete_job(self, job_id: JobId | str, result: JobResult) -> Job:
        job = self._repository.get(job_id).complete(result, at=self._clock())
        self._repository.save(job)
        return job

    def fail_job(self, job_id: JobId | str, failure: JobFailure) -> Job:
        job = self._repository.get(job_id).fail(failure, at=self._clock())
        self._repository.save(job)
        return job
