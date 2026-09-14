# MVP2 OCR: engine and core workflows

Commits 47–49 establish reusable Python OCR. OCR is not yet available through the API or browser.
Tesseract remains an external executable and is not installed in CI or production by these commits.

```text
ImageToTextRequest ──> ImageToTextConverter ──┐
                                             ├──> OcrEngine ──> TesseractEngine / future engine
ScannedPdfToTextRequest ──> bounded renderer ──┤
ScannedPdfToSearchablePdfRequest ──────────────┘
```

`OcrEngine` accepts immutable `OcrEngineRequest` values and returns a validated artifact identity.
`TesseractEngine` is the first implementation. It discovers the local executable, runs it without a
shell and with a finite timeout, and stages output per call. Text must decode as UTF-8; a PDF must
start with `%PDF-`. Symlinks and non-regular artifacts are rejected before atomic publication.
Engine requests may carry an explicit DPI; PDF workflows pass the renderer's DPI to Tesseract using
separate `--dpi` and numeric arguments. Ordinary image OCR need not specify DPI.

The image-to-text workflow accepts one JPEG, PNG, WebP, BMP, or TIFF raster. Pillow fully decodes it
before OCR, checks suffix/content agreement, and rejects multi-frame images. It passes the original
raster to an injected `OcrEngine` without re-encoding or preprocessing. The workflow validates the
engine result inside an isolated `.docuforge-image-ocr-*` directory, then atomically publishes exact
UTF-8 text to the caller-selected `.txt` path. Empty text, whitespace, line endings, and Unicode are
preserved. Structured engine failures propagate and existing output survives failures.

Commit 49 adds two scanned-PDF workflows:

```text
PDF -> bounded PNG rasterization -> per-page OcrEngine TXT -> "\f" aggregation -> TXT
PDF -> bounded PNG rasterization -> per-page OcrEngine PDF -> pypdf assembly -> searchable PDF
```

Both process **every page sequentially in source order** and make one OCR call per page. They reuse
`pdf_to_images_path` with PNG intermediates, 300 DPI by default, at most 100 pages, and at most
40,000,000 pixels per page. The OCR engine receives that explicit DPI. Each page gets its own engine
output directory inside one `.docuforge-pdf-ocr-*` workflow workspace. Render and engine results
are checked for identity, format, DPI, regular non-symlink files, and workspace containment.

Text extraction preserves each page's exact UTF-8 artifact in `page_texts`. The published `text` is
`"\f".join(page_texts)`: one form feed between pages and no other normalization. Empty page text is
valid. Searchable-PDF extraction requires each OCR page PDF to be parseable, unencrypted, exactly
one page, and within one point of the raster's expected physical dimensions (`pixels × 72 / DPI`).
The validated pages are assembled in order with pypdf; the final PDF is checked again before atomic
publication. Existing caller output survives any render, OCR, validation, assembly, or publication
failure, and temporary workspaces are cleaned.

These workflows are intended for scanned or image-based PDFs. They rasterize and OCR every page;
text-native PDFs are not specially optimized. Searchable output is reconstructed from OCR page PDFs.
It does not preserve original vectors, fonts, selectable text, annotations, forms, hyperlinks,
structure trees, or embedded files. Detecting existing text and hybrid preservation of original
visuals are outside Commit 49.

Tests use the real bounded PDF renderer with dynamically generated PDFs and fake OCR engines. No
test needs a Tesseract installation. There is no OCR API/browser workflow, OCR CLI command,
JobManager integration, cloud OCR, or persistent user-file storage beyond requested outputs.

The progression is:

1. Commit 47: OCR engine foundation — complete.
2. Commit 48: image to text OCR — complete.
3. Commit 49: scanned PDF to text and searchable PDF — complete/current.
4. Commit 50: OCR API and browser workflows.
