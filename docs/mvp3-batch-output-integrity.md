# Retained converted output integrity

Retained outputs are validated before selective or packaging-only recovery reuses a
previous result, and when a durable session restores that result. Status polling
does not scan outputs. The shared dispatch helper uses the existing image and PDF
validators. Images require the expected identity, path, format, single frame, and
successful Pillow decode. PDFs require the expected identity, path, source format,
regular nonempty file, and `%PDF-` signature; this is not a full PDF parser.

Trusted outputs retain selective or packaging-only recovery. Any untrusted completed
output discards the entire reusable result and archive reference. The session becomes
`ERROR` with `batch_output_integrity_failed` and the safe message:
“The retained batch outputs could not be verified. Retry the batch.”
Recovery then runs every item from the original uploads, preserving BatchId,
capability, request, and workspace identity. The new queued attempt increments once.

Authorization and active-download rejection precede scanning. Storage headroom and
execution admission precede mutation or filesystem reset. Rejection at either gate
leaves state, durable metadata, files, and attempt unchanged.

## Crash safety

Durable integrity degradation commits `result_json = NULL`, archive unavailable,
and the integrity error before live references change or generated files are reset.
The original terminal timestamp and attempt remain unchanged. Persistence failure
returns `503 batch_persistence_failed` without changing live state or files.
Ephemeral sessions apply the same logical transition without persistence.

Every full retry resets outputs and `result.zip` before worker submission, including
interrupted executions with no result. Packaging-only retry clears only the archive.
Fixed generated nodes may be files, directories, symlinks, or removable special
nodes; resets remove the nodes without following symlink targets. Inputs are preserved.
Reset is idempotent and recreates a real empty outputs directory.

Reset failures return `503 batch_recovery_failed` with
“The batch could not be prepared for recovery. Try again later.” No Retry-After
header is added. Admission is released and the attempt does not increment. An
already committed integrity error remains recoverable; another retry attempts reset
again. Submission or queued-persistence failures cannot resurrect discarded results.

## Restart

Structurally valid metadata with corrupt retained image/PDF files restores as a
recoverable integrity error and is persisted without result/archive references.
Healthy sibling sessions restore normally. Malformed JSON, domain state, identities,
operations, request/result pairs, or serialized paths remain startup-fatal persistence
errors. Expired terminal sessions follow existing retention cleanup before decoding.
Schema v3 preserves these output-integrity rules; there are no new settings or dependencies.

## Boundary

[Archive integrity](mvp3-batch-archive-integrity.md) separately validates the ZIP
served to downloads. A valid archive remains downloadable even if a converted source
output later changes. Existing download pins remain authoritative.

Converted-output validation adds no output hashes or continuous scanner. Separately,
[input integrity](mvp3-batch-input-integrity.md) records SHA-256 fingerprints of new
original uploads before conversion. Valid ZIPs and genuine packaging-only recovery
remain independent of original-file availability. Neither boundary claims a hostile-
filesystem tamper guarantee.
