"""Package entry point for the staged command-line interface."""

import sys
from collections.abc import Sequence

from trade_plan_monitor.cli import main as run_cli


def main(argv: Sequence[str] = ()) -> int:
    """Run the inert CLI skeleton with explicitly supplied arguments."""

    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
