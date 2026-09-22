# Private batch access

## Purpose

Durable batch sessions outlive one HTTP request. A `BatchId` is stable session identity, while a
separate random capability authorizes access to retained status, controls, and files.

## Creation

Successful batch creation returns the capability once in the `X-DocuForge-Batch-Token` response
header. The `Location` header contains only the BatchId. Creation responses use
`Cache-Control: no-store`.

## Protected operations

The same `X-DocuForge-Batch-Token` request header is required for status, cancellation, recovery,
ZIP download, and explicit terminal-session deletion. Missing, malformed, or incorrect tokens have the same `404 batch_not_found`
response as an unknown BatchId.

## Storage

Plaintext tokens are never persisted. SQLite stores only a canonical SHA-256 digest in a distinct
session column, and authorization uses constant-time digest comparison. Neither tokens nor hashes
appear in API JSON, URLs, filenames, archives, or logs.

## Browser behavior

The browser keeps the capability only in React component memory while the active batch workspace
is open. It is never written to local storage, session storage, IndexedDB, cookies, URLs, history,
DOM attributes, or visible text. Reloading or navigating away loses control of that anonymous
batch.

## Migration

Opening a schema-v1 durable database performs an explicit transactional migration to schema v2.
Pre-token records and their corresponding workspaces are then removed because no secure
capability was ever issued for them. The migration does not derive authority from BatchId and
does not reset the database.

## Logging

Normal structured request paths replace the UUID segment immediately following `/batches/` with
`{batch_id}`, including under a custom API prefix. Token headers are never logged.

## Boundary

This is anonymous capability-based access. It is not account authentication, user identity, role
authorization, permanent session history, JWT, or OAuth.
