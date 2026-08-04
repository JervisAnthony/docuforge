"""Dispatch parsed command-line arguments to command implementations."""

from argparse import Namespace

from docuforge.cli.commands.image_to_pdf import run_image_to_pdf
from docuforge.cli.commands.pdf_merge import run_pdf_merge
from docuforge.cli.commands.pdf_split import run_pdf_split


def dispatch(arguments: Namespace) -> int:
    """Run the command selected by parsed arguments."""
    command_handler = getattr(arguments, "command_handler", None)
    if command_handler == "pdf_merge":
        input_paths = (arguments.first_input, *arguments.input_paths)
        return run_pdf_merge(input_paths, arguments.output_path)
    if command_handler == "pdf_split":
        return run_pdf_split(arguments.input_path, arguments.output_directory)
    if command_handler == "image_to_pdf":
        return run_image_to_pdf(arguments.input_paths, arguments.output_path)

    raise ValueError("parsed arguments do not identify a command handler")
