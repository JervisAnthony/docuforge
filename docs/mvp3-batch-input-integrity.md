# Original upload integrity

Newly accepted batches record an immutable private fingerprint for every original
upload: ordered item identity, actual byte count, and a lowercase SHA-256 digest.
Capture happens after upload completion and request validation, before registration
or worker submission. Unreadable or unsafe originals reject acceptance with
`503 batch_input_unavailable` and “The uploaded batch inputs could not be verified.
Try again later.” Existing route abandonment removes the workspace and releases admission.

Hashing streams at most 1 MiB per read. It counts bytes rather than trusting upload
headers or file-size hints. The verifier checks canonical inputs containment, each
parent directory, non-symlink regular nodes, open-descriptor identity and stable
size/timestamps around the read. Where supported it uses O_NOFOLLOW and O_NONBLOCK.
Windows reparse points are rejected; Windows path/descriptor ctime differences are
excluded from consistency comparison. File identity, size, mtime and digest checks
remain in force. Zero-length files can be fingerprinted; conversion policy remains
responsible for whether their contents are usable.

## Conversion and recovery

Before first conversion and every queued conversion retry, the worker compares all
original inputs against their accepted manifest. It applies existing worker identity,
cancellation, and atomic error-publication rules. Failed verification prevents converter
invocation and produces safe `ERROR / batch_input_integrity_failed` with
“The original batch inputs could not be verified.” Admission is released normally.

Recovery requiring converters verifies the complete manifest after authorization,
eligibility and active-download rejection, before output reuse checks, storage/admission,
generated reset, queued publication or submission. Failure returns `409` with the same
safe input-integrity code/message and leaves phase, result, archive, BatchId, capability,
attempt, timestamp, generated files, manifest and durable row unchanged. Restoring the
exact accepted bytes permits retry; changed uploads are never silently re-enrolled.

A genuine packaging-only retry uses trusted converted outputs and does not hash inputs.
If output validation instead requires full retry, original inputs must verify before
any degradation or reset. Worker start rechecks after recovery admission, covering
changes while the attempt waited in the queue. These are reuse checks, not continuous
filesystem monitoring; status, download, TTL and deletion do not scan input contents.

## Completed artifacts and restart

Valid retained ZIPs remain downloadable when originals change or disappear. ZIP
download validation remains independent of upload fingerprints. Safe lexical input
paths can restore without existing input files or directories, while absolute paths,
drive/UNC paths, traversal and paths outside canonical inputs remain invalid metadata.
Retained result inputs must still match request inputs exactly; converted-output trust
checks remain authoritative. One unavailable original does not block healthy siblings.

## Schema version 3

The existing SQLite row adds nullable `input_manifest_json`, encoded deterministically
as version 1 JSON with algorithm `sha256` and ordered item fingerprints. New sessions
always save a complete manifest. Wrong types, identities, order, algorithm, fields,
lengths or digests are startup-fatal metadata errors, separate from unavailable files.

Under the existing owner lock, v2 databases migrate in one immediate transaction: add
the column, advance row schema versions and PRAGMA user_version to 3, then commit.
Failure rolls the transaction back for retry. Version 1 migrates directly to 3 and
retains pre-capability cleanup. Historical rows retain NULL manifests: migration and
retry never invent fingerprints of potentially changed old inputs. Legacy conversions
retain structural containment, node and readable-descriptor checks without claiming
historical byte verification. Schema changes add no settings or dependencies.

## Safety boundary

SHA-256 detects a difference between current input bytes and the digest recorded when
DocuForge accepted the upload. It does not prove authenticity if an attacker can replace
both filesystem content and the SQLite fingerprint. This is not a signed manifest,
remote attestation, hostile-root-filesystem protection, immutable object storage,
cryptographic chain of custody, or distributed integrity service. Simultaneous hostile
filesystem mutation is not absolutely prevented on every platform. Digests, filenames,
paths, capabilities and diagnostics remain private; errors never reveal comparisons.
