"""Deterministic durable batch workspace safety tests."""

from pathlib import Path

import pytest

from docuforge.api.batch_persistence import (
    BatchPersistenceError,
    BatchSessionWorkspace,
    prepare_durable_storage,
)
from docuforge.batch import BatchId


def test_durable_workspace_layout_and_restart_identity(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    workspace = BatchSessionWorkspace.durable_new(sessions_root)

    assert workspace.path == sessions_root / str(workspace.batch_id)
    assert workspace.inputs_directory == workspace.path / "inputs"
    assert workspace.output_directory == workspace.path / "outputs"
    assert workspace.archive_path == workspace.path / "result.zip"
    assert workspace.inputs_directory.is_dir()
    assert workspace.output_directory.is_dir()

    restored = BatchSessionWorkspace.durable_existing(
        sessions_root, workspace.batch_id
    )
    assert restored.path == workspace.path


def test_workspace_cleanup_removes_only_one_batch(tmp_path: Path) -> None:
    sessions_root, repository = prepare_durable_storage(tmp_path)
    first = BatchSessionWorkspace.durable_new(sessions_root)
    second = BatchSessionWorkspace.durable_new(sessions_root)

    first.cleanup()

    assert not first.path.exists()
    assert second.path.is_dir()
    assert repository.database_path.is_file()


def test_existing_workspace_rejects_missing_or_escaped_identity(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    with pytest.raises(BatchPersistenceError):
        BatchSessionWorkspace.durable_existing(sessions_root, BatchId.new())


def test_workspace_rejects_symlinked_session_directory(tmp_path: Path) -> None:
    sessions_root, _ = prepare_durable_storage(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    batch_id = BatchId.new()
    link = sessions_root / str(batch_id)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(BatchPersistenceError):
        BatchSessionWorkspace.durable_existing(sessions_root, batch_id)
