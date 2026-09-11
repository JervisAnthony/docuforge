# MVP2 Office conversion

## Purpose and scope

DocuForge uses LibreOffice as an external rendering backend because it provides one headless
conversion interface for the Open XML formats in this foundation:

- DOCX to PDF
- PPTX to PDF
- XLSX to PDF

Commit 42 provides the low-level engine contract. Commit 43 adds the first concrete core workflow,
DOCX to PDF, without FastAPI, CLI, frontend, jobs-package, or uploaded-file coupling. No
conversion-fidelity claim is made.

## DOCX to PDF core workflow

`DocxToPdfRequest` represents exactly one DOCX source and one exact PDF destination.
`DocxToPdfConverter` implements the standard converter contract and depends on an injected
`OfficeConversionEngine`; it does not select or instantiate LibreOffice itself. Custom destination
filenames are supported.

Rendering occurs in an isolated workflow workspace inside the destination directory. The workflow
checks that the engine result matches the requested input and DOCX-to-PDF identity, and that its
artifact resolves inside that workspace. Only a valid result is atomically published to the exact
requested output path. Existing output remains untouched when rendering or validation fails.

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
2. Commit 43: DOCX to PDF core workflow — complete/current.
3. Commit 44: PPTX to PDF core workflow.
4. Commit 45: XLSX to PDF core workflow.
5. Commit 46: Office API and browser workflows.

LibreOffice remains an external dependency and is not guaranteed in the production container. No
browser, API, CLI, or production Office workflow exists yet.
