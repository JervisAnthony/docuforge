# Durable batch sessions

## Purpose

Commit 56 adds optional restart durability to batch execution sessions. When configured, SQLite
stores session metadata and isolated filesystem workspaces retain inputs, validated outputs, and
the result archive. This is a post-MVP2 production-hardening change, not an extension of the
completed MVP2 batch roadmap.

## Storage model

The configured root contains the stable `batch-storage.lock` owner-lock file,
`batch-sessions.sqlite3`, and `sessions/<BatchId>/`. Each UUID-backed session directory has per-item
`inputs/`, deterministic `outputs/`, and `result.zip`. SQLite stores versioned, explicit JSON
metadata and relative artifact paths; absolute filesystem paths are never authoritative persisted
state.

Durability does not make BatchId sufficient authority. See
[Private batch access](mvp3-batch-access.md) for the per-session capability required to read or
control a retained session.

## Restart behavior

- READY sessions restore their status and validated ZIP download without reconversion.
- Partial terminal results restore validated successful outputs and can selectively retry failed or
  cancelled items with the same BatchId.
- Stored execution and packaging errors retain their safe recovery behavior.
- Work interrupted during conversion becomes a safe error offering **Retry batch**. It is not
  automatically resumed and receives a fresh cancellation token on recovery.
- Work interrupted during packaging with a trustworthy result becomes a safe error offering
  **Retry packaging** without reconversion.
- A missing or corrupt archive becomes packaging-recoverable only after the typed result and
  outputs revalidate.

## TTL

Terminal TTL uses a persisted wall-clock `updated_at`. Expired terminal and error sessions are
removed at startup or access time, including both their SQLite metadata and session workspace.
Interrupted active sessions receive a fresh recovery window when restored as an error.
Durable startup also removes unregistered UUID BatchId workspaces, including uploads left by a
process failure before metadata registration, so rowless batch content does not remain unmanaged.

Users may explicitly delete terminal sessions before TTL expiry. Durable deletion persists an
internal DELETING tombstone before removing the workspace and metadata; startup finishes interrupted
deletions before restoring sessions. TTL remains the automatic fallback. This is application-level
removal and does not claim physical media overwriting or storage-provider backup deletion.

Preparing, queued, processing, cancelling, and packaging work is bounded by process-local
[batch admission control](mvp3-batch-admission.md). Retained READY, ERROR, and DELETING sessions do
not consume execution admission. Aggregate retained-storage capacity remains a separate operational
concern because terminal sessions may remain until explicit deletion or TTL expiry.

## Production storage

The production image configures `DOCUFORGE_BATCH_STORAGE_DIRECTORY=/var/lib/docuforge` and grants
the non-root `docuforge` user access. Persistence survives an application-process restart while
the underlying filesystem remains. Surviving container replacement or redeployment requires a
persistent volume mounted at `/var/lib/docuforge`; the container filesystem alone is not durable
across replacement.

## Safety

- Persistence uses strict JSON encoders/decoders and never uses pickle.
- SQLite writes are parameterized and transactionally replace logical records.
- Persisted artifact paths are relative and checked for POSIX/Windows traversal, drive/UNC paths,
  symlinks, and workspace containment.
- Restored image, PDF, and ZIP artifacts are revalidated before use.
- Files are published and validated before metadata references them.
- Status and error responses do not expose storage paths, SQL, serialized state, or database
  diagnostics.
- SQLite stores only the SHA-256 access-token hash; plaintext capabilities are never persisted.
- Batch files may remain on disk until explicit deletion, terminal TTL expiry, or internal expiry cleanup. Single-file
  request workspaces remain request-scoped.

## Boundary

This is durable single-process orchestration. One DocuForge API process owns the bounded in-process
executor and holds an exclusive operating-system lock for the durable storage root throughout the
service lifetime. A competing process fails during startup before it opens SQLite or restores
sessions. This does not provide distributed execution, multi-worker coordination, queue-backed
processing, leasing, heartbeats, fencing, or cross-process cancellation.

See [Durable storage ownership](mvp3-durable-storage-ownership.md) for lock lifecycle and operator
guidance.
