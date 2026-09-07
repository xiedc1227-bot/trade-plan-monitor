"""Run stock or board-index live certification from local configuration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trade_plan_monitor.live_certification import (
    LiveCertificationSurface,
    launch_live_certification,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("surface", choices=("stock", "index"))
    parser.add_argument("--authorize", required=True)
    parser.add_argument("--config", type=Path, default=Path("config/app.yaml"))
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
            config_path=arguments.config,
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
