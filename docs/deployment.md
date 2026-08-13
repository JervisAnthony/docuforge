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

For preview deployments, add the exact preview origin to
`DOCUFORGE_CORS_ALLOWED_ORIGINS` as a comma-separated value. Do not use a wildcard origin for
the public deployment.

## Operational behavior

Every HTTP response receives an `X-Request-ID`. A valid client-supplied request ID is preserved;
otherwise the API generates one. Browser clients may read this header for configured CORS
origins, making support reports traceable to a single backend request.

The production launcher emits one JSON request record per completed request. Records contain the
request ID, method, path, status code, outcome, and duration, but intentionally omit query strings,
uploaded filenames, request bodies, and document contents.

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
3. Confirm the Vercel application reports the API as connected.
4. Exercise one PDF workflow and one image workflow with synthetic, non-sensitive fixtures.
5. Confirm the converted output downloads successfully.
6. Confirm responses include `X-Request-ID` and the defensive response headers.
7. Confirm an unknown web origin is not granted CORS access.

The deployment remains stateless: uploaded files are processed in request-scoped temporary
workspaces and are not intentionally persisted by the application.
