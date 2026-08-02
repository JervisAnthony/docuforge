from collections.abc import Sequence

from docuforge.cli.dispatch import dispatch
from docuforge.cli.parser import build_parser


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

    return dispatch(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
