# Retained batch archive integrity

Packaging validates ZIPs at publication, and durable restart already revalidates retained archives. Live downloads previously checked only path availability; acquisition now uses the same strong retained ZIP checks.

After capability authorization, new download acquisition revalidates the retained ZIP under the service lock before creating a reader pin or streaming. Restart restoration uses the same `archive_is_valid` validator. `download_path` also validates, but provides no lifetime guarantee.

Checks require a regular, non-symlink `result.zip` at the canonical workspace path, exact ordered names derived from retained successful outputs, no duplicate names, no directories, no encrypted members, and ZIP_DEFLATED compression. Reading and CRC verification must succeed. Malformed ZIP and filesystem/ZIP exceptions fail closed.

An invalid or missing READY archive becomes ERROR / `batch_packaging_failed` ("The batch outputs could not be packaged."). Conversion results, output files, item failures, attempt, capability, and terminal `updated_at` remain retained. Durable degradation is persisted before live mutation; persistence failure returns the existing 503 without changing live state or accepting a download. Invalid downloads return 409 / `batch_packaging_failed` ("The batch archive is unavailable."). Existing ERROR sessions retain their original error while their invalid archive reference is cleared.

Packaging-only recovery reconstructs `result.zip` without reconversion. Partial batches retain successful outputs and failed items; after packaging recovery, selective item recovery remains available. All-failed batches retain `batch_has_no_outputs`; active execution retains `batch_not_ready`.

Wrong capabilities receive the private 404 before any archive scanning or integrity mutation. Status polling and the TTL sweeper do not CRC-scan archives. Success and failure do not extend retention. Already accepted pinned streams are not retroactively revoked by later validation.

This provides structural and ZIP-integrity revalidation, with no cryptographic digest, hostile-filesystem tamper-proof guarantee, continuous monitoring, or completed-output reset/revalidation. Concurrent privileged filesystem replacement remains outside this guarantee.
