"""Small synthetic-PDF helpers shared by API route tests."""

from io import BytesIO

from pypdf import PdfReader, PdfWriter


def make_pdf(*widths: int, encrypted: bool = False) -> bytes:
    """Build a small PDF whose page widths make ordering observable."""
    output = BytesIO()
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=width + 100)
    if encrypted:
        writer.encrypt("secret")
    writer.write(output)
    writer.close()
    return output.getvalue()


def page_widths(pdf_bytes: bytes) -> list[int]:
    """Return integer page widths from one generated response PDF."""
    reader = PdfReader(BytesIO(pdf_bytes), strict=True)
    return [int(page.mediabox.width) for page in reader.pages]


def page_rotations(pdf_bytes: bytes) -> list[int]:
    """Return normalized clockwise rotations from one response PDF."""
    reader = PdfReader(BytesIO(pdf_bytes), strict=True)
    return [int(page.get("/Rotate", 0)) % 360 for page in reader.pages]
