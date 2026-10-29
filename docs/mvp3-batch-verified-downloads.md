# Verified ZIP downloads

## Prior gap

The process-local download pin already prevented DocuForge from deleting or
repackaging an accepted archive. It did not bind `archive_is_valid(path)` to the
later `FileResponse` open: an external pathname replacement could separate the
validated ZIP from the transmitted file.

## Acquisition and ownership

Under the service lock, acquisition rejects shutdown, authorizes the capability,
and applies existing phase/result eligibility before opening or scanning any
archive. Wrong or missing capabilities retain private `404 batch_not_found`.
Capability verification also precedes expiry cleanup and its filesystem/persistence
writes; authorized access and the idle sweeper retain the existing expiry rules.
Only the canonical `workspace.archive_path` is accepted. The internal
`_open_validated_download_archive` checks real directory ancestry, a regular
non-symlink/non-reparse file, and the opened descriptor's device, inode, mode,
size and nanosecond mtime against the pre-open snapshot. Comparable POSIX ctime
is also checked; Windows path/fstat ctime is deliberately excluded.

The shared `_archive_reader_is_valid` opens `ZipFile` on that reader. It verifies
exact ordered result-member names, uniqueness, no directories/encryption, DEFLATED
compression, structure and CRC. Closing the ZIP wrapper preserves the underlying
reader. Descriptor metadata, original path identity and ancestry are checked again
after validation; the reader is rewound to zero. Only then does the service create
the handle and register its unique active pin. There is one full CRC scan per
acquisition. The compatibility `archive_is_valid(path, result, workspace)` uses
the same helper but closes its reader rather than transferring ownership.

Each `BatchDownloadHandle` owns an independent binary reader, validated stat/size,
informational path and release callback. Its cursor is not shared with other
requests. Read and release use a per-handle lock: release waits for an in-progress
read, closes the reader, then unpins. A guarded once-only release prevents duplicate
descriptor closure. Expected close failures log a generic warning and still unpin
in `finally`; unexpected programming failures are not silently swallowed.

## HTTP streaming

The response adapter preserves Starlette's header and range parsing while replacing
all three file-reading branches: full, single-range and multipart-range responses.
It receives the validated descriptor stat, never stats/reopens the archive path,
and ignores ASGI pathsend even when advertised. This trades pathname-based zero-copy
optimization for same-descriptor transmission. Bounded threadpool reads use at most
1 MiB; there is no full-archive response buffer or temporary download copy.

An initial chunk is prepared before successful response headers. Later read/EOF
failures stop streaming without a false completed body; read errors have a generic
message. After headers start, transport failure cannot be replaced by a JSON error.
The ASGI `finally` closes/releases on completion, preparation/send failure,
cancellation, HEAD, and range errors. For ASGI 2.4+, the server signals disconnect
through send failures; older ASGI versions use a concurrent receive listener.
The route also retains immediate release if response construction fails.

## HTTP compatibility

The endpoint, capability header, `application/zip` type, `Cache-Control: no-store`,
attachment filename `docuforge-batch-{batch_id}.zip`, and `Accept-Ranges: bytes`
remain. Full GET returns 200 with the descriptor's validated Content-Length.
Valid single, open-ended, suffix and multiple ranges return 206 with the existing
range parsing/merging semantics and correct lengths. Multipart parts read from the
same owned descriptor. Unsatisfiable ranges retain 416 and `bytes */<size>`;
malformed ranges retain the framework's 400 behavior. The framework's existing
100-range limit/fallback is preserved.

HEAD emits no ZIP body and releases the handle when the adapter is used for HEAD;
no public HEAD route is added. If-Range matching follows the existing ETag or
Last-Modified comparison; a mismatch sends the full representation. Those headers
come from the validated descriptor stat. The existing metadata-derived ETag wire
format is preserved: it is a weak assurance of content identity, not a cryptographic
hash of ZIP bytes or proof that contents cannot change.

## Concurrent downloads, deletion and retention

Two accepted downloads own separate descriptors/cursors and unique pins. Releasing
one cannot close the other. DELETE still commits its tombstone first, returns 204,
and hides new access with private 404. Physical cleanup waits until the final owned
reader has closed. TTL follows the same rule; download acquisition/release does not
refresh terminal retention. The existing DELETING transition timestamp is unchanged.
Recovery still refuses active downloads with `409 batch_download_active` before
destructive reset, admission or submission. Graceful shutdown drains descriptors
before ephemeral cleanup or durable owner-lock release. Pins remain process-local;
process termination closes descriptors, with existing tombstones governing restart.

## Invalid archives and recovery

Missing, replaced, unreadable or invalid ZIPs leave no reader or pin and retain
`409 batch_packaging_failed` / `The batch archive is unavailable.` READY degrades
recoverably to ERROR while preserving result, batch, attempt and terminal timestamp.
SQLite persistence precedes live mutation; failure returns existing
`503 batch_persistence_failed` without publishing the candidate state. Existing
ERROR reasons remain authoritative. Stable retained results allow packaging-only
recovery without reconversion or original upload reads.

## Platform and concurrency boundaries

On supported POSIX platforms, each directory is opened relative to its verified
predecessor with `O_DIRECTORY | O_NOFOLLOW`; archive opening uses `O_RDONLY` and
available `O_NOFOLLOW`, `O_NONBLOCK` and `O_CLOEXEC`. Windows uses binary opening,
repeated ancestry/lstat/fstat checks and recognized reparse-point rejection without
pywin32. This Windows fallback is weaker than kernel-enforced no-follow traversal
and cannot exclude every transient link/directory race. Windows may prohibit moving
or unlinking an open archive; normal downloads, ranges and close-before-delete work.

A pinned descriptor fixes file identity, not immutable contents. Observable changes
during validation reject acquisition, and later pathname replacement cannot redirect
an accepted stream. Concurrent writes to the same inode after validation can still
affect transmitted bytes; a descriptor is not a filesystem snapshot or cryptographic
authenticity guarantee. No heavy full-ZIP buffering is introduced to claim otherwise.
No schema, durable lease, dependency, converter, frontend or public API changes are
introduced. Schema remains v3. [Source pinning during ZIP packaging](mvp3-batch-archive-source-integrity.md),
original input fingerprints, converted-output integrity and output budgets remain
separate, unchanged controls.
