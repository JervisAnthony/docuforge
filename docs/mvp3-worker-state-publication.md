# Atomic worker state publication

Live-first mutation could let API readers observe a checkpoint that SQLite never
committed. Worker checkpoints now construct a candidate with `dataclasses.replace`,
encode and save it under the service lock, then apply only worker-owned fields to
the existing session. Session identity, capability, request, workspace, attempt,
and cancellation-token identity remain stable. Ephemeral sessions use the same
publication path without SQLite.

The checkpoints are:

- **PROCESSING:** check storage headroom, retain committed cancellation intent,
  clear a selective attempt's old result reference, save, publish, then convert.
- **Progress:** verify attempt and cancellation-token identity, save the new
  immutable Batch and timestamp, then publish. Committed CANCELLING cannot become
  PROCESSING because of subsequent progress. A failed save aborts the attempt.
- **PACKAGING:** save the complete conversion result before publishing it or
  constructing a ZIP. Packaging-only retry also saves PACKAGING first and keeps
  its trusted result without rerunning conversion.
- **READY:** save the result, batch, archive reference (or None for no outputs),
  cleared session error, and timestamp before publishing success and releasing
  admission. ZIP construction alone cannot publish READY or download availability.
- **ERROR:** build a safe error candidate, preserve a trustworthy complete result
  when available, and save before publishing. Without a usable result, terminalize
  unfinished items. Storage errors keep their existing safe codes. A selective
  progress failure can retain the previous coherent terminal result for retry.

Cancellation still saves its intent before requesting cancellation on the live
token. The same lock serializes it with worker checkpoints. Old workers and old
progress callbacks cannot publish into a newer token/attempt, even when the numeric
attempt is reused after an unsuccessful queued publication.

## Complete SQLite failure

If the safe ERROR save also fails, the worker stops and releases admission. It
publishes only a best-effort in-memory ERROR marked `batch_persistence_failed`,
without an archive reference or private diagnostics. There is no guarantee of
durable error publication when SQLite itself is unavailable. Memory and SQLite
can differ at this explicit fallback boundary; there is no persistence busy loop.

Restart trusts the last successful SQLite commit. QUEUED/PROCESSING restore through
execution-interrupted recovery; PACKAGING with a trustworthy result restores through
packaging-interrupted recovery; READY revalidates retained artifacts; ERROR restores
its committed safe error. Full retry resets generated files before running original
uploads. Trusted selective and packaging recovery keep their existing reuse rules.

## Architecture boundary

This is atomic application publication relative to successful SQLite saves. It is
not a distributed transaction between SQLite and the filesystem. Uploaded inputs
and converted outputs remain separate filesystem artifacts, and unpublished files
may survive a failed checkpoint until full retry cleans them. The existing exclusive
single-owner service, schema version 3, storage/admission gates, output budget,
retention, deletion, and download/integrity protections remain authoritative.

The durable production smoke reports `PASS batch-worker-publication` after normal
READY convergence and a controlled READY-save failure followed by packaging recovery.
