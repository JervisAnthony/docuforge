"""Batch symbols stay public only at the batch domain boundary."""

from docuforge import batch, converters, jobs


def test_public_batch_api_is_explicit_and_does_not_pollute_other_packages() -> None:
    expected = {
        "Batch", "BatchError", "BatchId", "BatchItem", "BatchItemFailure",
        "BatchItemId", "BatchItemNotFoundError", "BatchItemRequest",
        "BatchItemResult", "BatchItemStatus", "BatchRequest", "BatchStatus",
        "BatchSummary", "InvalidBatchDefinitionError", "InvalidBatchTransitionError",
    }
    assert set(batch.__all__) == expected
    assert all(hasattr(batch, name) for name in expected)
    assert not any(name.startswith("_") for name in batch.__all__)
    assert not any(hasattr(converters, name) or hasattr(jobs, name) for name in expected)


def test_job_status_is_unchanged() -> None:
    assert [status.value for status in jobs.JobStatus] == [
        "pending", "running", "completed", "failed",
    ]
