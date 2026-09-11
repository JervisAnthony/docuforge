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
