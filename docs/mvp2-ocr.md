# MVP2 OCR: engine foundation and image-to-text workflow

Commit 47 established a reusable, framework-independent OCR engine boundary. Commit 48 adds a
Python image-to-text workflow on top of it. OCR is not yet available through the API or browser.

```text
ImageToTextRequest / future PDF workflow
            |
            v
    ImageToTextConverter
            |
            v
        OcrEngine
            |
            v
 TesseractEngine / future engine
            |
            v
  external Tesseract CLI
```

`OcrEngine` accepts immutable `OcrEngineRequest` values and returns an `OcrEngineResult` describing
one validated artifact. Workflows depend on this protocol and supply their own image or PDF content
checks. `TesseractEngine` is the first implementation; it invokes the external executable with
separate arguments, no shell, captured diagnostics, and a finite timeout. Public errors do not
include process output or local paths.

The low-level engine accepts one JPEG (`.jpg` or `.jpeg`), PNG, WebP, BMP, or TIFF (`.tif` or
`.tiff`) raster input. It emits either UTF-8 recognized text (`TXT`, including valid empty text) or
a searchable PDF (`PDF`) for that one raster image. It does not accept PDF input directly. A later
scanned-PDF workflow will rasterize pages before calling the engine.

Each engine call writes into a unique `.docuforge-ocr-*` directory inside the caller's existing
output directory. The staged file must be current, regular, non-symlink, contained within that
workspace, and valid for its format. A valid result is published with `os.replace`; existing output
survives timeouts, process errors, missing or malformed artifacts, and publication failures. The
temporary workspace is cleaned on success and normal failure.

`ImageToTextRequest` names one raster source, an exact caller-selected `.txt` destination, and an
OCR language selector. `ImageToTextConverter` requires an injected `OcrEngine` and returns an
`ImageToTextResult` containing the exact recognized text, source format, and requested paths. The
`extract_text_from_image` helper delegates to this converter.

The workflow uses Pillow to fully decode one JPEG, PNG, WebP, BMP, or TIFF image before invoking
OCR. The decoded format must agree with the filename suffix, and multi-frame images are rejected.
The original raster is passed to the engine without re-encoding or preprocessing. The engine runs
inside a unique `.docuforge-image-ocr-*` workflow directory beneath the output parent. Its returned
result is checked for source, TXT target, language, regular non-symlink artifact, workspace
containment, and UTF-8 content. Only then is the artifact atomically moved to the requested path.
Text is returned and published exactly as decoded, including whitespace, newlines, Unicode, and
valid empty output. Existing output survives engine or validation failures. Structured engine
errors propagate to callers. No user files are persisted beyond the requested result artifact.

Tesseract remains an external system dependency; Commit 48 does not install it in production or
CI. Engine tests inject executable resolution and process execution. Workflow tests use fake engines
and need no Tesseract binary. There is no OCR API or browser workflow, no OCR CLI command, and no
JobManager integration yet.

The progression is:

1. Commit 47: OCR engine foundation — complete.
2. Commit 48: image to text OCR — complete/current.
3. Commit 49: scanned PDF to searchable PDF or extracted text.
4. Commit 50: OCR API and browser workflows.
