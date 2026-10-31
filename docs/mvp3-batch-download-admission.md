# Bounded concurrent archive downloads

## Problem and capacity model

Accepted ZIP downloads retain an operating-system descriptor until response cleanup.
Worker admission ends when execution reaches a terminal state, so it cannot bound
long-lived READY downloads. Each BatchExecutionService now independently limits
accepted, unreleased reader handles globally and for each BatchId.

| Setting | Environment variable | Default |
| --- | --- | ---: |
| batch_max_active_downloads | DOCUFORGE_BATCH_MAX_ACTIVE_DOWNLOADS | 8 |
| batch_max_downloads_per_batch | DOCUFORGE_BATCH_MAX_DOWNLOADS_PER_BATCH | 4 |

Both settings and the service's max_active_downloads / max_downloads_per_batch
parameters require exact positive integers. Environment values use the existing
trimmed ASCII decimal parser. Empty, signed, fractional, non-ASCII, hexadecimal and
unit-suffixed values are rejected. A per-batch limit above the global limit is valid;
both constraints still apply. create_app passes the immutable settings to its own
service instance; apps do not share capacity.

## Admission ordering and safe backpressure

GET /api/v1/batches/{batch_id}/download retains X-DocuForge-Batch-Token authorization.

1. Authenticate the capability through the established authorization path.
2. Apply existing phase/output eligibility checks and reject an already-known
   unavailable archive (no retained result or no archive path).
3. Check global and per-batch capacity.
4. Open and validate the canonical archive descriptor, including ZIP structure/CRC
   and path/descriptor stability.
5. Create the reader-owned handle and register its unique pin.

The service's existing RLock covers the entire sequence through successful pin
registration. Counts are derived from _active_downloads pin sets; no separate
counter, provisional capacity reservation, queue or global singleton is added.

Invalid capabilities and DELETING sessions retain private 404 batch_not_found.
QUEUED, PROCESSING, CANCELLING and PACKAGING retain 409 batch_not_ready;
no-successful-output results retain 409 batch_has_no_outputs. These checks
precede capacity even when the service is full.

An already-known unavailable archive retains `409 batch_packaging_failed` and its
existing persistence behavior before capacity is considered. This checks only
retained session values, without filesystem inspection or ZIP validation. When both
the retained result and archive path exist, capacity still precedes opening and
validation of the filesystem node, even if that node is missing or corrupt.

Either exhausted limit produces the same safe response:

```json
{
  "code": "batch_download_capacity_exceeded",
  "message": "The batch download service is temporarily at capacity. Try again later."
}
```

The status is **503**, without Retry-After or numerical limits, counts, paths,
capabilities, BatchIds or pin identifiers. The response documents backpressure
without identifying which constraint is exhausted.

A capacity rejection performs no archive open or CRC scan, registers no pin, reserves
no execution admission, resets no workspace and does not mutate the target session,
its terminal timestamp or durable row. Existing authorized-request TTL housekeeping
still applies. At capacity, a corrupted archive is left unexamined and unchanged;
after a slot frees, normal validation can return recoverable 409 batch_packaging_failed.
Persistence failures during degradation retain their existing safe 503 behavior.

## Reader lifetime and fairness

At defaults, one BatchId can retain four readers while other batches can use the
remaining slots, up to eight across the service. This is immediate accept/reject
admission; it does not guarantee scheduled or starvation-free fairness.

Each accepted response owns its separately validated descriptor and independent
cursor. One full, single-range or multipart response consumes one slot. Existing
GET, Range, If-Range, adapter HEAD, ZIP headers and bounded 1 MiB reads are unchanged.
Accepted streams are never evicted to admit another request, and response streaming
does not reopen the archive pathname.

The handle closes its descriptor before releasing only its unique pin. Removing the
last pin removes the empty set, so capacity is immediately reusable. Duplicate
release is a no-op; expected close OSError logs a generic warning and still unpins.
Constructor/registration failure closes the new reader and rolls back its own pin.
All existing response finally paths free capacity: completion, range/HEAD responses,
construction errors, cancellation, receive disconnect, send failure and short reads.

## Deletion, retention, recovery and shutdown

DELETE stays available at capacity. Tombstones hide new access immediately; accepted
streams remain valid and physical deletion waits for their final pins. Unrelated
unpinned sessions can expire normally. Acquisition, rejection and release do not
extend terminal TTL. Graceful shutdown refuses new acquisition, drains accepted
readers with the existing condition variable and releases durable ownership last.

Recovery continues to refuse an active reader with 409 batch_download_active.
After the final release, existing recovery eligibility, worker admission and
packaging-only repair apply unchanged. Download admission consumes no worker or
upload admission: permitted uploads, queued conversions, packaging, polling,
cancellation and deletion continue at full reader capacity. Conversely, full worker
admission does not block an otherwise eligible download with an available slot.

## Process and operational boundaries

Capacity is process-local and applies equally to ephemeral and durable storage.
Historical archives and rejected/failed acquisitions consume no slots. Process
restart begins with no active HTTP readers; existing durable DELETING reconciliation
still applies. SQLite schema remains v3, without persistent reader metadata.

This policy bounds retained accepted descriptors. Permitted ZIP validation still
runs under the service lock and can cause lock contention. It is not bandwidth
limiting, per-user or per-IP rate limiting, distributed leasing, or complete
protection against slow-client resource use. No dependency or public success
contract changes are introduced.

## Verification

Focused tests cover defaults/configuration, privacy/phase/output precedence,
unchanged rejected state, forbidden open/CRC work, independent global/per-batch
boundaries, three-session fairness, synchronized acquisition and release races,
slow ranges/multipart responses and every cleanup path. Existing descriptor,
lifecycle, archive-integrity and execution-admission regressions remain required.

The production container independently emits PASS batch-download-admission using
synthetic ZIPs, safe rejection before opening, unchanged durable state, immediate
slot reuse, descriptor ZIP bytes/CRC, empty final pins and normal deletion.
The complete production image must emit seventeen PASS markers.
