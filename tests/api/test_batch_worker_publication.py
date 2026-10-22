"""SQLite saves are the publication boundary for worker-owned checkpoints."""

import json
from dataclasses import replace
from threading import Event
from unittest.mock import patch

import pytest

import docuforge.api.batches as module
import docuforge.batch.image as image_module
from docuforge.api.batch_persistence import BatchPersistenceError
from docuforge.api.batches import BatchExecutionPhase as Phase
from docuforge.api.errors import ApiError
from docuforge.batch import BatchCancellationToken, BatchStatus
from tests.api.test_batch_deletion import _ready
from tests.api.test_batch_service import create_request, service, wait_for
from tests.batch.test_image_processing import write_image


def queued(storage=None):
    runner = service(**({"storage_directory": storage} if storage else {}))
    workspace, request = create_request(runner)
    with patch.object(runner._executor, "submit"):
        grant = runner.create_session(request, workspace)
    return runner, workspace, str(request.batch_id), grant.access_token


def execute(runner, batch_id, *, selective=False, packaging_only=False):
    session = runner._sessions[batch_id]
    runner._execute(batch_id, selective, packaging_only, session.attempt, session.cancellation)


@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("fail", [False, True])
def test_helper_saves_before_applying_only_worker_fields(tmp_path, durable, fail):
    runner, _workspace, batch_id, token = queued(tmp_path if durable else None)
    try:
        session = runner._sessions[batch_id]
        before = replace(session)
        candidate = replace(
            session,
            phase=Phase.PROCESSING,
            updated_at=123.0,
            batch=session.batch.start_item(session.batch.items[0].id),
        )

        def persist(value):
            assert value is candidate
            assert session == before
            assert runner.get(batch_id, token).phase is Phase.QUEUED
            if fail:
                raise BatchPersistenceError("private database diagnostic")

        with runner._lock, patch.object(runner, "_persist_locked", side_effect=persist):
            if fail:
                with pytest.raises(BatchPersistenceError):
                    runner._publish_worker_state_locked(session, candidate=candidate)
                assert session == before
            else:
                runner._publish_worker_state_locked(session, candidate=candidate)
                assert session == candidate
        assert runner._sessions[batch_id] is session
        assert session.cancellation is before.cancellation
        assert session.request is before.request and session.workspace is before.workspace
        assert (
            session.attempt == before.attempt
            and session.access_token_hash == before.access_token_hash
        )
    finally:
        runner.shutdown()


def test_every_successful_checkpoint_saves_while_live_still_matches_previous_row(tmp_path):
    runner, _workspace, batch_id, token = queued(tmp_path)
    try:
        session = runner._sessions[batch_id]
        identity = session
        save = runner._repository.save
        phases = []

        def persist(row):
            # Reentrant API observation during save still sees the preceding commit.
            before = runner._repository.get(batch_id)
            live = runner.get(batch_id, token)
            assert live.phase.value == before.phase
            assert session.updated_at == before.updated_at
            assert session.attempt == before.attempt
            assert [i.status.value for i in live.batch.items] == [
                i["status"] for i in json.loads(before.batch_json)["items"]
            ]
            phases.append(row.phase)
            save(row)

        with patch.object(runner._repository, "save", side_effect=persist):
            execute(runner, batch_id)
        assert phases[0] == "processing" and phases[-2:] == ["packaging", "ready"]
        assert runner._sessions[batch_id] is identity
        assert runner.get(batch_id, token).phase is Phase.READY
        assert runner._repository.get(batch_id).phase == "ready"
        assert not runner._admitted_batch_ids
    finally:
        runner.shutdown()


@pytest.mark.parametrize("checkpoint", ["processing", "progress", "packaging", "ready"])
@pytest.mark.parametrize("fail_error_too", [False, True])
def test_checkpoint_failure_stops_publication_and_restores_last_commit(
    tmp_path, checkpoint, fail_error_too
):
    runner, workspace, batch_id, token = queued(tmp_path)
    session = runner._sessions[batch_id]
    save = runner._repository.save
    failed = []
    committed = [runner._repository.get(batch_id)]
    converter = image_module.convert_image_path
    package = module.package_batch_outputs

    def persist(row):
        completed = sum(i["status"] == "completed" for i in json.loads(row.batch_json)["items"])
        target = (
            row.phase == checkpoint
            if checkpoint != "progress"
            else row.phase == "processing" and completed == 1
        )
        if not failed and target:
            before = replace(session)
            assert session.phase.value != checkpoint or checkpoint == "processing"
            if checkpoint == "progress":
                assert session.batch.completed_count == 0
            if checkpoint == "ready":
                assert not runner.get(batch_id, token).can_download
                with pytest.raises(ApiError):
                    runner.acquire_download(batch_id, token)
            failed.append(before)
            raise BatchPersistenceError("private SQLite failure")
        if failed and fail_error_too:
            assert session == failed[0]
            raise BatchPersistenceError("private SQLite failure")
        if row.phase == "error":
            assert session == failed[0]
        save(row)
        committed[0] = row

    try:
        with (
            patch.object(runner._repository, "save", side_effect=persist),
            patch.object(image_module, "convert_image_path", wraps=converter) as convert,
            patch.object(module, "package_batch_outputs", wraps=package) as packaging,
        ):
            execute(runner, batch_id)
        assert failed
        assert session.phase is Phase.ERROR and session.archive_path is None
        assert not runner.get(batch_id, token).can_download
        assert not runner._admitted_batch_ids and session.attempt == 1
        assert runner._repository.get(batch_id) == committed[0]
        if fail_error_too:
            assert session.session_error.code == "batch_persistence_failed"
            assert committed[0].phase != "error"
        else:
            assert committed[0].phase == "error"
            assert json.loads(committed[0].session_error_json)["code"] == session.session_error.code
        assert (
            convert.call_count
            == {"processing": 0, "progress": 1, "packaging": 2, "ready": 2}[checkpoint]
        )
        assert packaging.call_count == (1 if checkpoint == "ready" else 0)
        # Uncommitted generated files must be removed by the later full retry.
        (workspace.output_directory / "uncommitted-stray").write_bytes(b"stale")
    finally:
        runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        snapshot = restored.get(batch_id, token)
        assert snapshot.phase is Phase.ERROR and snapshot.can_recover
        if committed[0].phase in {"queued", "processing"}:
            assert snapshot.session_error.code == "batch_execution_interrupted"
        elif committed[0].phase == "packaging":
            assert snapshot.session_error.code == "batch_packaging_interrupted"
        retained = restored._sessions[batch_id].result
        with patch.object(image_module, "convert_image_path", wraps=converter) as convert:
            restored.recover(batch_id, token)
            wait_for(restored, batch_id, token, Phase.READY)
        assert convert.call_count == (0 if retained is not None else 2)
        if retained is None:
            assert not (workspace.output_directory / "uncommitted-stray").exists()
        assert restored._repository.get(batch_id).phase == "ready"
        assert restored._sessions[batch_id].attempt == 2
    finally:
        restored.shutdown()


@pytest.mark.parametrize("fail_error_too", [False, True])
def test_packaging_only_checkpoint_is_saved_before_zip_and_retains_result(tmp_path, fail_error_too):
    runner, workspace, batch_id, token = _ready(tmp_path)
    try:
        session = runner._sessions[batch_id]
        workspace.archive_path.unlink()
        with pytest.raises(ApiError):
            runner.acquire_download(batch_id, token)
        retained = session.result
        with patch.object(runner._executor, "submit"):
            runner.recover(batch_id, token)
        before = replace(session)
        save = runner._repository.save

        def persist(row):
            assert session == before
            if row.phase == "packaging" or fail_error_too:
                raise BatchPersistenceError("private")
            save(row)

        with (
            patch.object(runner._repository, "save", side_effect=persist),
            patch.object(module, "package_batch_outputs") as package,
            patch.object(image_module, "convert_image_path") as convert,
        ):
            execute(runner, batch_id, packaging_only=True)
        package.assert_not_called()
        convert.assert_not_called()
        assert session.phase is Phase.ERROR and session.result is retained
        assert not runner._admitted_batch_ids
        # When error persistence is unavailable, restart remains authoritative.
        if not fail_error_too:
            runner.recover(batch_id, token)
            wait_for(runner, batch_id, token, Phase.READY)
            assert session.result is retained
    finally:
        runner.shutdown()


def test_selective_progress_failure_preserves_previous_coherent_result(tmp_path):
    runner = service(storage_directory=tmp_path)
    try:
        workspace, request = create_request(runner)
        request.items[1].input_path.write_bytes(b"bad")
        grant = runner.create_session(request, workspace)
        batch_id, token = str(request.batch_id), grant.access_token
        wait_for(runner, batch_id, token, Phase.READY)
        session = runner._sessions[batch_id]
        previous = session.result
        preserved = previous.outputs[0].output_path.read_bytes()
        write_image(request.items[1].input_path)
        with patch.object(runner._executor, "submit"):
            runner.recover(batch_id, token)
        save = runner._repository.save

        def persist(row):
            items = json.loads(row.batch_json)["items"]
            if row.phase == "processing" and items[1]["status"] == "running":
                raise BatchPersistenceError("private")
            save(row)

        with patch.object(runner._repository, "save", side_effect=persist):
            execute(runner, batch_id, selective=True)
        assert session.result is previous and session.batch is previous.batch
        assert session.phase is Phase.ERROR
        assert previous.outputs[0].output_path.read_bytes() == preserved
        with patch.object(
            image_module, "convert_image_path", wraps=image_module.convert_image_path
        ) as convert:
            runner.recover(batch_id, token)
            wait_for(runner, batch_id, token, Phase.READY)
        assert convert.call_count == 1
    finally:
        runner.shutdown()


@pytest.mark.parametrize("durable", [False, True])
def test_cancel_between_progress_checkpoints_cannot_be_overwritten(tmp_path, durable):
    runner = service(**({"storage_directory": tmp_path} if durable else {}))
    entered, release = Event(), Event()
    converter = image_module.convert_image_path

    def convert(request):
        entered.set()
        assert release.wait(10)
        return converter(request)

    try:
        workspace, request = create_request(runner)
        with patch.object(image_module, "convert_image_path", side_effect=convert):
            grant = runner.create_session(request, workspace)
            batch_id, token = str(request.batch_id), grant.access_token
            assert entered.wait(10)
            session = runner._sessions[batch_id]
            cancellation = session.cancellation
            runner.cancel(batch_id, token)
            publish = runner._publish_worker_state_locked
            progress_seen = []

            def observe(session, *, candidate):
                if candidate.phase in {Phase.PROCESSING, Phase.CANCELLING}:
                    assert candidate.phase is Phase.CANCELLING
                    assert candidate.cancellation is cancellation
                    progress_seen.append(candidate.batch)
                publish(session, candidate=candidate)

            with patch.object(runner, "_publish_worker_state_locked", side_effect=observe):
                release.set()
                snapshot = wait_for(runner, batch_id, token, Phase.READY)
            assert progress_seen
            assert snapshot.cancellation_requested
            assert snapshot.batch.status is BatchStatus.PARTIAL
            assert snapshot.batch.completed_count == 1 and snapshot.batch.cancelled_count == 1
            assert session.cancellation is cancellation
    finally:
        release.set()
        runner.shutdown()


@pytest.mark.parametrize("stale", ["attempt", "token"])
def test_stale_worker_and_progress_cannot_publish(tmp_path, stale):
    runner, _workspace, batch_id, _token = queued(tmp_path)
    try:
        session = runner._sessions[batch_id]
        old_attempt, old_token = session.attempt, session.cancellation
        callbacks = []

        def capture(request, **controls):
            callbacks.append(controls["on_progress"])

        with patch.object(module, "batch_convert_images", side_effect=capture):
            runner._run_request(session, None, old_attempt)
        if stale == "attempt":
            session.attempt += 1
        else:
            session.cancellation = BatchCancellationToken()
        before = replace(session)
        with (
            patch.object(runner._repository, "save") as save,
            patch.object(runner, "_run_request") as convert,
        ):
            callbacks[0](session.batch.start_item(session.batch.items[0].id))
            runner._execute(batch_id, False, False, old_attempt, old_token)
        save.assert_not_called()
        convert.assert_not_called()
        assert session == before
    finally:
        runner.shutdown()


@pytest.mark.parametrize("checkpoint", ["queued", "processing", "packaging", "ready", "error"])
def test_real_restart_uses_last_successful_checkpoint(tmp_path, checkpoint):
    runner, _workspace, batch_id, token = queued(tmp_path)
    rows = [runner._repository.get(batch_id)]
    save = runner._repository.save

    def persist(row):
        save(row)
        rows.append(row)

    with patch.object(runner._repository, "save", side_effect=persist):
        execute(runner, batch_id)
    if checkpoint == "error":
        with runner._lock:
            session = runner._sessions[batch_id]
            candidate = replace(
                session,
                phase=Phase.ERROR,
                archive_path=None,
                session_error=module.BatchSessionError("batch_packaging_failed", "Safe error."),
            )
            runner._publish_worker_state_locked(session, candidate=candidate)
            rows.append(runner._repository.get(batch_id))
    row = next(row for row in rows if row.phase == checkpoint)
    runner._repository.save(row)
    runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        snapshot = restored.get(batch_id, token)
        assert str(snapshot.batch.id) == batch_id and snapshot.attempt == row.attempt
        assert restored._sessions[batch_id].access_token_hash == row.access_token_hash
        if checkpoint == "ready":
            assert snapshot.phase is Phase.READY and snapshot.can_download
        else:
            assert snapshot.phase is Phase.ERROR and snapshot.can_recover
            if checkpoint in {"queued", "processing"}:
                assert snapshot.session_error.code == "batch_execution_interrupted"
            if checkpoint == "packaging":
                assert snapshot.session_error.code == "batch_packaging_interrupted"
            restored.recover(batch_id, token)
            wait_for(restored, batch_id, token, Phase.READY)
    finally:
        restored.shutdown()


def test_ephemeral_error_and_retry_need_no_repository():
    runner, _workspace, batch_id, token = queued()
    try:
        assert runner._repository is None
        with patch.object(module, "batch_convert_images", side_effect=RuntimeError("private")):
            execute(runner, batch_id)
        assert runner.get(batch_id, token).session_error.code == "batch_execution_failed"
        assert not runner._admitted_batch_ids
        runner.recover(batch_id, token)
        assert wait_for(runner, batch_id, token, Phase.READY).can_download
    finally:
        runner.shutdown()


@pytest.mark.parametrize("fail_error_save", [False, True])
def test_converter_error_is_saved_before_publication_or_falls_back(tmp_path, fail_error_save):
    runner, _workspace, batch_id, token = queued(tmp_path)
    session = runner._sessions[batch_id]
    committed = [runner._repository.get(batch_id)]
    save = runner._repository.save

    def persist(row):
        if row.phase == "error":
            assert session.phase is Phase.PROCESSING
            assert session.session_error is None
            assert runner._repository.get(batch_id) == committed[0]
            if fail_error_save:
                raise BatchPersistenceError("private database detail")
        save(row)
        committed[0] = row

    try:
        with (
            patch.object(
                module, "batch_convert_images", side_effect=RuntimeError("private source")
            ),
            patch.object(runner._repository, "save", side_effect=persist),
        ):
            execute(runner, batch_id)
        assert session.phase is Phase.ERROR and session.batch.is_terminal
        assert session.session_error.code == (
            "batch_persistence_failed" if fail_error_save else "batch_execution_failed"
        )
        assert "private" not in session.session_error.message
        assert not runner._admitted_batch_ids
        assert runner._repository.get(batch_id) == committed[0]
        assert committed[0].phase == ("processing" if fail_error_save else "error")
    finally:
        runner.shutdown()
    restored = service(storage_directory=tmp_path)
    try:
        snapshot = restored.get(batch_id, token)
        assert snapshot.session_error.code == (
            "batch_execution_interrupted" if fail_error_save else "batch_execution_failed"
        )
        restored.recover(batch_id, token)
        wait_for(restored, batch_id, token, Phase.READY)
    finally:
        restored.shutdown()


@pytest.mark.parametrize("durable", [False, True])
def test_cancellation_before_worker_start_never_publishes_processing(tmp_path, durable):
    runner, _workspace, batch_id, token = queued(tmp_path if durable else None)
    try:
        runner.cancel(batch_id, token)
        publish = runner._publish_worker_state_locked
        phases = []

        def observe(session, *, candidate):
            phases.append(candidate.phase)
            publish(session, candidate=candidate)

        with (
            patch.object(runner, "_publish_worker_state_locked", side_effect=observe),
            patch.object(image_module, "convert_image_path") as convert,
        ):
            execute(runner, batch_id)
        convert.assert_not_called()
        assert phases[0] is Phase.CANCELLING and Phase.PROCESSING not in phases
        snapshot = runner.get(batch_id, token)
        assert snapshot.phase is Phase.READY and not snapshot.can_download
        assert snapshot.batch.cancelled_count == 2 and snapshot.cancellation_requested
    finally:
        runner.shutdown()
