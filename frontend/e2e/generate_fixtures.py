"""Generate tiny deterministic documents used by Playwright browser tests."""

import sys
from pathlib import Path

from PIL import Image
from pypdf import PdfWriter


def _write_pdf(path: Path, *widths: int) -> None:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=width + 100)
    with path.open("wb") as output:
        writer.write(output)
    writer.close()


def _write_image(
    path: Path,
    *,
    size: tuple[int, int],
    base: tuple[int, int, int],
    image_format: str = "PNG",
) -> None:
    image = Image.new("RGB", size)
    for y in range(size[1]):
        for x in range(size[0]):
            image.putpixel(
                (x, y),
                (
                    (base[0] + x * 3 + y) % 256,
                    (base[1] + x + y * 5) % 256,
                    (base[2] + x * 2 + y * 2) % 256,
                ),
            )
    image.save(path, format=image_format, quality=92)
    image.close()


def main(output_directory: str) -> None:
    root = Path(output_directory)
    root.mkdir(parents=True, exist_ok=False)

    _write_pdf(root / "one-a.pdf", 120)
    _write_pdf(root / "one-b.pdf", 240)
    _write_pdf(root / "three-pages.pdf", 100, 200, 300)
    _write_image(root / "source.png", size=(160, 90), base=(10, 60, 120))
    _write_image(root / "portrait.png", size=(80, 120), base=(180, 20, 20))
    _write_image(root / "landscape.png", size=(160, 80), base=(20, 20, 180))
    _write_image(
        root / "compressible.jpg",
        size=(320, 200),
        base=(40, 90, 140),
        image_format="JPEG",
    )
    (root / "corrupt.png").write_bytes(b"not a valid raster image")
    (root / "corrupt.pdf").write_bytes(b"not a valid PDF document")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: generate_fixtures.py OUTPUT_DIRECTORY")
    main(sys.argv[1])
