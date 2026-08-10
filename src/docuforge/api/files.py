"""Safe generated-file download responses for the DocuForge API adapter."""

from os import PathLike
from pathlib import Path

from fastapi.responses import FileResponse

from docuforge.api.workspace import RequestWorkspace

MAX_DOWNLOAD_FILENAME_CHARS = 255


def create_download_response(
    *,
    workspace: RequestWorkspace,
    output_path: str | PathLike[str],
    download_filename: str,
    media_type: str | None = None,
) -> FileResponse:
    """Return a contained file and defer workspace cleanup until transmission ends."""
    workspace_path = workspace.path.resolve(strict=True)
    try:
        resolved_output = Path(output_path).resolve(strict=True)
    except FileNotFoundError:
        raise FileNotFoundError("download output does not exist") from None

    try:
        resolved_output.relative_to(workspace_path)
    except ValueError:
        raise ValueError("download output must be inside request workspace") from None
    if not resolved_output.is_file():
        raise ValueError("download output must be a regular file")

    _validate_download_filename(download_filename)
    response = FileResponse(
        path=resolved_output,
        media_type=media_type,
        filename=download_filename,
    )
    response.background = workspace.transfer_cleanup()
    return response


def _validate_download_filename(filename: str) -> None:
    if (
        not isinstance(filename, str)
        or filename in {"", ".", ".."}
        or not filename.strip()
        or len(filename) > MAX_DOWNLOAD_FILENAME_CHARS
        or "/" in filename
        or "\\" in filename
        or "\x00" in filename
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise ValueError("download filename must be a safe basename")
