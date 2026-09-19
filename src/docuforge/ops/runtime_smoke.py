"""Exercise the real production Office and OCR engines with synthetic fixtures."""

from __future__ import annotations

import stat
import sys
import tempfile
import zipfile
from collections.abc import Callable
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

from docuforge.converters.ocr import OcrEngineRequest, TesseractEngine
from docuforge.converters.office import LibreOfficeEngine, OfficeConversionRequest
from docuforge.core import DocumentFormat


class RuntimeSmokeError(RuntimeError):
    """Safe failure raised by a production runtime smoke check."""


OfficeFactory = Callable[[], LibreOfficeEngine]
OcrFactory = Callable[[], TesseractEngine]


def make_synthetic_docx() -> bytes:
    """Build a minimal valid DOCX containing only synthetic smoke text."""
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>DocuForge runtime smoke</w:t></w:r></w:p><w:sectPr/></w:body>
</w:document>"""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def make_synthetic_ocr_png() -> bytes:
    """Build a small synthetic raster fixture for Tesseract execution."""
    buffer = BytesIO()
    image = Image.new("RGB", (640, 160), "white")
    ImageDraw.Draw(image).text((32, 56), "DocuForge runtime smoke 123", fill="black")
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def run_runtime_smoke(
    *,
    office_engine_factory: OfficeFactory = LibreOfficeEngine,
    ocr_engine_factory: OcrFactory = TesseractEngine,
) -> tuple[str, ...]:
    """Run both engine checks in one automatically cleaned workspace."""
    with tempfile.TemporaryDirectory(prefix="docuforge-runtime-smoke-") as directory:
        workspace = Path(directory)
        checks = (
            ("office-runtime", lambda: _check_office(workspace, office_engine_factory)),
            ("ocr-runtime", lambda: _check_ocr(workspace, ocr_engine_factory)),
        )
        passed: list[str] = []
        for name, check in checks:
            try:
                check()
            except Exception as error:
                raise RuntimeSmokeError(f"{name} check failed") from error
            passed.append(name)
        return tuple(passed)


def _check_office(workspace: Path, engine_factory: OfficeFactory) -> None:
    source = workspace / "runtime-smoke.docx"
    output_directory = workspace / "office-output"
    source.write_bytes(make_synthetic_docx())
    output_directory.mkdir()
    result = engine_factory().convert_to_pdf(
        OfficeConversionRequest(source, output_directory)
    )
    output = _require_contained_regular_file(result.output_path, workspace)
    with output.open("rb") as artifact:
        if artifact.read(5) != b"%PDF-":
            raise RuntimeSmokeError("office runtime produced an invalid artifact")


def _check_ocr(workspace: Path, engine_factory: OcrFactory) -> None:
    source = workspace / "runtime-smoke.png"
    output_directory = workspace / "ocr-output"
    source.write_bytes(make_synthetic_ocr_png())
    output_directory.mkdir()
    result = engine_factory().recognize(
        OcrEngineRequest(
            input_path=source,
            output_directory=output_directory,
            output_format=DocumentFormat.TXT,
            language="eng",
        )
    )
    output = _require_contained_regular_file(result.output_path, workspace)
    output.read_bytes().decode("utf-8")


def _require_contained_regular_file(path: Path, workspace: Path) -> Path:
    candidate = Path(path)
    if not stat.S_ISREG(candidate.lstat().st_mode):
        raise RuntimeSmokeError("runtime produced an unsafe artifact")
    candidate.resolve(strict=True).relative_to(workspace.resolve(strict=True))
    return candidate


def main() -> int:
    """Run the production engine verifier with stable, safe console output."""
    try:
        checks = run_runtime_smoke()
    except (RuntimeSmokeError, OSError):
        print("FAIL production-runtime check failed", file=sys.stderr)
        return 1
    for check in checks:
        print(f"PASS {check}")
    print(f"Production runtime smoke passed: {len(checks)} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
