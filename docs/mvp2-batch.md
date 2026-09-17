# MVP2 Batch Processing Model

## Purpose

Commit 51 established framework-independent, immutable state for one ordered multi-item
operation. Commits 52 and 53 use that state for reusable Python batch image and Office-document
workflows, plus safe packaging of successful outputs, while keeping the batch layer independent
of HTTP, browser, job, and persistence concerns.

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

Failure of one item does not automatically fail another item or the whole batch. The image
workflows continue after expected item failures.

## Multi-file image processing

The public Python API provides batch format conversion, aspect-ratio-preserving resize, and
compression. Each workflow delegates raster decoding, EXIF orientation, resize calculations,
compression, encoding, and atomic staged writes to the existing single-image path converter.
The Commit 51 `Batch` remains the authoritative per-item lifecycle and aggregate state.

Items run sequentially in their original tuple order. Each transitions from `PENDING` to
`RUNNING`, then to `COMPLETED` or `FAILED`. Expected failures do not abort later items, so a batch
can finish as `COMPLETED`, `PARTIAL`, or `FAILED`. Successful output metadata retains original
zero-based positions even when intervening items fail.

Output filenames use deterministic one-based, four-digit prefixes such as `0001-photo.png` and
`0002-photo.png`. This safely separates duplicate source names. Each item writes first to its own
directory in a temporary per-batch workspace. The staged node and decoded image are validated
before atomic publication into the caller's existing output directory. A successful item replaces
its deterministic destination; a failed item leaves any existing destination untouched. The
temporary workspace is removed afterward.

## Multi-file document processing

The document workflow accepts a heterogeneous ordered tuple of DOCX, PPTX, and XLSX inputs and
routes each item through the existing Office-to-PDF converter layer with an injected
`OfficeConversionEngine`. It uses the stable `office.to_pdf` operation key and the same immutable
item lifecycle and partial-success rules as image processing.

Successful PDFs use position-preserving names such as `0001-report.pdf` and
`0003-financials.pdf`. Each converter writes through its existing isolated workflow into an
item-specific outer batch workspace. The batch boundary independently checks the returned path,
regular non-symlink node, containment, nonempty content, and `%PDF-` signature before atomically
publishing it. Expected request, format, engine, validation, and publication failures remain safe
per-item failures; unexpected programming errors propagate.

## ZIP packaging

`package_batch_outputs` packages the successful outputs from either a `BatchImageResult` or a
`BatchDocumentResult`. Partial results retain their original deterministic names and order, while
failed items contribute no member and are never renumbered. An all-failed result is valid but is
rejected for packaging rather than producing an empty ZIP.

Before writing, the archive layer revalidates each output against its result metadata and current
filesystem state: members must be unique safe basenames, files must be regular non-symlinks, and
resolved paths must remain within the result output directory. The ZIP is created in a temporary
workspace beside the requested destination, reopened to verify its exact member sequence and
integrity, and only then atomically published. Existing destinations therefore survive expected
creation, validation, and publication failures.

## Progress foundation

`Batch.summary` derives a fresh immutable `BatchSummary` from each snapshot. It records exact
`pending`, `running`, `completed`, `failed`, `processed`, and `remaining` counts alongside the
total and aggregate status. `processed = completed + failed`, `remaining = pending + running`,
and `processed + remaining = total`. Counts are derived rather than independently stored.
There is no percentage, polling, persistence, cancellation, or retry state yet.

## Deliberate exclusions and roadmap

The current batch foundation adds no API, browser, CLI, JobManager integration, persistence,
queue, workers, cancellation, retry, or recovery. Processing and packaging remain sequential.

1. Commit 51 — batch-processing model — complete.
2. Commit 52 — multi-file batch image processing — complete.
3. Commit 53 — batch document processing and ZIP — complete/current.
4. Commit 54 — progress/status UX, cancellation, and error recovery.
