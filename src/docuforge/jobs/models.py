"""Framework-independent domain models for processing jobs."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Self
from uuid import UUID, uuid4

from docuforge.jobs.exceptions import InvalidJobDefinitionError, InvalidJobTransitionError


class JobStatus(str, Enum):
    """States in the DocuForge job lifecycle."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobId(str):
    """An immutable, serializable, UUID-backed job identifier."""

    def __new__(cls, value: str | UUID) -> Self:
        try:
            normalized = str(UUID(str(value)))
        except (AttributeError, TypeError, ValueError) as error:
            raise InvalidJobDefinitionError(f"Invalid job ID: {value!r}.") from error
        return super().__new__(cls, normalized)

    @classmethod
    def new(cls) -> JobId:
        """Create a unique job identifier."""
        return cls(uuid4())


class OperationKey(str):
    """A generic identifier for the application operation a job will perform."""

    def __new__(cls, value: str) -> Self:
        if not isinstance(value, str) or not value.strip():
            raise InvalidJobDefinitionError("A job operation key is required.")
        return super().__new__(cls, value.strip())


def _utc_datetime(value: datetime, *, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidJobDefinitionError(f"{field_name} must be timezone-aware.")
    return value.astimezone(UTC)


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidJobDefinitionError(f"{field_name} is required.")
    return value.strip()


@dataclass(frozen=True, slots=True)
class JobRequest:
    """Immutable, transport-neutral intent for a processing job."""

    id: JobId
    operation: OperationKey
    created_at: datetime
    payload_descriptor: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", JobId(self.id))
        object.__setattr__(self, "operation", OperationKey(self.operation))
        object.__setattr__(
            self,
            "created_at",
            _utc_datetime(self.created_at, field_name="created_at"),
        )
        if self.payload_descriptor is not None:
            object.__setattr__(
                self,
                "payload_descriptor",
                _required_text(self.payload_descriptor, field_name="payload_descriptor"),
            )


@dataclass(frozen=True, slots=True)
class JobResult:
    """A safe, minimal descriptor for a successfully produced result."""

    descriptor: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "descriptor",
            _required_text(self.descriptor, field_name="result descriptor"),
        )


@dataclass(frozen=True, slots=True)
class JobFailure:
    """Safe failure information suitable for application-layer consumers."""

    code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, field_name="failure code"))
        object.__setattr__(
            self,
            "message",
            _required_text(self.message, field_name="failure message"),
        )


@dataclass(frozen=True, slots=True)
class Job:
    """An immutable job snapshot with validated lifecycle transitions."""

    request: JobRequest
    status: JobStatus = field(default=JobStatus.PENDING, init=False)
    started_at: datetime | None = field(default=None, init=False)
    finished_at: datetime | None = field(default=None, init=False)
    result: JobResult | None = field(default=None, init=False)
    failure: JobFailure | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, JobRequest):
            raise InvalidJobDefinitionError("A job requires a JobRequest.")

    @property
    def id(self) -> JobId:
        """Return the job identity from its immutable request."""
        return self.request.id

    @property
    def operation(self) -> OperationKey:
        """Return the operation requested for this job."""
        return self.request.operation

    @property
    def created_at(self) -> datetime:
        """Return the time at which this job was created."""
        return self.request.created_at

    def start(self, *, at: datetime | None = None) -> Job:
        """Move a pending job into the running state."""
        self._require_status(JobStatus.PENDING, target=JobStatus.RUNNING)
        started_at = self._transition_time(at)
        return self._snapshot(status=JobStatus.RUNNING, started_at=started_at)

    def complete(self, result: JobResult, *, at: datetime | None = None) -> Job:
        """Complete a running job with a result descriptor."""
        self._require_status(JobStatus.RUNNING, target=JobStatus.COMPLETED)
        if not isinstance(result, JobResult):
            raise InvalidJobDefinitionError("A completed job requires a JobResult.")
        finished_at = self._transition_time(at)
        return self._snapshot(
            status=JobStatus.COMPLETED,
            started_at=self.started_at,
            finished_at=finished_at,
            result=result,
        )

    def fail(self, failure: JobFailure, *, at: datetime | None = None) -> Job:
        """Fail a pending or running job with safe failure information."""
        if self.status not in {JobStatus.PENDING, JobStatus.RUNNING}:
            raise InvalidJobTransitionError(
                f"Cannot transition job {self.id} from {self.status.value} to failed."
            )
        if not isinstance(failure, JobFailure):
            raise InvalidJobDefinitionError("A failed job requires a JobFailure.")
        finished_at = self._transition_time(at)
        return self._snapshot(
            status=JobStatus.FAILED,
            started_at=self.started_at,
            finished_at=finished_at,
            failure=failure,
        )

    def _require_status(self, expected: JobStatus, *, target: JobStatus) -> None:
        if self.status is not expected:
            raise InvalidJobTransitionError(
                f"Cannot transition job {self.id} from {self.status.value} to {target.value}."
            )

    def _transition_time(self, value: datetime | None) -> datetime:
        transition_at = _utc_datetime(value or datetime.now(UTC), field_name="transition time")
        lower_bound = self.started_at or self.created_at
        if transition_at < lower_bound:
            raise InvalidJobDefinitionError(
                "A lifecycle timestamp cannot precede the previous lifecycle event."
            )
        return transition_at

    def _snapshot(
        self,
        *,
        status: JobStatus,
        started_at: datetime | None = None,
        finished_at: datetime | None = None,
        result: JobResult | None = None,
        failure: JobFailure | None = None,
    ) -> Job:
        snapshot = object.__new__(Job)
        object.__setattr__(snapshot, "request", self.request)
        object.__setattr__(snapshot, "status", status)
        object.__setattr__(snapshot, "started_at", started_at)
        object.__setattr__(snapshot, "finished_at", finished_at)
        object.__setattr__(snapshot, "result", result)
        object.__setattr__(snapshot, "failure", failure)
        return snapshot
