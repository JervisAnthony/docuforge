import threading

import pytest
from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.converters.office import OfficeEngineUnavailableError
from docuforge.ops import office_ocr_integration as integration
from docuforge.ops.deployment_smoke import OFFICE_OCR_CHECKS, DeploymentSmokeError, HttpResponse
from tests.ops.office_ocr_support import TextOcrEngine, TextOfficeEngine


def test_new_smoke_requests_through_local_api_with_parseable_engine_doubles():
    office = TextOfficeEngine()
    ocr = TextOcrEngine()
    with TestClient(
        create_app(office_engine_factory=lambda: office, ocr_engine_factory=lambda: ocr)
    ) as client:
        calls = []

        def requester(method, url, *, headers=None, body=None, timeout):
            from urllib.parse import urlsplit

            path = urlsplit(url).path
            calls.append(path)
            response = client.request(method, path, content=body, headers=headers)
            return HttpResponse(response.status_code, response.headers, response.content)

        runner = integration.ProductionSmokeRunner(
            api_url="https://api.example.com",
            frontend_url="https://app.example.com",
            requester=requester,
        )
        for name in OFFICE_OCR_CHECKS:
            getattr(runner, f"_check_{name.replace('-', '_')}")()
    assert calls == ["/api/v1/" + name.replace("-", "/", 1) for name in OFFICE_OCR_CHECKS]
    assert len(office.workspaces) == 2 and len(ocr.workspaces) == 4
    assert all(not path.exists() for path in office.workspaces + ocr.workspaces)


@pytest.mark.parametrize("fail", [False, True])
def test_disposable_loopback_harness_cleans_up_even_when_a_check_fails(fail, monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://unreachable.invalid:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://unreachable.invalid:1")
    office = TextOfficeEngine()
    ocr = TextOcrEngine()

    def factory():
        if fail:
            raise OfficeEngineUnavailableError("private engine path or diagnostics")
        return office

    app = create_app(office_engine_factory=factory, ocr_engine_factory=lambda: ocr)
    if fail:
        with pytest.raises(
            DeploymentSmokeError, match="office-pptx-to-pdf: download returned HTTP 503"
        ) as failure:
            integration.run_office_ocr_integration(app=app)
        assert "private" not in str(failure.value)
    else:
        assert integration.run_office_ocr_integration(app=app) == OFFICE_OCR_CHECKS
    assert not any(thread.name == "docuforge-office-ocr-api" for thread in threading.enumerate())
    assert all(not path.exists() for path in office.workspaces + ocr.workspaces)


def test_loopback_transport_uses_bounded_reads_and_cleans_up_on_oversize(monkeypatch):
    from docuforge.ops import deployment_smoke

    monkeypatch.setattr(deployment_smoke, "MAX_RESPONSE_BYTES", 8)
    app = create_app(office_engine_factory=TextOfficeEngine, ocr_engine_factory=TextOcrEngine)
    with pytest.raises(
        DeploymentSmokeError, match="office-pptx-to-pdf: response exceeds smoke size limit"
    ):
        integration.run_office_ocr_integration(app=app)
    assert not any(thread.name == "docuforge-office-ocr-api" for thread in threading.enumerate())


@pytest.mark.parametrize("fail", [False, True])
def test_integration_cli_labels_separate_evidence_and_never_prints_raw_errors(
    monkeypatch, capsys, fail
):
    def run():
        if fail:
            raise RuntimeError("private text and engine diagnostics")
        return OFFICE_OCR_CHECKS

    monkeypatch.setattr(integration, "run_office_ocr_integration", run)
    assert integration.main() == int(fail)
    output = capsys.readouterr()
    assert "private" not in output.out + output.err
    if not fail:
        assert output.out.strip() == "Office/OCR API integration PASS: 4 checks"
