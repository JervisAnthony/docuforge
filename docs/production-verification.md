# Production verification

After Vercel and Railway are public, run the DocuForge production verifier with the two HTTPS origins.

The repository includes a manually triggered **Production Smoke** GitHub Actions workflow. It first confirms that Railway reports the same release version as the checked-out code, then verifies the frontend, readiness, liveness, response headers, browser CORS behavior, PDF merge semantics, and image compression semantics using small generated fixtures.

Normal pushes and pull requests do not send traffic to the public deployment.

After the automated checks pass, run one PDF tool and one image tool in the browser, confirm both downloads open correctly, and hard-refresh the application once to confirm the catalog reloads.

See `docs/mvp1-launch.md` for the complete MVP1 go/no-go sequence.
