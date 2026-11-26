import json
import logging
import zipfile
from dataclasses import replace
from io import BytesIO

import pytest

from docuforge.ops import batch_smoke as smoke
from docuforge.ops.batch_summary import valid_report
from docuforge.ops.deployment_smoke import HttpResponse
from tests.ops.batch_support import (
    API,
    IDENTITY,
    TOKEN,
    Clock,
    Server,
    public_arguments,
    response,
    state,
)


def run(server, *, timing=smoke.DEFAULT_TIMING):
    clock = Clock()
    report = smoke.Lifecycle(
        API, requester=server, clock=clock, sleeper=clock.sleep, timing=timing
    ).run()
    assert valid_report(report)
    serialized = json.dumps(report)
    assert TOKEN not in serialized and IDENTITY not in serialized and "/batches/" not in serialized
    return report


def test_complete_four_case_contract_exact_multipart_and_sequential_cleanup():
    server = Server()
    report = run(server)
    assert report["result"] == "PASS" and report["attempted"] == report["passed"] == 4
    assert report["identity"] == "NOT_RUN"
    assert len(server.deleted) == 4 and not server.sessions
    creations = [
        index
        for index, call in enumerate(server.calls)
        if call[0] == "POST" and call[1] in smoke.CREATION_PATHS
    ]
    deletes = [index for index, call in enumerate(server.calls) if call[0] == "DELETE"]
    assert all(deletes[index] < creations[index + 1] for index in range(3))
    for case in report["checks"]:
        assert case["cleanup"] == "CONFIRMED"
    denials = [
        call
        for call in server.calls
        if call[0] == "GET" and call[2].get(smoke.TOKEN_HEADER) != TOKEN
    ]
    assert len(denials) == 16
    assert all(call[3] is None for call in server.calls if call[2].get(smoke.TOKEN_HEADER))


def test_public_identity_is_required_inside_command_before_first_creation():
    server = Server()
    report = smoke.run_public(**public_arguments(), requester=server)
    assert valid_report(report) and report["result"] == "PASS" and report["identity"] == "PASS"
    assert [call[1] for call in server.calls[:4]] == [
        "/api/v1/ready",
        "/api/v1/build",
        "/build-info.json",
        "/",
    ]


@pytest.mark.parametrize("path", ["/api/v1/ready", "/api/v1/build", "/build-info.json", "/"])
def test_identity_failure_never_creates(path):
    def hook(server, method, actual, headers, result):
        return HttpResponse(302, {"location": API}, b"") if actual == path else result

    server = Server(hook)
    report = smoke.run_public(**public_arguments(), requester=server)
    assert valid_report(report) and report["identity"] == "FAIL" and report["attempted"] == 0
    assert server.created == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_url", "http://localhost:8000"),
        ("api_url", API + "/api"),
        ("frontend_url", "https://user:password@example.com"),
        ("expected_api_revision", None),
        ("expected_frontend_revision", "guess"),
        ("expected_version", "private\ntext"),
    ],
)
def test_invalid_configuration_has_zero_network(field, value):
    arguments = public_arguments()
    arguments[field] = value
    server = Server()
    report = smoke.run_public(**arguments, requester=server)
    assert report["code"] == "configuration_invalid" and not server.calls
    assert valid_report(report)


@pytest.mark.parametrize(
    "field",
    ["timeout", "case_seconds", "suite_seconds", "cleanup_seconds", "poll_interval", "max_polls"],
)
@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "1", None])
def test_timing_rejects_nonfinite_and_untyped_before_network(field, value):
    server = Server()
    report = smoke.run_public(
        **public_arguments(),
        requester=server,
        timing=replace(smoke.DEFAULT_TIMING, **{field: value}),
    )
    assert report["code"] == "configuration_invalid" and not server.calls


@pytest.mark.parametrize(
    "field,value",
    [
        ("timeout", 61),
        ("case_seconds", 301),
        ("suite_seconds", 1201),
        ("cleanup_seconds", 121),
        ("poll_interval", 0.001),
        ("poll_interval", 6),
        ("max_polls", 1001),
        ("max_polls", 1.5),
    ],
)
def test_timing_has_upper_bounds(field, value):
    with pytest.raises(smoke.Failure, match="configuration_invalid"):
        replace(smoke.DEFAULT_TIMING, **{field: value}).validate()


SNAPSHOT_MUTATIONS = [
    ("id", "invalid"),
    ("operation", "image.other"),
    ("attempt", 2),
    ("attempt", True),
    ("phase", "unknown"),
    ("phase", []),
    ("status", "partial"),
    ("progress_percent", 99),
    ("progress_percent", True),
    ("can_download", False),
    ("can_cancel", True),
    ("can_recover", "no"),
    ("cancellation_requested", None),
    ("summary", {}),
    ("items", []),
    ("session_error", {}),
]


@pytest.mark.parametrize("field,value", SNAPSHOT_MUTATIONS)
def test_acceptance_snapshot_failure_still_cleans_up(field, value):
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            payload = json.loads(result.body)
            payload[field] = value
            return response(payload, 202, dict(result.headers))
        return result

    server = Server(hook)
    report = run(server)
    assert report["result"] == "FAIL" and report["attempted"] == 1
    assert report["checks"][0]["cleanup"] == "CONFIRMED" and len(server.deleted) == 1


@pytest.mark.parametrize(
    "field",
    [
        "attempt",
        "phase",
        "items",
        "summary",
        "session_error",
        "can_cancel",
        "can_recover",
        "can_download",
        "progress_percent",
    ],
)
def test_missing_required_snapshot_fields_fail_and_cleanup(field):
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            payload = json.loads(result.body)
            del payload[field]
            return response(payload, 202, dict(result.headers))
        return result

    server = Server(hook)
    assert run(server)["checks"][0]["cleanup"] == "CONFIRMED"
    assert len(server.deleted) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("position", True),
        ("position", 1),
        ("descriptor", "unknown.png"),
        ("result_descriptor", "server-chosen.jpg"),
        ("id", "bad"),
        ("status", "failed"),
        ("failure", {"code": "x", "message": TOKEN}),
    ],
)
def test_item_validation(field, value):
    case = smoke.cases()[0]
    payload = state(case)
    payload["items"][0][field] = value
    with pytest.raises(smoke.Failure):
        smoke.snapshot(payload, smoke.Owned(IDENTITY, TOKEN), case)


def test_counts_item_uniqueness_and_stable_ids_are_checked():
    case = smoke.cases()[0]
    for mutate in (
        lambda s: s["summary"].update(processed=3),
        lambda s: s["summary"].update(completed=True),
        lambda s: s["items"][1].update(id=s["items"][0]["id"]),
        lambda s: s["items"].reverse(),
    ):
        payload = state(case)
        mutate(payload)
        with pytest.raises(smoke.Failure, match="snapshot_invalid"):
            smoke.snapshot(payload, smoke.Owned(IDENTITY, TOKEN), case)
    owned = smoke.Owned(IDENTITY, TOKEN)
    smoke.snapshot(state(case), owned, case)
    payload = state(case)
    payload["items"][0]["id"] = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(smoke.Failure, match="snapshot_invalid"):
        smoke.snapshot(payload, owned, case)


@pytest.mark.parametrize(
    "location",
    [
        None,
        "https://evil.invalid/session",
        API + smoke.PREFIX + IDENTITY,
        "//evil.invalid/" + IDENTITY,
        smoke.PREFIX + IDENTITY + "?x=1",
        smoke.PREFIX + IDENTITY + "#x",
        smoke.PREFIX + "../" + IDENTITY,
        smoke.PREFIX + IDENTITY + "/../other",
        smoke.PREFIX + "%2e%2e",
        smoke.PREFIX + IDENTITY.upper(),
        smoke.PREFIX + "{" + IDENTITY + "}",
    ],
)
def test_untrusted_location_never_controls_protected_path_and_json_fallback_cleans(location):
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            changed = dict(result.headers)
            changed.pop("location")
            if location is not None:
                changed["location"] = location
            return HttpResponse(202, changed, result.body)
        return result

    server = Server(hook)
    report = run(server)
    assert report["checks"][0]["code"] == "acceptance_invalid"
    assert report["checks"][0]["cleanup"] == "CONFIRMED"
    assert server.deleted == [IDENTITY]
    assert all(
        call[1] == smoke.PREFIX + IDENTITY or call[1] == smoke.PREFIX + IDENTITY + "/download"
        for call in server.calls[1:]
    )


@pytest.mark.parametrize(
    "body",
    [
        b"private invalid JSON",
        b"[]",
        b'{"id":"a","id":"b"}',
        b"\xff",
        b"x" * (smoke.MAX_RESPONSE_BYTES + 1),
    ],
    ids=["invalid-json", "array", "duplicate-id", "invalid-utf8", "oversized"],
)
def test_location_ownership_survives_bad_acceptance_body(body):
    def hook(server, method, path, headers, result):
        return HttpResponse(202, result.headers, body) if path in smoke.CREATION_PATHS else result

    server = Server(hook)
    report = run(server)
    assert report["checks"][0]["cleanup"] == "CONFIRMED" and server.deleted == [IDENTITY]


def test_inconsistent_canonical_identities_attempts_all_candidates_without_false_cleanup():
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            changed = dict(
                result.headers, location=smoke.PREFIX + "11111111-1111-4111-8111-111111111111"
            )
            return HttpResponse(202, changed, result.body)
        return result

    server = Server(hook)
    report = run(server)
    assert server.deleted == [IDENTITY]  # the usable JSON candidate is still cleaned
    assert (
        report["checks"][0]["cleanup"] == "UNCONFIRMED"
    )  # nonexistent candidate wasn't authorized
    assert report["checks"][0]["code"] == "acceptance_invalid"


@pytest.mark.parametrize("failure", ["lost_reply", "missing_token", "missing_identity"])
def test_uncertain_creation_is_not_replayed_or_reported_cleaned(failure):
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            if failure == "lost_reply":
                raise TimeoutError(TOKEN + IDENTITY)
            if failure == "missing_token":
                changed = dict(result.headers)
                del changed[smoke.TOKEN_HEADER]
                return HttpResponse(202, changed, result.body)
            return response({}, 202, {smoke.TOKEN_HEADER: TOKEN})
        return result

    server = Server(hook)
    report = run(server)
    assert server.created == 1 and not server.deleted
    assert report["code"] == "creation_uncertain"
    assert report["checks"][0]["cleanup"] == "UNCONFIRMED"


@pytest.mark.parametrize("boundary", ["cache", "negative", "poll", "download", "zip", "exception"])
def test_cleanup_after_every_post_acceptance_failure_boundary(boundary):
    failed = False

    def hook(server, method, path, headers, result):
        nonlocal failed
        trigger = (
            (boundary == "cache" and path in smoke.CREATION_PATHS)
            or (boundary == "negative" and method == "GET" and not headers)
            or (
                boundary == "poll"
                and method == "GET"
                and path == smoke.PREFIX + IDENTITY
                and headers.get(smoke.TOKEN_HEADER) == TOKEN
            )
            or (
                boundary in {"download", "zip", "exception"}
                and path.endswith("/download")
                and result.status_code == 200
            )
        )
        if trigger and not failed:
            failed = True
            if boundary == "exception":
                raise ValueError(TOKEN + IDENTITY)
            if boundary == "cache":
                return HttpResponse(
                    202,
                    {k: v for k, v in result.headers.items() if k != "cache-control"},
                    result.body,
                )
            if boundary == "negative":
                return HttpResponse(200, {"content-type": "application/zip"}, b"output")
            if boundary == "zip":
                return HttpResponse(200, result.headers, b"bad zip " + TOKEN.encode())
            return response({}, 503)
        return result

    server = Server(hook)
    report = run(server)
    assert failed and server.deleted == [IDENTITY] and not server.sessions
    assert report["checks"][0]["outcome"] == "FAIL"
    assert report["checks"][0]["cleanup"] == "CONFIRMED"


def test_active_timeout_cancels_with_independent_cleanup_budget_then_deletes():
    server = Server(active=True)
    report = run(server, timing=smoke.Timing(case_seconds=0.1, poll_interval=0.05))
    assert report["code"] == "deadline_exceeded" and server.deleted == [IDENTITY]
    assert [call[0] for call in server.calls if call[1].endswith("/cancel")] == ["POST"]
    assert report["checks"][0]["cleanup"] == "CONFIRMED"
    assert all(
        call[4] <= 0.1
        for call in server.calls
        if call[0] == "POST" and call[1] in smoke.CREATION_PATHS
    )


@pytest.mark.parametrize(
    "failure",
    [
        "delete",
        "cancel",
        "cleanup_timeout",
        "post_delete_status",
        "post_delete_download",
        "unverified_404",
    ],
)
def test_cleanup_failure_always_fails_suite_and_preserves_primary(failure):
    def hook(server, method, path, headers, result):
        if failure == "delete" and method == "DELETE":
            return response({}, 503)
        if failure in {"cancel", "cleanup_timeout"} and path.endswith("/cancel"):
            server.sessions[IDENTITY]["phase"] = "processing"
            return response({}, 503 if failure == "cancel" else 202)
        if failure == "post_delete_status" and path == smoke.PREFIX + IDENTITY and server.deleted:
            return HttpResponse(404, {"content-type": "text/html"}, b"proxy")
        if failure == "post_delete_download" and path.endswith("/download") and server.deleted:
            return HttpResponse(302, {"location": API}, b"")
        if failure == "unverified_404":
            if path in smoke.CREATION_PATHS:
                return HttpResponse(202, result.headers, b"bad JSON")
            return response(
                {"code": "batch_not_found", "message": "The batch session was not found."}, 404
            )
        return result

    server = Server(hook, active=failure in {"cancel", "cleanup_timeout"})
    report = run(
        server, timing=smoke.Timing(case_seconds=0.1, cleanup_seconds=0.1, poll_interval=0.05)
    )
    assert report["result"] == "FAIL" and report["passed"] == 0 and report["attempted"] == 1
    assert report["checks"][0]["cleanup"] == "UNCONFIRMED"
    if failure in {"cancel", "cleanup_timeout"}:
        assert report["checks"][0]["code"] == "deadline_exceeded"
        assert report["checks"][0]["cleanup_code"] != "none"


def test_partial_report_stops_after_first_failure_keeps_previous_cleanup_evidence():
    def hook(server, method, path, headers, result):
        if path == smoke.PREFIX + "images/resize":
            return HttpResponse(202, result.headers, b"bad JSON")
        return result

    server = Server(hook)
    report = run(server)
    assert report["attempted"] == 2 and report["passed"] == 1 and len(server.deleted) == 2
    assert [row["outcome"] for row in report["checks"]] == ["PASS", "FAIL", "SKIPPED", "SKIPPED"]


def test_busy_loop_and_suite_deadline_are_bounded():
    server = Server(active=True)
    report = run(server, timing=smoke.Timing(max_polls=2))
    assert report["code"] == "poll_limit" and server.deleted == [IDENTITY]
    clock = Clock()
    server = Server()

    def requester(*args, **kwargs):
        result = server(*args, **kwargs)
        clock.now += 0.01
        return result

    report = smoke.Lifecycle(
        API,
        requester=requester,
        clock=clock,
        sleeper=clock.sleep,
        timing=smoke.Timing(suite_seconds=0.03),
    ).run()
    assert report["result"] == "FAIL" and report["attempted"] == 1
    assert server.deleted == [IDENTITY]


def test_cli_report_privacy_and_bad_destination_precedes_network(tmp_path, monkeypatch, capsys):
    args = [
        argument
        for key, value in public_arguments().items()
        for argument in ("--" + key.replace("_", "-"), value)
    ]
    calls = []
    original = smoke.run_public

    def invoke(**kwargs):
        calls.append(kwargs)
        return original(**kwargs, requester=Server())

    monkeypatch.setattr(smoke, "run_public", invoke)
    report_path = tmp_path / "evidence.json"
    assert smoke.main(args + ["--report-json", str(report_path)]) == 0
    assert valid_report(json.loads(report_path.read_text()))
    calls.clear()
    assert smoke.main(args + ["--report-json", str(tmp_path / "missing" / "report.json")]) == 1
    assert not calls
    output = capsys.readouterr()
    assert TOKEN not in output.out + output.err and IDENTITY not in output.out + output.err


def test_private_parser_output_is_suppressed(monkeypatch, capsys):
    def parser(*args):
        print(TOKEN + IDENTITY)
        logging.getLogger("pypdf").error(TOKEN)
        raise ValueError(TOKEN)

    monkeypatch.setattr(smoke, "_zip_members", parser)
    report = run(Server())
    assert report["code"] == "output_invalid"
    captured = capsys.readouterr()
    assert TOKEN not in captured.out + captured.err and IDENTITY not in captured.out + captured.err
    assert TOKEN not in repr(smoke.Owned(IDENTITY, TOKEN))


def test_unverified_creation_capability_cannot_make_private_404_prove_cleanup():
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            # Canonical grant, but a capability that has never authorized access.
            return HttpResponse(
                202, dict(result.headers, **{smoke.TOKEN_HEADER: "unverified-token"}), result.body
            )
        return result

    report = run(Server(hook))
    assert report["result"] == "FAIL" and report["checks"][0]["cleanup"] == "UNCONFIRMED"


def test_json_identity_can_establish_cleanup_candidate_even_with_wrong_media_and_location():
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            changed = dict(result.headers, location="/unsafe", **{"content-type": "text/plain"})
            return HttpResponse(202, changed, result.body)
        return result

    server = Server(hook)
    report = run(server)
    assert report["result"] == "FAIL" and server.deleted == [IDENTITY]
    assert report["checks"][0]["cleanup"] == "CONFIRMED"


@pytest.mark.parametrize(
    "status,code,expected",
    [
        (503, "batch_capacity_exceeded", "capacity_unavailable"),
        (507, "batch_storage_pressure", "storage_unavailable"),
        (503, "batch_storage_unavailable", "storage_unavailable"),
        (503, "office_engine_unavailable", "engine_unavailable"),
        (502, "unknown_proxy_error", "creation_uncertain"),
    ],
)
def test_named_rejections_and_ambiguous_server_errors_are_not_replayed(status, code, expected):
    calls = []

    def requester(method, url, **kwargs):
        calls.append((method, url))
        return response({"code": code, "message": TOKEN + IDENTITY}, status)

    report = run(requester)
    assert report["code"] == expected and len(calls) == 1
    row = report["checks"][0]
    assert row["cleanup"] == ("UNCONFIRMED" if expected == "creation_uncertain" else "NOT_NEEDED")


def cleanup_runner(requester, *, cleanup_seconds=1):
    clock = Clock()
    runner = smoke.Lifecycle(
        API,
        requester=requester,
        clock=clock,
        sleeper=clock.sleep,
        timing=smoke.Timing(cleanup_seconds=cleanup_seconds, poll_interval=0.05),
    )
    return runner, clock


def noncancellable_state(phase):
    case = smoke.cases()[0]
    value = state(case)
    value.update(phase=phase, can_cancel=False, can_download=False)
    if phase == "processing":
        # The final item is running; there is no pending work left to cancel.
        value.update(status="running", progress_percent=50)
        value["items"][1].update(status="running", result_descriptor=None)
        value["summary"].update(completed=1, running=1, processed=1, remaining=1)
    return value


@pytest.mark.parametrize("phase", ["packaging", "processing"])
def test_cleanup_waits_for_noncancellable_work_then_deletes_and_proves_absence(phase):
    server = Server()
    status_reads = 0

    def requester(method, url, **kwargs):
        nonlocal status_reads
        result = server(method, url, **kwargs)
        if method == "GET" and url == API + smoke.PREFIX + IDENTITY and not server.deleted:
            status_reads += 1
            if status_reads == 1:
                return response(noncancellable_state(phase))
        return result

    # Establish only this owned session; cleanup must not create or cancel work.
    server.sessions[IDENTITY] = state(server.fixtures[0])
    runner, clock = cleanup_runner(requester)
    runner.cleanup(smoke.Owned(IDENTITY, TOKEN))
    assert server.deleted == [IDENTITY] and not server.sessions
    assert status_reads == 2 and clock.sleeps == [0.05]
    assert [call[0] for call in server.calls] == ["GET", "GET", "DELETE", "GET", "GET"]
    assert [call[1] for call in server.calls[-2:]] == [
        smoke.PREFIX + IDENTITY,
        smoke.PREFIX + IDENTITY + "/download",
    ]
    assert all(call[2].get(smoke.TOKEN_HEADER) == TOKEN for call in server.calls)


@pytest.mark.parametrize("extra_active_status", [False, True])
def test_cleanup_accepts_exact_completion_race_without_repeating_cancellation(extra_active_status):
    server = Server()
    case = server.fixtures[0]
    server.sessions[IDENTITY] = state(case, active=True)
    raced = False

    def requester(method, url, **kwargs):
        nonlocal raced
        # Count and inspect actual requests through the normal HTTP double.
        result = server(method, url, **kwargs)
        if url.endswith("/cancel"):
            raced = True
            server.sessions[IDENTITY] = state(case, active=extra_active_status)
            return response(
                {
                    "code": "batch_not_cancellable",
                    "message": "The batch can no longer be cancelled.",
                },
                409,
            )
        if raced and extra_active_status and method == "GET" and not server.deleted:
            # Leave can_cancel=true in this one stale reply, to guard against a
            # repeated cancellation attempt after the documented 409 race.
            server.sessions[IDENTITY] = state(case)
        return result

    runner, clock = cleanup_runner(requester)
    runner.cleanup(smoke.Owned(IDENTITY, TOKEN))
    assert server.deleted == [IDENTITY]
    assert [call[0] for call in server.calls if call[1].endswith("/cancel")] == ["POST"]
    assert server.calls[2][0:2] == ("GET", smoke.PREFIX + IDENTITY)
    assert clock.sleeps == ([0.05] if extra_active_status else [])
    assert [call[0] for call in server.calls[-3:]] == ["DELETE", "GET", "GET"]


def test_noncancellable_work_exhausts_independent_cleanup_deadline_and_retains_primary_failure():
    def hook(server, method, path, headers, result):
        if path in smoke.CREATION_PATHS:
            # A primary acceptance failure triggers cleanup immediately.
            return HttpResponse(202, result.headers, b"malformed acceptance")
        if method == "GET" and result.status_code == 200:
            return response(noncancellable_state("packaging"))
        return result

    server = Server(hook)
    clock = Clock()
    runner = smoke.Lifecycle(
        API,
        requester=server,
        clock=clock,
        sleeper=clock.sleep,
        timing=smoke.Timing(case_seconds=0.01, cleanup_seconds=0.12, poll_interval=0.05),
    )
    report = runner.run()
    assert valid_report(report)
    assert report["attempted"] == server.created == 1 and not server.deleted
    row = report["checks"][0]
    assert row["code"] == "acceptance_invalid"
    assert row["cleanup"] == "UNCONFIRMED" and row["cleanup_code"] == "deadline_exceeded"
    assert clock.now == pytest.approx(0.12) and clock.sleeps == pytest.approx([0.05, 0.05, 0.02])
    assert all(0 < call[4] <= 0.12 for call in server.calls)
    assert not any(call[1].endswith("/cancel") or call[0] == "DELETE" for call in server.calls)
    assert TOKEN not in json.dumps(report) and IDENTITY not in json.dumps(report)


@pytest.mark.parametrize(
    "failure",
    [
        "unrelated",
        "wrong-message",
        "missing-message",
        "extra-field",
        "invalid-json",
        "wrong-media",
        "not-private",
        "redirect",
        "transport",
        "malformed-accepted",
    ],
)
def test_cleanup_rejects_unrelated_or_malformed_cancellation_replies(failure):
    server = Server()
    server.sessions[IDENTITY] = state(server.fixtures[0], active=True)

    def requester(method, url, **kwargs):
        result = server(method, url, **kwargs)
        if not url.endswith("/cancel"):
            return result
        value = {
            "code": "batch_not_cancellable",
            "message": "The batch can no longer be cancelled.",
        }
        headers = {}
        if failure == "unrelated":
            value["code"] = "batch_download_active"
        elif failure == "wrong-message":
            value["message"] = TOKEN + IDENTITY
        elif failure == "missing-message":
            del value["message"]
        elif failure == "extra-field":
            value["private"] = TOKEN
        elif failure == "wrong-media":
            headers["content-type"] = "text/html"
        elif failure == "not-private":
            headers["cache-control"] = "public"
        elif failure == "invalid-json":
            return HttpResponse(409, result.headers, b"not JSON")
        elif failure == "redirect":
            return HttpResponse(307, {"location": API}, b"")
        elif failure == "transport":
            raise OSError(TOKEN + IDENTITY)
        elif failure == "malformed-accepted":
            return response({}, 202)
        return response(value, 409, headers)

    runner, _ = cleanup_runner(requester)
    with pytest.raises(smoke.Failure) as error:
        runner.cleanup(smoke.Owned(IDENTITY, TOKEN))
    assert not server.deleted
    assert [call[0] for call in server.calls] == ["GET", "POST"]
    assert TOKEN not in str(error.value) and IDENTITY not in str(error.value)


def test_shared_immutable_fixtures_cross_docx_zip_timestamp_boundary_without_sleep(monkeypatch):
    smoke.cases.cache_clear()
    try:
        monkeypatch.setattr(
            zipfile.time, "localtime", lambda *args: (2026, 11, 26, 0, 0, 0, 3, 330, -1)
        )
        server = Server()
        docx_before = server.fixtures[3].files[0][2]
        monkeypatch.setattr(
            zipfile.time, "localtime", lambda *args: (2026, 11, 26, 0, 0, 2, 3, 330, -1)
        )
        docx_after = smoke.make_synthetic_docx()
        # Prove the old independent builders would produce unequal bytes across
        # precisely one ZIP timestamp tick; advance the clock without sleeping.
        assert docx_before != docx_after
        with (
            zipfile.ZipFile(BytesIO(docx_before)) as before,
            zipfile.ZipFile(BytesIO(docx_after)) as after,
        ):
            assert all(info.date_time[-1] == 0 for info in before.infolist())
            assert all(info.date_time[-1] == 2 for info in after.infolist())
        assert smoke.cases() is server.fixtures
        report = run(server)
        assert report["result"] == "PASS" and report["passed"] == report["attempted"] == 4
        assert len(server.deleted) == 4 and not server.sessions
        # All exact multipart field/name/media/content assertions in Server ran.
    finally:
        smoke.cases.cache_clear()
