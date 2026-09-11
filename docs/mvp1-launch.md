# MVP1 launch runbook

DocuForge MVP1 is release `0.1.0`. Feature development for this milestone is complete; the public deployment is live and has passed initial manual acceptance. Formal launch remains gated by production smoke verification and the dogfood window.

## Launch sequence

1. Merge the release candidate only after repository CI is green. ✅
2. Deploy the Railway API from `main` and confirm `/api/v1/ready` and `/api/v1/health`. ✅
3. Deploy the Vercel frontend from `frontend/` with `VITE_API_BASE_URL` pointing at Railway. ✅
4. Allow the exact Vercel production origin in Railway CORS configuration. ✅
5. Run the manual **Production Smoke** GitHub Actions workflow with both public HTTPS origins. ⏳
6. Require the release-identity check to confirm Railway is serving `0.1.0`. ✅ Manual verification completed; automated Production Smoke remains pending.
7. Run one PDF workflow and one image workflow in the browser and open both downloads. ✅
8. Hard-refresh the deployed application and confirm the catalog reconnects normally. ⏳
9. Dogfood the deployed MVP1 for approximately one week. ⏳
10. If no launch blocker remains, create the `v0.1.0` tag and GitHub release. ⏳

## Current production origins

- Frontend: `https://docuforge-five.vercel.app`
- API: `https://docuforge-production-c24b.up.railway.app`

The Railway readiness and health endpoints both reported version `0.1.0` during manual deployment acceptance.

## Manual acceptance completed

Initial public-browser acceptance confirmed that:

- the frontend can connect to the production API;
- a PDF workflow completes successfully and produces a usable download;
- an image workflow completes successfully and produces a usable download;
- the exact Vercel production origin is permitted by Railway CORS configuration.

## Launch blockers

Do not launch with crashes, repeated server errors, corrupted outputs, broken downloads, production connectivity failures, deployment instability, or a supported workflow that is unusable on the intended browser experience.

New formats, OCR, authentication, persistent storage, background jobs, office-document conversion, and minor visual polish are post-MVP1 work rather than launch requirements.

## Evidence to record

The final launch record should include the Vercel and Railway origins, successful Production Smoke run, deployed API version, manual PDF and image acceptance results, the dogfood window dates, and any launch-blocking defects discovered during dogfooding.

See [`mvp1-launch-record.md`](mvp1-launch-record.md) for the current launch evidence and [`mvp1-dogfood.md`](mvp1-dogfood.md) for the structured dogfood log.
