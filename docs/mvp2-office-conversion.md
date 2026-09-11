# MVP2 Office conversion engine

## Purpose and scope

DocuForge uses LibreOffice as an external rendering backend because it provides one headless
conversion interface for the Open XML formats in this foundation:

- DOCX to PDF
- PPTX to PDF
- XLSX to PDF

This is a low-level engine contract, not a user-facing Office workflow. The engine has no FastAPI,
CLI, frontend, jobs-package, or uploaded-file coupling, and no conversion-fidelity claim is made.

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

Success requires more than a zero process exit code: the expected output must exist, be a regular
non-empty file, and begin with the PDF signature `%PDF-`.

## Deployment status and progression

LibreOffice is an external system dependency and is not yet guaranteed to be installed in the
production container. No user-facing Office conversion is production-supported by this foundation.
The planned progression is:

1. Commit 43: DOCX to PDF workflow.
2. Commit 44: PPTX to PDF workflow.
3. Commit 45: XLSX to PDF workflow.
