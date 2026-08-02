"""Dispatch parsed command-line arguments to command implementations."""

import sys
from argparse import Namespace

from docuforge.cli.commands.pdf_merge import run_pdf_merge

PLACEHOLDER_EXIT_CODE = 2


def dispatch(arguments: Namespace) -> int:
    """Run the command selected by parsed arguments."""
    if getattr(arguments, "command_handler", None) == "pdf_merge":
        input_paths = (arguments.first_input, *arguments.input_paths)
        return run_pdf_merge(input_paths, arguments.output_path)

    command_path = arguments.command_path
    print(
        f"docuforge {command_path}: command execution will be added in a later commit",
        file=sys.stderr,
    )
    return PLACEHOLDER_EXIT_CODE
