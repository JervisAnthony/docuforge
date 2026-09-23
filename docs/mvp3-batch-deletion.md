# Batch session deletion

## Purpose

Capability holders can explicitly remove terminal retained batch sessions before TTL expiry.

## API

Send `DELETE /api/v1/batches/{BatchId}` with `X-DocuForge-Batch-Token`. Success returns `204 No
Content`. Missing, malformed, incorrect, and cross-session capabilities use the same indistinguishable
`404 batch_not_found` response as an unknown BatchId.

## Active sessions

Deletion is limited to READY and ERROR sessions. Active sessions return `409 batch_not_deletable`;
the user can cancel first, wait for a terminal state, and then delete.

## Crash safety

Durable deletion first persists an internal DELETING tombstone, then removes the workspace, then
removes SQLite metadata. The tombstone immediately hides the session from status, control, recovery,
and download operations. A failed cleanup can be retried with the same capability. Startup completes
committed deletion intents before restoring ordinary sessions and fails closed if cleanup cannot be
completed.

## Browser

Terminal sessions expose **Delete batch** with an inline irreversible-action confirmation. After a
successful deletion, the browser clears its in-memory capability, current session, and selected files.

## TTL

Terminal TTL remains the automatic fallback and uses the same tombstone-first cleanup ordering.

## Storage guarantee

Deletion removes application metadata and session files from DocuForge-managed session storage.
Filesystem and storage-provider retention, physical media sanitization, and backups remain outside
this process-level guarantee.

## Boundary

This feature does not add accounts, history, trash or undo, distributed deletion, or object storage.
