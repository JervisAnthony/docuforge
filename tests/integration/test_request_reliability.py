"""Request isolation, lifecycle, and repeat-operation integration coverage."""

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from threading import Lock
from zipfile import ZipFile

from fastapi.testclient import TestClient

from docuforge.api import create_app
from docuforge.api.workspace import RequestWorkspace
from tests.api.image_test_support import inspect_image, make_image
from tests.api.pdf_test_support import make_pdf, page_widths


def test_ten_concurrent_same_filename_requests_remain_isolated(
    monkeypatch,
) -> None:
    created_paths: list[Path] = []
    paths_lock = Lock()

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            with paths_lock:
                created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    monkeypatch.setattr("docuforge.api.routes.images.RequestWorkspace", RecordingWorkspace)

    def split_pdf(width: int) -> tuple[str, int]:
        response = TestClient(create_app()).post(
            "/api/v1/pdf/split",
            files={"file": ("input.pdf", make_pdf(width), "application/pdf")},
        )
        assert response.status_code == 200
        with ZipFile(BytesIO(response.content)) as archive:
            return "pdf", page_widths(archive.read(archive.namelist()[0]))[0]

    def resize_image(width: int) -> tuple[str, int]:
        response = TestClient(create_app()).post(
            "/api/v1/images/resize",
            files=[
                (
                    "file",
                    ("input.png", make_image(size=(width, 40)), "image/png"),
                ),
                ("format", (None, "png")),
                ("max_width", (None, str(width // 2))),
            ],
        )
        assert response.status_code == 200
        return "image", inspect_image(response.content)[1][0]

    def corrupt_pdf() -> tuple[str, int]:
        response = TestClient(create_app()).post(
            "/api/v1/pdf/split",
            files={"file": ("input.pdf", b"corrupt", "application/pdf")},
        )
        assert response.status_code == 422
        return "failure", response.status_code

    def corrupt_image() -> tuple[str, int]:
        response = TestClient(create_app()).post(
            "/api/v1/images/convert",
            files=[
                ("file", ("input.png", b"corrupt", "image/png")),
                ("format", (None, "webp")),
            ],
        )
        assert response.status_code == 422
        return "failure", response.status_code

    pdf_widths = [101, 202, 303, 404]
    image_widths = [80, 100, 120, 140]
    operations = [
        *(lambda width=width: split_pdf(width) for width in pdf_widths),
        *(lambda width=width: resize_image(width) for width in image_widths),
        corrupt_pdf,
        corrupt_image,
    ]
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda operation: operation(), operations))

    assert results[:4] == [("pdf", width) for width in pdf_widths]
    assert results[4:8] == [("image", width // 2) for width in image_widths]
    assert results[8:] == [("failure", 422), ("failure", 422)]
    assert len(created_paths) == 10
    assert len(set(created_paths)) == 10
    assert all(not path.exists() for path in created_paths)

    later_response = TestClient(create_app()).post(
        "/api/v1/images/convert",
        files=[
            ("file", ("input.png", make_image(size=(33, 22)), "image/png")),
            ("format", (None, "webp")),
        ],
    )
    assert later_response.status_code == 200
    assert inspect_image(later_response.content)[:2] == ("WEBP", (33, 22))
    assert len(created_paths) == 11
    assert not created_paths[-1].exists()


def test_success_and_failure_responses_clean_workspaces_after_body_consumption(
    monkeypatch,
) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.pdf.RequestWorkspace", RecordingWorkspace)
    monkeypatch.setattr("docuforge.api.routes.images.RequestWorkspace", RecordingWorkspace)
    client = TestClient(create_app())

    direct_pdf = client.post(
        "/api/v1/pdf/merge",
        files=[
            ("files", ("a.pdf", make_pdf(100), "application/pdf")),
            ("files", ("b.pdf", make_pdf(200), "application/pdf")),
        ],
    )
    direct_image = client.post(
        "/api/v1/images/convert",
        files=[
            ("file", ("source.png", make_image(), "image/png")),
            ("format", (None, "webp")),
        ],
    )
    archive = client.post(
        "/api/v1/pdf/split",
        files={"file": ("source.pdf", make_pdf(100, 200), "application/pdf")},
    )
    corrupt_pdf = client.post(
        "/api/v1/pdf/split",
        files={"file": ("broken.pdf", b"broken", "application/pdf")},
    )
    corrupt_image = client.post(
        "/api/v1/images/convert",
        files=[
            ("file", ("broken.png", b"broken", "image/png")),
            ("format", (None, "webp")),
        ],
    )
    invalid_conversion = client.post(
        "/api/v1/pdf/extract-pages",
        files=[
            ("file", ("source.pdf", make_pdf(100), "application/pdf")),
            ("page", (None, "2")),
        ],
    )

    assert page_widths(direct_pdf.content) == [100, 200]
    assert inspect_image(direct_image.content)[0] == "WEBP"
    with ZipFile(BytesIO(archive.content)) as output:
        assert len(output.namelist()) == 2
    assert [corrupt_pdf.status_code, corrupt_image.status_code] == [422, 422]
    assert invalid_conversion.status_code == 400
    assert len(created_paths) == 6
    assert all(not path.exists() for path in created_paths)


def test_twenty_sequential_conversions_do_not_accumulate_state(
    monkeypatch,
) -> None:
    created_paths: list[Path] = []

    class RecordingWorkspace(RequestWorkspace):
        def __init__(self) -> None:
            super().__init__()
            created_paths.append(self.path)

    monkeypatch.setattr("docuforge.api.routes.images.RequestWorkspace", RecordingWorkspace)
    client = TestClient(create_app())

    for iteration in range(20):
        size = (40 + iteration, 30)
        response = client.post(
            "/api/v1/images/convert",
            files=[
                ("file", ("input.png", make_image(size=size), "image/png")),
                ("format", (None, "webp")),
            ],
        )
        assert response.status_code == 200
        assert inspect_image(response.content)[:2] == ("WEBP", size)

    assert len(created_paths) == 20
    assert len(set(created_paths)) == 20
    assert all(not path.exists() for path in created_paths)
