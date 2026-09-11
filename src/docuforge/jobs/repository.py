"""Storage contracts and process-local storage for jobs."""

from typing import Protocol

from docuforge.jobs.exceptions import DuplicateJobError, JobNotFoundError
from docuforge.jobs.models import Job, JobId


class JobRepository(Protocol):
    """Storage contract used by the job application layer."""

    def add(self, job: Job) -> None:
        """Store a newly created job."""

    def get(self, job_id: JobId | str) -> Job:
        """Retrieve a job by identity."""

    def save(self, job: Job) -> None:
        """Persist a new snapshot for an existing job."""


class InMemoryJobRepository:
    """An instance-scoped, process-local job repository."""

    def __init__(self) -> None:
        self._jobs: dict[JobId, Job] = {}

    def add(self, job: Job) -> None:
        if job.id in self._jobs:
            raise DuplicateJobError(f"Job {job.id} already exists.")
        self._jobs[job.id] = job

    def get(self, job_id: JobId | str) -> Job:
        normalized_id = JobId(job_id)
        try:
            return self._jobs[normalized_id]
        except KeyError as error:
            raise JobNotFoundError(f"Job {normalized_id} was not found.") from error

    def save(self, job: Job) -> None:
        if job.id not in self._jobs:
            raise JobNotFoundError(f"Job {job.id} was not found.")
        self._jobs[job.id] = job
