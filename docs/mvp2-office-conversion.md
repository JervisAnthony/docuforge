# MVP2 Office conversion

## Purpose and scope

DocuForge uses LibreOffice as an external rendering backend because it provides one headless
conversion interface for the Open XML formats in this foundation:

- DOCX to PDF
- PPTX to PDF
- XLSX to PDF

Commit 42 provides the low-level engine contract. Commits 43 through 45 add concrete DOCX-to-PDF,
PPTX-to-PDF, and XLSX-to-PDF core workflows without FastAPI, CLI, frontend, jobs-package, or
uploaded-file coupling. No conversion-fidelity claim is made.

## DOCX to PDF core workflow

`DocxToPdfRequest` represents exactly one DOCX source and one exact PDF destination.
`DocxToPdfConverter` implements the standard converter contract and depends on an injected
`OfficeConversionEngine`; it does not select or instantiate LibreOffice itself. Custom destination
filenames are supported. Before rendering, the workflow performs lightweight DOCX authenticity
checking by requiring a readable OOXML ZIP package containing `[Content_Types].xml` and
`word/document.xml`.

Rendering occurs in an isolated workflow workspace inside the destination directory. The workflow
checks that the engine result matches the requested input and DOCX-to-PDF identity, and that its
artifact resolves inside that workspace. Only a valid result is atomically published to the exact
requested output path. Symlink and non-regular engine artifacts are rejected before publication.
Existing output remains untouched when rendering or validation fails.

## PPTX to PDF core workflow

`PptxToPdfRequest` fixes the conversion identity to one PPTX source and a caller-selected PDF
destination. `PptxToPdfConverter` uses an injected `OfficeConversionEngine` and validates a readable
OOXML ZIP package containing `[Content_Types].xml` and `ppt/presentation.xml` before invoking it.
Rendering uses a unique workflow workspace in the destination directory. The workflow checks the
engine result's PPTX-to-PDF identity, source path, regular-file artifact, and workspace provenance;
symlinks are rejected. It then atomically publishes the artifact to the exact requested destination.
The private workflow mechanics are shared with DOCX while each converter retains its own format
policy.

## XLSX to PDF core workflow

`XlsxToPdfRequest` fixes the identity to one XLSX workbook and an exact caller-selected PDF path.
`XlsxToPdfConverter` depends on an injected `OfficeConversionEngine` and uses the private shared
Office workflow. Before rendering, it requires a readable OOXML ZIP package containing
`[Content_Types].xml` and `xl/workbook.xml`.

The engine renders inside an isolated `.docuforge-xlsx-*` workspace in the destination directory.
The workflow checks result identity, source provenance, regular-file type, and workspace containment;
it rejects symlinks and non-regular artifacts before atomically publishing to the requested path.
Workbook rendering behavior is delegated to the Office engine. This core workflow exposes no
worksheet, range, or page-layout controls.

## Process model

`OfficeConversionEngine` defines the application-neutral contract. `LibreOfficeEngine` implements
it by resolving an explicitly configured executable first, followed by `soffice` and then
`libreoffice` on `PATH`.

Each conversion invokes LibreOffice in the current application process through a child process. The
arguments request headless PDF conversion, are passed without shell interpolation, and include a
finite timeout of 90 seconds by default. Standard output and error are captured, while public errors
remain safe and do not include raw process diagnostics.

Every invocation creates a unique temporary LibreOffice user profile and supplies its absolute file
URI through `-env:UserInstallation`. The profile is removed after success or failure. This avoids a
shared profile lock without introducing application or distributed locking.

LibreOffice writes into a unique staging directory inside the requested output directory. Success
requires more than a zero process exit code: the staged output must exist, be a regular non-empty
file, and begin with the PDF signature `%PDF-`. Only then is it atomically promoted to the final
path. A pre-existing destination is never treated as evidence from the current invocation and is
replaced only after the newly staged PDF passes validation.

## Deployment status and progression

LibreOffice is an external system dependency and is not yet guaranteed to be installed in the
production container. No user-facing Office conversion is production-supported by this foundation.
The progression is:

1. Commit 42: Office engine foundation — complete.
2. Commit 43: DOCX to PDF core workflow — complete.
3. Commit 44: PPTX to PDF core workflow — complete.
4. Commit 45: XLSX to PDF core workflow — complete/current.
5. Commit 46: Office API and browser workflows.

LibreOffice remains an external dependency and is not guaranteed in the production container. No
browser, API, CLI, or production Office workflow exists yet.
