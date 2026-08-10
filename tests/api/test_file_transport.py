from typing import Annotated

from fastapi import File, UploadFile
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.errors import ApiError
from docuforge.api.files import create_download_response
from docuforge.api.uploads import UploadPolicy, store_uploads
from docuforge.api.workspace import RequestWorkspace


def _small_policy(*, max_file_bytes: int = 100) -> UploadPolicy:
    return UploadPolicy(
        max_files=2,
        max_file_bytes=max_file_bytes,
        max_request_bytes=200,
        chunk_bytes=3,
    )


def test_multipart_upload_to_download_pipeline_cleans_after_response() -> None:
    application = create_app()
    workspace_paths = []

    @application.post("/test-transport")
    async def transport(files: Annotated[list[UploadFile], File()]):
        with RequestWorkspace() as workspace:
            workspace_paths.append(workspace.path)
            stored = await store_uploads(
                files,
                workspace=workspace,
                policy=_small_policy(),
            )
            output_path = workspace.path / "result.bin"
            output_path.write_bytes(b"result:" + stored[0].stored_path.read_bytes())
            assert workspace.path.exists()
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename="result.bin",
                media_type="application/octet-stream",
            )

    response = TestClient(application).post(
        "/test-transport",
        files={"files": ("../../source.txt", b"input", "text/plain")},
    )

    assert response.status_code == 200
    assert response.content == b"result:input"
    assert response.headers["content-disposition"] == 'attachment; filename="result.bin"'
    assert not workspace_paths[0].exists()


def test_processing_failure_after_upload_cleans_workspace_and_files() -> None:
    application = create_app()
    workspace_paths = []
    stored_paths = []

    @application.post("/test-failure")
    async def fail_after_upload(files: Annotated[list[UploadFile], File()]):
        with RequestWorkspace() as workspace:
            workspace_paths.append(workspace.path)
            stored = await store_uploads(
                files,
                workspace=workspace,
                policy=_small_policy(),
            )
            stored_paths.extend(item.stored_path for item in stored)
            raise ApiError(
                status_code=422,
                code="test_processing_failed",
                message="Test processing failed.",
            )

    response = TestClient(application).post(
        "/test-failure",
        files={"files": ("source.txt", b"input", "text/plain")},
    )

    assert response.status_code == 422
    assert response.json() == {
        "code": "test_processing_failed",
        "message": "Test processing failed.",
    }
    assert not workspace_paths[0].exists()
    assert all(not path.exists() for path in stored_paths)


def test_multipart_size_rejection_cleans_partial_upload() -> None:
    application = create_app()
    workspace_paths = []

    @application.post("/test-size-limit")
    async def enforce_size(files: Annotated[list[UploadFile], File()]):
        with RequestWorkspace() as workspace:
            workspace_paths.append(workspace.path)
            await store_uploads(
                files,
                workspace=workspace,
                policy=_small_policy(max_file_bytes=4),
            )

    response = TestClient(application).post(
        "/test-size-limit",
        files={"files": ("large.bin", b"12345", "application/octet-stream")},
    )

    assert response.status_code == 413
    assert response.json()["code"] == "upload_too_large"
    assert not workspace_paths[0].exists()


def test_production_application_exposes_no_file_routes() -> None:
    application = create_app(ApiSettings())

    assert set(application.openapi()["paths"]) == {"/api/v1", "/api/v1/health"}
    assert TestClient(application).post("/api/v1/upload").status_code == 404
