"""Inspect real synthetic input structure, without accepting placeholder packages."""

import posixpath
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from docuforge.ops.smoke_fixtures import (
    PPTX_MARKER,
    SCAN_PAGE_SIZES,
    XLSX_MARKER,
    make_synthetic_pptx,
    make_synthetic_scanned_pdf,
    make_synthetic_xlsx,
)


@pytest.mark.parametrize("make", [make_synthetic_pptx, make_synthetic_xlsx])
def test_ooxml_package_has_valid_xml_types_and_resolvable_relationships(make):
    payload = make()
    assert payload == make()
    assert len(payload) < 20_000
    with ZipFile(BytesIO(payload)) as archive:
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert "[Content_Types].xml" in names and "_rels/.rels" in names
        types = ElementTree.fromstring(archive.read("[Content_Types].xml"))
        overrides = {
            node.attrib["PartName"].lstrip("/"): node.attrib["ContentType"]
            for node in types
            if node.tag.endswith("}Override")
        }
        defaults = {
            node.attrib["Extension"]: node.attrib["ContentType"]
            for node in types
            if node.tag.endswith("}Default")
        }
        assert defaults["rels"] == "application/vnd.openxmlformats-package.relationships+xml"
        for name in names:
            root = ElementTree.fromstring(archive.read(name))
            if name.endswith(".rels"):
                ids = []
                base = "" if name == "_rels/.rels" else posixpath.dirname(posixpath.dirname(name))
                for relationship in root:
                    ids.append(relationship.attrib["Id"])
                    target = posixpath.normpath(posixpath.join(base, relationship.attrib["Target"]))
                    assert target in names
                    assert relationship.attrib["Type"].startswith(
                        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
                    )
                assert len(ids) == len(set(ids))
            elif name != "[Content_Types].xml":
                assert overrides[name].startswith("application/vnd.openxmlformats-officedocument.")
                assert root.tag.startswith("{http://schemas.openxmlformats.org/")


def test_pptx_is_one_slide_with_a_text_shape_and_master_layout_theme():
    with ZipFile(BytesIO(make_synthetic_pptx())) as archive:
        ns = {
            "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
            "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
        }
        presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
        assert len(presentation.findall("p:sldIdLst/p:sldId", ns)) == 1
        slide = ElementTree.fromstring(archive.read("ppt/slides/slide1.xml"))
        assert [node.text for node in slide.findall(".//a:t", ns)] == [PPTX_MARKER]
        assert {
            "ppt/slideLayouts/slideLayout1.xml",
            "ppt/slideMasters/slideMaster1.xml",
            "ppt/theme/theme1.xml",
        } <= set(archive.namelist())


def test_xlsx_is_one_sheet_with_inline_text_and_single_page_print_layout():
    with ZipFile(BytesIO(make_synthetic_xlsx())) as archive:
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        assert len(workbook.findall("s:sheets/s:sheet", ns)) == 1
        assert workbook.find("s:definedNames/s:definedName", ns).text.strip() == "'Smoke'!$A$1:$A$1"
        sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        assert [node.text for node in sheet.findall(".//s:t", ns)] == [XLSX_MARKER]
        setup = sheet.find("s:pageSetup", ns)
        assert setup.attrib["fitToWidth"] == setup.attrib["fitToHeight"] == "1"


def test_scanned_fixture_has_two_distinct_nonblank_image_only_pages():
    payload = make_synthetic_scanned_pdf()
    assert len(payload) < 256_000
    reader = PdfReader(BytesIO(payload), strict=True)
    assert not reader.is_encrypted
    assert len(reader.pages) == 2
    for page, size in zip(reader.pages, SCAN_PAGE_SIZES, strict=True):
        assert (float(page.mediabox.width), float(page.mediabox.height)) == size
        assert not page.extract_text().strip()
        images = list(page.images)
        assert len(images) == 1
        image = images[0].image.convert("L")
        try:
            assert image.width >= 1000 and image.height >= 600
            assert image.getextrema() == (0, 255)
            histogram = image.histogram()
            assert histogram[0] > 1000 and histogram[255] > 1000
        finally:
            image.close()
