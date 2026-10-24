from __future__ import annotations

import argparse
import csv
import logging
import sys
import warnings
from datetime import date
from pathlib import Path

from quant_dashboard.db import SessionLocal
from quant_dashboard.models import RunStatus

from .service import SecuritySpec, ensure_securities, execute_run, plan_run
from .yahoo import YahooSource

# Filter pandas 3.x deprecation warning
warnings.filterwarnings("ignore", module=r"yfinance\..")


def load_universe(path: Path) -> list[SecuritySpec]:
    with path.open(newline="") as f:
        return [
            SecuritySpec(
                ticker=row["ticker"].strip(),
                mic=row["mic"].strip(),
                currency=row["currency"].strip(),
                name=(row.get("name") or "").strip() or None,
            )
            for row in csv.DictReader(f)
        ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest daily prices")
    parser.add_argument("--universe", type=Path, default=Path("data/universe.csv"))
    parser.add_argument("--start", type=date.fromisoformat, default=date(2015, 1, 1))
    parser.add_argument("--overlap-days", type=int, default=7)
    parser.add_argument("--resume", type=int, metavar="RUN_ID", help="retry unfinished items")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    source = YahooSource()

    with SessionLocal() as session:
        if args.resume is not None:
            run_id = args.resume
        else:
            securities = ensure_securities(session, load_universe(args.universe))
            run_id = plan_run(
                session,
                source_name=source.name,
                securities=securities,
                default_start=args.start,
                end=date.today(),
                overlap_days=args.overlap_days,
            )
        status = execute_run(session, source, run_id)

    print(f"run {run_id}: {status.value}")
    return 0 if status is RunStatus.SUCCEEDED else 1


if __name__ == "__main__":
    sys.exit(main())
