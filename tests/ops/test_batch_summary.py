import copy
import json
from pathlib import Path

import pytest

from docuforge.ops.batch_smoke import run_public
from docuforge.ops.batch_summary import render_summary, valid_report
from tests.ops.batch_support import (
    API,
    API_REVISION,
    FRONTEND,
    FRONTEND_REVISION,
    Server,
    public_arguments,
)


def environment():
    return {
        "DOCUFORGE_API_URL": API,
        "DOCUFORGE_FRONTEND_URL": FRONTEND,
        "DOCUFORGE_EXPECTED_API_REVISION": API_REVISION,
        "DOCUFORGE_EXPECTED_FRONTEND_REVISION": FRONTEND_REVISION,
        "DOCUFORGE_EXPECTED_VERSION": "0.1.0",
        "BATCH_OUTCOME": "success",
    }


@pytest.fixture
def report():
    return run_public(**public_arguments(), requester=Server())


def test_full_success_requires_four_lifecycles_and_cleanup(report, tmp_path):
    assert valid_report(report)
    (tmp_path / "batch-smoke.json").write_text(json.dumps(report))
    text = render_summary(environment(), directory=tmp_path)
    assert "Overall: PASS" in text and "confirmed cleanup: 4 / 4" in text


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("mode", "other"),
        ("identity", "FAIL"),
        ("passed", True),
        ("passed", 3),
        ("attempted", 3),
        ("checks", []),
        ("code", "secret"),
    ],
)
def test_malformed_top_level_evidence_cannot_pass(report, tmp_path, key, value):
    report[key] = value
    assert not valid_report(report)
    (tmp_path / "batch-smoke.json").write_text(json.dumps(report))
    assert "Overall: FAIL" in render_summary(environment(), directory=tmp_path)


@pytest.mark.parametrize(
    "key,value",
    [
        ("cleanup", "UNCONFIRMED"),
        ("cleanup", "NOT_NEEDED"),
        ("cleanup_code", "cleanup_failed"),
        ("ownership", "NONE"),
        ("stage", "download"),
        ("code", "output_invalid"),
        ("outcome", "SKIPPED"),
        ("name", "invented"),
        ("capability", "private-sentinel"),
    ],
)
def test_partial_rows_and_extra_private_fields_never_pass(report, tmp_path, key, value):
    report["checks"][0][key] = value
    assert not valid_report(report)
    (tmp_path / "batch-smoke.json").write_text(json.dumps(report))
    text = render_summary(environment(), directory=tmp_path)
    assert "Overall: FAIL" in text and "private-sentinel" not in text


@pytest.mark.parametrize(
    "key",
    [
        "BATCH_OUTCOME",
        "DOCUFORGE_API_URL",
        "DOCUFORGE_EXPECTED_API_REVISION",
        "DOCUFORGE_EXPECTED_VERSION",
    ],
)
def test_step_outcome_or_different_expected_deployment_prevents_pass(report, tmp_path, key):
    (tmp_path / "batch-smoke.json").write_text(json.dumps(report))
    env = environment()
    env[key] = "skipped" if key == "BATCH_OUTCOME" else "different"
    assert "Overall: FAIL" in render_summary(env, directory=tmp_path)


@pytest.mark.parametrize(
    "data",
    [None, "{}", "{invalid", '{"result":"PASS","result":"PASS"}', "x" * 32769],
    ids=["missing", "empty", "invalid", "duplicate", "oversize"],
)
def test_missing_or_invalid_reports_fail_closed(tmp_path, data):
    if data is not None:
        (tmp_path / "batch-smoke.json").write_text(data)
    text = render_summary(environment(), directory=tmp_path)
    assert "Overall: FAIL" in text and "evidence missing or invalid" in text


def test_four_check_names_or_success_step_alone_cannot_pass(report, tmp_path):
    fake = {"result": "PASS", "checks": [row["name"] for row in report["checks"]]}
    (tmp_path / "batch-smoke.json").write_text(json.dumps(fake))
    assert "Overall: FAIL" in render_summary(environment(), directory=tmp_path)
    local = copy.deepcopy(report)
    local.update(mode="lifecycle", identity="NOT_RUN")
    del local["deployment"]
    assert valid_report(local)
    (tmp_path / "batch-smoke.json").write_text(json.dumps(local))
    assert "Overall: FAIL" in render_summary(environment(), directory=tmp_path)


def test_manual_workflow_and_ci_keep_separate_evidence():
    workflow = Path(".github/workflows/production-batch-smoke.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert (
        "  push:" not in workflow
        and "  pull_request:" not in workflow
        and "schedule:" not in workflow
    )
    assert "contents: read" in workflow and "if: always()" in workflow
    assert "group: production-batch-smoke" in workflow and "cancel-in-progress: false" in workflow
    assert "timeout-minutes: 20" in workflow
    assert "--cleanup-seconds 60" in workflow and "--suite-seconds 600" in workflow
    assert "docuforge.ops.batch_smoke" in workflow and "docuforge.ops.batch_summary" in workflow
    assert "upload-artifact" not in workflow
    assert '--api-url "$DOCUFORGE_API_URL"' in workflow
    ci = Path(".github/workflows/ci.yml").read_text()
    for module in (
        "runtime_smoke",
        "office_ocr_integration",
        "batch_persistence_smoke",
        "batch_integration",
    ):
        assert f"docuforge.ops.{module}" in ci
    assert "Windows durable storage ownership" in ci and "Full-stack E2E (Chromium)" in ci
