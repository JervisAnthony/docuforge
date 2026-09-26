"""Fresh-process checks for the API factory and deployed ASGI lifecycle."""

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

import pytest

from docuforge.api import run


def run_child(script: str) -> None:
    environment = {
        name: value for name, value in os.environ.items() if not name.startswith("DOCUFORGE_")
    }
    result = subprocess.run(
        [sys.executable, "-c", dedent(script)],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert result.stderr == ""


@pytest.mark.parametrize("module", ["docuforge.api", "docuforge.api.app"])
def test_public_and_factory_imports_do_not_start_cleanup(module: str) -> None:
    run_child(f"""
        import importlib
        import threading

        imported = importlib.import_module({module!r})
        assert callable(imported.create_app)
        assert not hasattr(imported, 'app') or {module!r} == 'docuforge.api'
        assert not any(
            thread.name == 'docuforge-batch-cleanup'
            for thread in threading.enumerate()
        )
    """)


def test_asgi_import_owns_exactly_one_cleanup_thread_and_shutdown_stops_it() -> None:
    run_child("""
        import threading
        import docuforge.api.asgi as asgi

        service = asgi.app.state.batch_service
        cleanup = service._cleanup_thread
        try:
            assert cleanup.is_alive()
            assert [
                thread for thread in threading.enumerate()
                if thread.name == 'docuforge-batch-cleanup'
            ] == [cleanup]
        finally:
            service.shutdown()
        assert not cleanup.is_alive()
        assert not any(
            thread.name == 'docuforge-batch-cleanup'
            for thread in threading.enumerate()
        )
    """)


def test_production_runner_uses_asgi_entry_with_hardened_options(monkeypatch) -> None:
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8123")
    with (
        patch.object(run.uvicorn, "run") as start,
        patch.object(run, "configure_request_logging") as configure_logging,
    ):
        run.main()
    configure_logging.assert_called_once_with()
    start.assert_called_once_with(
        "docuforge.api.asgi:app",
        host="127.0.0.1",
        port=8123,
        access_log=False,
        server_header=False,
    )
