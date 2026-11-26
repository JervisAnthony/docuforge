"""Deterministic HTTP double, not evidence of real API/engine execution."""

import copy
import json
from email.parser import BytesParser
from email.policy import default
from io import BytesIO
from urllib.parse import urlsplit
from uuid import UUID
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from docuforge.ops.batch_smoke import PREFIX, TOKEN_HEADER, cases
from docuforge.ops.deployment_smoke import HttpResponse
from tests.ops.office_ocr_support import text_pdf

TOKEN = "sentinel-private-capability"
IDENTITY = "12345678-1234-4234-9234-123456789abc"
API = "https://api.example.com"
FRONTEND = "https://app.example.com"
API_REVISION = "a" * 40
FRONTEND_REVISION = "b" * 40


def response(value, status=200, headers=None):
    return HttpResponse(
        status,
        {"content-type": "application/json", "cache-control": "no-store", **(headers or {})},
        json.dumps(value).encode(),
    )


def not_found():
    return response({"code": "batch_not_found", "message": "The batch session was not found."}, 404)


def state(case, identity=IDENTITY, *, active=False):
    status = "pending" if active else "completed"
    count = len(case.files)
    return {
        "id": identity,
        "operation": case.operation,
        "attempt": 1,
        "phase": "processing" if active else "ready",
        "status": status,
        "progress_percent": 0 if active else 100,
        "cancellation_requested": False,
        "can_cancel": active,
        "can_recover": False,
        "can_download": not active,
        "session_error": None,
        "summary": {
            "total": count,
            "pending": count if active else 0,
            "running": 0,
            "completed": 0 if active else count,
            "failed": 0,
            "cancelled": 0,
            "processed": 0 if active else count,
            "remaining": count if active else 0,
        },
        "items": [
            {
                "id": str(UUID(int=index + 1)),
                "position": index,
                "descriptor": file[1],
                "status": status,
                "result_descriptor": None if active else case.outputs[index],
                "failure": None,
            }
            for index, file in enumerate(case.files)
        ],
    }


def archive(case):
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as output:
        for index, name in enumerate(case.outputs):
            if case.markers:
                data = text_pdf((200, 120, case.markers[index]))
            else:
                image_buffer = BytesIO()
                with Image.new("RGB", case.dimensions[index], "navy") as image:
                    image.save(image_buffer, format="PNG" if name.endswith("png") else "JPEG")
                data = image_buffer.getvalue()
            output.writestr(name, data)
    return buffer.getvalue()


class Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += seconds


class Server:
    def __init__(self, hook=None, active=False):
        self.calls = []
        self.sessions = {}
        self.hook = hook
        self.active = active
        self.created = 0
        self.deleted = []
        self.fixtures = cases()

    def __call__(self, method, url, *, headers=None, body=None, timeout):
        assert 0 < timeout <= 60
        parts = urlsplit(url)
        assert f"{parts.scheme}://{parts.netloc}" in {API, FRONTEND}
        assert not parts.query and not parts.fragment
        headers = headers or {}
        path = parts.path
        self.calls.append((method, path, headers, body, timeout))
        identity_routes = {
            "/api/v1/ready": {"status": "ready", "service": "docuforge", "version": "0.1.0"},
            "/api/v1/build": {
                "schema_version": 1,
                "service": "docuforge",
                "version": "0.1.0",
                "revision": API_REVISION,
            },
            "/build-info.json": {
                "schema_version": 1,
                "service": "docuforge-frontend",
                "version": "0.1.0",
                "revision": FRONTEND_REVISION,
            },
        }
        if path in identity_routes:
            result = response(identity_routes[path])
        elif path == "/":
            result = HttpResponse(
                200,
                {"content-type": "text/html"},
                (
                    '<head><meta name="docuforge-version" content="0.1.0">'
                    f'<meta name="docuforge-revision" content="{FRONTEND_REVISION}">'
                    "</head>"
                ).encode(),
            )
        elif method == "POST" and any(path == PREFIX + case.route for case in self.fixtures):
            case = next(case for case in self.fixtures if path == PREFIX + case.route)
            assert TOKEN_HEADER not in headers
            message = BytesParser(policy=default).parsebytes(
                ("Content-Type: " + headers["Content-Type"] + "\r\n\r\n").encode() + body
            )
            fields, files = [], []
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if part.get_filename():
                    files.append(
                        (
                            name,
                            part.get_filename(),
                            part.get_payload(decode=True),
                            part.get_content_type(),
                        )
                    )
                else:
                    fields.append((name, part.get_content()))
            assert tuple(fields) == case.fields
            assert tuple(files) == case.files
            self.created += 1
            identity = IDENTITY if self.created == 1 else str(UUID(int=1000 + self.created))
            self.sessions[identity] = state(case, identity, active=self.active)
            result = response(
                copy.deepcopy(self.sessions[identity]),
                202,
                {"location": PREFIX + identity, TOKEN_HEADER: TOKEN},
            )
        else:
            identity = path[len(PREFIX) :].split("/")[0]
            value = self.sessions.get(identity)
            if value is None or headers.get(TOKEN_HEADER) != TOKEN:
                result = not_found()
            elif method == "DELETE":
                assert value["phase"] in {"ready", "error"}
                del self.sessions[identity]
                self.deleted.append(identity)
                result = HttpResponse(204, {}, b"")
            elif path.endswith("/cancel"):
                value["phase"] = "error"
                result = response(copy.deepcopy(value), 202)
            elif path.endswith("/download"):
                case = next(c for c in self.fixtures if c.operation == value["operation"])
                result = HttpResponse(
                    200,
                    {
                        "content-type": "application/zip",
                        "cache-control": "no-store",
                        "content-disposition": f'attachment; filename="batch-{identity}.zip"',
                    },
                    archive(case),
                )
            else:
                result = response(copy.deepcopy(value))
        return self.hook(self, method, path, headers, result) if self.hook else result


def public_arguments():
    return {
        "api_url": API,
        "frontend_url": FRONTEND,
        "expected_api_revision": API_REVISION,
        "expected_frontend_revision": FRONTEND_REVISION,
        "expected_version": "0.1.0",
    }
