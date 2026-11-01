import pytest

from docuforge.ops import batch_persistence_smoke
from docuforge.ops.batch_persistence_smoke import BatchPersistenceSmokeError


def test_batch_persistence_smoke_runs_real_restart_cycle() -> None:
    assert batch_persistence_smoke.run_batch_persistence_smoke() == (
        "batch-storage-owner-lock",
        "batch-admission-control",
        "batch-session-restart",
        "batch-session-delete",
        "batch-ttl-sweeper",
        "batch-storage-pressure",
        "batch-output-budget",
        "batch-download-lifecycle",
        "batch-archive-integrity",
        "batch-output-integrity",
        "batch-worker-publication",
        "batch-input-integrity",
        "batch-archive-source-pinning",
        "batch-download-descriptor-pinning",
        "batch-download-admission",
        "batch-download-validation-concurrency",
    )


def test_batch_persistence_smoke_cli_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        batch_persistence_smoke,
        "run_batch_persistence_smoke",
        lambda: (
            "batch-storage-owner-lock",
            "batch-admission-control",
            "batch-session-restart",
            "batch-session-delete",
            "batch-ttl-sweeper",
            "batch-storage-pressure",
            "batch-output-budget",
            "batch-download-lifecycle",
            "batch-archive-integrity",
            "batch-output-integrity",
            "batch-worker-publication",
            "batch-input-integrity",
            "batch-archive-source-pinning",
            "batch-download-descriptor-pinning",
            "batch-download-admission",
            "batch-download-validation-concurrency",
        ),
    )
    assert batch_persistence_smoke.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS batch-storage-owner-lock",
        "PASS batch-admission-control",
        "PASS batch-session-restart",
        "PASS batch-session-delete",
        "PASS batch-ttl-sweeper",
        "PASS batch-storage-pressure",
        "PASS batch-output-budget",
        "PASS batch-download-lifecycle",
        "PASS batch-archive-integrity",
        "PASS batch-output-integrity",
        "PASS batch-worker-publication",
        "PASS batch-input-integrity",
        "PASS batch-archive-source-pinning",
        "PASS batch-download-descriptor-pinning",
        "PASS batch-download-admission",
        "PASS batch-download-validation-concurrency",
        "Durable batch persistence smoke passed: 16 checks",
    ]


def test_batch_persistence_smoke_cli_failure_is_safe(monkeypatch, capsys) -> None:
    def fail():
        raise BatchPersistenceSmokeError("private database path")

    monkeypatch.setattr(batch_persistence_smoke, "run_batch_persistence_smoke", fail)
    assert batch_persistence_smoke.main() == 1
    assert capsys.readouterr().err == "FAIL durable batch persistence check failed\n"


def test_concurrency_marker_requires_its_independent_check(monkeypatch):
    def fail(storage):
        raise BatchPersistenceSmokeError("concurrency check failed")

    monkeypatch.setattr(batch_persistence_smoke, "_verify_download_validation_concurrency", fail)
    with pytest.raises(BatchPersistenceSmokeError, match="concurrency check failed"):
        batch_persistence_smoke.run_batch_persistence_smoke()
