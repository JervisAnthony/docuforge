"""Small deterministic raster helpers shared by image API tests."""

from io import BytesIO

from PIL import Image


def make_image(
    image_format: str = "PNG",
    *,
    size: tuple[int, int] = (120, 80),
    mode: str = "RGB",
) -> bytes:
    """Return a deterministic textured image in the requested format."""
    image = Image.new(mode, size)
    for y in range(size[1]):
        for x in range(size[0]):
            if mode == "RGBA":
                color: int | tuple[int, ...] = (
                    x * 17 % 256,
                    y * 23 % 256,
                    (x + y) * 11 % 256,
                    96,
                )
            else:
                color = (x * 17 % 256, y * 23 % 256, (x + y) * 11 % 256)
            image.putpixel((x, y), color)
    output = BytesIO()
    image.save(output, format=image_format)
    image.close()
    return output.getvalue()


def inspect_image(content: bytes) -> tuple[str | None, tuple[int, int], str]:
    """Fully decode response image content and return observable identity."""
    with Image.open(BytesIO(content)) as image:
        image.load()
        return image.format, image.size, image.mode
