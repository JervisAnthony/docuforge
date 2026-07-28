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
