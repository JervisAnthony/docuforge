from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.converters.ocr import OcrEngineUnavailableError
from docuforge.converters.office import OfficeEngineUnavailableError


class AvailableOfficeEngine:
    def convert_to_pdf(self, request):
        raise AssertionError("capability probes must not perform conversion")


class AvailableOcrEngine:
    def recognize(self, request):
        raise AssertionError("capability probes must not perform OCR")


def _unavailable_office():
    raise OfficeEngineUnavailableError("private /opt/office path")


def _unavailable_ocr():
    raise OcrEngineUnavailableError("private /opt/tesseract path")


def test_health_endpoint_returns_liveness_contract() -> None:
    settings = ApiSettings()
    response = TestClient(create_app(settings)).get("/api/v1/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "status": "ok",
        "service": "docuforge",
        "version": settings.version,
    }


def test_metadata_endpoint_returns_api_contract() -> None:
    settings = ApiSettings()
    response = TestClient(create_app(settings)).get("/api/v1")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {
        "name": "DocuForge API",
        "version": settings.version,
        "status": "available",
    }


def test_capabilities_report_both_injected_engines_available() -> None:
    response = TestClient(create_app(
        office_engine_factory=AvailableOfficeEngine,
        ocr_engine_factory=AvailableOcrEngine,
    )).get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "office_to_pdf": {"available": True},
        "ocr": {"available": True},
    }


def test_capabilities_report_office_unavailable_without_leaking_details() -> None:
    response = TestClient(create_app(
        office_engine_factory=_unavailable_office,
        ocr_engine_factory=AvailableOcrEngine,
    )).get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "office_to_pdf": {"available": False},
        "ocr": {"available": True},
    }
    assert "/opt/office" not in response.text


def test_capabilities_report_ocr_unavailable_without_leaking_details() -> None:
    response = TestClient(create_app(
        office_engine_factory=AvailableOfficeEngine,
        ocr_engine_factory=_unavailable_ocr,
    )).get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "office_to_pdf": {"available": True},
        "ocr": {"available": False},
    }
    assert "/opt/tesseract" not in response.text


def test_capabilities_return_200_when_both_engines_are_unavailable() -> None:
    response = TestClient(create_app(
        office_engine_factory=_unavailable_office,
        ocr_engine_factory=_unavailable_ocr,
    )).get("/api/v1/capabilities")

    assert response.status_code == 200
    assert response.json() == {
        "office_to_pdf": {"available": False},
        "ocr": {"available": False},
    }
    assert all(value not in response.text for value in ("/opt/office", "/opt/tesseract"))


def test_capabilities_follow_custom_api_prefix() -> None:
    client = TestClient(create_app(
        ApiSettings(api_prefix="/custom"),
        office_engine_factory=AvailableOfficeEngine,
        ocr_engine_factory=AvailableOcrEngine,
    ))

    assert client.get("/custom/capabilities").status_code == 200
    assert client.get("/api/v1/capabilities").status_code == 404


def test_health_readiness_and_metadata_do_not_probe_engine_factories() -> None:
    calls = {"office": 0, "ocr": 0}

    def office_factory():
        calls["office"] += 1
        return AvailableOfficeEngine()

    def ocr_factory():
        calls["ocr"] += 1
        return AvailableOcrEngine()

    settings = ApiSettings()
    client = TestClient(create_app(
        settings,
        office_engine_factory=office_factory,
        ocr_engine_factory=ocr_factory,
    ))
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert client.get("/api/v1/ready").json() == {
        "status": "ready",
        "service": "docuforge",
        "version": settings.version,
    }
    assert client.get("/api/v1").json()["status"] == "available"
    assert calls == {"office": 0, "ocr": 0}

    assert client.get("/api/v1/capabilities").status_code == 200
    assert calls == {"office": 1, "ocr": 1}


def test_separate_apps_keep_capability_factories_independent() -> None:
    available = TestClient(create_app(
        office_engine_factory=AvailableOfficeEngine,
        ocr_engine_factory=AvailableOcrEngine,
    ))
    unavailable = TestClient(create_app(
        office_engine_factory=_unavailable_office,
        ocr_engine_factory=_unavailable_ocr,
    ))

    assert available.get("/api/v1/capabilities").json()["office_to_pdf"]["available"]
    assert not unavailable.get("/api/v1/capabilities").json()["office_to_pdf"]["available"]
