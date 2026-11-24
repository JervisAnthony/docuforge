"""Small, public synthetic documents for production coverage; no engine dependency."""

from io import BytesIO
from time import gmtime
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from PIL import Image, ImageDraw, ImageFont

PPTX_MARKER = "DOCUFORGE PPTX ALPHA"
XLSX_MARKER = "DOCUFORGE XLSX BRAVO"
SCAN_MARKERS = ("ALPHA", "BRAVO")
SCAN_PAGE_SIZES = ((360, 216), (432, 252))

_OPC = "http://schemas.openxmlformats.org/package/2006"
_OFFICE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
_PRESENTATION = "http://schemas.openxmlformats.org/presentationml/2006/main"
_SHEET = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_GROUP = """<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>
<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>"""


def _package(parts: dict[str, str]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        for name, xml in parts.items():
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, xml.encode("utf-8"))
    return buffer.getvalue()


def _relationships(*items: tuple[str, str, str]) -> str:
    return (
        f'<Relationships xmlns="{_OPC}/relationships">'
        + "".join(
            f'<Relationship Id="{identity}" Type="{_OFFICE}/{kind}" Target="{target}"/>'
            for identity, kind, target in items
        )
        + "</Relationships>"
    )


def _content_types(parts: dict[str, str]) -> str:
    return (
        f'<Types xmlns="{_OPC}/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        + "".join(
            f'<Override PartName="/{part}" ContentType="{kind}"/>' for part, kind in parts.items()
        )
        + "</Types>"
    )


def make_synthetic_pptx() -> bytes:
    """One 10 by 7.5 inch slide, with a complete master/layout/theme graph."""
    mime = "application/vnd.openxmlformats-officedocument.presentationml."
    parts = {
        "[Content_Types].xml": _content_types(
            {
                "ppt/presentation.xml": mime + "presentation.main+xml",
                "ppt/slides/slide1.xml": mime + "slide+xml",
                "ppt/slideLayouts/slideLayout1.xml": mime + "slideLayout+xml",
                "ppt/slideMasters/slideMaster1.xml": mime + "slideMaster+xml",
                "ppt/theme/theme1.xml": "application/vnd.openxmlformats-officedocument.theme+xml",
            }
        ),
        "_rels/.rels": _relationships(("rId1", "officeDocument", "ppt/presentation.xml")),
        "ppt/presentation.xml": f'''<p:presentation xmlns:p="{_PRESENTATION}" xmlns:r="{_OFFICE}">
<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>
<p:sldIdLst><p:sldId id="256" r:id="rId2"/></p:sldIdLst>
<p:sldSz cx="9144000" cy="6858000" type="screen4x3"/><p:notesSz cx="6858000" cy="9144000"/>
</p:presentation>''',
        "ppt/_rels/presentation.xml.rels": _relationships(
            ("rId1", "slideMaster", "slideMasters/slideMaster1.xml"),
            ("rId2", "slide", "slides/slide1.xml"),
        ),
        "ppt/slides/slide1.xml": f'''<p:sld xmlns:p="{_PRESENTATION}" xmlns:a="{_DRAWING}">
<p:cSld><p:spTree>{_GROUP}<p:sp><p:nvSpPr><p:cNvPr id="2" name="Synthetic marker"/>
<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr><p:spPr><a:xfrm>
<a:off x="914400" y="914400"/><a:ext cx="7315200" cy="1828800"/>
</a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/></p:spPr>
<p:txBody><a:bodyPr wrap="none"/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US" sz="2800">
<a:solidFill><a:srgbClr val="000000"/></a:solidFill><a:latin typeface="Liberation Sans"/>
</a:rPr><a:t>{PPTX_MARKER}</a:t></a:r><a:endParaRPr lang="en-US"/></a:p></p:txBody>
</p:sp></p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>''',
        "ppt/slides/_rels/slide1.xml.rels": _relationships(
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
        ),
        "ppt/slideLayouts/slideLayout1.xml": f'''<p:sldLayout xmlns:p="{_PRESENTATION}"
xmlns:a="{_DRAWING}" type="blank" preserve="1"><p:cSld name="Blank"><p:spTree>{_GROUP}
</p:spTree></p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>''',
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _relationships(
            ("rId1", "slideMaster", "../slideMasters/slideMaster1.xml"),
        ),
        "ppt/slideMasters/slideMaster1.xml": f'''<p:sldMaster xmlns:p="{_PRESENTATION}"
xmlns:a="{_DRAWING}" xmlns:r="{_OFFICE}"><p:cSld><p:bg><p:bgPr><a:solidFill>
<a:srgbClr val="FFFFFF"/></a:solidFill><a:effectLst/></p:bgPr></p:bg><p:spTree>{_GROUP}
</p:spTree></p:cSld><p:clrMap accent1="accent1" accent2="accent2" accent3="accent3"
accent4="accent4" accent5="accent5" accent6="accent6" bg1="lt1" bg2="lt2"
folHlink="folHlink" hlink="hlink" tx1="dk1" tx2="dk2"/>
<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>
<p:txStyles><p:titleStyle/><p:bodyStyle/><p:otherStyle/></p:txStyles></p:sldMaster>''',
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _relationships(
            ("rId1", "slideLayout", "../slideLayouts/slideLayout1.xml"),
            ("rId2", "theme", "../theme/theme1.xml"),
        ),
        "ppt/theme/theme1.xml": _theme(),
    }
    return _package(parts)


def _theme() -> str:
    colors = (
        "dk1",
        "lt1",
        "dk2",
        "lt2",
        "accent1",
        "accent2",
        "accent3",
        "accent4",
        "accent5",
        "accent6",
        "hlink",
        "folHlink",
    )
    scheme = "".join(
        f'<a:{name}><a:srgbClr val="{"FFFFFF" if name.startswith("lt") else "000000"}"/></a:{name}>'
        for name in colors
    )
    font = '<a:latin typeface="Liberation Sans"/><a:ea typeface=""/><a:cs typeface=""/>'
    fill = '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    line = f'<a:ln w="9525" cap="flat" cmpd="sng" algn="ctr">{fill}<a:prstDash val="solid"/></a:ln>'
    return f'''<a:theme xmlns:a="{_DRAWING}" name="Synthetic"><a:themeElements>
<a:clrScheme name="Synthetic">{scheme}</a:clrScheme><a:fontScheme name="Synthetic">
<a:majorFont>{font}</a:majorFont><a:minorFont>{font}</a:minorFont></a:fontScheme>
<a:fmtScheme name="Synthetic"><a:fillStyleLst>{fill * 3}</a:fillStyleLst>
<a:lnStyleLst>{line * 3}</a:lnStyleLst><a:effectStyleLst>
{"<a:effectStyle><a:effectLst/></a:effectStyle>" * 3}</a:effectStyleLst>
<a:bgFillStyleLst>{fill * 3}</a:bgFillStyleLst></a:fmtScheme></a:themeElements></a:theme>'''


def make_synthetic_xlsx() -> bytes:
    """One worksheet/cell with inline text and an explicit one-page A4 print area."""
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml."
    return _package(
        {
            "[Content_Types].xml": _content_types(
                {
                    "xl/workbook.xml": mime + "sheet.main+xml",
                    "xl/worksheets/sheet1.xml": mime + "worksheet+xml",
                    "xl/styles.xml": mime + "styles+xml",
                }
            ),
            "_rels/.rels": _relationships(("rId1", "officeDocument", "xl/workbook.xml")),
            "xl/workbook.xml": f'''<workbook xmlns="{_SHEET}" xmlns:r="{_OFFICE}">
<bookViews><workbookView/></bookViews><sheets><sheet name="Smoke" sheetId="1" r:id="rId1"/>
</sheets><definedNames><definedName name="_xlnm.Print_Area" localSheetId="0">
'Smoke'!$A$1:$A$1</definedName></definedNames></workbook>''',
            "xl/_rels/workbook.xml.rels": _relationships(
                ("rId1", "worksheet", "worksheets/sheet1.xml"),
                ("rId2", "styles", "styles.xml"),
            ),
            "xl/worksheets/sheet1.xml": f'''<worksheet xmlns="{_SHEET}">
<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr><dimension ref="A1"/>
<sheetViews><sheetView workbookViewId="0"/></sheetViews><sheetFormatPr defaultRowHeight="15"/>
<cols><col min="1" max="1" width="60" customWidth="1"/></cols>
<sheetData><row r="1" ht="30" customHeight="1"><c r="A1" s="1" t="inlineStr">
<is><t>{XLSX_MARKER}</t></is></c></row></sheetData><printOptions gridLines="0"/>
<pageMargins left="0.5" right="0.5" top="0.5" bottom="0.5" header="0" footer="0"/>
<pageSetup paperSize="9" orientation="portrait" fitToWidth="1" fitToHeight="1"/>
</worksheet>''',
            "xl/styles.xml": f'''<styleSheet xmlns="{_SHEET}"><fonts count="2">
<font><sz val="11"/><name val="Liberation Sans"/></font>
<font><sz val="18"/><name val="Liberation Sans"/></font></fonts><fills count="2">
<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
</fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>''',
        }
    )


def make_synthetic_scanned_pdf() -> bytes:
    """Two image-only pages at 200 DPI, with large built-in Pillow font markers."""
    pages = []
    try:
        for marker, (width, height) in zip(SCAN_MARKERS, SCAN_PAGE_SIZES, strict=True):
            image = Image.new("RGB", (width * 200 // 72, height * 200 // 72), "white")
            pages.append(image)
            ImageDraw.Draw(image).multiline_text(
                (70, 80),
                f"DOCUFORGE\n{marker}\nSCANNED PAGE",
                fill="black",
                font=ImageFont.load_default(size=72),
                spacing=36,
            )
        buffer = BytesIO()
        pages[0].save(
            buffer,
            format="PDF",
            save_all=True,
            append_images=pages[1:],
            resolution=200,
            quality=95,
            creationDate=gmtime(0),
            modDate=gmtime(0),
        )
        return buffer.getvalue()
    finally:
        for image in pages:
            image.close()
