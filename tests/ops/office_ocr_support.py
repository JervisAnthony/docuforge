"""Parseable synthetic PDF/text engine doubles; never real OCR/rendering evidence."""

from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from docuforge.converters.ocr import OcrEngineResult
from docuforge.converters.office import OfficeConversionResult
from docuforge.core import DocumentFormat
from docuforge.ops.smoke_fixtures import SCAN_MARKERS


def text_pdf(*pages: tuple[float, float, str]) -> bytes:
    """Make real PDF text objects with the built-in Helvetica font, for doubles."""
    writer = PdfWriter()
    for width, height, text in pages:
        page = writer.add_blank_page(width=width, height=height)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {
                        NameObject("/F1"): DictionaryObject(
                            {
                                NameObject("/Type"): NameObject("/Font"),
                                NameObject("/Subtype"): NameObject("/Type1"),
                                NameObject("/BaseFont"): NameObject("/Helvetica"),
                            }
                        )
                    }
                ),
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 18 Tf 20 80 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TextOfficeEngine:
    def __init__(self):
        self.workspaces = []

    def convert_to_pdf(self, request):
        self.workspaces.append(request.input_path.parent)
        with ZipFile(request.input_path) as archive:
            if request.input_path.suffix == ".pptx":
                root = ElementTree.fromstring(archive.read("ppt/slides/slide1.xml"))
            else:
                root = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            marker = " ".join(
                node.text for node in root.iter() if node.tag.endswith("}t") and node.text
            )
        output = request.output_directory / "office.pdf"
        output.write_bytes(text_pdf((720, 540, marker)))
        return OfficeConversionResult(
            request.input_path,
            output,
            DocumentFormat.normalize(request.input_path.suffix[1:]),
        )


class TextOcrEngine:
    def __init__(self):
        self.workspaces = []

    def recognize(self, request):
        self.workspaces.append(request.input_path.parent)
        index = int(request.input_path.stem.rsplit("-", 1)[1]) - 1
        marker = SCAN_MARKERS[index]
        output = request.output_directory / f"recognized.{request.output_format.value}"
        if request.output_format is DocumentFormat.TXT:
            output.write_bytes((marker + "\n").encode())
        else:
            with Image.open(request.input_path) as image:
                width, height = image.size
            output.write_bytes(
                text_pdf((width * 72 / request.dpi, height * 72 / request.dpi, marker))
            )
        return OcrEngineResult(
            request.input_path,
            output,
            request.output_format,
            request.language,
            request.dpi,
        )
