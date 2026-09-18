"""Public immutable batch-processing domain API."""

from docuforge.batch.archive import BatchArchiveResult, package_batch_outputs
from docuforge.batch.control import BatchCancellationToken, BatchProgressCallback
from docuforge.batch.document import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchDocumentOutput,
    BatchDocumentResult,
    batch_convert_documents,
)
from docuforge.batch.exceptions import (
    BatchError,
    BatchItemNotFoundError,
    BatchProcessingError,
    InvalidBatchDefinitionError,
    InvalidBatchTransitionError,
)
from docuforge.batch.image import (
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageOutput,
    BatchImageResizeRequest,
    BatchImageResult,
    batch_compress_images,
    batch_convert_images,
    batch_resize_images,
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
    "BatchArchiveResult",
    "BatchCancellationToken",
    "BatchDocumentConvertRequest",
    "BatchDocumentInput",
    "BatchDocumentOutput",
    "BatchDocumentResult",
    "BatchError",
    "BatchId",
    "BatchImageCompressRequest",
    "BatchImageConvertRequest",
    "BatchImageInput",
    "BatchImageOutput",
    "BatchImageResizeRequest",
    "BatchImageResult",
    "BatchItem",
    "BatchItemFailure",
    "BatchItemId",
    "BatchItemNotFoundError",
    "BatchItemRequest",
    "BatchItemResult",
    "BatchItemStatus",
    "BatchProcessingError",
    "BatchProgressCallback",
    "BatchRequest",
    "BatchStatus",
    "BatchSummary",
    "InvalidBatchDefinitionError",
    "InvalidBatchTransitionError",
    "batch_compress_images",
    "batch_convert_documents",
    "batch_convert_images",
    "batch_resize_images",
    "package_batch_outputs",
]
