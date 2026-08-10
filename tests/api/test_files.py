from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docuforge.api.files import create_download_response
from docuforge.api.workspace import RequestWorkspace


def test_download_returns_exact_file_and_cleans_workspace_after_response() -> None:
    application = FastAPI()
    workspace_paths = []

    @application.get("/download")
    async def download():
        with RequestWorkspace() as workspace:
            workspace_paths.append(workspace.path)
            output_path = workspace.path / "internal-result.bin"
            output_path.write_bytes(b"download payload")
            return create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename="result.bin",
                media_type="application/x-docuforge-test",
            )

    response = TestClient(application).get("/download")

    assert response.status_code == 200
    assert response.content == b"download payload"
    assert response.headers["content-type"] == "application/x-docuforge-test"
    assert response.headers["content-disposition"] == 'attachment; filename="result.bin"'
    assert not workspace_paths[0].exists()
    assert str(workspace_paths[0]) not in response.text


def test_missing_download_output_is_rejected_and_workspace_is_cleaned() -> None:
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        with pytest.raises(FileNotFoundError, match="download output does not exist"):
            create_download_response(
                workspace=workspace,
                output_path=workspace.path / "missing.bin",
                download_filename="result.bin",
            )

    assert not workspace_path.exists()


def test_directory_download_output_is_rejected() -> None:
    with RequestWorkspace() as workspace:
        directory = workspace.path / "output"
        directory.mkdir()

        with pytest.raises(ValueError, match="regular file"):
            create_download_response(
                workspace=workspace,
                output_path=directory,
                download_filename="result.bin",
            )


def test_download_output_outside_workspace_is_rejected(tmp_path) -> None:
    outside_path = tmp_path / "outside.bin"
    outside_path.write_bytes(b"outside")

    with (
        RequestWorkspace() as workspace,
        pytest.raises(ValueError, match="inside request workspace"),
    ):
        create_download_response(
            workspace=workspace,
            output_path=outside_path,
            download_filename="result.bin",
        )


def test_parent_escape_download_path_is_rejected() -> None:
    with RequestWorkspace() as workspace:
        escaped_path = workspace.path.parent / f"docuforge-escape-{uuid4().hex}.bin"
        escaped_path.write_bytes(b"escape")
        try:
            with pytest.raises(ValueError, match="inside request workspace"):
                create_download_response(
                    workspace=workspace,
                    output_path=workspace.path / ".." / escaped_path.name,
                    download_filename="result.bin",
                )
        finally:
            escaped_path.unlink()


@pytest.mark.parametrize(
    "filename",
    ["", "   ", ".", "..", "../result.bin", "..\\result.bin", "bad\x00name", "bad\nname"],
)
def test_unsafe_download_filename_is_rejected(filename: str) -> None:
    with RequestWorkspace() as workspace:
        output_path = workspace.path / "output.bin"
        output_path.write_bytes(b"output")

        with pytest.raises(ValueError, match="safe basename"):
            create_download_response(
                workspace=workspace,
                output_path=output_path,
                download_filename=filename,
            )
