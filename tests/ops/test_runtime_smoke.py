"""Unit coverage for the production runtime verifier without host engines."""

import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest

from docuforge.ops import runtime_smoke
from docuforge.ops.runtime_smoke import RuntimeSmokeError, make_synthetic_docx


class FakeOfficeEngine:
    workspaces: ClassVar[list[Path]] = []

    def convert_to_pdf(self, request):
        self.workspaces.append(request.input_path.parent)
        output = request.output_directory / "runtime-smoke.pdf"
        output.write_bytes(b"%PDF-1.7\nsynthetic")
        return SimpleNamespace(output_path=output)


class FakeOcrEngine:
    workspaces: ClassVar[list[Path]] = []

    def recognize(self, request):
        self.workspaces.append(request.input_path.parent)
        output = request.output_directory / "runtime-smoke.txt"
        output.write_text("synthetic OCR", encoding="utf-8")
        return SimpleNamespace(output_path=output)


def test_synthetic_docx_has_minimum_valid_ooxml_parts() -> None:
    payload = make_synthetic_docx()

    with zipfile.ZipFile(BytesIO(payload)) as archive:
        assert set(archive.namelist()) == {
            "[Content_Types].xml",
            "_rels/.rels",
            "word/document.xml",
        }
        assert b"DocuForge runtime smoke" in archive.read("word/document.xml")


def test_runtime_smoke_succeeds_and_cleans_temporary_workspace() -> None:
    FakeOfficeEngine.workspaces.clear()
    FakeOcrEngine.workspaces.clear()

    checks = runtime_smoke.run_runtime_smoke(
        office_engine_factory=FakeOfficeEngine,
        ocr_engine_factory=FakeOcrEngine,
    )

    assert checks == ("office-runtime", "ocr-runtime")
    paths = FakeOfficeEngine.workspaces + FakeOcrEngine.workspaces
    assert paths and all(not path.exists() for path in paths)


def test_runtime_smoke_reports_safe_office_failure() -> None:
    def fail_office():
        raise RuntimeError("private Office executable path")

    with pytest.raises(RuntimeSmokeError, match="office-runtime check failed") as failure:
        runtime_smoke.run_runtime_smoke(
            office_engine_factory=fail_office,
            ocr_engine_factory=FakeOcrEngine,
        )
    assert "private Office" not in str(failure.value)


def test_runtime_smoke_reports_safe_ocr_failure() -> None:
    def fail_ocr():
        raise RuntimeError("private Tesseract stderr")

    with pytest.raises(RuntimeSmokeError, match="ocr-runtime check failed") as failure:
        runtime_smoke.run_runtime_smoke(
            office_engine_factory=FakeOfficeEngine,
            ocr_engine_factory=fail_ocr,
        )
    assert "private Tesseract" not in str(failure.value)


def test_runtime_smoke_cli_prints_stable_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        runtime_smoke,
        "run_runtime_smoke",
        lambda: ("office-runtime", "ocr-runtime"),
    )

    assert runtime_smoke.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS office-runtime",
        "PASS ocr-runtime",
        "Production runtime smoke passed: 2 checks",
    ]


def test_runtime_smoke_cli_failure_is_safe_and_nonzero(monkeypatch, capsys) -> None:
    def fail():
        raise RuntimeSmokeError("private engine exception")

    monkeypatch.setattr(runtime_smoke, "run_runtime_smoke", fail)

    assert runtime_smoke.main() == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "FAIL production-runtime check failed\n"
    assert "private engine" not in captured.err
