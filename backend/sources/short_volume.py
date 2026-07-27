"""FINRA daily short-VOLUME (flow) — deliberately kept distinct from short INTEREST.

    Short interest  = position: shares sold short and not yet covered (bi-monthly).
    Short volume    = flow:     how many of today's traded shares were sold short (daily).

Much of daily short volume is market-maker hedging that is covered the same day, so
a stock can print 50% short volume every day with zero change in short interest.
This module therefore only ever feeds a *trend* indicator, never the % of float.
"""
from datetime import date, timedelta

import requests
from sqlalchemy import select

from db import DailyShortVolume, SessionLocal, init_db

_BASE = "https://cdn.finra.org/equity/regsho/daily"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) short-interest-app"


def fetch_day(http: requests.Session, d: date):
    """Return {symbol: (short_volume, total_volume)} for one session, or None if no file."""
    url = f"{_BASE}/CNMSshvol{d.strftime('%Y%m%d')}.txt"
    try:
        r = http.get(url, timeout=60)
    except requests.RequestException:
        return None
    if r.status_code != 200 or "Symbol" not in r.text[:200]:
        return None
    out = {}
    for line in r.text.splitlines()[1:]:
        parts = line.split("|")
        if len(parts) < 5:
            continue
        sym = parts[1].strip().upper()
        try:
            sv, tv = float(parts[2]), float(parts[4])
        except ValueError:
            continue
        if tv > 0:
            out[sym] = (sv, tv)
    return out


def backfill(days: int = 30, symbols: set[str] | None = None) -> dict:
    """Load the last `days` sessions of short-volume data."""
    init_db()
    http = requests.Session()
    http.headers.update({"User-Agent": _UA})
    db = SessionLocal()
    added, files = 0, 0
    try:
        have = {d for (d,) in db.execute(select(DailyShortVolume.date).distinct()).all()}
        for back in range(days):
            d = date.today() - timedelta(days=back)
            if d.weekday() >= 5 or d.isoformat() in have:
                continue
            data = fetch_day(http, d)
            if not data:
                continue
            batch = []
            for sym, (sv, tv) in data.items():
                if symbols and sym not in symbols:
                    continue
                batch.append(DailyShortVolume(
                    symbol=sym, date=d.isoformat(),
                    short_volume=sv, total_volume=tv, ratio=round(sv / tv, 4),
                ))
            db.bulk_save_objects(batch)
            db.commit()
            files += 1
            added += len(batch)
        return {"sessions": files, "rows": added}
    finally:
        db.close()


def trend(symbol: str, days: int = 20) -> dict:
    """Recent short-volume ratios plus a simple direction read.

    A rising ratio between official reports suggests shorts are actively adding —
    a 'nowcast' that partly closes the two-week blind spot in the bi-monthly data.
    """
    db = SessionLocal()
    try:
        rows = (
            db.query(DailyShortVolume)
            .filter(DailyShortVolume.symbol == symbol.upper())
            .order_by(DailyShortVolume.date.desc())
            .limit(days)
            .all()
        )
        rows = list(reversed(rows))
        series = [{"date": r.date, "ratio": r.ratio} for r in rows]
        direction, recent, earlier = None, None, None
        if len(series) >= 6:
            half = len(series) // 2
            earlier = sum(s["ratio"] for s in series[:half]) / half
            recent = sum(s["ratio"] for s in series[half:]) / (len(series) - half)
            if recent > earlier * 1.05:
                direction = "rising"
            elif recent < earlier * 0.95:
                direction = "falling"
            else:
                direction = "flat"
        return {
            "series": series,
            "direction": direction,
            "recent_avg": round(recent, 4) if recent else None,
            "earlier_avg": round(earlier, 4) if earlier else None,
            "note": "Flow, not position. Includes market-maker hedging; not % of float shorted.",
        }
    finally:
        db.close()


if __name__ == "__main__":
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    print(backfill(days=n))
