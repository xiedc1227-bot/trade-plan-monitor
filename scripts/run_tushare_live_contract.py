"""Secret-blind parent launcher for stock or board-index live certification."""

from __future__ import annotations

import argparse
import json

from trade_plan_monitor.live_certification import (
    DEFAULT_CREDENTIAL_TARGET,
    LiveCertificationSurface,
    launch_live_certification,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("surface", choices=("stock", "index"))
    parser.add_argument("--authorize", required=True)
    parser.add_argument("--credential-target", default=DEFAULT_CREDENTIAL_TARGET)
    arguments = parser.parse_args()
    surface = (
        LiveCertificationSurface.STOCK
        if arguments.surface == "stock"
        else LiveCertificationSurface.BOARD_INDEX
    )
    try:
        result = launch_live_certification(
            surface=surface,
            authorization=arguments.authorize,
            credential_target=arguments.credential_target,
        )
    except ValueError:
        print(
            json.dumps(
                {"outcome": "NOT_RUN_UNAUTHORIZED", "surface": surface.value},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
        return 2
    if result.outcome != "COMPLETED":
        print(
            json.dumps(
                {"outcome": result.outcome, "surface": surface.value},
                ensure_ascii=True,
                sort_keys=True,
            )
        )
    return result.return_code


if __name__ == "__main__":
    raise SystemExit(main())
