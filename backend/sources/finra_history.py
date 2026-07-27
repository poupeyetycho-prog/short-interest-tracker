"""Backfill the FINRA short-interest archive and detect when shorting ramped.

FINRA settlement dates are the 15th and the last day of each month, **snapped back
to a business day**. Probing a raw calendar date that falls on a weekend/holiday
returns HTTP 403 (verified: 2026-05-31 is a Sunday -> 403), so each candidate is
walked backwards until a file is found.
"""
import io
from datetime import date, timedelta

import pandas as pd
import requests
from sqlalchemy import select

from config import EXCHANGE_LISTED_CLASSES, FINRA_CDN_BASE
from db import SessionLocal, ShortInterestHistory, init_db

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) short-interest-app"


def _settlement_candidates(start: date, end: date):
    """Yield nominal settlement dates (15th + month-end) between start and end, newest first."""
    out = []
    y, m = end.year, end.month
    while True:
        if m == 12:
            last = date(y, 12, 31)
        else:
            last = date(y, m + 1, 1) - timedelta(days=1)
        for d in (last, date(y, m, 15)):
            if start <= d <= end:
                out.append(d)
        m -= 1
        if m == 0:
            m = 12
            y -= 1
        if date(y, m, 1) < start:
            break
    return sorted(set(out), reverse=True)


def _fetch(session, d: date, back_days: int = 5):
    """Try a settlement date, walking back up to `back_days` to hit a business day."""
    for delta in range(back_days + 1):
        probe = d - timedelta(days=delta)
        url = f"{FINRA_CDN_BASE}/shrt{probe.strftime('%Y%m%d')}.csv"
        try:
            r = session.get(url, timeout=90)
        except requests.RequestException:
            continue
        if r.status_code == 200 and r.text and "|" in r.text[:200]:
            return probe.strftime("%Y-%m-%d"), r.text
    return None, None


def backfill(years: int = 3, symbols: set[str] | None = None) -> dict:
    """Load `years` of archive into short_interest_history.

    `symbols` limits storage to a subset (the app's ranked universe) to keep the
    table small; None stores every exchange-listed symbol in each file.
    """
    init_db()
    http = requests.Session()
    http.headers.update({"User-Agent": _UA})

    end = date.today()
    start = end - timedelta(days=365 * years)
    loaded_files, rows_added = 0, 0

    db = SessionLocal()
    try:
        existing = {
            d for (d,) in db.execute(
                select(ShortInterestHistory.settlement_date).distinct()
            ).all()
        }
        for nominal in _settlement_candidates(start, end):
            settle, text = _fetch(http, nominal)
            if not settle or settle in existing:
                continue
            df = pd.read_csv(io.StringIO(text), delimiter="|", dtype=str).fillna("")
            df = df[df["marketClassCode"].isin(EXCHANGE_LISTED_CLASSES)]
            batch = []
            for _, r in df.iterrows():
                sym = (r.get("symbolCode") or "").strip().upper()
                if not sym or (symbols and sym not in symbols):
                    continue
                batch.append(ShortInterestHistory(
                    symbol=sym,
                    settlement_date=settle,
                    short_interest=_i(r.get("currentShortPositionQuantity")),
                    avg_daily_volume=_i(r.get("averageDailyVolumeQuantity")),
                    days_to_cover=_f(r.get("daysToCoverQuantity")),
                ))
            db.bulk_save_objects(batch)
            db.commit()
            existing.add(settle)
            loaded_files += 1
            rows_added += len(batch)
        return {"files": loaded_files, "rows": rows_added}
    finally:
        db.close()


def timeline(symbol: str) -> list[dict]:
    """Full short-interest history for one symbol, oldest first, with period-over-period change."""
    db = SessionLocal()
    try:
        rows = (
            db.query(ShortInterestHistory)
            .filter(ShortInterestHistory.symbol == symbol.upper())
            .order_by(ShortInterestHistory.settlement_date)
            .all()
        )
        out, prev = [], None
        for r in rows:
            chg = None
            if prev and prev > 0 and r.short_interest is not None:
                chg = round((r.short_interest - prev) / prev * 100, 2)
            out.append({
                "settlement_date": r.settlement_date,
                "short_interest": r.short_interest,
                "days_to_cover": r.days_to_cover,
                "change_pct": chg,
            })
            prev = r.short_interest
        return out
    finally:
        db.close()


def inflections(symbol: str, top: int = 3, min_pct: float = 25.0) -> list[dict]:
    """The periods where short interest jumped hardest — the windows worth
    explaining. Each is returned with a +/-5 day window for evidence lookup."""
    tl = timeline(symbol)
    scored = [t for t in tl if t["change_pct"] is not None and t["change_pct"] >= min_pct]
    scored.sort(key=lambda t: t["change_pct"], reverse=True)
    out = []
    for t in scored[:top]:
        d = date.fromisoformat(t["settlement_date"])
        out.append({
            **t,
            "window_start": (d - timedelta(days=20)).isoformat(),
            "window_end": (d + timedelta(days=5)).isoformat(),
        })
    return out


def _i(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    import sys
    yrs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    print(backfill(years=yrs))
