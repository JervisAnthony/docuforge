# DocuForge

DocuForge is a privacy-conscious PDF and image toolkit with a browser application, FastAPI service, command-line interface, and reusable Python conversion layer.

The MVP is intentionally focused: process common document and image tasks without accounts, persistent document storage, or browser-side document parsing.

## MVP1 status

**Release candidate: `0.1.0`**

All ten MVP1 browser workflows are implemented, covered by full-stack reliability tests, and supported by production deployment and verification tooling. The repository does **not** consider MVP1 launched until the public Vercel and Railway deployments pass the launch runbook in [`docs/mvp1-launch.md`](docs/mvp1-launch.md), including Production Smoke and the planned dogfood window.

## MVP1 tools

| Category | Tool | Browser | API |
| --- | --- | --- | --- |
| PDF | Merge PDFs | Yes | `POST /api/v1/pdf/merge` |
| PDF | Split PDF | Yes | `POST /api/v1/pdf/split` |
| PDF | Rotate pages | Yes | `POST /api/v1/pdf/rotate` |
| PDF | Remove pages | Yes | `POST /api/v1/pdf/remove-pages` |
| PDF | Extract pages | Yes | `POST /api/v1/pdf/extract-pages` |
| PDF | PDF to images | Yes | `POST /api/v1/pdf/to-images` |
| Image | Convert format | Yes | `POST /api/v1/images/convert` |
| Image | Resize | Yes | `POST /api/v1/images/resize` |
| Image | Compress | Yes | `POST /api/v1/images/compress` |
| Image | Images to PDF | Yes | `POST /api/v1/images/to-pdf` |

## Architecture

DocuForge keeps document-processing logic independent from its interfaces:

```text
React / Vite browser app
          |
          v
FastAPI HTTP adapter
          |
          v
Reusable DocuForge converters
          |
          v
pypdf / Pillow / PDFium
```

The CLI and Python APIs call the same reusable conversion layer. Web routes adapt HTTP requests into converter requests rather than reimplementing PDF or image behavior.

The deployed design is stateless. Uploads are processed inside request-scoped temporary workspaces and are not intentionally persisted by the application. Production request logs record operational metadata such as request ID, method, path, status, and duration rather than uploaded document contents.

## Local development

### Python

DocuForge requires Python 3.11 or newer.

```bash
python -m venv .venv
python -m pip install -e ".[dev,web]"
python -m pytest
python -m ruff check .
```

Activate the virtual environment before installing. On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### Frontend

Frontend development requires Node.js 24 and npm.

Start the API:

```bash
python -m uvicorn docuforge.api.app:app --reload
```

Then start the Vite application in another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Frontend quality checks:

```bash
npm run lint
npm run test
npm run build
```

The full-stack Chromium suite starts both the API and frontend automatically:

```bash
cd frontend
npx playwright install chromium
npm run test:e2e
```

## CLI quick start

Install the project and inspect available commands:

```bash
python -m pip install -e .
docuforge --help
```

Examples:

```bash
# Merge PDFs in input order
docuforge pdf merge first.pdf second.pdf -o combined.pdf

# Rotate page 2 clockwise
docuforge pdf rotate combined.pdf -o rotated.pdf --rotate 2:90

# Remove selected pages
docuforge pdf remove-pages source.pdf -o trimmed.pdf --page 2 --page 4

# Extract pages in request order
docuforge pdf extract-pages source.pdf -o selected.pdf --page 4 --page 2

# Split into one PDF per page
docuforge pdf split source.pdf --output-dir pages

# Combine images into a PDF
docuforge image to-pdf cover.jpg diagram.png -o document.pdf
```

CLI page numbers are one-based. Python converter APIs use zero-based page indices. Run `docuforge pdf --help`, `docuforge image --help`, or any leaf command with `--help` for the full command contract.

## Python API

High-level path APIs expose the same conversion engine to Python code. For example:

```python
from pathlib import Path

from docuforge.converters import PdfExtractPagesPathRequest, extract_pdf_pages

result = extract_pdf_pages(
    PdfExtractPagesPathRequest(
        input_path=Path("source.pdf"),
        output_path=Path("selected.pdf"),
        page_indices=(3, 1),
    )
)

print(result.output_path)
```

The reusable conversion layer covers PDF merge, split, rotation, page removal and extraction, PDF rendering to raster images, image format conversion, aspect-preserving resize, image compression, and ordered images-to-PDF conversion.

## Web API

Install the web dependencies and run:

```bash
python -m pip install -e ".[web]"
python -m uvicorn docuforge.api.app:app --reload
```

System endpoints:

- `GET /api/v1` — API metadata
- `GET /api/v1/health` — liveness
- `GET /api/v1/ready` — readiness

Interactive documentation is available at `/docs` and `/redoc` in environments where API docs are enabled.

Multipart uploads are bounded by API transport limits and processed in request-scoped workspaces. Split and PDF-to-images return ZIP archives; the remaining workflows return the converted PDF or image directly.

## Deployment

MVP1 uses a split production deployment:

- **Vercel** — Vite frontend rooted at `frontend/`
- **Railway** — FastAPI service built from the repository root

See [`docs/deployment.md`](docs/deployment.md) for environment configuration and [`docs/production-verification.md`](docs/production-verification.md) for live smoke verification.

The manual **Production Smoke** workflow verifies that the deployed API reports the expected release version before exercising the public frontend, readiness/liveness contracts, response headers, CORS, PDF merge, and image compression.

## Release quality

The repository CI covers:

- Ruff
- Python 3.11, 3.12, and 3.13 test suites
- frontend lint, tests, and production build
- Python distribution build verification
- full-stack Chromium E2E workflows

Production verification is intentionally manual because it targets the real public Vercel and Railway origins rather than test infrastructure.

## Current MVP1 limitations

The following are intentionally outside the MVP1 scope:

- authentication and user accounts
- persistent cloud document storage
- background job infrastructure
- OCR
- office-document conversion
- password input for encrypted PDFs
- in-place PDF modification

These are future product decisions, not missing requirements for the current ten-tool MVP.

## Feedback

Early testing reports are welcome through GitHub Issues. Useful reports include the operating system or browser, the workflow used, expected and actual results, and a minimal synthetic reproduction when possible.

Do not upload sensitive documents to issue reports.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
