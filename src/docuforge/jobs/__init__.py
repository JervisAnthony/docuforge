"""Public domain and application API for DocuForge processing jobs."""

from docuforge.jobs.exceptions import (
    DuplicateJobError,
    InvalidJobDefinitionError,
    InvalidJobTransitionError,
    JobError,
    JobNotFoundError,
)
from docuforge.jobs.models import (
    Job,
    JobFailure,
    JobId,
    JobRequest,
    JobResult,
    JobStatus,
    OperationKey,
)
from docuforge.jobs.repository import InMemoryJobRepository, JobRepository
from docuforge.jobs.service import JobManager

__all__ = [
    "DuplicateJobError",
    "InMemoryJobRepository",
    "InvalidJobDefinitionError",
    "InvalidJobTransitionError",
    "Job",
    "JobError",
    "JobFailure",
    "JobId",
    "JobManager",
    "JobNotFoundError",
    "JobRepository",
    "JobRequest",
    "JobResult",
    "JobStatus",
    "OperationKey",
]
