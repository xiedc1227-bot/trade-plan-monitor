"""Explicit, bounded rebuild of disposable review metadata in a chosen result store."""

import argparse
import json
import re
from pathlib import Path

from trade_plan_monitor.backtest.results import BacktestResultStore
from trade_plan_monitor.backtest.review import rebuild_review_batch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--after")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if not Path(args.database).is_file():
        parser.error("database must be an existing result database")
    if re.fullmatch(r"[0-9a-f]{64}", args.run_id) is None:
        parser.error("run-id must be 64 lowercase hexadecimal characters")
    store = BacktestResultStore(args.database)
    after = rebuild_review_batch(store, args.run_id, after=args.after, limit=args.limit)
    print(json.dumps({"nextAfter": after, "hasMore": after is not None}))


if __name__ == "__main__":
    main()
