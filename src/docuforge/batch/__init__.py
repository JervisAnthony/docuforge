"""Public immutable batch-processing domain API."""

from docuforge.batch.exceptions import (
    BatchError,
    BatchItemNotFoundError,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from docuforge.batch.models import (
    Batch,
    BatchId,
    BatchItem,
    BatchItemFailure,
    BatchItemId,
    BatchItemRequest,
    BatchItemResult,
    BatchItemStatus,
    BatchRequest,
    BatchStatus,
    BatchSummary,
)

__all__ = [
    "Batch",
    "BatchError",
    "BatchId",
    "BatchItem",
    "BatchItemFailure",
    "BatchItemId",
    "BatchItemNotFoundError",
    "BatchItemRequest",
    "BatchItemResult",
    "BatchItemStatus",
    "BatchRequest",
    "BatchStatus",
    "BatchSummary",
    "InvalidBatchDefinitionError",
    "InvalidBatchTransitionError",
]
