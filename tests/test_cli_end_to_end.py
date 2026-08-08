"""End-to-end smoke coverage for every supported conversion CLI workflow."""

from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

from docuforge.__main__ import main

FIVE_PAGE_SIZES = (
    (100, 200),
    (200, 300),
    (300, 400),
    (400, 500),
    (500, 600),
)


def _write_pdf(path: Path, page_sizes: tuple[tuple[int, int], ...]) -> None:
    writer = PdfWriter()
    try:
        for width, height in page_sizes:
            writer.add_blank_page(width=width, height=height)
        writer.write(path)
    finally:
        writer.close()


def _write_image(path: Path, size: tuple[int, int], image_format: str) -> None:
    image = Image.new("RGB", size, "white")
    try:
        image.save(path, format=image_format)
    finally:
        image.close()


def _page_metadata(path: Path) -> list[tuple[int, int, int]]:
    return [
        (
            int(page.mediabox.width),
            int(page.mediabox.height),
            page.rotation,
        )
        for page in PdfReader(path, strict=True).pages
    ]


def _page_sizes(path: Path) -> list[tuple[int, int]]:
    return [(width, height) for width, height, _ in _page_metadata(path)]


def test_pdf_merge_cli_combines_real_sources_in_input_order(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    output = tmp_path / "merged.pdf"
    _write_pdf(first, ((100, 200), (200, 300)))
    _write_pdf(second, ((300, 400), (400, 500)))
    sources_before = (first.read_bytes(), second.read_bytes())

    result = main(["pdf", "merge", str(first), str(second), "-o", str(output)])

    assert result == 0
    assert output.is_file()
    assert _page_sizes(output) == [
        (100, 200),
        (200, 300),
        (300, 400),
        (400, 500),
    ]
    assert (first.read_bytes(), second.read_bytes()) == sources_before


def test_pdf_split_cli_writes_one_ordered_real_pdf_per_page(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output_directory = tmp_path / "pages"
    _write_pdf(source, ((100, 200), (200, 300), (300, 400)))
    source_before = source.read_bytes()

    result = main(
        ["pdf", "split", str(source), "--output-dir", str(output_directory)]
    )

    outputs = [
        output_directory / f"source-page-{page_number:04d}.pdf"
        for page_number in range(1, 4)
    ]
    assert result == 0
    assert sorted(output_directory.iterdir()) == outputs
    assert [_page_sizes(path) for path in outputs] == [
        [(100, 200)],
        [(200, 300)],
        [(300, 400)],
    ]
    assert source.read_bytes() == source_before


def test_pdf_rotate_cli_changes_only_selected_page_rotation(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "rotated.pdf"
    _write_pdf(source, ((100, 200), (300, 400), (500, 600)))
    source_before = source.read_bytes()

    result = main(
        [
            "pdf",
            "rotate",
            str(source),
            "-o",
            str(output),
            "--rotate",
            "2:90",
        ]
    )

    assert result == 0
    assert output.is_file()
    assert _page_metadata(output) == [
        (100, 200, 0),
        (300, 400, 90),
        (500, 600, 0),
    ]
    assert source.read_bytes() == source_before
    assert _page_metadata(source) == [
        (100, 200, 0),
        (300, 400, 0),
        (500, 600, 0),
    ]


def test_pdf_remove_pages_cli_retains_source_order(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "trimmed.pdf"
    _write_pdf(source, FIVE_PAGE_SIZES)
    source_before = source.read_bytes()

    result = main(
        [
            "pdf",
            "remove-pages",
            str(source),
            "-o",
            str(output),
            "--page",
            "4",
            "--page",
            "2",
        ]
    )

    assert result == 0
    assert output.is_file()
    assert _page_sizes(output) == [(100, 200), (300, 400), (500, 600)]
    assert source.read_bytes() == source_before


def test_pdf_extract_pages_cli_preserves_user_request_order(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "selected.pdf"
    _write_pdf(source, FIVE_PAGE_SIZES)
    source_before = source.read_bytes()

    result = main(
        [
            "pdf",
            "extract-pages",
            str(source),
            "-o",
            str(output),
            "--page",
            "4",
            "--page",
            "2",
            "--page",
            "5",
        ]
    )

    assert result == 0
    assert output.is_file()
    assert _page_sizes(output) == [(400, 500), (200, 300), (500, 600)]
    assert source.read_bytes() == source_before


def test_image_to_pdf_cli_preserves_real_image_order(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.jpg"
    third = tmp_path / "third.bmp"
    output = tmp_path / "images.pdf"
    _write_image(first, (10, 20), "PNG")
    _write_image(second, (30, 40), "JPEG")
    _write_image(third, (50, 60), "BMP")
    sources_before = tuple(path.read_bytes() for path in (first, second, third))

    result = main(
        [
            "image",
            "to-pdf",
            str(first),
            str(second),
            str(third),
            "-o",
            str(output),
        ]
    )

    assert result == 0
    assert output.is_file()
    assert _page_sizes(output) == [(10, 20), (30, 40), (50, 60)]
    assert tuple(path.read_bytes() for path in (first, second, third)) == sources_before


def test_pdf_cli_outputs_chain_through_merge_remove_and_extract(tmp_path: Path) -> None:
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    merged = tmp_path / "merged.pdf"
    trimmed = tmp_path / "trimmed.pdf"
    selected = tmp_path / "selected.pdf"
    _write_pdf(first, ((100, 200), (200, 300)))
    _write_pdf(second, ((300, 400), (400, 500), (500, 600)))
    sources_before = (first.read_bytes(), second.read_bytes())

    assert main(["pdf", "merge", str(first), str(second), "-o", str(merged)]) == 0
    assert _page_sizes(merged) == list(FIVE_PAGE_SIZES)
    assert main(
        [
            "pdf",
            "remove-pages",
            str(merged),
            "-o",
            str(trimmed),
            "--page",
            "2",
            "--page",
            "4",
        ]
    ) == 0
    assert _page_sizes(trimmed) == [(100, 200), (300, 400), (500, 600)]
    assert main(
        [
            "pdf",
            "extract-pages",
            str(trimmed),
            "-o",
            str(selected),
            "--page",
            "3",
            "--page",
            "1",
        ]
    ) == 0

    assert _page_sizes(selected) == [(500, 600), (100, 200)]
    assert (first.read_bytes(), second.read_bytes()) == sources_before


def test_cli_structural_failure_returns_two() -> None:
    assert main(["pdf", "merge"]) == 2


def test_cli_operational_failure_returns_one(tmp_path: Path) -> None:
    assert main(
        [
            "pdf",
            "split",
            str(tmp_path / "missing.pdf"),
            "-o",
            str(tmp_path / "pages"),
        ]
    ) == 1
    assert not (tmp_path / "pages").exists()
