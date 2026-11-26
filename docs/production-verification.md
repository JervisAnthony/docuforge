# Production verification

Public batch lifecycle verification is a separately invoked, mutating suite of four
cases. The **Production Batch Smoke** manual workflow and
`python -m docuforge.ops.batch_smoke` verify strict identity internally, create small
synthetic sessions, validate private access and ZIP semantics, and require confirmed
cleanup. See [usage, ownership, deadlines, privacy and TTL fallback](public-batch-verification.md).
Its four lifecycle outcomes stay separate from this document's twenty-one semantic
checks, eighteen runtime/durable markers, and four Office/OCR API integration checks.
The disposable production image additionally runs `python -m docuforge.ops.batch_integration`
with real mixed Office conversion; ordinary local tests use parseable Office doubles.
Neither form proves a public run passed or changes historical/Pending launch records.

After Vercel and Railway are public, run the DocuForge production verifier with the two HTTPS origins.

The repository includes a manually triggered **Production Smoke** GitHub Actions workflow. It
first verifies independently expected API and frontend build revisions, API readiness and
release version, and frontend HTML consistency, then runs **twenty-one** ordered semantic
checks. Both HTTPS origins and both full expected revisions are required workflow inputs.
See [build identity setup and exact CLI usage](deployed-build-identity.md).
The authoritative semantic identifiers live in
`SMOKE_CHECKS` in `src/docuforge/ops/deployment_smoke.py`:

| # | Check | Required semantics |
| --- | --- | --- |
| 1 | `frontend` | HTML identifying DocuForge |
| 2 | `readiness` | Ready DocuForge service and nonempty version |
| 3 | `runtime-capabilities` | Office and OCR available |
| 4 | `liveness-and-headers` | Healthy API, security headers, request ID and CORS exposure |
| 5 | `cors` | Configured frontend origin and request-ID preflight |
| 6 | `pdf-merge` | PDF widths 100, 200 in upload order |
| 7 | `pdf-split` | Three ordered single-page PDFs with widths 100, 200, 300 |
| 8 | `pdf-rotate` | Original page order and rotations 90, 180, 0 |
| 9 | `pdf-remove-pages` | Surviving widths 100, 300 |
| 10 | `pdf-extract-pages` | Requested widths 300, 100 in that order |
| 11 | `pdf-to-images` | Three ordered PNGs at 72 DPI, sizes 100/200/300 by 120 |
| 12 | `image-convert` | Actual JPEG, 96 by 64 |
| 13 | `image-resize` | Actual PNG, 48 by 32, preserving aspect ratio |
| 14 | `image-compression` | Actual JPEG, original 96 by 64 dimensions |
| 15 | `images-to-pdf` | Two PDF pages, landscape then portrait |
| 16 | `office-docx-to-pdf` | Parseable nonempty PDF |
| 17 | `ocr-image-to-text` | Valid UTF-8 plain text |
| 18 | `office-pptx-to-pdf` | One unencrypted PDF page containing the normalized PPTX marker |
| 19 | `office-xlsx-to-pdf` | One unencrypted PDF page containing the normalized XLSX marker |
| 20 | `ocr-pdf-to-text` | Two nonempty UTF-8 page segments, one form-feed boundary, ALPHA then BRAVO |
| 21 | `ocr-pdf-to-searchable-pdf` | Two unencrypted pages with matching geometry and ordered extractable ALPHA/BRAVO text |

This covers all ten MVP1 API operations plus the frontend, readiness, runtime capabilities,
health/security headers, browser CORS, all three Office-to-PDF routes and all three OCR routes.
Every conversion uses small generated,
non-sensitive fixtures in memory. Expected response media types and supplied download filenames
are checked. OCR recognition is not benchmarked for exact line breaks or broad accuracy.

The four additions are appended after the original seventeen identifiers. They are mandatory:
an unavailable engine, timeout or failed download causes a named failure and a nonzero exit,
with passed identifiers and the attempted count retained in JSON evidence. Full success prints
`Production smoke passed: 21/21 checks`; incomplete or old seventeen-check evidence cannot
satisfy the current gate. The authoritative full contract remains `SMOKE_CHECKS`.

## Controlled Office and scanned-PDF semantics

`smoke_fixtures.py` creates Office ZIPs in memory with real OOXML content types and
relationships. The PPTX has a single slide plus its master, layout and theme, with
`DOCUFORGE PPTX ALPHA`. The XLSX has one worksheet, a single inline-string cell containing
`DOCUFORGE XLSX BRAVO`, and an explicit single-page A4 print area. Each request supplies
exactly one `file` field with the correct extension and OOXML MIME type. A PDF signature
alone is insufficient: output must parse, be unencrypted, have exactly one page and expose
its expected marker as text. This narrow fixture does not establish general rendering fidelity.

The scanned input consists of two raster images with large black English text on white,
using Pillow's built-in font, embedded in a PDF at 200 DPI. It has no pre-existing extractable
text. The pages are 360 by 216 and 432 by 252 PDF points, carrying ALPHA and BRAVO respectively.
The API uses its existing default English OCR and 300 DPI render settings. No new fonts,
Office binaries, dependencies or customer processing limits are introduced.

For `ocr-pdf-to-text`, require `text/plain`, valid UTF-8, exactly two nonempty segments
separated by the converter's form-feed (`\f`) aggregation contract, and markers in page
order. For searchability, require a parseable unencrypted two-page PDF with geometry within
one PDF point per axis (the converter's existing rounding tolerance) and a nonempty extractable
text layer with the right marker on each page. Case and whitespace are ignored in marker
comparison; other text need not exactly match. Missing/reordered/merged page markers, empty
text, markup masquerading as OCR text, blank PDFs, lost pages and returning the image-only
input are rejected. These are controlled searchability/order checks, not broad OCR accuracy
or preservation of every original PDF feature. Failure diagnostics never include extracted
text, response bodies, engine stderr or filesystem paths.

Split and rendered-image ZIPs require the exact ordered safe filenames, no extra, duplicate,
directory or encrypted entries, and valid CRC. Members are read directly in memory and never
extracted. Public HTTP reads, including HTTP-error bodies, are bounded at **10 MiB per response**
using a limit-plus-one read. ZIP members are capped at **2 MiB each**, with **6 MiB total
uncompressed content** checked before decompression. These are synthetic smoke-verifier safety
limits, not customer upload or processing limits.

The runner stops at the first failed check and the CLI exits nonzero with a stable check name
and safe reason, without response bodies or document contents. The manual workflow writes a
job summary even after failure, including public origins, expected version, attempted check
count, passed identifiers, overall result and workflow run URL. Missing or incomplete evidence
cannot report overall PASS.

The strict release-identity command compares each component's reported build revision with
its own explicitly expected revision. It also compares frontend manifest and HTML metadata.
This diagnostic mechanism is not cryptographic attestation or reproducible-build provenance.
Legacy semantic-only use explicitly reports that revisions were not verified. Strict identity
is a separate prerequisite to the twenty-one-check matrix and does not change the eighteen
image runtime/durable markers. The always-run summary includes expected/observed component revisions
and identity outcome; skipped/failed verification and missing/malformed evidence cannot PASS.

## Distinct verification evidence

1. Ordinary CI uses synthetic doubles and local API integration tests, with no external HTTP
   or engine binary requirements. The original ten MVP1 operations use explicit named selection;
   appending checks cannot accidentally add Office/OCR requirements to that test. Office/OCR
   doubles generate parseable PDFs with real PDF text objects, but do not prove real rendering
   or recognition.
2. The production-image CI job runs the four new checks through a real disposable loopback API,
   LibreOffice and Tesseract using `python -m docuforge.ops.office_ocr_integration`. It binds an
   ephemeral loopback listener, bypasses HTTP proxies, uses the existing bounded response reader,
   and owns server/lifespan cleanup even when a conversion check fails. Public HTTPS-origin
   validation stays unchanged. The helper has no public URL option and the CLI always uses real
   engines. Its separately labeled result is `Office/OCR API integration PASS: 4 checks`.
   This is additional integration evidence alongside the unchanged eighteen image markers.
3. Actual public Production Smoke requires the manual workflow, independent expected API/frontend
   revisions, and all twenty-one checks against the deployed origins. Normal CI never contacts
   Railway/Vercel. Local/double/container success does not establish this public outcome.
4. Manual browser acceptance, hard-refresh and dogfood evidence remain separate launch gates.

For a disposable local production image, from a clean checkout of the intended source:

```powershell
$testRevision = (git rev-parse HEAD)
docker build --build-arg "DOCUFORGE_BUILD_REVISION=$testRevision" -t docuforge-runtime-local .
docker run --rm docuforge-runtime-local python -m docuforge.ops.office_ocr_integration
```

CI uses its checked-out test revision for the image stamp, which may be a PR merge revision.
That is not an assumed production or eventual squash-merge revision. If Docker is unavailable,
real-image execution remains unverified until CI actually passes; doubles are never a substitute.

Repository CI success is separate from a successful manually triggered public run. API smoke
also does not establish manual acceptance of all ten browser interfaces. Record public evidence
in [the launch record](mvp1-launch-record.md), then complete browser hard-refresh verification
and dogfooding before a release decision. These gates remain pending until verified.

The **twenty-one public checks** are distinct from the **eighteen production Docker image
runtime/durable markers**, ending with `PASS batch-download-validation-concurrency`.

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
all pins and delete normally. The current production image must emit **eighteen**
PASS markers (two engine checks plus sixteen batch checks, including validation
concurrency below). See
[bounded download admission](mvp3-batch-download-admission.md).

Require `PASS batch-download-validation-concurrency`: pause a real synthetic ZIP
scan after provisional admission, complete authorized status while it is paused,
reject excess capacity before opening, promote the same descriptor and pin, verify
ZIP structure/CRC, release all pins and delete. The production image must now emit
**eighteen** PASS markers (two runtime and sixteen durable checks). All previous
markers remain required. Windows CI also runs core concurrency and download
lifecycle/descriptor checks. See
[validation concurrency](mvp3-batch-download-validation-concurrency.md).
