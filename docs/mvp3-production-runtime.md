# Production runtime capabilities

## Purpose

Commit 55 begins the post-MVP2 production-hardening phase. It moves the existing Office-to-PDF
and OCR workflows from optional deployment capabilities to verified capabilities of the production
container. It does not extend the completed MVP2 batch roadmap.

## Production runtime

The production Docker image installs the headless LibreOffice Writer, Impress, and Calc components
used by the existing `LibreOfficeEngine`. It also installs Tesseract, English trained data, and a
small baseline of DejaVu and Liberation fonts. The API, runtime verifier, LibreOffice temporary
profiles, Tesseract staging, request workspaces, and batch workspaces all run as the dedicated
non-root `docuforge` user.

Local and non-container installations may still omit these system binaries. Core PDF and image
workflows remain usable when an optional local engine is absent.

## Capability reporting

`GET /api/v1/capabilities` returns the availability of `office_to_pdf` and `ocr`:

```json
{
  "office_to_pdf": {"available": true},
  "ocr": {"available": true}
}
```

The endpoint reports availability as data with HTTP 200. It is separate from liveness and
readiness, uses the application's configured engine factories, and does not expose executable
paths, process output, temporary paths, or operating-system user details.

## Verification

Run `python -m docuforge.ops.runtime_smoke` inside the production image. It creates synthetic DOCX
and PNG fixtures, performs a real LibreOffice conversion and a real English Tesseract OCR call,
validates the artifacts, and removes its temporary workspace.

The **Production runtime image** CI job builds the real Dockerfile and runs that verifier. The
manually triggered **Production Smoke** workflow checks public capability reporting and exercises
DOCX-to-PDF and image-to-text alongside the existing deployment checks.

## Boundaries

- Capability checks confirm runtime discovery, not conversion quality for arbitrary documents.
- OCR recognition accuracy depends on scan quality; English is the only guaranteed OCR language.
- Production verification uses generated, non-sensitive fixtures.
- Office and OCR processing remains local to the API runtime; no third-party conversion service is
  used.
- Uploaded documents are not retained by this change.
- Batch sessions remain process-local and do not survive restart or cross-worker routing.
- Commit 55 adds no durable session persistence, database, queue, worker, or authentication layer.
