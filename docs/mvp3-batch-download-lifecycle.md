# Batch download lifecycle

## Problem

Returning an authorized archive path releases the service lock before asynchronous
FileResponse opens and streams it. Concurrent deletion or recovery could remove or
replace that archive during this gap.

## Download pin

`acquire_download` validates the capability once and establishes a process-local pin
atomically under the service RLock. A handle holds the archive Path and an idempotent
release callback. Bookkeeping maps BatchIds to sets of unique opaque UUID pin IDs;
it contains no capability, token hash, client metadata or range state. Multiple
accepted downloads release independently. Reads consume no execution admission or
storage-write reservation and make no persistence writes.

The internal FileResponse subclass preserves ZIP headers, Content-Length,
Content-Disposition, efficient streaming and native Range handling. Its ASGI
`finally` releases the exact pin on completion, send failure or cancellation.
Response construction failures also release the handle. The compatibility
`download_path` inspection method provides no lifetime guarantee; HTTP streaming
uses the scoped handle.

## Deletion and TTL

DELETE commits irreversible DELETING intent before returning 204. New status,
download, recovery and cancellation access immediately returns 404 batch_not_found.
Already accepted archives remain readable. Physical workspace and metadata deletion
wait for the final pin. Final release attempts deletion; a cleanup failure preserves
the tombstone, logs only a generic warning and allows the sweeper to retry.

TTL expires at its existing boundary. Starting or finishing a download never
refreshes updated_at. Expiry may commit DELETING during a stream, hiding new access
while physical cleanup waits. A pinned tombstone is a normal deferred cleanup state.

## Recovery

Otherwise recoverable batches return `409 batch_download_active` with message
`The batch cannot be recovered while a download is active.` and no Retry-After.
This check precedes storage measurement, admission, submission and state/persistence
mutation because recovery may replace the archive. Recovery resumes after release.

## Shutdown and crash boundary

Graceful shutdown stops the sweeper and workers, drains pending upload writes and
all accepted downloads, then cleans ephemeral workspaces and clears sessions.
Durable storage ownership remains held until downloads drain and is released last.
New service-level download acquisition after shutdown begins is refused.

Pins are process-local and never persisted; schema remains v2. Process crashes
terminate streams and close descriptors. Existing OS owner-lock semantics and
persisted DELETING tombstones allow restart to finish cleanup with no pin recovery.
No additional OS archive file lock is needed under exclusive storage ownership.

## Boundary

This is not distributed leasing, persistent reader tracking, download resumption,
bandwidth limiting or range-state persistence.
