import sys
from collections.abc import Sequence

from docuforge.cli.parser import build_parser

PLACEHOLDER_EXIT_CODE = 2


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DocuForge command-line interface and return its exit code."""
    parser = build_parser()

    try:
        arguments = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)

    if arguments.command is None:
        parser.print_help()
        return 0

    command_path = arguments.command_path
    print(
        f"docuforge {command_path}: command execution will be added in a later commit",
        file=sys.stderr,
    )
    return PLACEHOLDER_EXIT_CODE


if __name__ == "__main__":
    raise SystemExit(main())
