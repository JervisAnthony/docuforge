# Durable storage pressure

## Purpose

TTL controls terminal retention age, but valid traffic can consume durable storage faster than
retention reclaims it. The durable filesystem headroom guard refuses new work at controlled write
boundaries. Ephemeral batches and generic single-request uploads remain outside this guard.

## Minimum free-space floor

`DOCUFORGE_BATCH_MIN_FREE_STORAGE_BYTES` defaults to `209715200` bytes (200 MiB). It must be a
strict positive integer; blank, zero, negative, boolean, fractional and unit-suffixed values fail
safely. Direct settings and service constructor values also reject booleans, floats and strings.
Keeping the reserve at least around the maximum batch upload size is recommended, not required.

## Creation admission

Before creating a durable workspace or taking execution admission, the service attempts existing
tombstone and eligible TTL cleanup, then requires measured free bytes minus pending upload writes
to cover the minimum free floor plus one maximum batch upload request. The defaults therefore
require approximately 400 MiB. This is a conservative admission check, not a permanent reservation
for all possible future uploads. Failed reclamation does not prevent admission if enough space
still exists. Existing execution admission limits continue to apply.

## Streaming uploads

Each batch chunk is size-validated before a process-local reservation checks:

`measured_free - pending_writes - chunk_bytes >= minimum_free_floor`.

Reservations are synchronized under the service lock. Writes are flushed before successful release,
and reservations unwind on exceptions. They reduce concurrent upload oversubscription of one
observed free-space value. Rejected uploads remove their partial file and abandon the workspace
and admission reservation; no session row or capability is issued. Shutdown drains outstanding
reservations before releasing durable storage ownership.

## Execution and packaging

Headroom is rechecked before queued conversion and before ZIP packaging, without another maximum
upload allowance. Conversion refusal becomes a recoverable ERROR and releases execution admission.
Packaging refusal preserves the trustworthy result, successful outputs and item state, with no
archive. After capacity returns, those errors support packaging-only recovery without conversion.
Storage pressure is separate from user cancellation.

## Recovery

Recovery checks the minimum floor minus pending writes before changing attempt, phase, result,
archive, persistence or admission. Pressure and inspection failure preserve terminal state.
After headroom returns, recovery uses the existing BatchId and capability. Status, download,
explicit DELETE and cancellation remain available under pressure; health and readiness are unchanged.

## Reclamation

Only committed DELETING and TTL-eligible terminal sessions are automatically reclaimed. Periodic
retention responsibilities remain unchanged. Low space never shortens TTL or evicts unexpired
READY/ERROR sessions, active sessions or preparing uploads.

## Errors

- `507 batch_storage_pressure`: `Batch storage is temporarily full. Try again later.`
- `503 batch_storage_unavailable`: `Batch storage is temporarily unavailable. Try again later.`

The second error means capacity inspection failed or returned an invalid value. Responses do not
expose capacities, thresholds, paths, drive details or raw filesystem errors, and include no guessed
Retry-After. Worker errors use the same safe codes and messages. Existing private-route no-store
behavior remains. No storage metrics endpoint is added.

## Boundary

This is NOT a hard byte quota. Converter staging can temporarily consume additional space between
checks because output expansion is not always predictable before conversion. The guard does not
guarantee that transient filesystem exhaustion or reserve crossing can never occur, including
from other processes. It does not add pre-TTL eviction or converter-specific quotas.
