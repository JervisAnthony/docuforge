import json

import pytest

from docuforge.ops import release_identity
from docuforge.ops.deployment_smoke import DeploymentSmokeError, HttpResponse
from docuforge.ops.release_identity import (
    BuildVerificationError,
    verify_deployed_builds,
    verify_release_identity,
)


def _response(version: str) -> HttpResponse:
    payload = {"status": "ready", "service": "docuforge", "version": version}
    return HttpResponse(200, {"content-type": "application/json"}, json.dumps(payload).encode())


def test_release_identity_matches_expected_version() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        return _response("0.1.0")

    assert (
        verify_release_identity(
            "https://docuforge.invalid",
            expected_version="0.1.0",
            requester=requester,
        )
        == "0.1.0"
    )


def test_release_identity_rejects_version_mismatch() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        return _response("0.0.9")

    with pytest.raises(DeploymentSmokeError, match="does not match expected release"):
        verify_release_identity(
            "https://docuforge.invalid",
            expected_version="0.1.0",
            requester=requester,
        )


def test_release_identity_rejects_bad_readiness_state() -> None:
    def requester(method, url, *, headers=None, body=None, timeout):
        payload = {"status": "starting", "service": "docuforge", "version": "0.1.0"}
        return HttpResponse(200, {}, json.dumps(payload).encode())

    with pytest.raises(DeploymentSmokeError, match="unexpected service state"):
        verify_release_identity(
            "https://docuforge.invalid",
            expected_version="0.1.0",
            requester=requester,
        )


API_SHA = "a1" * 20
FRONTEND_SHA = "b2" * 20


def _json(payload, media="application/json"):
    return HttpResponse(200, {"Content-Type": media}, json.dumps(payload).encode())


def _stamp(service, sha):
    return {"schema_version": 1, "service": service, "version": "0.1.0", "revision": sha}


def _html(sha=FRONTEND_SHA):
    return (
        '<!doctype html><html><head><meta name="docuforge-version" content="0.1.0">'
        f'<meta name="docuforge-revision" content="{sha}"></head><body>DocuForge</body></html>'
    ).encode()


class StrictRequester:
    def __init__(self):
        self.calls = []
        self.responses = {
            "https://api.example.com/api/v1/ready": _response("0.1.0"),
            "https://api.example.com/api/v1/build": _json(_stamp("docuforge", API_SHA)),
            "https://app.example.com/build-info.json": _json(
                _stamp("docuforge-frontend", FRONTEND_SHA)
            ),
            "https://app.example.com/": HttpResponse(
                200, {"content-type": "text/html; charset=utf-8"}, _html()
            ),
        }

    def __call__(self, method, url, *, headers=None, body=None, timeout):
        assert method == "GET" and body is None and timeout == 15
        assert "no-cache" in headers["Cache-Control"]
        assert "no-store" in headers["Cache-Control"]
        assert headers["Pragma"] == "no-cache"
        self.calls.append(url)
        return self.responses[url]


def _verify(requester, **overrides):
    options = {
        "api_url": "https://api.example.com",
        "frontend_url": "https://app.example.com",
        "expected_api_revision": API_SHA,
        "expected_frontend_revision": FRONTEND_SHA,
        "expected_version": "0.1.0",
        "requester": requester,
    }
    options.update(overrides)
    return verify_deployed_builds(**options)


def test_strict_accepts_independently_expected_revisions_and_requests_fresh_metadata():
    requester = StrictRequester()
    report = _verify(requester, expected_api_revision=API_SHA.upper())
    assert report["result"] == "PASS"
    assert report["components"]["api"]["observed_revision"] == API_SHA
    assert report["components"]["frontend"]["observed_revision"] == FRONTEND_SHA
    assert len(requester.calls) == 4


@pytest.mark.parametrize(
    "name,path,service,sha",
    [
        ("api", "/api/v1/build", "docuforge", API_SHA),
        ("frontend", "/build-info.json", "docuforge-frontend", FRONTEND_SHA),
    ],
)
@pytest.mark.parametrize(
    "field,value",
    [
        ("revision", "c" * 40),
        ("revision", None),
        ("revision", ""),
        ("revision", "abc"),
        ("revision", "private\ncontrol"),
        ("revision", True),
        ("schema_version", True),
        ("schema_version", 1.0),
        ("schema_version", 2),
        ("schema_version", "1"),
        ("service", "other"),
        ("version", "0.0.9"),
        ("version", "private\nversion"),
    ],
)
def test_strict_rejects_invalid_or_stale_component(name, path, service, sha, field, value):
    requester = StrictRequester()
    origin = "https://api.example.com" if name == "api" else "https://app.example.com"
    payload = _stamp(service, sha)
    payload[field] = value
    requester.responses[origin + path] = _json(payload)
    with pytest.raises(BuildVerificationError) as raised:
        _verify(requester)
    report = raised.value.report
    assert report["result"] == "FAIL"
    assert report["components"][name]["outcome"] == "FAIL"
    other = "frontend" if name == "api" else "api"
    assert report["components"][other]["outcome"] == "PASS"
    assert name in str(raised.value)
    assert "private" not in json.dumps(report) + str(raised.value)


@pytest.mark.parametrize("path", ["/api/v1/build", "/build-info.json"])
@pytest.mark.parametrize(
    "response",
    [
        HttpResponse(404, {}, b"private response"),
        HttpResponse(200, {"content-type": "text/html"}, b"<html>private</html>"),
        HttpResponse(200, {"content-type": "application/json"}, b"<html>private</html>"),
        HttpResponse(200, {"content-type": "application/json"}, b"{}"),
        HttpResponse(200, {"content-type": "application/json"}, b"null"),
        HttpResponse(200, {"content-type": "application/json"}, b"[]"),
        HttpResponse(200, {}, b"{}"),
        HttpResponse(200, {"content-type": "application/json"}, b"x" * 4097),
        HttpResponse(
            200, {"content-type": "application/json"}, b'{"revision":null,"revision":null}'
        ),
    ],
)
def test_strict_rejects_missing_malformed_media_type_and_size(path, response):
    requester = StrictRequester()
    origin = "https://api.example.com" if path.startswith("/api") else "https://app.example.com"
    requester.responses[origin + path] = response
    with pytest.raises(BuildVerificationError) as raised:
        _verify(requester)
    assert "private" not in str(raised.value) + json.dumps(raised.value.report)


@pytest.mark.parametrize(
    "body",
    [
        b"<html><head></head><body>DocuForge</body></html>",
        _html("c" * 40),
        _html().replace(b"0.1.0", b"0.0.9"),
        _html().replace(b"</head>", b'<meta name="docuforge-version" content="0.1.0"></head>'),
        _html().replace(
            b'name="docuforge-revision"', b'name="docuforge-revision" name="docuforge-revision"'
        ),
        _html().replace(b"<head>", b"<body>").replace(b"</head>", b"</body>"),
        b"\xff",
        b"x" * (1024 * 1024 + 1),
    ],
    ids=[
        "missing",
        "stale-revision",
        "stale-version",
        "duplicate-tag",
        "duplicate-attribute",
        "outside-head",
        "invalid-encoding",
        "oversized",
    ],
)
def test_frontend_html_must_match_manifest_once(body):
    requester = StrictRequester()
    requester.responses["https://app.example.com/"] = HttpResponse(
        200, {"content-type": "text/html"}, body
    )
    with pytest.raises(BuildVerificationError, match="frontend"):
        _verify(requester)


@pytest.mark.parametrize(
    "origin",
    [
        "http://api.example.com",
        "https://api.example.com/path",
        "https://user:private@api.example.com",
        "https://api.example.com?private",
        "https://api.example.com#private",
        "https://",
        "https://api.example.com:bad",
        "https://api.example.com:99999",
        "https://api.example.com:0",
        "https://api.example.com\n",
        "https://api.exa\tmple.com",
        "https://api.example.com////",
    ],
)
@pytest.mark.parametrize("key", ["api_url", "frontend_url"])
def test_invalid_origins_rejected_before_network(key, origin):
    requester = StrictRequester()
    with pytest.raises(BuildVerificationError) as raised:
        _verify(requester, **{key: origin})
    assert not requester.calls
    assert raised.value.report["result"] == "FAIL"
    assert "private" not in json.dumps(raised.value.report) + str(raised.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"expected_api_revision": "abc"},
        {"expected_frontend_revision": ""},
        {"expected_version": "private\nversion"},
        {"timeout": 0},
        {"timeout": float("nan")},
    ],
)
def test_invalid_expectations_before_network(overrides):
    requester = StrictRequester()
    with pytest.raises(BuildVerificationError):
        _verify(requester, **overrides)
    assert not requester.calls


def test_readiness_remains_a_gate_and_unavailable_transport_has_safe_partial_report():
    requester = StrictRequester()
    requester.responses["https://api.example.com/api/v1/ready"] = _response("0.0.9")
    with pytest.raises(BuildVerificationError, match="api: readiness") as raised:
        _verify(requester)
    assert raised.value.report["components"]["frontend"]["outcome"] == "PASS"

    def unavailable(*args, **kwargs):
        raise DeploymentSmokeError("private transport info")

    with pytest.raises(BuildVerificationError) as raised:
        _verify(unavailable)
    assert "private" not in str(raised.value) + json.dumps(raised.value.report)


@pytest.mark.parametrize(
    "args",
    [
        ["--expected-api-revision", API_SHA],
        ["--expected-frontend-revision", FRONTEND_SHA],
        ["--frontend-url", "https://app.example.com"],
        ["--expected-api-revision", API_SHA, "--expected-frontend-revision", FRONTEND_SHA],
    ],
)
def test_partial_cli_arguments_fail_with_report(tmp_path, monkeypatch, args):
    monkeypatch.setattr(
        release_identity, "verify_deployed_builds", lambda *a, **k: pytest.fail("network")
    )
    target = tmp_path / "report.json"
    assert (
        release_identity.main(
            ["--api-url", "https://api.example.com", "--report-json", str(target), *args]
        )
        == 1
    )
    assert json.loads(target.read_bytes())["result"] == "FAIL"


@pytest.mark.parametrize("success", [True, False])
def test_strict_cli_exit_codes_and_structured_reports(tmp_path, monkeypatch, capsys, success):
    requester = StrictRequester()
    if not success:
        requester.responses["https://app.example.com/build-info.json"] = _json(
            _stamp("docuforge-frontend", "c" * 40)
        )
    original = verify_deployed_builds
    monkeypatch.setattr(
        release_identity,
        "verify_deployed_builds",
        lambda *a, **kw: original(*a, **kw, requester=requester),
    )
    target = tmp_path / "report.json"
    code = release_identity.main(
        [
            "--api-url",
            "https://api.example.com",
            "--frontend-url",
            "https://app.example.com",
            "--expected-api-revision",
            API_SHA,
            "--expected-frontend-revision",
            FRONTEND_SHA,
            "--report-json",
            str(target),
        ]
    )
    assert code == (0 if success else 1)
    assert json.loads(target.read_bytes())["result"] == ("PASS" if success else "FAIL")
    output = capsys.readouterr()
    assert ("PASS deployed-build-identity" in output.out) == success


def test_legacy_cli_clearly_disclaims_revision_verification(monkeypatch, capsys):
    monkeypatch.setattr(release_identity, "verify_release_identity", lambda *a, **kw: "0.1.0")
    assert release_identity.main(["--api-url", "https://api.example.com"]) == 0
    assert "revisions NOT verified" in capsys.readouterr().out


def test_strict_uses_shared_bounded_http_reads(monkeypatch):
    from io import BytesIO

    from docuforge.ops import deployment_smoke

    responses = StrictRequester().responses
    reads = []

    class Stream(BytesIO):
        def __init__(self, response):
            super().__init__(response.body)
            self.status = response.status_code
            self.headers = response.headers

        def read(self, size=-1):
            reads.append(size)
            return super().read(size)

    def urlopen(request, *, timeout):
        assert request.get_header("Cache-control") == "no-cache, no-store"
        return Stream(responses[request.full_url])

    monkeypatch.setattr(deployment_smoke, "urlopen", urlopen)
    assert _verify(deployment_smoke.request_http)["result"] == "PASS"
    assert reads == [deployment_smoke.MAX_RESPONSE_BYTES + 1] * 4


@pytest.mark.parametrize("origin", ["https://-bad.example", "https://bad..example", "https://."])
def test_invalid_dns_names_are_not_origins(origin):
    requester = StrictRequester()
    with pytest.raises(BuildVerificationError):
        _verify(requester, api_url=origin)
    assert not requester.calls
