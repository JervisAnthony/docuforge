import json

import pytest

from docuforge.ops.deployment_smoke import SMOKE_CHECKS
from docuforge.ops.production_summary import render_summary


@pytest.mark.parametrize(
    "scenario",
    [
        "pass",
        "identity-failed",
        "identity-skipped",
        "smoke-skipped",
        "missing",
        "malformed",
        "wrong-schema",
        "semantic-only",
        "unknown",
        "wrong-observed",
        "missing-component",
        "malformed-component",
        "invalid-expected",
        "untrusted-observed",
        "wrong-origin",
        "malformed-smoke",
        "malformed-count",
        "untrusted-check",
        "short-count",
        "duplicate-report-fields",
    ],
)
def test_summary_requires_complete_valid_identity_and_smoke(tmp_path, scenario):
    env = {
        "DOCUFORGE_API_URL": "https://api.example.com",
        "DOCUFORGE_FRONTEND_URL": "https://app.example.com",
        "DOCUFORGE_EXPECTED_API_REVISION": "a" * 40,
        "DOCUFORGE_EXPECTED_FRONTEND_REVISION": "b" * 40,
        "IDENTITY_OUTCOME": "success",
        "SMOKE_OUTCOME": "success",
    }
    evidence = {
        "schema_version": 1,
        "mode": "strict",
        "result": "PASS",
        "expected_version": "0.1.0",
        "components": {},
    }
    for name, sha in (("api", "a" * 40), ("frontend", "b" * 40)):
        evidence["components"][name] = {
            "origin": env[f"DOCUFORGE_{name.upper()}_URL"],
            "expected_revision": sha,
            "observed_revision": sha,
            "observed_version": "0.1.0",
            "outcome": "PASS",
        }
    if scenario in {"identity-failed", "identity-skipped"}:
        env["IDENTITY_OUTCOME"] = "skipped" if scenario.endswith("skipped") else "failure"
    if scenario == "smoke-skipped":
        env["SMOKE_OUTCOME"] = "skipped"
    if scenario == "wrong-schema":
        evidence["schema_version"] = True
    if scenario == "semantic-only":
        evidence["mode"] = "semantic-only"
    if scenario == "unknown":
        evidence["components"]["api"]["observed_revision"] = None
    if scenario == "wrong-observed":
        evidence["components"]["frontend"]["observed_revision"] = "c" * 40
    if scenario == "missing-component":
        evidence["components"].pop("frontend")
    if scenario == "malformed-component":
        evidence["components"] = []
    if scenario == "invalid-expected":
        env["DOCUFORGE_EXPECTED_API_REVISION"] = "private input"
    if scenario == "untrusted-observed":
        evidence["components"]["frontend"]["observed_revision"] = "private metadata"
    if scenario == "wrong-origin":
        evidence["components"]["api"]["origin"] = "https://other.example.com"
    if scenario == "duplicate-report-fields":
        text = json.dumps(evidence).replace(
            '"result": "PASS"', '"result": "FAIL", "result": "PASS"'
        )
        (tmp_path / "release-identity.json").write_text(text)
    elif scenario != "missing":
        (tmp_path / "release-identity.json").write_text(
            "{bad" if scenario == "malformed" else json.dumps(evidence)
        )
    smoke = {"result": "PASS", "passed_checks": list(SMOKE_CHECKS), "checks_executed": 17}
    if scenario == "malformed-count":
        smoke["checks_executed"] = True
    if scenario == "short-count":
        smoke["checks_executed"] = 16
    if scenario == "untrusted-check":
        smoke["passed_checks"] = ["private response"]
    (tmp_path / "production-smoke.json").write_text(
        "[]" if scenario == "malformed-smoke" else json.dumps(smoke)
    )
    summary = render_summary(env, directory=tmp_path)
    assert f"Overall: {'PASS' if scenario == 'pass' else 'FAIL'}" in summary
    assert "private" not in summary
    assert "/ 17" in summary
