# Durable storage ownership

## Purpose

DocuForge's durable batch service combines SQLite metadata with an in-memory session registry,
cancellation state, a bounded executor, and filesystem workspaces. SQLite transaction locking alone
cannot coordinate those resources between API processes. DocuForge therefore permits one live
process to own each durable batch-storage root.

## Lock model

The storage root contains a stable `batch-storage.lock` regular file. The service opens it with
private `0o600` creation permissions where supported, makes the descriptor non-inheritable, and
holds an exclusive non-blocking operating-system lock for its full lifetime. POSIX uses
`fcntl.flock(LOCK_EX | LOCK_NB)`; Windows uses `msvcrt.locking(LK_NBLCK)` over one constant byte.
Both implementations use only the Python standard library.

The operating-system lock is authoritative. The file contains no PID, path, capability, or request
data.

## Crash behavior

The lock file remains in place and is reused after orderly shutdown or a crash; DocuForge never
deletes it as stale metadata. Orderly shutdown explicitly unlocks before closing the descriptor.
After abnormal process termination, the operating system releases the abandoned lock. On Windows,
that release may not become observable immediately. Production acquisition remains fail-fast: a
replacement started during this short cleanup interval may receive the normal "already in use"
error. Verify the old process has exited, wait briefly, and retry startup. Do not delete
`batch-storage.lock`.

## Startup behavior

DocuForge validates that the configured root is a real directory and that the lock node is a regular
file rather than a symlink or another node type. It acquires ownership before initializing SQLite,
creating the session tree, completing deletion tombstones, reconciling workspaces, or restoring
sessions. A competing process fails immediately with a safe generic error and performs none of
those operations. If initialization fails after acquisition, constructor cleanup releases the lock.

## Shutdown

Shutdown first requests cancellation, joins the executor, preserves durable state, and clears the
in-memory registry. It releases storage ownership only after those operations finish. Release is
idempotent, and the stable lock file remains available for the next owner.

## Deployment

Run one Uvicorn process or replica for a given `DOCUFORGE_BATCH_STORAGE_DIRECTORY`. If multiple
workers intentionally target the same root, only the first can start. Stop the current owner before
starting its replacement. A replacement can acquire the same file and run the existing startup
recovery after the previous process exits. Do not remove the lock file. Separate processes can run
concurrently when each has a different durable root, and ephemeral services acquire no storage lock.

## Validation

The ownership tests cover same-process contention, real child-process contention, graceful immediate
release, bounded reacquisition after forced child termination, stable-file reuse, non-inheritable
descriptors, unsafe filesystem nodes, constructor failures, shutdown ordering, and independent roots. The production image smoke
reports `PASS batch-storage-owner-lock` before its restart and deletion markers. Current exact suite
totals are recorded in the Commit 59 pull request after validation.

## Deliberate boundary

This does not provide distributed execution, leases, heartbeats, fencing, multi-host consensus, or
queue infrastructure. DocuForge remains single-process by design.
