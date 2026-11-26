from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.converters.office import OfficeConversionResult, OfficeEngineUnavailableError
from docuforge.core import DocumentFormat
from docuforge.ops import batch_integration as integration
from docuforge.ops.batch_smoke import BATCH_CHECKS, Lifecycle, Timing
from docuforge.ops.deployment_smoke import HttpResponse
from tests.ops.office_ocr_support import text_pdf


class MixedOfficeDouble:
    """Parseable Office double for three formats; never real LibreOffice evidence."""

    def __init__(self):
        self.workspaces = []

    def convert_to_pdf(self, request):
        self.workspaces.append(request.input_path.parent)
        with ZipFile(BytesIO(request.input_path.read_bytes())) as archive:
            source = {
                ".docx": "word/document.xml",
                ".pptx": "ppt/slides/slide1.xml",
                ".xlsx": "xl/worksheets/sheet1.xml",
            }[request.input_path.suffix]
            root = ElementTree.fromstring(archive.read(source))
            text = " ".join(
                node.text for node in root.iter() if node.tag.endswith("}t") and node.text
            )
        output = request.output_directory / "result.pdf"
        output.write_bytes(text_pdf((200, 120, text)))
        return OfficeConversionResult(
            request.input_path, output, DocumentFormat.normalize(request.input_path.suffix[1:])
        )


def test_real_image_routes_mixed_office_doubles_delete_all_owned_workspaces():
    engine = MixedOfficeDouble()
    app = create_app(office_engine_factory=lambda: engine)
    service = app.state.batch_service
    workspaces = []
    with TestClient(app) as client:

        def requester(method, url, *, headers=None, body=None, timeout):
            result = client.request(
                method, url, content=body, headers=headers, follow_redirects=False
            )
            workspaces.extend(session.workspace.path for session in service._sessions.values())
            return HttpResponse(result.status_code, result.headers, result.content)

        report = Lifecycle(
            "https://testserver", requester=requester, timing=Timing(poll_interval=0.01)
        ).run()
        assert report["result"] == "PASS", report
        assert not service._sessions and not service._active_downloads
        assert workspaces and all(not path.exists() for path in workspaces)
    assert len(engine.workspaces) == 3
    assert report["identity"] == "NOT_RUN"


@pytest.mark.parametrize("fail", [False, True])
def test_disposable_loopback_harness_uses_real_routes_and_shuts_down(fail, monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://unreachable.invalid:1")
    engine = MixedOfficeDouble()

    def factory():
        if fail:
            raise OfficeEngineUnavailableError("private engine path")
        return engine

    app = create_app(office_engine_factory=factory)
    if fail:
        with pytest.raises(RuntimeError, match="batch_integration_failed"):
            integration.run_batch_integration(app=app)
    else:
        assert integration.run_batch_integration(app=app) == BATCH_CHECKS
    assert not app.state.batch_service._sessions
    assert all(not workspace.exists() for workspace in engine.workspaces)


@pytest.mark.parametrize("fail", [False, True])
def test_integration_cli_safe_separate_label(monkeypatch, capsys, fail):
    def run():
        if fail:
            raise RuntimeError("private engine path and token")
        return BATCH_CHECKS

    monkeypatch.setattr(integration, "run_batch_integration", run)
    assert integration.main() == int(fail)
    output = capsys.readouterr().out
    assert "private" not in output
    if not fail:
        assert output.strip() == "Batch API integration PASS: 4 lifecycles with confirmed cleanup"
