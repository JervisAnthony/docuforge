"""Structured failures for immutable batch domain values and transitions."""

from docuforge.core.exceptions import DocuForgeError


class BatchError(DocuForgeError):
    """Base class for expected batch-domain failures."""


class InvalidBatchDefinitionError(BatchError):
    """A batch identity, request, value, or snapshot is invalid."""


class InvalidBatchTransitionError(BatchError):
    """A batch item cannot move to the requested lifecycle state."""


class BatchItemNotFoundError(BatchError):
    """A valid item identity is absent from the requested batch."""


class BatchProcessingError(BatchError):
    """Batch-wide processing infrastructure could not complete safely."""
