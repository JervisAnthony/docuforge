"""Argument parser construction for the DocuForge command-line interface."""

import re
from argparse import Action, ArgumentError, ArgumentParser, ArgumentTypeError, Namespace
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from docuforge.converters import PageRotation

DEVELOPMENT_VERSION = "0.1.0.dev0"
ROTATION_SYNTAX_ERROR = (
    "rotation must use PAGE:DEGREES with PAGE >= 1 and DEGREES one of "
    "90, 180, or 270"
)
PAGE_NUMBER_ERROR = "page must be a positive one-based integer"


def parse_positive_page(value: str) -> int:
    """Parse one positive, one-based CLI page number."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+", value) is None:
        raise ArgumentTypeError(PAGE_NUMBER_ERROR)

    page_number = int(value)
    if page_number < 1:
        raise ArgumentTypeError(PAGE_NUMBER_ERROR)

    return page_number


def parse_page_rotation(value: str) -> PageRotation:
    """Parse one one-based CLI rotation into a zero-based instruction."""
    if not isinstance(value, str) or re.fullmatch(r"[0-9]+:[0-9]+", value) is None:
        raise ArgumentTypeError(ROTATION_SYNTAX_ERROR)

    page_text, degrees_text = value.split(":")
    page_number = int(page_text)
    degrees = int(degrees_text)
    if page_number < 1 or degrees not in {90, 180, 270}:
        raise ArgumentTypeError(ROTATION_SYNTAX_ERROR)

    return PageRotation(page_index=page_number - 1, degrees=degrees)


class _AppendUniquePageRotation(Action):
    """Append rotations in CLI order while rejecting repeated pages."""

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: PageRotation,
        option_string: str | None = None,
    ) -> None:
        rotations = getattr(namespace, self.dest, None)
        if rotations is not None and any(
            rotation.page_index == values.page_index for rotation in rotations
        ):
            raise ArgumentError(
                self,
                f"each page may be rotated only once: {values.page_index + 1}",
            )

        ordered_rotations = [] if rotations is None else [*rotations]
        ordered_rotations.append(values)
        setattr(namespace, self.dest, ordered_rotations)


class _AppendUniquePage(Action):
    """Append one-based pages in CLI order while rejecting duplicates."""

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: int,
        option_string: str | None = None,
    ) -> None:
        pages = getattr(namespace, self.dest, None)
        if pages is not None and values in pages:
            raise ArgumentError(self, f"Each page may be removed only once: {values}")

        ordered_pages = [] if pages is None else [*pages]
        ordered_pages.append(values)
        setattr(namespace, self.dest, ordered_pages)


class _AppendUniqueExtractPage(Action):
    """Append extraction pages in CLI order while rejecting duplicates."""

    def __call__(
        self,
        parser: ArgumentParser,
        namespace: Namespace,
        values: int,
        option_string: str | None = None,
    ) -> None:
        pages = getattr(namespace, self.dest, None)
        if pages is not None and values in pages:
            raise ArgumentError(self, f"Each page may be extracted only once: {values}")

        ordered_pages = [] if pages is None else [*pages]
        ordered_pages.append(values)
        setattr(namespace, self.dest, ordered_pages)


def package_version() -> str:
    """Return the installed package version or the source-tree development version."""
    try:
        return version("docuforge")
    except PackageNotFoundError:
        return DEVELOPMENT_VERSION


def build_parser() -> ArgumentParser:
    """Build and return the DocuForge command-line parser."""
    parser = ArgumentParser(
        prog="docuforge",
        description="Convert and compose documents from the command line.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {package_version()}",
    )

    commands = parser.add_subparsers(dest="command", title="commands")

    pdf_parser = commands.add_parser("pdf", help="Work with PDF documents.")
    pdf_commands = pdf_parser.add_subparsers(dest="pdf_command", required=True)

    merge_parser = pdf_commands.add_parser(
        "merge",
        help="Merge PDF documents.",
        description="Merge two or more PDF documents in input order.",
    )
    merge_parser.add_argument(
        "first_input",
        type=Path,
        metavar="INPUT",
        help="First input PDF path.",
    )
    merge_parser.add_argument(
        "input_paths",
        type=Path,
        nargs="+",
        metavar="INPUT",
        help="Second and additional input PDF paths.",
    )
    merge_parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        required=True,
        metavar="OUTPUT",
        help="Destination PDF path.",
    )
    merge_parser.set_defaults(command_handler="pdf_merge")

    split_parser = pdf_commands.add_parser(
        "split",
        help="Split a PDF document.",
        description="Split a PDF into one output file per page.",
    )
    split_parser.add_argument(
        "input_path",
        type=Path,
        metavar="INPUT",
        help="Input PDF path.",
    )
    split_parser.add_argument(
        "-o",
        "--output-dir",
        dest="output_directory",
        type=Path,
        required=True,
        metavar="OUTPUT_DIR",
        help="Destination directory for split PDF files.",
    )
    split_parser.set_defaults(command_handler="pdf_split")

    rotate_parser = pdf_commands.add_parser(
        "rotate",
        help="Rotate selected PDF pages.",
        description=(
            "Rotate selected pages using one-based page numbers and clockwise "
            "degrees 90, 180, or 270. Repeat --rotate for additional pages."
        ),
    )
    rotate_parser.add_argument(
        "input_path",
        type=Path,
        metavar="INPUT",
        help="Input PDF path.",
    )
    rotate_parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        required=True,
        metavar="OUTPUT",
        help="Destination PDF path.",
    )
    rotate_parser.add_argument(
        "--rotate",
        dest="rotations",
        type=parse_page_rotation,
        action=_AppendUniquePageRotation,
        required=True,
        metavar="PAGE:DEGREES",
        help=(
            "Rotate one one-based PAGE clockwise by 90, 180, or 270 degrees; "
            "repeat for additional pages."
        ),
    )
    rotate_parser.set_defaults(command_handler="pdf_rotate")

    remove_pages_parser = pdf_commands.add_parser(
        "remove-pages",
        help="Remove selected PDF pages.",
        description=(
            "Remove selected pages using one-based page numbers. "
            "Repeat --page for additional pages."
        ),
    )
    remove_pages_parser.add_argument(
        "input_path",
        type=Path,
        metavar="INPUT",
        help="Input PDF path.",
    )
    remove_pages_parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        required=True,
        metavar="OUTPUT",
        help="Destination PDF path.",
    )
    remove_pages_parser.add_argument(
        "--page",
        dest="pages",
        type=parse_positive_page,
        action=_AppendUniquePage,
        required=True,
        metavar="PAGE",
        help="Remove one one-based PAGE; repeat for additional pages.",
    )
    remove_pages_parser.set_defaults(command_handler="pdf_remove_pages")

    extract_pages_parser = pdf_commands.add_parser(
        "extract-pages",
        help="Extract selected PDF pages.",
        description=(
            "Extract selected pages in request order using one-based page numbers. "
            "Repeat --page for additional pages."
        ),
    )
    extract_pages_parser.add_argument(
        "input_path",
        type=Path,
        metavar="INPUT",
        help="Input PDF path.",
    )
    extract_pages_parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        required=True,
        metavar="OUTPUT",
        help="Destination PDF path.",
    )
    extract_pages_parser.add_argument(
        "--page",
        dest="pages",
        type=parse_positive_page,
        action=_AppendUniqueExtractPage,
        required=True,
        metavar="PAGE",
        help="Extract one one-based PAGE; repeat in the desired output order.",
    )
    extract_pages_parser.set_defaults(command_handler="pdf_extract_pages")

    image_parser = commands.add_parser("image", help="Work with image documents.")
    image_commands = image_parser.add_subparsers(dest="image_command", required=True)

    to_pdf_parser = image_commands.add_parser(
        "to-pdf",
        help="Combine images into a PDF document.",
        description="Combine one or more ordered image files into a PDF document.",
    )
    to_pdf_parser.add_argument(
        "input_paths",
        type=Path,
        nargs="+",
        metavar="INPUT",
        help="Input image paths in PDF page order.",
    )
    to_pdf_parser.add_argument(
        "-o",
        "--output",
        dest="output_path",
        type=Path,
        required=True,
        metavar="OUTPUT",
        help="Destination PDF path.",
    )
    to_pdf_parser.set_defaults(command_handler="image_to_pdf")

    return parser
