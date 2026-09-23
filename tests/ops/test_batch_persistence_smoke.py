from docuforge.ops import batch_persistence_smoke
from docuforge.ops.batch_persistence_smoke import BatchPersistenceSmokeError


def test_batch_persistence_smoke_runs_real_restart_cycle() -> None:
    assert batch_persistence_smoke.run_batch_persistence_smoke() == (
        "batch-session-restart",
        "batch-session-delete",
    )


def test_batch_persistence_smoke_cli_success(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        batch_persistence_smoke,
        "run_batch_persistence_smoke",
        lambda: ("batch-session-restart", "batch-session-delete"),
    )
    assert batch_persistence_smoke.main() == 0
    assert capsys.readouterr().out.splitlines() == [
        "PASS batch-session-restart",
        "PASS batch-session-delete",
        "Durable batch persistence smoke passed: 2 checks",
    ]


def test_batch_persistence_smoke_cli_failure_is_safe(monkeypatch, capsys) -> None:
    def fail():
        raise BatchPersistenceSmokeError("private database path")

    monkeypatch.setattr(batch_persistence_smoke, "run_batch_persistence_smoke", fail)
    assert batch_persistence_smoke.main() == 1
    assert capsys.readouterr().err == "FAIL durable batch persistence check failed\n"
