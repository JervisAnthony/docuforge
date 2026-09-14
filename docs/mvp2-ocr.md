# MVP2 OCR: engine foundation

Commit 47 establishes a reusable, framework-independent OCR engine boundary. It does not yet
provide an image-to-text or scanned-PDF workflow to users.

```text
Future image / PDF workflow
            |
            v
        OcrEngine
            |
            v
     TesseractEngine
            |
            v
  external Tesseract CLI
```

`OcrEngine` accepts immutable `OcrEngineRequest` values and returns an `OcrEngineResult` describing
one validated artifact. Future workflows depend on this protocol and supply their own image or PDF
content checks. `TesseractEngine` is the first implementation; it invokes the external executable
with separate arguments, no shell, captured diagnostics, and a finite timeout. Public errors do not
include process output or local paths.

The low-level engine accepts one JPEG (`.jpg` or `.jpeg`), PNG, WebP, BMP, or TIFF (`.tif` or
`.tiff`) raster input. It emits either UTF-8 recognized text (`TXT`, including valid empty text) or
a searchable PDF (`PDF`) for that one raster image. It does not accept PDF input directly. A later
scanned-PDF workflow will rasterize pages before calling the engine.

Each call writes into a unique `.docuforge-ocr-*` directory inside the caller's existing output
directory. The staged file must be current, regular, non-symlink, contained within that workspace,
and valid for its format. A valid result is published with `os.replace`; existing output survives
timeouts, process errors, missing or malformed artifacts, and publication failures. The temporary
workspace is cleaned on success and normal failure. No user files are persistently stored by this
engine beyond the requested result artifact.

Tesseract remains an external system dependency. Commit 47 does not install it in production or
CI. Unit tests inject executable resolution and process execution, so CI needs no Tesseract binary.
There is no OCR API or browser workflow, no OCR CLI command, and no JobManager integration yet.

The progression is:

1. Commit 47: OCR engine foundation — complete/current.
2. Commit 48: image to text OCR.
3. Commit 49: scanned PDF to searchable PDF or extracted text.
4. Commit 50: OCR API and browser workflows.
