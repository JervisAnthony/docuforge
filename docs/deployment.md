# DocuForge deployment

DocuForge MVP1 uses a split deployment:

- **Frontend:** Vercel, with the Vite application rooted at `frontend/`.
- **API:** Railway, built from the repository root with the root `Dockerfile`.

## Railway API

Create a Railway service from this repository. Railway will detect `railway.json` and build the
Dockerfile. The service readiness check is `/api/v1/ready`; `/api/v1/health` remains the
lightweight liveness endpoint.

Set these variables in Railway:

```text
DOCUFORGE_ENVIRONMENT=production
DOCUFORGE_DOCS_ENABLED=false
DOCUFORGE_CORS_ALLOWED_ORIGINS=<your Vercel production origin>
```

`PORT` is supplied by Railway automatically. The production launcher reads it at runtime,
disables Uvicorn's identifying `Server` header, and replaces duplicate access logs with
DocuForge's structured request records.

The production image includes the headless LibreOffice Writer, Impress, and Calc components,
Tesseract with English language data, and baseline DejaVu/Liberation fonts. The API runs as a
dedicated non-root user. These system packages make the image larger than a Python-only image.
The **Production runtime image** CI job builds the real image and verifies actual Office and OCR
execution. Local or non-Docker runs still require the binaries to be installed separately.

## Durable batch storage

The production image sets:

```text
DOCUFORGE_BATCH_STORAGE_DIRECTORY=/var/lib/docuforge
```

This enables SQLite session metadata and deterministic per-BatchId workspaces. The non-root API
user owns the directory. Process restarts restore terminal status, downloads, selective recovery,
and packaging-only recovery while the same filesystem remains available.

The container filesystem alone does not survive every container replacement or redeployment.
Mount a persistent volume at `/var/lib/docuforge` when deployment-level batch durability is
required. This remains single-process orchestration; do not run multiple API processes against the
same executor state.

Opening a Commit 56 schema-v1 database migrates it transactionally to schema v2. Pre-token rows
and their BatchId workspaces are removed because no secure access capability was issued for them.

For preview deployments, add the exact preview origin to
`DOCUFORGE_CORS_ALLOWED_ORIGINS` as a comma-separated value. Do not use a wildcard origin for
the public deployment.
The explicit CORS allowlist permits and exposes `X-DocuForge-Batch-Token`, allowing the configured
Vercel frontend to read the creation response header and send it on later protected requests.

## Operational behavior

Every HTTP response receives an `X-Request-ID`. A valid client-supplied request ID is preserved;
otherwise the API generates one. Browser clients may read this header for configured CORS
origins, making support reports traceable to a single backend request.

The production launcher emits one JSON request record per completed request. Records contain the
request ID, method, path, status code, outcome, and duration, but intentionally omit query strings,
uploaded filenames, request bodies, and document contents.
BatchId UUIDs are normalized to `{batch_id}` in batch request paths. Access-token headers and
token hashes are never logged.

Batch capabilities are generated independently for each session; no deployment secret is needed.
The frontend retains a capability only in component memory, so reloading or leaving the active
workspace intentionally loses access to that anonymous batch.

API responses also receive defensive browser headers. Production responses add
`Strict-Transport-Security`; the header is intentionally omitted from local-mode responses.

## Vercel frontend

Create a Vercel project from this repository and set the project root directory to `frontend`.

Set the build-time variable:

```text
VITE_API_BASE_URL=<your Railway public API origin>
```

The included `frontend/vercel.json` uses the Vite build and rewrites browser routes to
`index.html` so the single-page application can be refreshed safely.

## Smoke check

After both deployments are available:

1. Open the Railway `/api/v1/ready` endpoint and confirm a successful `ready` response.
2. Open `/api/v1/health` and confirm the liveness response remains healthy.
3. Open `/api/v1/capabilities` and confirm `office_to_pdf.available` and `ocr.available` are true.
4. Confirm the Vercel application reports the API as connected.
5. Exercise PDF merge, image compression, Office DOCX-to-PDF, and OCR image-to-text with
   synthetic, non-sensitive fixtures.
6. Confirm the converted outputs download successfully.
7. Confirm responses include `X-Request-ID` and the defensive response headers.
8. Confirm an unknown web origin is not granted CORS access.
9. Confirm batch creation exposes `X-DocuForge-Batch-Token` to the configured origin and protected
   requests succeed without displaying or logging its value.

Single-file uploads use request-scoped temporary workspaces. Batch uploads use isolated session
workspaces and may remain on disk until terminal TTL expiry or internal expiry cleanup. They are
not permanent records.
Office and OCR processing remains inside the Railway API container and does not use an external
conversion or OCR service.
