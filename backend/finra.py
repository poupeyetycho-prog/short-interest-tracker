"""Download and parse the official FINRA bi-monthly short-interest file."""
import io
from datetime import date, datetime, timedelta

import pandas as pd
import requests

from config import EXCHANGE_LISTED_CLASSES, EXCHANGE_NAMES, FINRA_CDN_BASE
from db import SessionLocal, Stock, init_db, set_meta

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 short-interest-app"


def _candidate_dates(today: date | None = None):
    """FINRA settlement dates are the 15th and last day of each month.
    Generate candidates (newest first) for the last few months to probe the CDN."""
    today = today or date.today()
    cands = []
    for months_back in range(0, 4):
        y = today.year
        m = today.month - months_back
        while m <= 0:
            m += 12
            y -= 1
        # last day of month
        if m == 12:
            last = date(y, 12, 31)
        else:
            last = date(y, m + 1, 1) - timedelta(days=1)
        mid = date(y, m, 15)
        cands.extend([last, mid])
    # newest first, and only dates that are actually in the past
    cands = sorted({d for d in cands if d <= today}, reverse=True)
    return cands


def find_latest_file(today: date | None = None):
    """Probe the FINRA CDN for the most recent available settlement file.

    Settlement dates snap back to a business day, so each nominal date is walked
    backwards a few days before giving up — without this the latest report is
    silently missed whenever the 15th or month-end falls on a weekend/holiday.

    Returns (settlement_date_str, raw_csv_text) or raises RuntimeError.
    """
    session = requests.Session()
    session.headers.update({"User-Agent": _UA})
    for d in _candidate_dates(today):
        for delta in range(6):
            probe = d - timedelta(days=delta)
            url = f"{FINRA_CDN_BASE}/shrt{probe.strftime('%Y%m%d')}.csv"
            try:
                resp = session.get(url, timeout=60)
            except requests.RequestException:
                continue
            if resp.status_code == 200 and resp.text and "|" in resp.text[:200]:
                return probe.strftime("%Y-%m-%d"), resp.text
    raise RuntimeError("No FINRA short-interest file found in the probed date range.")


def _to_int(v):
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def parse_file(csv_text: str) -> pd.DataFrame:
    """Parse the pipe-delimited FINRA file into a DataFrame of exchange-listed rows."""
    df = pd.read_csv(io.StringIO(csv_text), delimiter="|", dtype=str)
    df = df[df["marketClassCode"].isin(EXCHANGE_LISTED_CLASSES)].copy()
    df = df.fillna("")  # missing cells arrive as NaN; normalize to empty strings
    return df


def ingest(today: date | None = None) -> dict:
    """Download the latest file, load exchange-listed rows into the stocks table
    (upsert — preserves existing yfinance enrichment). Returns a summary dict."""
    init_db()
    settlement_date, csv_text = find_latest_file(today)
    df = parse_file(csv_text)

    session = SessionLocal()
    loaded = 0
    try:
        seen = set()
        for _, r in df.iterrows():
            symbol = (r.get("symbolCode") or "").strip().upper()
            if not symbol or symbol in seen:
                continue
            seen.add(symbol)

            stock = session.get(Stock, symbol) or Stock(symbol=symbol)
            stock.name = (r.get("issueName") or "").strip()
            cls = (r.get("marketClassCode") or "").strip()
            stock.exchange = EXCHANGE_NAMES.get(cls, cls)
            stock.short_interest = _to_int(r.get("currentShortPositionQuantity"))
            stock.prev_short_interest = _to_int(r.get("previousShortPositionQuantity"))
            stock.avg_daily_volume = _to_int(r.get("averageDailyVolumeQuantity"))
            stock.days_to_cover = _to_float(r.get("daysToCoverQuantity"))
            stock.change_percent = _to_float(r.get("changePercent"))
            stock.settlement_date = settlement_date
            stock.updated_at = datetime.utcnow()

            # Recompute short % of outstanding/float if we already have enrichment.
            if stock.float_shares:
                stock.short_pct_float = (
                    round(stock.short_interest / stock.float_shares * 100, 2)
                    if stock.short_interest else None
                )
            if stock.shares_outstanding:
                stock.short_pct_outstanding = (
                    round(stock.short_interest / stock.shares_outstanding * 100, 2)
                    if stock.short_interest else None
                )

            session.add(stock)
            loaded += 1

        set_meta(session, "settlement_date", settlement_date)
        set_meta(session, "last_ingest_at", datetime.utcnow().isoformat())
        session.commit()
    finally:
        session.close()

    return {"settlement_date": settlement_date, "rows_loaded": loaded}


if __name__ == "__main__":
    print(ingest())
