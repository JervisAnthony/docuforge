"""Batch symbols stay public only at the batch domain boundary."""

from docuforge import batch, converters, jobs


def test_public_batch_api_is_explicit_and_does_not_pollute_other_packages() -> None:
    expected = {
        "Batch", "BatchArchiveResult", "BatchDocumentConvertRequest", "BatchDocumentInput",
        "BatchDocumentOutput", "BatchDocumentResult", "BatchError", "BatchId",
        "BatchImageCompressRequest", "BatchImageConvertRequest", "BatchImageInput", "BatchImageOutput",
        "BatchImageResizeRequest", "BatchImageResult", "BatchItem", "BatchItemFailure",
        "BatchItemId", "BatchItemNotFoundError", "BatchItemRequest", "BatchItemResult",
        "BatchItemStatus", "BatchProcessingError", "BatchRequest", "BatchStatus",
        "BatchSummary", "InvalidBatchDefinitionError", "InvalidBatchTransitionError",
        "batch_compress_images", "batch_convert_documents", "batch_convert_images",
        "batch_resize_images", "package_batch_outputs",
    }
    assert set(batch.__all__) == expected
    assert all(hasattr(batch, name) for name in expected)
    assert not any(name.startswith("_") for name in batch.__all__)
    assert not any(hasattr(converters, name) or hasattr(jobs, name) for name in expected)


def test_job_status_is_unchanged() -> None:
    assert [status.value for status in jobs.JobStatus] == [
        "pending", "running", "completed", "failed",
    ]
