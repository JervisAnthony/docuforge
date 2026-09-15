# MVP2 Batch Processing Model

## Purpose

Commit 51 establishes framework-independent, immutable state for one ordered multi-item
operation. It gives upcoming image and document workflows stable batch and item UUID identities,
deterministic item order, safe result and failure metadata, and exact per-item progress counts.
It does not process files yet.

## Relationship to jobs

The existing `Job` models the lifecycle of a whole processing operation. `Batch` models ordered
item state within a future multi-item operation. `BatchRequest.operation` reuses the generic
`docuforge.jobs.OperationKey`; there is no second operation identity type. A `Batch` does not
automatically create a `Job` or use `JobManager` or `JobRepository`. The job foundation remains
unchanged, and no duplicate job system is introduced.

## Item lifecycle

```text
PENDING -> RUNNING -> COMPLETED
    |          |
    +----------+----> FAILED
```

An item may fail while pending if validation discovers a problem before execution. Completed and
failed items are terminal. A completed item carries one safe `BatchItemResult`; a failed item
carries one safe `BatchItemFailure`. Every transition returns a new item and batch snapshot,
leaving earlier snapshots unchanged. Multiple items may be running at the same time; this model
does not schedule them.

## Ordering and aggregate state

`BatchRequest.items` is a nonempty tuple. Positions must be exactly `0, 1, ..., N-1` in tuple
order, and item IDs must be unique. Duplicate display descriptors are valid. The model never
sorts or renumbers items, and transitions replace only the identified item at its original
position.

`BatchStatus` is derived from item states:

- `PENDING`: every item is pending.
- `RUNNING`: some work has started or failed, and at least one item is not terminal.
- `COMPLETED`: every item completed.
- `FAILED`: every item failed.
- `PARTIAL`: all items are terminal, with at least one completion and one failure.

Failure of one item does not automatically fail another item or the whole batch. Future workflows
will decide whether to continue after an item failure.

## Progress foundation

`Batch.summary` derives a fresh immutable `BatchSummary` from each snapshot. It records exact
`pending`, `running`, `completed`, `failed`, `processed`, and `remaining` counts alongside the
total and aggregate status. `processed = completed + failed`, `remaining = pending + running`,
and `processed + remaining = total`. Counts are derived rather than independently stored.
There is no percentage, polling, persistence, cancellation, or retry state yet.

## Deliberate exclusions and roadmap

Commit 51 adds no converter execution, batch file workflow, ZIP archive, API, browser, CLI,
JobManager integration, persistence, queue, workers, cancellation, retry, or recovery.

1. Commit 51 — batch model — complete/current.
2. Commit 52 — multi-file batch image processing.
3. Commit 53 — batch document processing and ZIP.
4. Commit 54 — progress/status UX, cancellation, and error recovery.
