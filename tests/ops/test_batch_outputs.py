import json
import struct
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

import pytest
from pypdf import PdfWriter

from docuforge.ops import batch_smoke as smoke
from docuforge.ops import deployment_smoke
from docuforge.ops.deployment_smoke import HttpResponse
from tests.ops.batch_support import Server, archive
from tests.ops.test_batch_smoke import run


def zip_bytes(entries, *, compression=ZIP_DEFLATED):
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=compression) as output:
        for name, content in entries:
            output.writestr(name, content)
    return buffer.getvalue()


def mutate_zip(payload, mutation):
    with ZipFile(BytesIO(payload)) as source:
        entries = [(name, source.read(name)) for name in source.namelist()]
    if mutation == "order":
        entries.reverse()
    elif mutation == "missing":
        entries.pop()
    elif mutation == "extra":
        entries.append(("extra.jpg", b"extra"))
    elif mutation == "duplicate":
        entries[1] = entries[0]
    elif mutation == "directory":
        entries[0] = ("directory/", b"")
    elif mutation == "escape":
        entries[0] = ("../output.jpg", b"unsafe")
    elif mutation == "wrong-format":
        entries[0] = (entries[0][0], b"not an image")
    elif mutation == "dimensions":
        # A real decodable JPEG with the other source's dimensions.
        entries[0] = (entries[0][0], entries[1][1])
    result = bytearray(
        zip_bytes(entries, compression=ZIP_STORED if mutation == "crc" else ZIP_DEFLATED)
    )
    if mutation == "crc":
        # Change stored bytes without updating the local or central CRC.
        name_len, extra_len = struct.unpack_from("<HH", result, 26)
        result[30 + name_len + extra_len + 10] ^= 1
    elif mutation == "encrypted":
        offset = result.index(b"PK\x01\x02")
        result[offset + 8] |= 1
    return bytes(result)


@pytest.mark.parametrize(
    "mutation",
    [
        "order",
        "missing",
        "extra",
        "duplicate",
        "directory",
        "escape",
        "wrong-format",
        "dimensions",
        "crc",
        "encrypted",
    ],
)
def test_zip_names_order_safety_crc_and_image_semantics_fail_with_cleanup(mutation):
    def hook(server, method, path, headers, result):
        if path.endswith("/download") and result.status_code == 200:
            return HttpResponse(200, result.headers, mutate_zip(result.body, mutation))
        return result

    server = Server(hook)
    report = run(server)
    assert report["code"] == "output_invalid" and len(server.deleted) == 1
    assert report["checks"][0]["cleanup"] == "CONFIRMED"


@pytest.mark.parametrize("limit", ["member", "total", "http"])
def test_existing_smoke_size_limits_are_enforced_without_customer_budget_changes(
    monkeypatch, limit
):
    if limit == "member":
        monkeypatch.setattr(deployment_smoke, "MAX_ZIP_MEMBER_BYTES", 8)
    elif limit == "total":
        monkeypatch.setattr(deployment_smoke, "MAX_ZIP_TOTAL_BYTES", 8)

    def hook(server, method, path, headers, result):
        if limit == "http" and path.endswith("/download") and result.status_code == 200:
            return HttpResponse(200, result.headers, b"x" * (smoke.MAX_RESPONSE_BYTES + 1))
        return result

    server = Server(hook)
    report = run(server)
    assert report["result"] == "FAIL" and len(server.deleted) == 1
    assert report["code"] == ("response_too_large" if limit == "http" else "output_invalid")


@pytest.mark.parametrize(
    "disposition",
    [
        'attachment; filename="../private.zip"',
        'inline; filename="output.zip"',
        'attachment; filename="bad:output.zip"',
    ],
)
def test_safe_attachment_filename_is_required_when_supplied(disposition):
    def hook(server, method, path, headers, result):
        if path.endswith("/download") and result.status_code == 200:
            return HttpResponse(
                200, dict(result.headers, **{"content-disposition": disposition}), result.body
            )
        return result

    report = run(Server(hook))
    assert report["code"] == "output_invalid"


@pytest.mark.parametrize("kind", ["wrong-marker", "encrypted", "malformed"])
def test_office_members_must_be_unencrypted_pdfs_with_corresponding_markers(kind):
    def hook(server, method, path, headers, result):
        if path.endswith("/download") and result.status_code == 200 and server.created == 4:
            with ZipFile(BytesIO(result.body)) as source:
                entries = [(name, source.read(name)) for name in source.namelist()]
            if kind == "wrong-marker":
                entries[0] = (entries[0][0], entries[1][1])
            elif kind == "encrypted":
                writer = PdfWriter(BytesIO(entries[0][1]))
                writer.encrypt("private-password")
                buffer = BytesIO()
                writer.write(buffer)
                entries[0] = (entries[0][0], buffer.getvalue())
            else:
                entries[0] = (entries[0][0], b"%PDF-private malformed data")
            return HttpResponse(200, result.headers, zip_bytes(entries))
        return result

    server = Server(hook)
    report = run(server)
    assert report["code"] == "output_invalid" and report["passed"] == 3 and len(server.deleted) == 4
    assert report["checks"][3]["cleanup"] == "CONFIRMED"


def test_fixtures_have_different_dimensions_and_content_and_known_output_names():
    cases = smoke.cases()
    assert cases[0].files[0][2] != cases[0].files[1][2]
    assert cases[1].dimensions == ((48, 32), (24, 40))
    assert cases[3].outputs == ("0001-alpha.pdf", "0002-bravo.pdf", "0003-charlie.pdf")
    assert len(archive(cases[3])) > 0
    assert json.dumps([case.name for case in cases]) == json.dumps(list(smoke.BATCH_CHECKS))
