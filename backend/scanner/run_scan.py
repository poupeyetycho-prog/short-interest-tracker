"""The 5-minute scan. Entry point for both local runs and GitHub Actions.

Exits within seconds when the market is closed, which keeps 288 runs/day cheap.

    python -m scanner.run_scan            # normal scan
    python -m scanner.run_scan --dry-run  # evaluate + print, never push
    python -m scanner.run_scan --close    # post-close confirmation pass
"""
import argparse
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, ".")

from analysis import catalyst as catalyst_mod
from analysis.squeeze_rules import (
    TIER_META, evaluate_close, evaluate_intraday, passes_gate,
)
from config import WATCHLIST_MAX
from db import Alert, SessionLocal, Stock, WatchlistEntry, init_db
from market_data import get_candles, get_quote
from scanner import notify

ET = timezone(timedelta(hours=-4))  # US Eastern (EDT)


def market_open_now(now_et: datetime | None = None) -> bool:
    """Extended hours: 04:00-20:00 ET, weekdays."""
    now = now_et or datetime.now(ET)
    if now.weekday() >= 5:
        return False
    return time(4, 0) <= now.time() <= time(20, 0)


def build_watchlist() -> list[WatchlistEntry]:
    """Structural gate — only heavily-shorted, slow-to-cover names can alert."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Stock)
            .filter(Stock.short_pct_float.isnot(None), Stock.short_pct_float <= 100)
            .order_by(Stock.short_pct_float.desc())
            .limit(400)
            .all()
        )
        keep = [s for s in rows if passes_gate(s.short_pct_float, s.days_to_cover)][:WATCHLIST_MAX]
        db.query(WatchlistEntry).delete()
        for s in keep:
            db.add(WatchlistEntry(symbol=s.symbol, short_pct_float=s.short_pct_float,
                                  days_to_cover=s.days_to_cover))
        db.commit()
        return keep
    finally:
        db.close()


def _already_alerted(db, symbol: str, tier: str, trade_date: str) -> bool:
    """One push per ticker per tier per day."""
    return db.query(Alert).filter_by(symbol=symbol, tier=tier, trade_date=trade_date).first() is not None


def _rvol(symbol: str) -> float | None:
    """Cumulative volume today vs the same-time-of-day 20-day baseline.

    Comparing today's partial volume against a *full-day* average would make
    every morning look quiet and every afternoon look explosive — so the baseline
    is built from the same number of elapsed 5-minute bars on prior sessions.
    """
    try:
        bars = get_candles(symbol, "1mo", "5m")
    except Exception:
        return None
    if not bars:
        return None
    by_day: dict[str, list] = {}
    for b in bars:
        day = datetime.fromtimestamp(int(b["time"]), tz=timezone.utc).astimezone(ET).date().isoformat()
        by_day.setdefault(day, []).append(b)
    days = sorted(by_day)
    if len(days) < 5:
        return None
    today, prior = days[-1], days[-6:-1]
    n = len(by_day[today])
    today_vol = sum(b["volume"] for b in by_day[today])
    base = [sum(b["volume"] for b in by_day[d][:n]) for d in prior if len(by_day[d]) >= n]
    if not base:
        return None
    avg = sum(base) / len(base)
    return round(today_vol / avg, 2) if avg else None


def scan(dry_run: bool = False, close_pass: bool = False) -> dict:
    init_db()
    now = datetime.now(ET)
    if not close_pass and not market_open_now(now):
        return {"skipped": "market closed", "at": now.isoformat()}

    watch = build_watchlist()
    trade_date = now.date().isoformat()
    fired, pushed = [], 0

    db = SessionLocal()
    try:
        for entry in watch:
            sym = entry.symbol
            try:
                q = get_quote(sym)
            except Exception:
                continue
            price, prev = q.get("price"), q.get("prev_close")
            if not price or not prev:
                continue

            sig = (evaluate_close(sym, price, prev) if close_pass
                   else evaluate_intraday(sym, price, prev, rvol=_rvol(sym)))
            if not sig:
                continue
            if _already_alerted(db, sym, sig.tier, trade_date):
                continue

            # Catalyst is a LABEL: looked up after the decision to alert, and it
            # can never suppress one.
            cat = catalyst_mod.find(sym) if TIER_META[sig.tier]["push"] else None
            ok = False
            if not dry_run:
                ok = notify.push(sig, cat, click_url=f"http://localhost:5173/#{sym}")
                pushed += 1 if ok else 0

            db.add(Alert(symbol=sym, tier=sig.tier, trade_date=trade_date,
                         price=sig.price, prev_close=sig.prev_close,
                         pct_change=sig.pct_change, rvol=sig.rvol,
                         catalyst=cat, pushed=1 if ok else 0))
            db.commit()
            fired.append({"symbol": sym, "tier": sig.tier, "pct": sig.pct_change,
                          "rvol": sig.rvol, "catalyst": cat, "pushed": ok})
        return {"watchlist": len(watch), "signals": fired, "pushed": pushed,
                "dry_run": dry_run, "close_pass": close_pass, "at": now.isoformat()}
    finally:
        db.close()


def scan_stateless(state_dir: str, dry_run: bool = False, close_pass: bool = False) -> dict:
    """Scan using JSON state instead of SQLite — for ephemeral CI runners.

    Reads the watchlist and cooldown state from `state_dir`, and writes the
    cooldown file back only if an alert actually fired.
    """
    from scanner import state as st

    now = datetime.now(ET)
    if not close_pass and not market_open_now(now):
        return {"skipped": "market closed", "at": now.isoformat(), "changed": False}

    watch = st.load_watchlist(state_dir)
    if not watch:
        return {"skipped": "no watchlist state", "at": now.isoformat(), "changed": False}

    alerts = st.load_alerts(state_dir)
    trade_date = now.date().isoformat()
    fired, pushed, changed = [], 0, False

    for entry in watch:
        sym = entry["symbol"]
        try:
            q = get_quote(sym)
        except Exception:
            continue
        price, prev = q.get("price"), q.get("prev_close")
        if not price or not prev:
            continue

        sig = (evaluate_close(sym, price, prev) if close_pass
               else evaluate_intraday(sym, price, prev, rvol=_rvol(sym)))
        if not sig:
            continue

        key = st.cooldown_key(sym, sig.tier, trade_date)
        if key in alerts:
            continue

        cat = catalyst_mod.find(sym) if TIER_META[sig.tier]["push"] else None
        ok = False
        if not dry_run:
            ok = notify.push(sig, cat)
            pushed += 1 if ok else 0

        alerts[key] = {"date": trade_date, "pct": sig.pct_change,
                       "catalyst": cat, "pushed": ok}
        changed = True
        fired.append({"symbol": sym, "tier": sig.tier, "pct": sig.pct_change,
                      "catalyst": cat, "pushed": ok})

    if changed and not dry_run:
        st.save_alerts(state_dir, alerts)

    return {"watchlist": len(watch), "signals": fired, "pushed": pushed,
            "changed": changed, "at": now.isoformat()}


def refresh_watchlist_state(state_dir: str) -> dict:
    """Rebuild the watchlist from fresh FINRA + enrichment data (runs once daily)."""
    from finra import ingest
    from enrich import enrich as enrich_fn
    from scanner import state as st

    init_db()
    ingest()
    enrich_fn(limit=400)
    keep = build_watchlist()
    st.save_watchlist(state_dir, [
        {"symbol": s.symbol, "short_pct_float": s.short_pct_float,
         "days_to_cover": s.days_to_cover} for s in keep
    ])
    return {"watchlist": len(keep)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="evaluate and print, never push")
    ap.add_argument("--close", action="store_true", help="post-close confirmation pass")
    ap.add_argument("--state-dir", help="use JSON state in this dir (CI mode)")
    ap.add_argument("--refresh-watchlist", action="store_true",
                    help="rebuild watchlist state from FINRA + enrichment")
    args = ap.parse_args()

    if args.refresh_watchlist:
        print(refresh_watchlist_state(args.state_dir or "state"))
        return

    if args.state_dir:
        result = scan_stateless(args.state_dir, dry_run=args.dry_run, close_pass=args.close)
        if "skipped" in result:
            print(f"Skipped: {result['skipped']} ({result['at']})")
            return
        print(f"Watchlist: {result['watchlist']} | signals: {len(result['signals'])} "
              f"| pushed: {result['pushed']} | state changed: {result['changed']}")
        for s in result["signals"]:
            print(f"  {s['tier']:<12} {s['symbol']:<6} {s['pct']:+.2f}%  "
                  f"catalyst={s['catalyst'] or 'none'}")
        return

    result = scan(dry_run=args.dry_run, close_pass=args.close)
    if "skipped" in result:
        print(f"Market closed ({result['at']}) — exiting.")
        return
    print(f"Watchlist: {result['watchlist']} | signals: {len(result['signals'])} "
          f"| pushed: {result['pushed']}")
    for s in result["signals"]:
        print(f"  {s['tier']:<12} {s['symbol']:<6} {s['pct']:+.2f}%  "
              f"catalyst={s['catalyst'] or 'none'}")


if __name__ == "__main__":
    main()
