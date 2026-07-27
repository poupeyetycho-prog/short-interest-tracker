"""One-shot data pipeline: download FINRA short interest, then enrich with yfinance.

Usage:
    python pipeline.py                 # ingest FINRA + enrich 300 top names
    python pipeline.py --enrich 1000   # ingest + enrich 1000
    python pipeline.py --ingest-only   # just refresh the FINRA data
    python pipeline.py --enrich-only 500
"""
import argparse

from db import init_db
from enrich import enrich
from finra import ingest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--enrich", type=int, default=300, help="how many stocks to enrich")
    ap.add_argument("--ingest-only", action="store_true")
    ap.add_argument("--enrich-only", type=int, default=None)
    args = ap.parse_args()

    init_db()

    if args.enrich_only is not None:
        print("Enriching...", enrich(limit=args.enrich_only))
        return

    print("Ingesting FINRA short interest...")
    print(ingest())
    if not args.ingest_only:
        print(f"Enriching top {args.enrich} names via yfinance...")
        print(enrich(limit=args.enrich))


if __name__ == "__main__":
    main()
