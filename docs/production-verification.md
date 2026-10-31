# Production verification

After Vercel and Railway are public, run the DocuForge production verifier with the two HTTPS origins.

The repository includes a manually triggered **Production Smoke** GitHub Actions workflow. It
first confirms that Railway reports the same release version as the checked-out code, then checks:

1. frontend availability
2. API readiness
3. LibreOffice and Tesseract runtime capabilities
4. liveness, response headers, and browser CORS behavior
5. PDF merge semantics
6. image compression semantics
7. Office DOCX-to-PDF execution
8. OCR image-to-text execution

Every conversion check uses a small generated, non-sensitive fixture. The Office result must be a
parseable PDF and the OCR result must be valid UTF-8; OCR text is not benchmarked for exact
recognition.

The CI **Production runtime image** job also runs synthetic durable storage ownership, batch restart,
deletion and idle TTL checks inside the production container. It reports `PASS batch-storage-owner-lock`,
`PASS batch-admission-control`, `PASS batch-session-restart`, `PASS batch-session-delete`, and
`PASS batch-ttl-sweeper`, and `PASS batch-storage-pressure`, verifies non-root
SQLite/workspace access, and confirms a wrong capability is rejected. Its output remains generic
and never prints capability values. Public Production Smoke does not restart the deployed Railway
service.

CI also runs the focused **Windows durable storage ownership** job on Windows with Python 3.13,
alongside the Linux production-image verification.

Normal pushes and pull requests do not send traffic to the public deployment.

After the automated checks pass, run one PDF, image, Office, and OCR tool in the browser, confirm
the downloads open correctly, and hard-refresh the application once to confirm the catalog
reloads.

See `docs/mvp1-launch.md` for the complete MVP1 go/no-go sequence.

The durable smoke must additionally report `PASS batch-download-lifecycle`, verifying immediate logical deletion and deferred physical cleanup of a pinned archive.

The durable smoke must report `PASS batch-archive-integrity`, verifying fail-closed acquisition and packaging-only repair of a corrupted retained archive.

The durable smoke must also report `PASS batch-output-integrity`: corrupt a retained image after shutdown, restore a recoverable integrity error with the same capability, fully retry from uploads, validate the fresh output/archive, and delete normally. Together with the two runtime engine checks, the image reports twelve PASS markers.

Require `PASS batch-worker-publication` for a controlled worker READY-save failure with no false success and successful recovery. Together with existing runtime/batch checks, the production image reports thirteen PASS markers. See [worker state publication](mvp3-worker-state-publication.md).

Require `PASS batch-input-integrity`: durable restart, refusal of same-length altered uploads without state/reset/attempt mutation, exact-byte restoration, successful recovery, and normal deletion. The production image now reports fourteen PASS markers. See [input integrity](mvp3-batch-input-integrity.md).

Require `PASS batch-archive-source-pinning`: package stable synthetic outputs,
verify bytes and CRC, inject a regular-file replacement before descriptor opening,
require safe rejection, preserve the previous ZIP and external sentinel, and clean
staging. The production image now reports fifteen PASS markers (two runtime engine
checks plus thirteen batch checks). See [safe ZIP source pinning](mvp3-batch-archive-source-integrity.md).

Require `PASS batch-download-descriptor-pinning`: acquire a validated synthetic ZIP
reader, verify its identity, exercise path replacement where supported, reject a
second response pathname open/pathsend, verify transmitted ZIP bytes and CRC, close
the reader, clear pins and delete normally. The production image now reports sixteen
PASS markers (two engine checks plus fourteen batch checks). See
[verified ZIP downloads](mvp3-batch-verified-downloads.md).

Require `PASS batch-download-admission`: fill a low synthetic reader limit,
reject another acquisition before archive opening without changing durable state
or existing readers, release/reuse a slot, verify descriptor ZIP bytes/CRC, release
all pins and delete normally. The current production image must emit **seventeen**
PASS markers (two engine checks plus fifteen batch checks). See
[bounded download admission](mvp3-batch-download-admission.md).
