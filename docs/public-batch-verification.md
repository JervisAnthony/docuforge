# Public batch lifecycle verification

Project Commit 78 adds separate batch-readiness evidence. It does not change the
twenty-one public semantic checks, strict API/frontend identity contract, eighteen
production-image runtime/durable markers, or four-route Office/OCR integration.
Historical launch evidence and Pending gates remain unchanged. This is not a new
retroactive MVP1 release prerequisite.

## Public command and mutations

Install the ordinary package; the verifier needs no FastAPI, Pydantic, httpx,
LibreOffice or Tesseract on the client. The deployed API needs its existing engines.
Choose both expected full revisions independently from deployment records. Never
infer expectations from the endpoints or the verifier checkout.

```powershell
python -m docuforge.ops.batch_smoke `
  --api-url https://API_HOST `
  --frontend-url https://FRONTEND_HOST `
  --expected-api-revision <independently-expected-40-character-API-SHA> `
  --expected-frontend-revision <independently-expected-40-character-frontend-SHA> `
  --expected-version 0.1.0 `
  --timeout 20 --case-seconds 120 --suite-seconds 600 `
  --cleanup-seconds 60 --poll-interval 0.5 --max-polls 240 `
  --report-json batch-smoke.json
```

Invoking this command **creates and deletes synthetic sessions**. There is no
additional interactive confirmation. All configuration and the optional evidence
destination are checked before network/mutation. Strict Commit 76 identity
verification runs inside the command and must pass before the first creation.
Only HTTPS origins without paths, credentials, queries or fragments are accepted.
There is no insecure/local-origin switch. The direct transport ignores proxy
environment variables, follows no redirects (including same-origin redirects),
does not retry, and consumes/closes every response before returning it.

The separate **Production Batch Smoke** workflow is `workflow_dispatch` only. It
requires explicit origins and independent expected revisions, passes inputs through
environment variables and quoted arguments, has read-only repository permission,
and serializes its own runs without cancelling an earlier run. Its 20-minute job
timeout allows room beyond the default 600-second normal-work budget and bounded
cleanup. Summary rendering always runs and validates evidence plus step outcome
and the independently supplied deployment expectations. It uploads no artifacts.
The existing Production Smoke workflow remains unchanged. Normal PR/push CI makes
no public requests.

## Four sequential cases

| Identifier | Creation route | Operation and ZIP semantics |
| --- | --- | --- |
| `batch-image-convert` | `POST /api/v1/batches/images/convert` | `image.convert`; two JPEGs preserving 96×64 and 24×40 dimensions |
| `batch-image-resize` | `POST /api/v1/batches/images/resize` | `image.resize`; PNG within 48×48, yielding 48×32 and 24×40 without upscaling |
| `batch-image-compress` | `POST /api/v1/batches/images/compress` | `image.compress`; quality 70 JPEGs preserving source dimensions; no size-ratio claim |
| `batch-office-to-pdf` | `POST /api/v1/batches/office/to-pdf` | `office.to_pdf`; ordered DOCX/PPTX/XLSX converted to three unencrypted, parseable PDFs with corresponding synthetic text markers |

Requests use repeated multipart fields named `file`, two distinct synthetic images,
and the existing real Office fixture builders. Expected ZIP names follow the existing
position prefix rule: `0001-alpha.jpg`, `0002-bravo.jpg` for JPEG cases; corresponding
`.png` names for resize; `0001-alpha.pdf`, `0002-bravo.pdf`, `0003-charlie.pdf` for Office.
Expectations come from known requests, not returned filenames.
The ordered fixture tuple and frozen case records are shared in memory, including
the original DOCX bytes, so exact multipart checks do not depend on wall-clock ZIP
timestamp boundaries. Source names, fields, media types and content remain exact.

Each case validates 202 acceptance, JSON/no-store headers, canonical relative Location,
canonical UUID identity, matching JSON identity and private capability. It checks
missing and wrong capability status/download responses for exact private
`404 batch_not_found`, then verifies authorized access still works. Typed snapshots
must retain identity, operation, attempt 1, unique stable ordered item identities,
fixture descriptors, positions, result descriptors and consistent counts/progress.
The case accepts skipped intermediate phases and immediate completion, but only
successful `ready`/`completed`, progress 100, no item/session failures and downloadable
outputs satisfies the normal path.

ZIPs are read in memory and never extracted. Validation covers application/zip,
safe attachment basenames when supplied, exact ordered unique names, no directories,
encryption or unexpected members, CRC, decoding, formats, dimensions and PDF text.
Existing limits stay at 10 MiB per HTTP response, 2 MiB per ZIP member and 6 MiB total
uncompressed content. Customer upload, output and storage budgets are unchanged.

## Ownership, cleanup and uncertainty

At most one normal smoke batch is active. After the first failure, normal creation
stops and partial evidence is retained. Safe canonical Location/JSON candidates and
the private capability are registered before later acceptance/snapshot assertions.
Protected paths are constructed under the configured API origin; returned hosts,
arbitrary paths, queries and fragments are never used. A malformed Location can use
a valid JSON identity for cleanup and vice versa. Contradictory canonical identities
retain both candidates and attempt cleanup for both; an unverified candidate's 404
does not prove absence. A 200 authorized status with the matching identity establishes
that the capability works before an already-absent private 404 can confirm cleanup.

Every registered candidate receives cleanup in `finally`, including failures in
negative probes, snapshots, polling, conversion, archive validation, download or
unexpected exceptions. Downloads are fully closed first. Cleanup reads authorized
status and sends at most one cooperative cancel request when `can_cancel` is true.
Packaging and processing the final item can legitimately be non-cancellable; cleanup
polls that owned work toward `ready`/`error` within the same independent cleanup
deadline. If completion races with cancellation, only the exact no-store JSON
`409 batch_not_cancellable` contract is accepted as a reason to re-read authorized
status and continue waiting. Cancellation is never retried. Unrelated or malformed
409 responses, redirects and transport failures fail cleanup. Terminal work proceeds
to DELETE. Normal cleanup requires DELETE 204 and subsequent
authorized status and download returning exact no-store private 404 responses.
An already-absent session is accepted only after earlier validated authorized access
and that same safe absence contract. Redirects, HTML proxy errors, an unverified
capability or network failure never prove absence.

Cleanup is application-level logical deletion evidence, not secure erasure or proof
of physical volume removal. Existing accepted readers can defer physical deletion.
This verifier finishes its own download before deletion. Failure evidence preserves
the primary failure and separately records cleanup failure. All registered candidates
are attempted even if one cleanup fails. Any unconfirmed cleanup fails the suite.
Cancellation is used only for cleanup; cancellation/recovery correctness, restart
durability and browser recovery are not new public claims.

Creation is never automatically replayed after a timeout or ambiguous/lost reply.
If no usable identity/capability can be established, evidence records
`creation_uncertain`, ownership `UNCERTAIN` and cleanup `UNCONFIRMED`. A body-read
failure after 202 retains usable response headers for cleanup where possible.
Missing/invalid capabilities, unusable identities, transport loss before acceptance
headers, process kills or exhausted cleanup budgets can leave sessions behind.
The existing server terminal TTL (default 3600 seconds) and sweeper (default 60
seconds) are fallback retention cleanup, not immediate or verified cleanup. Active
work must reach terminal state before terminal TTL applies. The verifier does not
restart services, force worker termination or change retention/storage policies.

## Bounded timing and private evidence

Defaults: request timeout 20 seconds, per-case normal deadline 120 seconds,
suite normal deadline 600 seconds (including identity), separate cleanup deadline
60 seconds per candidate, poll interval 0.5 seconds, at most 240 poll attempts per
normal or cleanup loop. Requests are capped by remaining monotonic budget; sleeping
never exceeds it. The default transport checks the exchange deadline while reading
bounded response chunks and shuts down its client socket on the exchange deadline,
including trickling headers. Synchronous OS DNS resolution also depends on OS timeout
behavior; a process kill cannot guarantee cleanup.

All timing values must be finite, positive numbers, excluding booleans. Maximums
are 60/300/1200/120 seconds for request/case/suite/cleanup, poll interval is at least
0.01 and at most 5 seconds, and max polls is an integer from 1 through 1000. No
automatic retries occur for creation, recovery, cancellation or deletion.

Tokens live only in memory and only in the capability request header. Console,
reports and summaries contain no tokens, hashes, recovery keys, BatchIds, session
URLs, raw headers, filenames, document text, bodies, raw exceptions, engine
diagnostics or filesystem paths. Parser output is suppressed during untrusted
image/PDF/ZIP validation. Deployment origins, expected revisions/version, fixed
check names and stage/outcome codes are safe report fields.

`batch-smoke.json` uses schema version 1: mode, overall result, strict identity
outcome, validated deployment expectations for public mode, attempted/passed counts,
suite code, and exactly four fixed ordered check records. Each record carries
outcome, stage, code, ownership, cleanup and cleanup_code. Unattempted cases are
SKIPPED. Full PASS requires all four complete lifecycles with CONFIRMED cleanup;
four names, HTTP success, step success, local-mode evidence, missing or malformed
reports cannot establish public PASS. Reports are deliberately small and contain
no session-level identifiers. Exit status is nonzero on validation, identity,
transport, cleanup or evidence-write failure. Cleanup success never hides a primary
failure.

## Local tests and production-image evidence

Focused tests require no external HTTP or Office/Tesseract installation:

```text
python -m pytest tests/ops/test_batch_smoke.py tests/ops/test_batch_transport.py tests/ops/test_batch_outputs.py tests/ops/test_batch_summary.py tests/ops/test_batch_integration.py
```

They inject deterministic transport/clock behavior, exercise the default transport
against owned local listeners, and run real FastAPI image converters with parseable
Office doubles. Double-based results are not real engine evidence. The separately
testable `Lifecycle` core reports mode `lifecycle`, identity `NOT_RUN`; it cannot
stand in for public strict frontend verification.

Disposable production-image integration uses an owned ephemeral loopback API and
real mixed Office engines, reusing the existing Office/OCR listener/lifespan harness:

```text
docker run --rm docuforge-runtime-local python -m docuforge.ops.batch_integration
```

Its distinct result is `Batch API integration PASS: 4 lifecycles with confirmed cleanup`.
CI retains packaged identity, non-root checks, all eighteen runtime/durable markers
and four real Office/OCR API checks. Batch integration adds a separate result; none
of these local/container results proves public deployment readiness. If Docker is
unavailable, real-image execution remains pending until CI actually passes.
