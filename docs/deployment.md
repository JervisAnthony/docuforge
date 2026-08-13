# DocuForge deployment

DocuForge MVP1 uses a split deployment:

- **Frontend:** Vercel, with the Vite application rooted at `frontend/`.
- **API:** Railway, built from the repository root with the root `Dockerfile`.

## Railway API

Create a Railway service from this repository. Railway will detect `railway.json` and build the Dockerfile. The service health check is `/api/v1/health`.

Set these variables in Railway:

```text
DOCUFORGE_ENVIRONMENT=production
DOCUFORGE_DOCS_ENABLED=false
DOCUFORGE_CORS_ALLOWED_ORIGINS=<your Vercel production origin>
```

`PORT` is supplied by Railway automatically. The production launcher reads it at runtime.

For preview deployments, add the exact preview origin to `DOCUFORGE_CORS_ALLOWED_ORIGINS` as a comma-separated value. Do not use a wildcard origin for the public deployment.

## Vercel frontend

Create a Vercel project from this repository and set the project root directory to `frontend`.

Set the build-time variable:

```text
VITE_API_BASE_URL=<your Railway public API origin>
```

The included `frontend/vercel.json` uses the Vite build and rewrites browser routes to `index.html` so the single-page application can be refreshed safely.

## Smoke check

After both deployments are available:

1. Open the Railway `/api/v1/health` endpoint and confirm a successful response.
2. Open the Vercel application and confirm the API status is healthy.
3. Exercise one PDF workflow and one image workflow with synthetic, non-sensitive fixtures.
4. Confirm the converted output downloads successfully.
5. Confirm an unknown web origin is not granted CORS access.

The deployment remains stateless: uploaded files are processed in request-scoped temporary workspaces and are not intentionally persisted by the application.
