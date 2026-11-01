# Nonblocking ZIP download validation

`acquire_download()` previously held the service-wide `RLock` while opening the
archive, scanning ZIP structure and CRC, constructing a handle, and registering
its reader pin. Large retained ZIPs could therefore delay unrelated status,
cancellation, upload admission, deletion, and retention operations.

Acquisition now uses admission, off-lock validation, and final atomic promotion.
The route remains synchronous and uses the existing FastAPI execution model;
there is no additional production executor or validation queue.

## Admission and temporary ownership

Under the service lock, acquisition rejects shutdown, authenticates the private
capability, checks phase/output eligibility and known archive availability, and
checks global and per-batch reader capacity. It then inserts a unique provisional
pin in `_active_downloads: dict[str, set[str]]` before releasing the lock. It
captures the original session object, phase, attempt, retained result, archive
path, workspace, cancellation identity and cancellation state, and session error.

The defaults remain eight global readers and four per batch, configured by
`DOCUFORGE_BATCH_MAX_ACTIVE_DOWNLOADS` and
`DOCUFORGE_BATCH_MAX_DOWNLOADS_PER_BATCH`. Both pending validations and accepted
streams count against those same limits. The capacity check and insertion are
atomic. No separate mutable counter, persistent lease, or pending table exists.

Invalid, missing, malformed, or cross-session capabilities receive private
`404 batch_not_found` before pin registration, opening, scanning, or capacity
disclosure. Existing eligibility precedence is preserved: active phases return
`409 batch_not_ready`; deleting or expired sessions return private 404; no outputs
returns `409 batch_has_no_outputs`; known missing retained result/archive uses
`409 batch_packaging_failed`, or `503 batch_persistence_failed` if its required
durable update cannot commit. Known-unavailable handling precedes capacity.

An otherwise eligible excess request receives
`503 batch_download_capacity_exceeded` with the unchanged message:
“The batch download service is temporarily at capacity. Try again later.”
It performs no archive opening or CRC scan and registers no pin. Counts and
configured limits are not exposed.

## Off-lock validation and promotion

The acquisition attempt initially owns no descriptor. Outside the service lock,
the existing secure canonical-archive helper opens a reader, checks source and
descriptor identity, scans real ZIP structure and CRC through that reader, then
rechecks the descriptor, path, and parent directories. The helper owns and closes
any unsuccessfully validated reader. On success it transfers that reader to the
acquisition attempt.

Promotion reacquires the service lock and checks shutdown, authorization and
expiry, original session object identity, phase, attempt number, result identity,
archive path, workspace, cancellation identity/state, and session error. Polling
status alone does not invalidate acquisition. Irrelevant mutable fields and the
retention timestamp are not compared or refreshed.

Only an unchanged eligible session can receive a `BatchDownloadHandle`. Promotion
transfers the exact validated reader and retains the exact provisional pin. It
does not remove/reinsert the pin, create a capacity gap, count twice, reopen the
path, or repeat the CRC scan. The handle then owns the reader until normal,
idempotent release. Its cursor lock is independent of other handles and the
service lock.

## Deletion, retention, recovery, and shutdown

A provisional pin participates in the existing reader lifecycle:

- DELETE persists the DELETING tombstone before publishing it. New access is
  denied immediately; physical cleanup waits for provisional and accepted pins.
  A pending validation cannot promote after tombstoning, even if its ZIP is valid.
- Terminal TTL processing can proceed while CRC work is stalled. Promotion checks
  expiry again even if no other operation ran during validation. Expired sessions
  cannot be resurrected, and attempting validation does not extend retention.
- Recovery of an otherwise recoverable session returns `409 batch_download_active`
  while a provisional pin protects its archive. No conversion/reset can begin
  during that protected interval. After failed validation releases its pin,
  recovery follows the resulting authoritative state.
- Shutdown enters its shutdown state without waiting for CRC to release the
  service lock, then waits for all provisional and accepted pins before releasing
  durable storage ownership. Validation completing after shutdown cannot promote.
  Shutdown still waits for an in-progress validation to return; this does not
  forcibly interrupt a blocked filesystem read.

Previously promoted streams retain their existing deletion/draining behavior.
Ephemeral and durable services use the same process-local pin registry. Pins are
never persisted: after process termination, existing restoration and tombstone
reconciliation remain authoritative. SQLite `SCHEMA_VERSION` remains 3.

## Failure cleanup

Validation failure reacquires the lock and checks the expected session before
applying the existing archive-failure transition. READY degrades to recoverable
ERROR only after a required durable save succeeds. A failed save returns safe
`503 batch_persistence_failed` and leaves the original live archive/result state
authoritative. Deletion or expiry wins over either successful or failed CRC work;
failure cannot overwrite a committed tombstone with ERROR.

Failed promotion is separate from archive corruption. Unexpected exceptions
propagate while `finally` closes the attempt-owned reader before releasing its
pin. Expected close errors retain a generic warning without filesystem details.
Handle-construction failure follows the same ordering. Partial insertion rollback
removes only the newly generated pin, including insertion that mutates before
raising; it also removes empty registry entries. Release uses the built-in set
discard operation so a failing set override cannot strand a reservation.
The last pin release can trigger deferred deletion only after reader closure.

## Compatibility, verification, and limits

The existing response API, ZIP bytes, filename, Content-Length,
Content-Disposition, Accept-Ranges, ZIP content type and `Cache-Control: no-store`
remain unchanged. Full, single/open/suffix/multipart ranges, If-Range,
unsatisfiable/malformed ranges and applicable HEAD behavior retain descriptor
streaming. No pathname reopening, FileResponse pathsend fallback, frontend
product change, dependency change or schema migration is introduced.

Event-controlled tests pause a real descriptor scan and exercise status, upload
admission, cancellation, another validation, bounded capacity, DELETE, TTL,
recovery, shutdown, promotion identity changes, durable persistence failure and
independent accepted streams. The descriptor suite continues to check real CRC,
same-descriptor transmission and cleanup on source/metadata/recheck failures.
Windows CI now runs concurrency, descriptor and lifecycle tests alongside durable
storage ownership. POSIX directory-descriptor/no-follow protection remains in the
existing helper; Windows retains its available node/identity rechecks and deferred
deletion while readers are open. Unsupported FIFO and open-file unlink tests keep
their platform skips; core lock-release and admission tests run on both systems.

Production smoke independently requires
`PASS batch-download-validation-concurrency`: reserve the only slot during a paused
real scan, complete authorized status, reject excess acquisition before opening,
promote the original reader/pin, validate returned ZIP bytes, release, and delete.
Together with existing runtime and durable checks, eighteen markers are required.

Permitted CRC scans still consume CPU, disk I/O, file descriptors, and memory.
Admission bounds concurrent scans plus streams; it does not guarantee response
latency, FIFO fairness, unlimited parallelism or preemption of slow I/O. Other
service operations may still perform their own storage work under the lock.
The storage root must remain private and trusted. Descriptor pinning does not
make concurrent in-place archive mutation by a privileged local writer safe, nor
does it add multiprocess/distributed storage coordination.
