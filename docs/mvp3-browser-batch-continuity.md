# Browser batch continuity

## Why

A component-local capability disappeared when BatchToolWorkspace unmounted on return to the catalog. Durable server batches could outlive browser access to them.

## In-memory continuity

App owns a separate BatchSessionHandle for each of the four batch tools in React state. Each accepted handle contains the snapshot and its original access token. Navigation preserves handles; independent app instances do not share them. A bound workspace requires successful server deletion before starting another batch. Back is disabled until creation returns and App registers the accepted handle.

## Revalidation

Reopening a workspace fetches authoritative GET status with the original BatchId and X-DocuForge-Batch-Token header. BatchId and exact server operation must match the selected tool. Mutations and download remain disabled until validation succeeds. Polling runs only while mounted, stops for terminal phases, and shares a request lock with explicit actions. Unmount cancels timers and invalidates late responses, including under StrictMode.

## Manual recovery key

Copy recovery key explicitly writes `DFB1:<canonical-uuid>:<opaque-url-safe-capability>` to the clipboard. The parser requires version 1, a canonical UUID, a nonempty URL-safe token of at most 256 characters, and at most 298 characters overall. It rejects extra separators, unknown versions, whitespace and control characters before any network request.

After reload, open the matching tool, select Resume a batch, paste into the labeled password field and select Resume. This only calls existing GET status; both returned identity and operation must match before attachment. Success or dismissal clears the typed key. A wrong-tool key causes a safe error without attachment or mutation.

## Credential confidentiality

Anyone with this key can access this batch until it expires or is deleted. Keep it private.

Copying requires an explicit click and confirmation waits for clipboard success. Failed copying leaves the handle valid. Clipboard content may be visible to other software and can remain after deletion. Keys are never automatically displayed. The only credential entry is the explicit password-type resume form with autocomplete disabled. Capabilities stay in application memory and private request headers, outside URLs, history, analytics, logs and DOM attributes.

## Failure and expiry

Transient reentry errors preserve the same handle and offer Retry status. A private `404 batch_not_found` clears the stale handle and reports that the batch may have expired or been deleted. This also applies to later status checks of terminal batches. Manual resume uses a generic unavailable-or-invalid message for private 404s and retains the typed key for a network retry while the form remains open. Successful deletion clears only that tool's matching handle. Failed deletion preserves the snapshot and capability.

## Boundaries

There is no automatic capability persistence in localStorage, sessionStorage, IndexedDB or cookies, no automatic reload restoration, no account recovery and no server token lookup. After reload, access requires a previously copied recovery key. If it is lost, the app cannot retrieve it. Closing or refreshing before creation returns the accepted handle can lose the unreturned credential. Server TTL and explicit deletion still control resource lifetime; navigation does not extend TTL.

Backend endpoints, schema v3, capability generation, storage and integrity checks remain unchanged. All fourteen existing production smoke markers remain backend checks; browser continuity is covered by frontend unit tests and real full-stack Chromium scenarios.
