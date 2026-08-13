# Production verification

After Vercel and Railway are public, run the DocuForge production verifier with the two HTTPS origins.

The verifier checks the frontend, readiness, liveness and security headers, browser CORS behavior,
PDF merge semantics, and image compression semantics. It creates only small synthetic fixtures and
never reads local user documents.

The repository also includes a manually triggered **Production Smoke** GitHub Actions workflow.
Normal pushes and pull requests do not send traffic to the public deployment.

After the automated checks pass, run one PDF tool and one image tool in the browser, confirm both
downloads open correctly, and hard-refresh the application once to confirm the catalog reloads.
