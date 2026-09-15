"""Framework-independent, immutable ordered batch and per-item lifecycle models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Self
from uuid import UUID, uuid4

from docuforge.batch.exceptions import (
    BatchItemNotFoundError,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from docuforge.jobs import InvalidJobDefinitionError, OperationKey


def _canonical_uuid(value: str | UUID, *, name: str) -> str:
    if not isinstance(value, (str, UUID)):
        raise InvalidBatchDefinitionError(f"Invalid {name}.")
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as error:
        raise InvalidBatchDefinitionError(f"Invalid {name}.") from error


class BatchId(str):
    """Stable, serializable UUID-backed identity for one ordered batch."""

    def __new__(cls, value: str | UUID) -> Self:
        return super().__new__(cls, _canonical_uuid(value, name="batch ID"))

    @classmethod
    def new(cls) -> BatchId:
        """Create a new batch identity."""
        return cls(uuid4())


class BatchItemId(str):
    """Stable, serializable UUID-backed identity for one batch item."""

    def __new__(cls, value: str | UUID) -> Self:
        return super().__new__(cls, _canonical_uuid(value, name="batch item ID"))

    @classmethod
    def new(cls) -> BatchItemId:
        """Create a new item identity."""
        return cls(uuid4())


class BatchItemStatus(str, Enum):
    """The lifecycle of one independently tracked batch item."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BatchStatus(str, Enum):
    """Aggregate lifecycle derived solely from ordered item states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


def _required_text(value: str, *, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InvalidBatchDefinitionError(f"{name} is required.")
    return value.strip()


@dataclass(frozen=True, slots=True)
class BatchItemRequest:
    """Stable identity, zero-based position, and safe description of one item."""

    id: BatchItemId
    position: int
    descriptor: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", BatchItemId(self.id))
        if type(self.position) is not int or self.position < 0:
            raise InvalidBatchDefinitionError("Batch item position must be non-negative.")
        object.__setattr__(self, "descriptor", _required_text(self.descriptor, name="Item descriptor"))


@dataclass(frozen=True, slots=True)
class BatchRequest:
    """Ordered, nonempty batch intent using the existing generic operation key."""

    id: BatchId
    operation: OperationKey
    items: tuple[BatchItemRequest, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", BatchId(self.id))
        try:
            object.__setattr__(self, "operation", OperationKey(self.operation))
        except InvalidJobDefinitionError:
            raise InvalidBatchDefinitionError("A batch operation key is required.") from None
        if not isinstance(self.items, tuple) or not self.items:
            raise InvalidBatchDefinitionError("A batch requires a nonempty item tuple.")
        seen_ids: set[BatchItemId] = set()
        for expected_position, item in enumerate(self.items):
            if not isinstance(item, BatchItemRequest):
                raise InvalidBatchDefinitionError("A batch requires BatchItemRequest values.")
            if item.id in seen_ids:
                raise InvalidBatchDefinitionError("Batch item IDs must be unique.")
            if item.position != expected_position:
                raise InvalidBatchDefinitionError("Batch item positions must match tuple order.")
            seen_ids.add(item.id)


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    """Safe application-level metadata for one successful item."""

    descriptor: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "descriptor", _required_text(self.descriptor, name="Result descriptor"))


@dataclass(frozen=True, slots=True)
class BatchItemFailure:
    """Safe application-level code and message for one failed item."""

    code: str
    message: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _required_text(self.code, name="Failure code"))
        object.__setattr__(self, "message", _required_text(self.message, name="Failure message"))


@dataclass(frozen=True, slots=True)
class BatchItem:
    """Immutable item snapshot with explicit, validated transitions."""

    request: BatchItemRequest
    status: BatchItemStatus = field(default=BatchItemStatus.PENDING, init=False)
    result: BatchItemResult | None = field(default=None, init=False)
    failure: BatchItemFailure | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, BatchItemRequest):
            raise InvalidBatchDefinitionError("A batch item requires a BatchItemRequest.")

    @property
    def id(self) -> BatchItemId:
        return self.request.id

    @property
    def position(self) -> int:
        return self.request.position

    @property
    def descriptor(self) -> str:
        return self.request.descriptor

    def start(self) -> BatchItem:
        """Return a running snapshot from a pending item."""
        self._require_status(BatchItemStatus.PENDING, target=BatchItemStatus.RUNNING)
        return self._snapshot(status=BatchItemStatus.RUNNING)

    def complete(self, result: BatchItemResult) -> BatchItem:
        """Return a completed snapshot from a running item."""
        self._require_status(BatchItemStatus.RUNNING, target=BatchItemStatus.COMPLETED)
        if not isinstance(result, BatchItemResult):
            raise InvalidBatchDefinitionError("A completed item requires a BatchItemResult.")
        return self._snapshot(status=BatchItemStatus.COMPLETED, result=result)

    def fail(self, failure: BatchItemFailure) -> BatchItem:
        """Return a failed snapshot from a pending or running item."""
        if self.status not in {BatchItemStatus.PENDING, BatchItemStatus.RUNNING}:
            raise InvalidBatchTransitionError("A terminal batch item cannot fail again.")
        if not isinstance(failure, BatchItemFailure):
            raise InvalidBatchDefinitionError("A failed item requires a BatchItemFailure.")
        return self._snapshot(status=BatchItemStatus.FAILED, failure=failure)

    def _require_status(self, expected: BatchItemStatus, *, target: BatchItemStatus) -> None:
        if self.status is not expected:
            raise InvalidBatchTransitionError(
                f"Cannot transition batch item from {self.status.value} to {target.value}."
            )

    def _snapshot(
        self, *, status: BatchItemStatus,
        result: BatchItemResult | None = None,
        failure: BatchItemFailure | None = None,
    ) -> BatchItem:
        snapshot = object.__new__(BatchItem)
        object.__setattr__(snapshot, "request", self.request)
        object.__setattr__(snapshot, "status", status)
        object.__setattr__(snapshot, "result", result)
        object.__setattr__(snapshot, "failure", failure)
        return snapshot


def _status_from_counts(
    total: int, pending: int, running: int, completed: int, failed: int,
) -> BatchStatus:
    if pending == total:
        return BatchStatus.PENDING
    if completed == total:
        return BatchStatus.COMPLETED
    if failed == total:
        return BatchStatus.FAILED
    if pending == 0 and running == 0:
        return BatchStatus.PARTIAL
    return BatchStatus.RUNNING


@dataclass(frozen=True, slots=True)
class BatchSummary:
    """Validated exact counts and derived aggregate state for one snapshot."""

    status: BatchStatus
    total_count: int
    pending_count: int
    running_count: int
    completed_count: int
    failed_count: int
    processed_count: int
    remaining_count: int

    def __post_init__(self) -> None:
        counts = (
            self.total_count, self.pending_count, self.running_count,
            self.completed_count, self.failed_count, self.processed_count,
            self.remaining_count,
        )
        if any(type(count) is not int or count < 0 for count in counts) or self.total_count == 0:
            raise InvalidBatchDefinitionError("Batch summary counts must be valid integers.")
        if (
            self.pending_count + self.running_count + self.completed_count + self.failed_count
            != self.total_count
            or self.processed_count != self.completed_count + self.failed_count
            or self.remaining_count != self.pending_count + self.running_count
        ):
            raise InvalidBatchDefinitionError("Batch summary counts are inconsistent.")
        expected_status = _status_from_counts(
            self.total_count, self.pending_count, self.running_count,
            self.completed_count, self.failed_count,
        )
        if not isinstance(self.status, BatchStatus) or self.status is not expected_status:
            raise InvalidBatchDefinitionError("Batch summary status is inconsistent.")


@dataclass(frozen=True, slots=True)
class Batch:
    """Ordered immutable batch snapshot; aggregate state is always derived."""

    request: BatchRequest
    items: tuple[BatchItem, ...] = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, BatchRequest):
            raise InvalidBatchDefinitionError("A batch requires a BatchRequest.")
        object.__setattr__(self, "items", tuple(BatchItem(item) for item in self.request.items))

    @property
    def id(self) -> BatchId:
        return self.request.id

    @property
    def operation(self) -> OperationKey:
        return self.request.operation

    @property
    def summary(self) -> BatchSummary:
        """Derive a fresh immutable summary from this exact item snapshot."""
        pending = running = completed = failed = 0
        for item in self.items:
            if item.status is BatchItemStatus.PENDING:
                pending += 1
            elif item.status is BatchItemStatus.RUNNING:
                running += 1
            elif item.status is BatchItemStatus.COMPLETED:
                completed += 1
            else:
                failed += 1
        total = len(self.items)
        return BatchSummary(
            status=_status_from_counts(total, pending, running, completed, failed),
            total_count=total, pending_count=pending, running_count=running,
            completed_count=completed, failed_count=failed,
            processed_count=completed + failed, remaining_count=pending + running,
        )

    @property
    def status(self) -> BatchStatus:
        return self.summary.status

    @property
    def total_count(self) -> int:
        return len(self.items)

    @property
    def pending_count(self) -> int:
        return self.summary.pending_count

    @property
    def running_count(self) -> int:
        return self.summary.running_count

    @property
    def completed_count(self) -> int:
        return self.summary.completed_count

    @property
    def failed_count(self) -> int:
        return self.summary.failed_count

    @property
    def processed_count(self) -> int:
        return self.summary.processed_count

    @property
    def remaining_count(self) -> int:
        return self.summary.remaining_count

    @property
    def is_terminal(self) -> bool:
        return self.status in {BatchStatus.COMPLETED, BatchStatus.PARTIAL, BatchStatus.FAILED}

    def get_item(self, item_id: BatchItemId | str) -> BatchItem:
        """Look up an item by stable UUID identity, never by descriptor."""
        return self.items[self._item_index(item_id)]

    def start_item(self, item_id: BatchItemId | str) -> Batch:
        """Return a new batch with exactly one item started."""
        index = self._item_index(item_id)
        return self._replace_item(index, self.items[index].start())

    def complete_item(self, item_id: BatchItemId | str, result: BatchItemResult) -> Batch:
        """Return a new batch with exactly one item completed."""
        index = self._item_index(item_id)
        return self._replace_item(index, self.items[index].complete(result))

    def fail_item(self, item_id: BatchItemId | str, failure: BatchItemFailure) -> Batch:
        """Return a new batch with exactly one item failed."""
        index = self._item_index(item_id)
        return self._replace_item(index, self.items[index].fail(failure))

    def _item_index(self, item_id: BatchItemId | str) -> int:
        normalized = BatchItemId(item_id)
        for index, item in enumerate(self.items):
            if item.id == normalized:
                return index
        raise BatchItemNotFoundError("Batch item was not found.")

    def _replace_item(self, index: int, item: BatchItem) -> Batch:
        snapshot = object.__new__(Batch)
        object.__setattr__(snapshot, "request", self.request)
        object.__setattr__(
            snapshot, "items", self.items[:index] + (item,) + self.items[index + 1:]
        )
        return snapshot
