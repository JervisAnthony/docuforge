"""Dispatch parsed command-line arguments to command implementations."""

import sys
from argparse import Namespace

from docuforge.cli.commands.pdf_merge import run_pdf_merge
from docuforge.cli.commands.pdf_split import run_pdf_split

PLACEHOLDER_EXIT_CODE = 2


def dispatch(arguments: Namespace) -> int:
    """Run the command selected by parsed arguments."""
    command_handler = getattr(arguments, "command_handler", None)
    if command_handler == "pdf_merge":
        input_paths = (arguments.first_input, *arguments.input_paths)
        return run_pdf_merge(input_paths, arguments.output_path)
    if command_handler == "pdf_split":
        return run_pdf_split(arguments.input_path, arguments.output_directory)

    command_path = arguments.command_path
    print(
        f"docuforge {command_path}: command execution will be added in a later commit",
        file=sys.stderr,
    )
    return PLACEHOLDER_EXIT_CODE
