import asyncio

import pytest

from docuforge.api.workspace import RequestWorkspace


def test_workspaces_are_unique_and_isolated() -> None:
    first = RequestWorkspace()
    second = RequestWorkspace()

    try:
        assert first.path != second.path
        assert first.path.is_dir()
        assert second.path.is_dir()
        (first.path / "only-first.txt").write_text("first", encoding="utf-8")
        assert not (second.path / "only-first.txt").exists()
    finally:
        first.cleanup()
        second.cleanup()


def test_context_manager_cleans_workspace_normally() -> None:
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        (workspace_path / "nested").mkdir()
        (workspace_path / "nested" / "file.txt").write_text("data", encoding="utf-8")
        assert workspace_path.exists()

    assert not workspace_path.exists()


def test_context_manager_cleans_workspace_after_exception() -> None:
    with (
        pytest.raises(RuntimeError, match="processing failed"),
        RequestWorkspace() as workspace,
    ):
        workspace_path = workspace.path
        raise RuntimeError("processing failed")

    assert not workspace_path.exists()


def test_cleanup_is_idempotent() -> None:
    workspace = RequestWorkspace()
    workspace_path = workspace.path

    workspace.cleanup()
    workspace.cleanup()

    assert not workspace_path.exists()


def test_transferred_cleanup_is_deferred_until_background_task_runs() -> None:
    with RequestWorkspace() as workspace:
        workspace_path = workspace.path
        background_task = workspace.transfer_cleanup()

    assert workspace.cleanup_transferred is True
    assert workspace_path.exists()

    asyncio.run(background_task())

    assert not workspace_path.exists()
