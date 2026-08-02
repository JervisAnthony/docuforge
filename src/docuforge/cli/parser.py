"""Argument parser construction for the DocuForge command-line interface."""

from argparse import ArgumentParser
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEVELOPMENT_VERSION = "0.1.0.dev0"


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

    image_parser = commands.add_parser("image", help="Work with image documents.")
    image_commands = image_parser.add_subparsers(dest="image_command", required=True)

    to_pdf_parser = image_commands.add_parser(
        "to-pdf",
        help="Combine images into a PDF document.",
    )
    to_pdf_parser.set_defaults(command_path="image to-pdf")

    return parser
