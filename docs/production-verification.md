# Production verification

After Vercel and Railway are public, run the DocuForge production verifier with the two HTTPS origins.

The repository includes a manually triggered **Production Smoke** GitHub Actions workflow. It
first confirms that Railway reports the same release version as the checked-out code, then checks:

1. frontend availability
2. API readiness
3. LibreOffice and Tesseract runtime capabilities
4. liveness, response headers, and browser CORS behavior
5. PDF merge semantics
6. image compression semantics
7. Office DOCX-to-PDF execution
8. OCR image-to-text execution

Every conversion check uses a small generated, non-sensitive fixture. The Office result must be a
parseable PDF and the OCR result must be valid UTF-8; OCR text is not benchmarked for exact
recognition.

The CI **Production runtime image** job also runs a synthetic durable batch restart check inside
the production container. It verifies non-root SQLite/workspace access and ZIP download after
service recreation with the same in-process capability and confirms a wrong capability is
rejected. Its output remains generic and never prints capability values. Public Production Smoke
does not restart the deployed Railway service.

Normal pushes and pull requests do not send traffic to the public deployment.

After the automated checks pass, run one PDF, image, Office, and OCR tool in the browser, confirm
the downloads open correctly, and hard-refresh the application once to confirm the catalog
reloads.

See `docs/mvp1-launch.md` for the complete MVP1 go/no-go sequence.
