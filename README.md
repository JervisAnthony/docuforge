# DocuForge

DocuForge is a consumer-focused document conversion toolkit designed to make common document operations fast, private, and reliable.

## Vision

Build a modular platform for converting, merging, splitting, and optimizing documents across PDF, image, and office formats.

## Planned interfaces

- Command-line interface
- REST API
- Web application
- Desktop application

## Project status

DocuForge is in active development. The first milestone establishes the repository architecture, engineering standards, and product roadmap.

## Quick start

```bash
python -m docuforge
```

Expected output:

```text
DocuForge development build
```

## Command-line usage

PDF merge, PDF split, and image-to-PDF commands perform real conversion. Combine
one or more ordered image files into a PDF with:

```bash
docuforge image to-pdf cover.jpg diagram.png --output document.pdf
```

The `-o` and `--output` options select the destination PDF. Supported inputs are
JPG, JPEG, PNG, BMP, TIF, and TIFF files, and their command-line order determines
the PDF page order. The output filename must use the `.pdf` extension.

Rotate selected PDF pages with one-based page numbers:

```bash
docuforge pdf rotate source.pdf --output rotated.pdf --rotate 1:90 --rotate 3:270
```

The repeatable `--rotate` option supports clockwise rotations of 90, 180, and
270 degrees. Selected pages rotate while every page remains in source order. The
output must use the `.pdf` extension, and missing output directories are not
created.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Repository layout

```text
src/docuforge/       Application source
 tests/               Automated tests
 docs/                Product and engineering documentation
 .github/workflows/   Continuous integration workflows
```

## Roadmap

See [docs/ROADMAP.md](docs/ROADMAP.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Licensed under the MIT License. See [LICENSE](LICENSE).
