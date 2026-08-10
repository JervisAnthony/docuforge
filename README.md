# DocuForge

DocuForge is a Python document-processing toolkit with a command-line interface
and public conversion APIs for focused PDF page operations and image-to-PDF
workflows.

## Status

DocuForge is under active development and currently uses a pre-alpha development
version. The implemented CLI and Python APIs are functional and covered by unit,
regression, and real-file end-to-end tests. The project is suitable for technical
demos and early testing, but behavior may evolve before a stable release.

## Requirements

- Python 3.11 or newer
- A local checkout of this repository; DocuForge is not documented here as a
  published PyPI package

Runtime dependencies are installed from `pyproject.toml` during installation.

## Installation

From the repository root, create a virtual environment and install the project in
editable mode:

```bash
python -m venv .venv
```

Activate it on Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Then install and verify the CLI:

```bash
python -m pip install -e .
docuforge --help
```

To run the optional web application, install the web dependencies as well:

```bash
python -m pip install -e ".[web]"
```

## Quick Start

Merge two PDFs in input order:

```bash
docuforge pdf merge first.pdf second.pdf -o combined.pdf
```

Rotate page 2 clockwise by 90 degrees:

```bash
docuforge pdf rotate combined.pdf -o rotated.pdf --rotate 2:90
```

Combine images into a PDF in command-line order:

```bash
docuforge image to-pdf cover.jpg diagram.png -o document.pdf
```

Run `docuforge pdf --help`, `docuforge image --help`, or a leaf command such as
`docuforge pdf merge --help` for more detail.

## CLI Overview

| Category | Command | Purpose |
| --- | --- | --- |
| PDF | `docuforge pdf merge` | Combine two or more PDFs in input order |
| PDF | `docuforge pdf split` | Write one PDF per source page |
| PDF | `docuforge pdf rotate` | Rotate selected pages clockwise |
| PDF | `docuforge pdf remove-pages` | Remove selected pages |
| PDF | `docuforge pdf extract-pages` | Copy selected pages into a new PDF |
| Image | `docuforge image to-pdf` | Combine ordered images into a PDF |

All commands write a new destination. Existing destination files may be replaced
when the operation succeeds; source files are not modified.

## PDF Commands

### Merge

```text
docuforge pdf merge INPUT INPUT [INPUT ...] -o OUTPUT
```

Merge requires at least two input PDFs. Files are processed in command-line order,
and pages retain their order within each source file. `-o` and `--output` select
the destination.

```bash
docuforge pdf merge chapter-1.pdf chapter-2.pdf appendix.pdf -o book.pdf
```

### Split

```text
docuforge pdf split INPUT -o OUTPUT_DIR
```

`-o` and `--output-dir` select the destination directory, which is created when
needed. A source named `report.pdf` produces ordered files such as
`report-page-0001.pdf`, `report-page-0002.pdf`, and so on.

```bash
docuforge pdf split report.pdf --output-dir report-pages
```

### Rotate

```text
docuforge pdf rotate INPUT -o OUTPUT --rotate PAGE:DEGREES [--rotate PAGE:DEGREES ...]
```

`PAGE` is one-based. `DEGREES` must be `90`, `180`, or `270` and represents a
clockwise rotation. Repeat `--rotate` to rotate more than one page. Each page may
be specified only once, and page order in the document does not change.

```bash
docuforge pdf rotate source.pdf -o rotated.pdf --rotate 1:90 --rotate 3:270
```

### Remove Pages

```text
docuforge pdf remove-pages INPUT -o OUTPUT --page PAGE [--page PAGE ...]
```

`--page` is repeatable and uses one-based page numbers. Duplicate selections are
rejected. Selected pages are removed, while retained pages remain in source order.
For example, this removes pages 4 and 2; all remaining pages keep their original
relative order:

```bash
docuforge pdf remove-pages source.pdf -o trimmed.pdf --page 4 --page 2
```

### Extract Pages

```text
docuforge pdf extract-pages INPUT -o OUTPUT --page PAGE [--page PAGE ...]
```

`--page` is repeatable and uses one-based page numbers. Duplicate selections are
rejected. Unlike removal, extraction preserves the user's request order. This
command writes source pages 4, 2, and 5 to the output in exactly that order:

```bash
docuforge pdf extract-pages source.pdf -o selected.pdf --page 4 --page 2 --page 5
```

## Image Commands

### Images to PDF

```text
docuforge image to-pdf INPUT [INPUT ...] -o OUTPUT
```

Each image becomes one PDF page, and command-line input order determines page
order. Supported input extensions are JPG, JPEG, PNG, BMP, TIF, and TIFF,
case-insensitively. `-o` and `--output` select the destination PDF.

```bash
docuforge image to-pdf cover.jpg chart.png scan.tiff -o images.pdf
```

## Page Numbering and Ordering

- CLI page numbers are **one-based**: page `1` is the first page.
- Python API page indices are **zero-based**: index `0` is the first page.
- Rotation changes selected pages without reordering the document.
- Removal deletes selected pages and retains the others in **source order**.
- Extraction copies selected pages in **request order**. For example,
  `--page 4 --page 2` produces page 4 followed by page 2.

Page ranges such as `1-3` and comma-separated lists such as `1,2,3` are not
accepted. Repeat the relevant option instead.

## Exit Codes and Errors

The CLI follows these broad exit-code conventions:

| Code | Meaning |
| --- | --- |
| `0` | Conversion completed successfully |
| `1` | An operational DocuForge error occurred, such as an invalid path or PDF |
| `2` | Command syntax or structural CLI input was invalid |

Errors are written to standard error. Successful commands print a short summary
that includes the destination.

## Demo Workflow

The following chain demonstrates that one DocuForge output can be used directly
by another operation. Use two input PDFs containing at least three pages in total:

```bash
docuforge pdf merge first.pdf second.pdf -o merged.pdf
docuforge pdf remove-pages merged.pdf -o trimmed.pdf --page 2
docuforge pdf extract-pages trimmed.pdf -o selected.pdf --page 2 --page 1
```

The workflow merges the source documents, removes the second merged page, then
extracts the second and first remaining pages in that requested order.

## Python API

High-level path APIs expose the same conversion capabilities to Python code. Page
indices in Python are zero-based:

```python
from pathlib import Path

from docuforge.converters import PdfExtractPagesPathRequest, extract_pdf_pages

result = extract_pdf_pages(
    PdfExtractPagesPathRequest(
        input_path=Path("source.pdf"),
        output_path=Path("selected.pdf"),
        page_indices=(3, 1),  # Source pages 4, then 2.
    )
)

print(result.output_path)
```

The Python API also supports raster re-encoding among JPEG, PNG, WebP, BMP,
and TIFF through `ImageConvertPathRequest` and `convert_image_path`. The target
format is inferred from the destination suffix. The reusable image API can also
resize while preserving aspect ratio, encode JPEG or WebP at a chosen quality,
and compress supported raster formats to a maximum byte size through
`resize_image_path` and `compress_image_path`. These capabilities are Python-only;
no image optimization HTTP or CLI commands are currently exposed.

## Development

Install the development tools after activating the virtual environment:

```bash
python -m pip install -e ".[dev,web]"
python -m pytest
python -m ruff check .
```

The repository includes unit, regression, and real-file end-to-end CLI tests.

## Web API

After installing the optional web dependencies, start the local API server with:

```bash
python -m uvicorn docuforge.api.app:app --reload
```

The current system endpoints are `GET /api/v1` for API metadata and
`GET /api/v1/health` for liveness. Interactive documentation is available at
`/docs` and `/redoc`, with the OpenAPI document at `/openapi.json`. PDF workflows
are available through these operation-oriented endpoints:

- `POST /api/v1/pdf/merge`
- `POST /api/v1/pdf/split`
- `POST /api/v1/pdf/rotate`
- `POST /api/v1/pdf/remove-pages`
- `POST /api/v1/pdf/extract-pages`

Each operation accepts multipart uploads directly. Files are scoped to the
request and are not persistently stored. HTTP page numbers are one-based. Split
returns a ZIP containing one PDF per page; the other operations return a PDF.

For example, merge two PDFs with:

```bash
curl -X POST \
  -F "files=@first.pdf" \
  -F "files=@second.pdf" \
  http://127.0.0.1:8000/api/v1/pdf/merge \
  -o merged.pdf
```

Repository layout:

```text
src/docuforge/       Application source
tests/               Automated tests
.github/workflows/   Continuous integration workflows
```

## Current Limitations

- The feature surface is intentionally focused on the six CLI workflows above;
  office-document conversion is not currently implemented.
- Page ranges and comma-separated page lists are not supported.
- Every CLI operation requires an explicit output file or output directory;
  in-place PDF modification is not supported.
- Password-protected/encrypted PDFs are rejected; password input is not supported.
- The REST API supports the five PDF workflows above; image conversion over HTTP
  and a graphical web interface are not implemented.
- APIs and CLI behavior may change before a stable release.

## Alpha / Beta Feedback

Early testing reports are welcome through GitHub Issues in this repository. A
useful report includes:

- operating system and Python version
- the exact DocuForge command used
- expected and actual results
- complete error output
- a minimal reproducible sample when it is safe to share

Do not upload sensitive documents. Prefer a small synthetic file that reproduces
the behavior.

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
