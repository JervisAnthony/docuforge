# MVP1 launch record

This document records the production baseline for DocuForge MVP1 before the `v0.1.0` tag and GitHub release are created.

## Production deployment

- Frontend: `https://docuforge-five.vercel.app`
- API: `https://docuforge-production-c24b.up.railway.app`
- Deployed API version: `0.1.0`
- Frontend host: Vercel
- API host: Railway
- Deployment model: Vite SPA → FastAPI → reusable DocuForge conversion engine

## Verified production state

Manual verification completed on 2026-09-11:

- `/api/v1/ready` returned a ready response for DocuForge version `0.1.0`.
- `/api/v1/health` returned a healthy response for DocuForge version `0.1.0`.
- Railway production settings were applied with production mode enabled and API documentation disabled.
- Railway CORS was restricted to the exact Vercel production origin.
- The Vercel frontend connected successfully to the Railway API.
- At least one PDF workflow completed successfully in the public browser application.
- At least one image workflow completed successfully in the public browser application.
- Successful outputs were downloadable from the browser.

## Remaining launch gates

The following remain before the formal `v0.1.0` release:

- run the manual Production Smoke GitHub Actions workflow against the public origins;
- confirm a hard-refresh reconnects normally;
- complete the planned dogfood window;
- triage any launch-blocking defects;
- create the `v0.1.0` tag and GitHub release if no launch blocker remains.

## Release decision rule

MVP1 may be formally released when no known launch blocker remains. Launch blockers include crashes, repeated server errors, corrupted outputs, broken downloads, production connectivity failures, deployment instability, or a supported workflow that is unusable in the intended browser experience.

## Seventeen-check public smoke evidence

This new matrix has not yet been executed against the public deployment. Historical acceptance
above remains unchanged. Use the [complete ordered matrix](production-verification.md) and attach
the workflow summary when recording a real run.

| Evidence field | Value |
| --- | --- |
| Execution date | Pending |
| Workflow run URL | Pending |
| Frontend origin used for this run | Pending |
| API origin used for this run | Pending |
| Expected version | 0.1.0 |
| Observed version for this run | Pending |
| Check count (expected 17) | Pending |
| Result | Pending |
| Browser hard-refresh verification | Pending |
| Dogfood completion | Pending |
| Outstanding launch blockers | Pending verification of public smoke, hard-refresh and dogfood gates |
| Release decision | Pending |

Semantic version consistency does not establish exact deployed frontend or API commit identity.
A passing API matrix does not imply all ten browser interfaces were manually exercised. Formal
launch, the `v0.1.0` tag and GitHub Release remain gated by verified evidence and a release decision.
