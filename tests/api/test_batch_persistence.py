"""Durable batch repository, serialization, and restart integration coverage."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from time import monotonic, sleep
from unittest.mock import patch
from zipfile import ZipFile

import pytest
from PIL import Image

import docuforge.api.batch_persistence as persistence_module
import docuforge.api.batches as batches_module
from docuforge.api.batch_persistence import (
    DATABASE_NAME,
    SCHEMA_VERSION,
    BatchPersistenceError,
    BatchSessionRecord,
    BatchSessionRepository,
    BatchSessionWorkspace,
    decode_record,
    encode_record,
    prepare_durable_storage,
)
from docuforge.api.batches import BatchExecutionPhase, BatchExecutionService, _initial_batch
from docuforge.batch import (
    BatchDocumentConvertRequest,
    BatchDocumentInput,
    BatchDocumentOutput,
    BatchDocumentResult,
    BatchId,
    BatchImageCompressRequest,
    BatchImageConvertRequest,
    BatchImageInput,
    BatchImageResizeRequest,
    BatchItemFailure,
    BatchItemResult,
    BatchItemStatus,
    BatchProcessingError,
)
from tests.batch.test_document import RecordingEngine


def service(storage: Path, **kwargs) -> BatchExecutionService:
    return BatchExecutionService(
        office_engine_factory=RecordingEngine,
        max_workers=1,
        storage_directory=storage,
        **kwargs,
    )


def image_request(
    runner: BatchExecutionService, names: tuple[str, ...] = ("one.png", "two.png")
):
    workspace = runner.create_workspace()
    items = []
    for position, name in enumerate(names, start=1):
        directory = workspace.inputs_directory / f"item-{position:04d}"
        directory.mkdir()
        path = directory / name
        Image.new("RGB", (8, 8), "blue").save(path)
        items.append(BatchImageInput(path, descriptor=name))
    request = BatchImageConvertRequest(
        tuple(items), workspace.output_directory, "jpg", workspace.batch_id
    )
    return workspace, request


def wait_for(runner: BatchExecutionService, batch_id: str, phase: BatchExecutionPhase):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        snapshot = runner.get(batch_id)
        if snapshot.phase is phase:
            return snapshot
        sleep(0.01)
    raise AssertionError("batch did not reach expected phase")


def record(batch_id: str) -> BatchSessionRecord:
    return BatchSessionRecord(
        batch_id=batch_id,
        operation="image.convert",
        attempt=1,
        phase="queued",
        cancellation_requested=False,
        request_json="{}",
        batch_json="{}",
        result_json=None,
        session_error_json=None,
        archive_available=False,
        updated_at=100.0,
    )


def test_repository_initializes_version_and_crud(tmp_path: Path) -> None:
    repository = BatchSessionRepository(tmp_path)
    batch_id = "11111111-1111-4111-8111-111111111111"
    value = record(batch_id)

    with sqlite3.connect(tmp_path / DATABASE_NAME) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    repository.add(value)
    assert repository.get(batch_id) == value
    updated = replace(value, attempt=2, updated_at=200.0)
    repository.save(updated)
    assert repository.list_all() == (updated,)
    repository.delete(batch_id)
    assert repository.get(batch_id) is None


def test_repository_reopens_and_rejects_duplicate_or_newer_schema(tmp_path: Path) -> None:
    repository = BatchSessionRepository(tmp_path)
    value = record("22222222-2222-4222-8222-222222222222")
    repository.add(value)
    assert BatchSessionRepository(tmp_path).get(value.batch_id) == value
    with pytest.raises(BatchPersistenceError):
        repository.add(value)

    newer = tmp_path / "newer"
    newer.mkdir()
    with sqlite3.connect(newer / DATABASE_NAME) as connection:
        connection.execute("PRAGMA user_version = 99")
    with pytest.raises(BatchPersistenceError, match="Unsupported"):
        BatchSessionRepository(newer)


def test_repository_parameterizes_unusual_json_and_hides_sql_details(tmp_path: Path) -> None:
    repository = BatchSessionRepository(tmp_path)
    value = replace(
        record("33333333-3333-4333-8333-333333333333"),
        request_json=json.dumps({"descriptor": "'); DROP TABLE batch_sessions; --"}),
    )
    repository.add(value)
    assert repository.get(value.batch_id) == value
    assert len(repository.list_all()) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"schema_version": True},
        {"operation": "unknown.operation"},
        {"attempt": True},
        {"phase": "unknown"},
        {"cancellation_requested": 1},
        {"archive_available": 0},
        {"updated_at": float("inf")},
    ],
)
def test_repository_rejects_invalid_record_scalars(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    repository = BatchSessionRepository(tmp_path)
    value = replace(record("34343434-3434-4434-8434-343434343434"), **changes)

    with pytest.raises(BatchPersistenceError):
        repository.add(value)


def test_repository_connections_are_safe_across_threads(tmp_path: Path) -> None:
    repository = BatchSessionRepository(tmp_path)
    value = record("44444444-4444-4444-8444-444444444444")
    repository.add(value)

    with ThreadPoolExecutor(max_workers=4) as executor:
        updates = tuple(
            executor.map(
                lambda attempt: repository.save(replace(value, attempt=attempt)),
                range(1, 9),
            )
        )

    assert updates == (None,) * 8
    assert repository.get(value.batch_id) is not None


def test_startup_removes_crash_before_registration_workspace_and_upload(
    tmp_path: Path,
) -> None:
    first = service(tmp_path)
    workspace = first.create_workspace()
    item_directory = workspace.inputs_directory / "item-0001"
    item_directory.mkdir()
    upload = item_directory / "private-upload.png"
    upload.write_bytes(b"synthetic upload")
    first.shutdown()

    second = service(tmp_path)
    assert not workspace.path.exists()
    assert not upload.exists()
    second.shutdown()


def test_startup_removes_rowless_workspace_from_interrupted_cleanup(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    rowless = BatchSessionWorkspace.durable_new(sessions_root)
    marker = rowless.output_directory / "stale-output.bin"
    marker.write_bytes(b"stale")

    runner = service(tmp_path)
    assert not rowless.path.exists()
    runner.shutdown()


def test_startup_removes_only_orphan_and_preserves_referenced_workspace(
    tmp_path: Path,
) -> None:
    first = service(tmp_path)
    referenced, request = image_request(first, ("one.png",))
    first.create_session(request, referenced)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    first.shutdown()
    orphan = BatchSessionWorkspace.durable_new(tmp_path / "sessions")

    second = service(tmp_path)
    assert not orphan.path.exists()
    assert referenced.path.is_dir()
    assert second.get(str(request.batch_id)).phase is BatchExecutionPhase.READY
    second.shutdown()


def test_startup_leaves_unrelated_non_batch_entry_untouched(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    unrelated = sessions_root / "operator-notes"
    unrelated.mkdir()
    marker = unrelated / "keep.txt"
    marker.write_text("keep", encoding="utf-8")

    runner = service(tmp_path)
    assert marker.read_text(encoding="utf-8") == "keep"
    runner.shutdown()


def test_startup_never_follows_uuid_named_symlink(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    link = sessions_root / str(BatchId.new())
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(BatchPersistenceError, match="reconciliation failed"):
        service(tmp_path)
    assert marker.read_text(encoding="utf-8") == "keep"


def test_orphan_cleanup_failure_fails_startup_without_path_leak(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    orphan = BatchSessionWorkspace.durable_new(sessions_root)
    with (
        patch.object(persistence_module.shutil, "rmtree", side_effect=OSError("private path")),
        pytest.raises(BatchPersistenceError) as error,
    ):
        service(tmp_path)

    assert str(error.value) == "Batch workspace reconciliation failed."
    assert str(orphan.path) not in str(error.value)


@pytest.mark.parametrize("kind", ["convert", "resize", "compress", "document"])
def test_request_and_batch_serialization_round_trip(tmp_path: Path, kind: str) -> None:
    runner = service(tmp_path)
    workspace = runner.create_workspace()
    item_dir = workspace.inputs_directory / "item-0001"
    item_dir.mkdir()
    suffix = ".docx" if kind == "document" else ".png"
    source = item_dir / f"file with spaces{suffix}"
    source.write_bytes(b"office" if kind == "document" else b"not-needed-for-metadata")
    if kind == "document":
        request = BatchDocumentConvertRequest(
            (BatchDocumentInput(source, descriptor="same ☃"),),
            workspace.output_directory,
            workspace.batch_id,
        )
    else:
        item = (BatchImageInput(source, descriptor="same ☃"),)
        if kind == "convert":
            request = BatchImageConvertRequest(item, workspace.output_directory, "jpg", workspace.batch_id)
        elif kind == "resize":
            request = BatchImageResizeRequest(
                item, workspace.output_directory, "png", max_width=10,
                allow_upscale=True, batch_id=workspace.batch_id,
            )
        else:
            request = BatchImageCompressRequest(
                item, workspace.output_directory, "webp", quality=70,
                batch_id=workspace.batch_id,
            )
    batch = _initial_batch(request)
    persisted = encode_record(
        request=request, batch=batch, result=None, attempt=1, phase="queued",
        cancellation_requested=False, session_error=None, archive_available=False,
        updated_at=10.0, workspace=workspace,
    )
    restored_request, restored_batch, result, error = decode_record(persisted, workspace)
    assert type(restored_request) is type(request)
    assert restored_request == request
    assert restored_batch.request == batch.request
    assert result is error is None
    runner.shutdown()


def test_batch_item_states_round_trip(tmp_path: Path) -> None:
    runner = service(tmp_path)
    workspace, request = image_request(runner, ("one.png", "two.png", "three.png", "four.png"))
    batch = _initial_batch(request)
    batch = batch.start_item(batch.items[0].id)
    batch = batch.complete_item(batch.items[0].id, BatchItemResult("0001-one.jpg"))
    batch = batch.fail_item(batch.items[1].id, BatchItemFailure("safe", "Safe failure."))
    batch = batch.cancel_item(batch.items[2].id)
    batch = batch.start_item(batch.items[3].id)
    persisted = encode_record(
        request=request, batch=batch, result=None, attempt=2, phase="processing",
        cancellation_requested=True, session_error=("safe_error", "Safe error."),
        archive_available=False, updated_at=20.0, workspace=workspace,
    )
    _, restored, _, error = decode_record(persisted, workspace)
    assert [item.status for item in restored.items] == [
        BatchItemStatus.COMPLETED,
        BatchItemStatus.FAILED,
        BatchItemStatus.CANCELLED,
        BatchItemStatus.RUNNING,
    ]
    assert error == ("safe_error", "Safe error.")
    runner.shutdown()


def test_typed_document_result_round_trip_revalidates_pdf(tmp_path: Path) -> None:
    runner = service(tmp_path)
    workspace = runner.create_workspace()
    item_dir = workspace.inputs_directory / "item-0001"
    item_dir.mkdir()
    source = item_dir / "proposal.docx"
    source.write_bytes(b"synthetic office input")
    request = BatchDocumentConvertRequest(
        (BatchDocumentInput(source, descriptor="proposal.docx"),),
        workspace.output_directory,
        workspace.batch_id,
    )
    batch = _initial_batch(request)
    output = workspace.output_directory / "0001-proposal.pdf"
    output.write_bytes(b"%PDF-1.7\nsynthetic")
    batch = batch.start_item(batch.items[0].id)
    batch = batch.complete_item(batch.items[0].id, BatchItemResult(output.name))
    result = BatchDocumentResult(
        batch,
        workspace.output_directory,
        (BatchDocumentOutput(
            batch.items[0].id, 0, source, output, "docx"
        ),),
    )
    persisted = encode_record(
        request=request, batch=batch, result=result, attempt=1, phase="ready",
        cancellation_requested=False, session_error=None, archive_available=False,
        updated_at=20.0, workspace=workspace,
    )
    _, _, restored, _ = decode_record(persisted, workspace)
    assert isinstance(restored, BatchDocumentResult)
    assert restored.outputs[0].output_path == output
    runner.shutdown()


@pytest.mark.parametrize(
    "unsafe",
    ["../escape.png", "/absolute.png", "C:/drive.png", "C:\\drive.png", "\\\\server\\file"],
)
def test_serialization_rejects_unsafe_persisted_input_paths(
    tmp_path: Path, unsafe: str
) -> None:
    runner = service(tmp_path)
    workspace, request = image_request(runner, ("one.png",))
    persisted = encode_record(
        request=request, batch=_initial_batch(request), result=None, attempt=1,
        phase="queued", cancellation_requested=False, session_error=None,
        archive_available=False, updated_at=10.0, workspace=workspace,
    )
    payload = json.loads(persisted.request_json)
    payload["items"][0]["input"] = unsafe
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, request_json=json.dumps(payload)), workspace)
    runner.shutdown()


@pytest.mark.parametrize(
    ("changes"),
    [
        {"schema_version": 2},
        {"batch_id": "not-a-uuid"},
        {"operation": "unknown.operation"},
        {"phase": "unknown"},
    ],
)
def test_decoder_rejects_unknown_record_identity_and_enums(
    tmp_path: Path, changes: dict[str, object]
) -> None:
    runner = service(tmp_path)
    workspace, request = image_request(runner, ("one.png",))
    persisted = encode_record(
        request=request, batch=_initial_batch(request), result=None, attempt=1,
        phase="queued", cancellation_requested=False, session_error=None,
        archive_available=False, updated_at=10.0, workspace=workspace,
    )
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, **changes), workspace)
    runner.shutdown()


def test_decoder_rejects_unknown_status_duplicate_ids_and_bad_format(tmp_path: Path) -> None:
    runner = service(tmp_path)
    workspace, request = image_request(runner, ("one.png", "two.png"))
    persisted = encode_record(
        request=request, batch=_initial_batch(request), result=None, attempt=1,
        phase="queued", cancellation_requested=False, session_error=None,
        archive_available=False, updated_at=10.0, workspace=workspace,
    )
    batch_payload = json.loads(persisted.batch_json)
    batch_payload["items"][0]["status"] = "unknown"
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, batch_json=json.dumps(batch_payload)), workspace)

    batch_payload = json.loads(persisted.batch_json)
    batch_payload["items"][0]["status"] = "running"
    batch_payload["items"][0]["result"] = "impossible.jpg"
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, batch_json=json.dumps(batch_payload)), workspace)

    request_payload = json.loads(persisted.request_json)
    request_payload["items"][1]["id"] = request_payload["items"][0]["id"]
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, request_json=json.dumps(request_payload)), workspace)
    request_payload = json.loads(persisted.request_json)
    request_payload["target_format"] = "gif"
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, request_json=json.dumps(request_payload)), workspace)
    runner.shutdown()


def test_decoder_rejects_impossible_terminal_error_and_archive_combinations(
    tmp_path: Path,
) -> None:
    runner = service(tmp_path)
    workspace, request = image_request(runner, ("one.png",))
    request.items[0].input_path.write_bytes(b"corrupt image")
    runner.create_session(request, workspace)
    wait_for(runner, str(request.batch_id), BatchExecutionPhase.READY)
    repository = BatchSessionRepository(tmp_path)
    persisted = repository.get(str(request.batch_id))
    assert persisted is not None and persisted.result_json is not None

    with pytest.raises(BatchPersistenceError):
        decode_record(
            replace(
                persisted,
                session_error_json=json.dumps({"code": "impossible", "message": "error"}),
            ),
            workspace,
        )
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, phase="error"), workspace)
    with pytest.raises(BatchPersistenceError):
        decode_record(replace(persisted, archive_available=True), workspace)
    runner.shutdown()


def test_ready_status_and_download_survive_restart(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first)
    first.create_session(request, workspace)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    archive_before = first.download_path(str(request.batch_id)).read_bytes()
    first.shutdown()
    assert workspace.path.exists()

    second = service(tmp_path)
    restored = second.get(str(request.batch_id))
    assert restored.phase is BatchExecutionPhase.READY
    assert second.download_path(str(request.batch_id)).read_bytes() == archive_before
    with ZipFile(second.download_path(str(request.batch_id))) as archive:
        assert archive.namelist() == ["0001-one.jpg", "0002-two.jpg"]
    second.shutdown()


def test_selective_recovery_survives_restart(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first)
    failed_input = request.items[0].input_path
    failed_input.write_bytes(b"corrupt image")
    first.create_session(request, workspace)
    partial = wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    assert partial.can_recover
    preserved = workspace.output_directory / "0002-two.jpg"
    before = preserved.read_bytes()
    first.shutdown()

    second = service(tmp_path)
    Image.new("RGB", (8, 8), "green").save(failed_input)
    assert second.recover(str(request.batch_id)).attempt == 2
    final = wait_for(second, str(request.batch_id), BatchExecutionPhase.READY)
    assert final.batch.completed_count == 2
    assert preserved.read_bytes() == before
    second.shutdown()


def test_committed_selective_recovery_state_is_restart_safe(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first)
    failed_input = request.items[0].input_path
    failed_input.write_bytes(b"corrupt image")
    first.create_session(request, workspace)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    Image.new("RGB", (8, 8), "green").save(failed_input)

    with patch.object(first._executor, "submit") as submit:
        queued = first.recover(str(request.batch_id))
    assert queued.attempt == 2
    assert queued.phase is BatchExecutionPhase.QUEUED
    submit.assert_called_once()
    first.shutdown()

    second = service(tmp_path)
    interrupted = second.get(str(request.batch_id))
    assert interrupted.phase is BatchExecutionPhase.ERROR
    assert interrupted.session_error.code == "batch_execution_interrupted"
    second.shutdown()


def test_packaging_failure_and_recovery_survive_restart(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first, ("one.png",))
    with patch.object(
        batches_module,
        "package_batch_outputs",
        side_effect=BatchProcessingError("private"),
    ):
        first.create_session(request, workspace)
        failed = wait_for(first, str(request.batch_id), BatchExecutionPhase.ERROR)
    assert failed.session_error.code == "batch_packaging_failed"
    output = workspace.output_directory / "0001-one.jpg"
    before = output.read_bytes()
    first.shutdown()

    second = service(tmp_path)
    with patch.object(
        batches_module,
        "batch_convert_images",
        side_effect=AssertionError("must not reconvert"),
    ):
        second.recover(str(request.batch_id))
        wait_for(second, str(request.batch_id), BatchExecutionPhase.READY)
    assert output.read_bytes() == before
    second.shutdown()


def test_interrupted_packaging_restores_packaging_only_recovery(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first, ("one.png",))
    first.create_session(request, workspace)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    first.shutdown()
    repository = BatchSessionRepository(tmp_path)
    persisted = repository.get(str(request.batch_id))
    assert persisted is not None
    repository.save(replace(persisted, phase="packaging", archive_available=False))
    workspace.archive_path.unlink()

    second = service(tmp_path)
    interrupted = second.get(str(request.batch_id))
    assert interrupted.phase is BatchExecutionPhase.ERROR
    assert interrupted.session_error.code == "batch_packaging_interrupted"
    with patch.object(
        batches_module,
        "batch_convert_images",
        side_effect=AssertionError("must not reconvert"),
    ):
        second.recover(str(request.batch_id))
        wait_for(second, str(request.batch_id), BatchExecutionPhase.READY)
    second.shutdown()


def test_corrupt_archive_restores_packaging_recoverable_error(tmp_path: Path) -> None:
    first = service(tmp_path)
    workspace, request = image_request(first, ("one.png",))
    first.create_session(request, workspace)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    first.shutdown()
    workspace.archive_path.write_bytes(b"not a zip")

    second = service(tmp_path)
    restored = second.get(str(request.batch_id))
    assert restored.phase is BatchExecutionPhase.ERROR
    assert restored.session_error.code == "batch_packaging_failed"
    assert restored.can_recover
    second.shutdown()


def test_interrupted_processing_restores_safe_error_and_full_retry(tmp_path: Path) -> None:
    seed = service(tmp_path)
    workspace, request = image_request(seed, ("one.png",))
    repository = BatchSessionRepository(tmp_path)
    repository.add(encode_record(
        request=request, batch=_initial_batch(request), result=None, attempt=1,
        phase="processing", cancellation_requested=False, session_error=None,
        archive_available=False, updated_at=10.0, workspace=workspace,
    ))
    seed.shutdown()

    restored = service(tmp_path)
    interrupted = restored.get(str(request.batch_id))
    assert interrupted.phase is BatchExecutionPhase.ERROR
    assert interrupted.session_error.code == "batch_execution_interrupted"
    assert interrupted.can_cancel is False and interrupted.can_recover is True
    assert restored.recover(str(request.batch_id)).attempt == 2
    wait_for(restored, str(request.batch_id), BatchExecutionPhase.READY)
    restored.shutdown()


def test_persisted_ttl_removes_metadata_and_files_after_restart(tmp_path: Path) -> None:
    now = [100.0]
    first = service(tmp_path, terminal_ttl_seconds=10, clock=lambda: now[0])
    workspace, request = image_request(first, ("one.png",))
    first.create_session(request, workspace)
    wait_for(first, str(request.batch_id), BatchExecutionPhase.READY)
    first.shutdown()
    now[0] = 111.0

    second = service(tmp_path, terminal_ttl_seconds=10, clock=lambda: now[0])
    assert BatchSessionRepository(tmp_path).get(str(request.batch_id)) is None
    assert not workspace.path.exists()
    second.shutdown()
