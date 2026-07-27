"""Enrich stocks with yfinance fundamentals and compute the short % of float ranking metric.

Float is not in the FINRA file, so it must be fetched per-symbol. That is rate-limited,
so enrichment is prioritized (largest short positions first) and bounded by a limit.
Results persist in the DB, so re-running expands coverage over time.
"""
import time
from datetime import datetime, timedelta

from sqlalchemy import or_

from config import ENRICH_SLEEP_SECONDS, ENRICH_TTL_HOURS
from db import SessionLocal, Stock, set_meta
from market_data import get_fundamentals


def _compute_metrics(stock: Stock):
    si = stock.short_interest
    if si and stock.float_shares:
        stock.short_pct_float = round(si / stock.float_shares * 100, 2)
    else:
        stock.short_pct_float = None
    if si and stock.shares_outstanding:
        stock.short_pct_outstanding = round(si / stock.shares_outstanding * 100, 2)
    else:
        stock.short_pct_outstanding = None


def enrich(limit: int = 300, force: bool = False) -> dict:
    """Fetch fundamentals for up to `limit` stocks that need it, then compute metrics.

    Prioritizes never-enriched / stale rows, ordered by short-interest size so the
    most-shorted names get float data first. Returns a summary dict.
    """
    session = SessionLocal()
    updated, failed = 0, 0
    try:
        q = session.query(Stock)
        if not force:
            stale_before = datetime.utcnow() - timedelta(hours=ENRICH_TTL_HOURS)
            q = q.filter(or_(Stock.enriched_at.is_(None), Stock.enriched_at < stale_before))
        stocks = (
            q.order_by(Stock.short_interest.desc().nullslast())
            .limit(limit)
            .all()
        )

        for stock in stocks:
            try:
                data = get_fundamentals(stock.symbol)
                stock.float_shares = data["float_shares"]
                stock.shares_outstanding = data["shares_outstanding"]
                stock.market_cap = data["market_cap"]
                stock.last_close = data["last_close"]
                stock.last_volume = data["last_volume"]
                stock.dollar_volume = data["dollar_volume"]
                stock.enriched_at = datetime.utcnow()
                _compute_metrics(stock)
                updated += 1
            except Exception:
                failed += 1
            finally:
                time.sleep(ENRICH_SLEEP_SECONDS)

            if updated % 25 == 0:
                session.commit()

        set_meta(session, "last_enrich_at", datetime.utcnow().isoformat())
        session.commit()
    finally:
        session.close()

    return {"enriched": updated, "failed": failed, "requested": limit}


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    print(enrich(limit=n))
