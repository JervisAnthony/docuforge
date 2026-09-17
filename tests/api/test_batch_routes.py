"""FastAPI batch creation, polling, control, and download coverage."""

from io import BytesIO
from threading import Event
from time import monotonic, sleep
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

import docuforge.api.batches as batches_module
from docuforge.api import create_app
from tests.api.image_test_support import make_image
from tests.batch.test_document import RecordingEngine


def wait_for_terminal(client: TestClient, location: str) -> dict[str, object]:
    deadline = monotonic() + 5
    while monotonic() < deadline:
        payload = client.get(location).json()
        if payload["phase"] in {"ready", "error"}:
            return payload
        sleep(0.01)
    raise AssertionError("batch route did not reach a terminal phase")


def image_files(*names: str) -> list[tuple[str, tuple[str | None, bytes | str, str | None]]]:
    return [("file", (name, make_image(), "image/png")) for name in names]


@pytest.mark.parametrize(
    ("path", "fields", "operation"),
    [
        ("/api/v1/batches/images/convert", [("format", (None, "jpeg"))], "image.convert"),
        (
            "/api/v1/batches/images/resize",
            [("format", (None, "png")), ("max_width", (None, "60"))],
            "image.resize",
        ),
        (
            "/api/v1/batches/images/compress",
            [("format", (None, "webp")), ("quality", (None, "70"))],
            "image.compress",
        ),
    ],
)
def test_image_batch_routes_accept_order_poll_and_download(
    path: str,
    fields: list[tuple[str, tuple[None, str]]],
    operation: str,
) -> None:
    with TestClient(create_app()) as client:
        response = client.post(path, files=[*image_files("first.png", "second.png"), *fields])
        assert response.status_code == 202
        assert response.headers["location"].startswith("/api/v1/batches/")
        accepted = response.json()
        assert accepted["operation"] == operation
        assert [item["descriptor"] for item in accepted["items"]] == [
            "first.png",
            "second.png",
        ]
        assert all("path" not in item for item in accepted["items"])

        final = wait_for_terminal(client, response.headers["location"])
        assert final["status"] == "completed"
        assert final["progress_percent"] == 100
        assert final["summary"]["processed"] == 2
        assert final["can_download"] is True
        download = client.get(f"{response.headers['location']}/download")
        assert download.status_code == 200
        assert download.headers["content-type"] == "application/zip"
        assert "docuforge-batch-" in download.headers["content-disposition"]
        with ZipFile(BytesIO(download.content)) as archive:
            assert len(archive.namelist()) == 2


def office_bytes(extension: str) -> bytes:
    required = {
        ".docx": "word/document.xml",
        ".pptx": "ppt/presentation.xml",
        ".xlsx": "xl/workbook.xml",
    }[extension]
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(required, "<document/>")
    return output.getvalue()


def test_office_batch_allows_mixed_duplicate_and_unicode_names() -> None:
    app = create_app(office_engine_factory=RecordingEngine)
    files = [
        ("file", ("résumé.docx", office_bytes(".docx"), "application/octet-stream")),
        ("file", ("same.pptx", office_bytes(".pptx"), "application/octet-stream")),
        ("file", ("same.xlsx", office_bytes(".xlsx"), "application/octet-stream")),
    ]
    with TestClient(app) as client:
        response = client.post("/api/v1/batches/office/to-pdf", files=files)
        assert response.status_code == 202
        final = wait_for_terminal(client, response.headers["location"])
        assert [item["descriptor"] for item in final["items"]] == [
            "résumé.docx",
            "same.pptx",
            "same.xlsx",
        ]
        assert final["status"] == "completed"


def test_batch_validation_and_unknown_session_errors_are_safe() -> None:
    with TestClient(create_app()) as client:
        invalid = client.post(
            "/api/v1/batches/images/resize",
            files=[*image_files("one.png"), ("format", (None, "png"))],
        )
        assert invalid.status_code == 400
        assert invalid.json()["code"] == "invalid_batch_request"
        for suffix, method in [
            ("", client.get),
            ("/cancel", client.post),
            ("/recover", client.post),
            ("/download", client.get),
        ]:
            response = method(f"/api/v1/batches/unknown{suffix}")
            assert response.status_code == 404
            assert response.json()["code"] == "batch_not_found"


def test_cancel_is_cooperative_idempotent_and_recovery_reuses_identity() -> None:
    entered = Event()
    release = Event()
    real_runner = batches_module.batch_convert_images

    def blocking_runner(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_runner(*args, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(batches_module, "batch_convert_images", side_effect=blocking_runner),
        TestClient(create_app()) as client,
    ):
        response = client.post(
            "/api/v1/batches/images/convert",
            files=[*image_files("one.png", "two.png"), ("format", (None, "jpeg"))],
        )
        location = response.headers["location"]
        assert entered.wait(5)
        first = client.post(f"{location}/cancel")
        second = client.post(f"{location}/cancel")
        assert first.status_code == second.status_code == 202
        assert second.json()["cancellation_requested"] is True
        assert second.json()["phase"] == "cancelling"
        release.set()
        cancelled = wait_for_terminal(client, location)
        assert cancelled["status"] == "cancelled"
        assert cancelled["summary"]["cancelled"] == 2
        assert client.get(f"{location}/download").json()["code"] == "batch_has_no_outputs"

        recovered = client.post(f"{location}/recover")
        assert recovered.status_code == 202
        assert recovered.json()["attempt"] == 2
        final = wait_for_terminal(client, location)
        assert final["id"] == cancelled["id"]
        assert final["status"] == "completed"
        assert client.post(f"{location}/cancel").status_code == 409


def test_apps_do_not_share_batch_sessions() -> None:
    first_app = create_app()
    second_app = create_app()
    with TestClient(first_app) as first, TestClient(second_app) as second:
        response = first.post(
            "/api/v1/batches/images/convert",
            files=[*image_files("one.png"), ("format", (None, "jpeg"))],
        )
        assert second.get(response.headers["location"]).status_code == 404


def test_packaging_status_does_not_offer_or_accept_cancellation() -> None:
    entered = Event()
    release = Event()
    real_packager = batches_module.package_batch_outputs

    def blocking_packager(*args: object, **kwargs: object) -> object:
        entered.set()
        assert release.wait(5)
        return real_packager(*args, **kwargs)  # type: ignore[arg-type]

    with (
        patch.object(
            batches_module, "package_batch_outputs", side_effect=blocking_packager
        ),
        TestClient(create_app()) as client,
    ):
        response = client.post(
            "/api/v1/batches/images/convert",
            files=[*image_files("one.png"), ("format", (None, "jpeg"))],
        )
        location = response.headers["location"]
        assert entered.wait(5)
        packaging = client.get(location)
        assert packaging.status_code == 200
        assert packaging.json()["phase"] == "packaging"
        assert packaging.json()["can_cancel"] is False
        rejected = client.post(f"{location}/cancel")
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "batch_not_cancellable"
        release.set()
        assert wait_for_terminal(client, location)["phase"] == "ready"
