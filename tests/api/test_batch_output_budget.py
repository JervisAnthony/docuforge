"""Service policy, settings, archives and durable capability recovery."""

from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from docuforge.api import ApiSettings, create_app
from docuforge.api.batch_access import BATCH_TOKEN_HEADER
from docuforge.api.batches import BatchExecutionPhase as Phase
from docuforge.batch import BatchItemStatus, BatchStatus
from tests.api.test_batch_service import create_request, service, wait_for

ENV = "DOCUFORGE_BATCH_MAX_PUBLISHED_OUTPUT_BYTES"


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "100", None])
def test_settings_and_service_validate(value):
    with pytest.raises(ValueError):
        ApiSettings(batch_max_published_output_bytes=value)
    with pytest.raises(ValueError):
        service(max_published_output_bytes=value)


@pytest.mark.parametrize(
    "value", ["", " ", "0", "-1", "1.5", "true", "false", "200MB", "1GiB", "bad"]
)
def test_environment_rejects_invalid(monkeypatch, value):
    monkeypatch.setenv(ENV, value)
    with pytest.raises(ValueError, match=ENV):
        ApiSettings.from_environment()


@pytest.mark.parametrize("value", [104857600, 209715200, 536870912])
def test_environment_and_independent_policy(monkeypatch, value):
    monkeypatch.setenv(ENV, str(value))
    assert ApiSettings.from_environment().batch_max_published_output_bytes == value
    assert ApiSettings(batch_max_published_output_bytes=1).batch_max_published_output_bytes == 1


def test_default_and_app_wiring(monkeypatch):
    monkeypatch.delenv(ENV, raising=False)
    assert ApiSettings.from_environment().batch_max_published_output_bytes == 209715200
    app = create_app(ApiSettings(batch_max_published_output_bytes=123))
    with TestClient(app):
        assert app.state.batch_service._max_published_output_bytes == 123


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("partial", [False, True])
def test_item_failure_and_archive(tmp_path, durable, partial):
    # Real JPEG output is independent of upload byte size; determine its exact size.
    runner = service(**({"storage_directory": tmp_path} if durable else {}))
    try:
        workspace, request = create_request(runner)
        grant = runner.create_session(request, workspace)
        ready = wait_for(runner, str(request.batch_id), grant.access_token, Phase.READY)
        size = (workspace.output_directory / ready.batch.items[0].result.descriptor).lstat().st_size
        runner.delete_session(str(request.batch_id), grant.access_token)
    finally:
        runner.shutdown()
    runner = service(
        max_published_output_bytes=size if partial else 1,
        **({"storage_directory": tmp_path} if durable else {}),
    )
    try:
        workspace, request = create_request(runner)
        grant = runner.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        ready = wait_for(runner, batch_id, token, Phase.READY)
        assert ready.batch.status is (BatchStatus.PARTIAL if partial else BatchStatus.FAILED)
        assert ready.session_error is None and ready.can_recover
        assert ready.can_download is partial
        failures = [item for item in ready.batch.items if item.status is BatchItemStatus.FAILED]
        assert all(item.failure.code == "batch_output_limit_exceeded" for item in failures)
        assert all(
            item.failure.message == "The batch output limit was exceeded." for item in failures
        )
        assert len(list(workspace.output_directory.iterdir())) == int(partial)
        if partial:
            path = runner.download_path(batch_id, token)
            with ZipFile(path) as archive:
                assert archive.namelist() == [ready.batch.items[0].result.descriptor]
            assert path.lstat().st_size + size > size  # ZIP bytes are outside policy.
        else:
            assert not (workspace.path / "result.zip").exists()
    finally:
        runner.shutdown()


@pytest.mark.parametrize("next_limit", [1, 1048576])
def test_durable_restart_same_capability_recovery(tmp_path, next_limit):
    first = service(storage_directory=tmp_path, max_published_output_bytes=1)
    try:
        workspace, request = create_request(first)
        grant = first.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        wait_for(first, batch_id, token, Phase.READY)
    finally:
        first.shutdown()
    second = service(storage_directory=tmp_path, max_published_output_bytes=next_limit)
    try:
        restored = second.get(batch_id, token)
        assert restored.batch.status is BatchStatus.FAILED and restored.can_recover
        second.recover(batch_id, token)
        ready = wait_for(second, batch_id, token, Phase.READY)
        assert ready.attempt == 2 and ready.session_error is None
        assert ready.batch.status is (
            BatchStatus.FAILED if next_limit == 1 else BatchStatus.COMPLETED
        )
        assert ready.can_download is (next_limit > 1)
        if next_limit > 1:
            with ZipFile(second.download_path(batch_id, token)) as archive:
                assert len(archive.namelist()) == 2
    finally:
        second.shutdown()


def test_http_accepted_then_normal_item_failure():
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (1, 1)).save(image, format="PNG")
    with TestClient(create_app(ApiSettings(batch_max_published_output_bytes=1))) as client:
        response = client.post(
            "/api/v1/batches/images/convert",
            files=[("file", ("tiny.png", image.getvalue(), "image/png"))],
            data={"format": "bmp"},
        )
        assert response.status_code == 202
        token = response.headers[BATCH_TOKEN_HEADER]
        location = response.headers["location"]
        from time import monotonic, sleep

        deadline = monotonic() + 5
        while monotonic() < deadline:
            status = client.get(location, headers={BATCH_TOKEN_HEADER: token})
            assert status.status_code == 200
            body = status.json()
            if body["phase"] == "ready":
                break
            sleep(0.01)
        assert body["session_error"] is None
        assert body["items"][0]["failure"]["code"] == "batch_output_limit_exceeded"


def test_lowered_limit_preserves_terminal_archive_and_selective_recovery(tmp_path):
    from PIL import Image

    from docuforge.batch import BatchImageConvertRequest

    first = service(storage_directory=tmp_path, max_published_output_bytes=58)
    try:
        workspace, base = create_request(first)
        for item in base.items:
            Image.new("RGB", (1, 1)).save(item.input_path)
        request = BatchImageConvertRequest(base.items, base.output_directory, "bmp", base.batch_id)
        grant = first.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        ready = wait_for(first, batch_id, token, Phase.READY)
        assert ready.batch.status is BatchStatus.PARTIAL
        preserved = workspace.output_directory / ready.batch.items[0].result.descriptor
        contents = preserved.read_bytes()
    finally:
        first.shutdown()
    lowered = service(storage_directory=tmp_path, max_published_output_bytes=1)
    try:
        assert lowered.get(batch_id, token).can_download
        assert lowered.download_path(batch_id, token).is_file()
        lowered.recover(batch_id, token)
        ready = wait_for(lowered, batch_id, token, Phase.READY)
        assert ready.batch.status is BatchStatus.PARTIAL
        assert ready.batch.items[1].failure.code == "batch_output_limit_exceeded"
        assert preserved.read_bytes() == contents
        assert ready.can_download and ready.can_recover and ready.session_error is None
    finally:
        lowered.shutdown()
    raised = service(storage_directory=tmp_path, max_published_output_bytes=116)
    try:
        raised.recover(batch_id, token)
        ready = wait_for(raised, batch_id, token, Phase.READY)
        assert ready.batch.status is BatchStatus.COMPLETED
        assert preserved.read_bytes() == contents
    finally:
        raised.shutdown()


@pytest.mark.parametrize("operation", ["convert", "resize", "compress", "documents"])
def test_service_supplies_policy_to_every_operation(operation):
    from unittest.mock import patch

    import docuforge.api.batches as module
    from docuforge.batch import (
        BatchDocumentConvertRequest,
        BatchDocumentInput,
        BatchImageCompressRequest,
        BatchImageResizeRequest,
    )
    from tests.batch.test_document import write_office

    runner = service(max_published_output_bytes=1)
    try:
        workspace, base = create_request(runner, ("one.png",))
        if operation == "convert":
            request, function = base, "batch_convert_images"
        elif operation == "resize":
            request = BatchImageResizeRequest(
                base.items, base.output_directory, "jpg", max_width=1, batch_id=base.batch_id
            )
            function = "batch_resize_images"
        elif operation == "compress":
            request = BatchImageCompressRequest(
                base.items, base.output_directory, "jpg", quality=80, batch_id=base.batch_id
            )
            function = "batch_compress_images"
        else:
            source = base.items[0].input_path.with_suffix(".docx")
            write_office(source)
            request = BatchDocumentConvertRequest(
                (BatchDocumentInput(source),), base.output_directory, base.batch_id
            )
            function = "batch_convert_documents"
        with patch.object(module, function, wraps=getattr(module, function)) as convert:
            grant = runner.create_session(request, workspace)
            ready = wait_for(runner, str(request.batch_id), grant.access_token, Phase.READY)
        assert convert.call_args.kwargs["max_published_output_bytes"] == 1
        assert ready.batch.items[0].failure.code == "batch_output_limit_exceeded"
        assert ready.session_error is None
    finally:
        runner.shutdown()
