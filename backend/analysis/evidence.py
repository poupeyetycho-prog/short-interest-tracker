"""Assemble the evidence bundle behind 'Reason Short' and 'Reason Short Squeeze'.

Both buttons share this pipeline; they differ in time window and in the prompt
used to synthesize the result. Every source degrades independently — a failing
source reports itself unavailable rather than sinking the whole bundle.
"""
import concurrent.futures as futures
from datetime import date, timedelta

from db import SessionLocal, Stock
from sources import edgar, ftd, finra_history, news, short_volume, social


def _safe(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as e:  # a dead source must not sink the bundle
        return {"available": False, "error": str(e)[:200]}


def _stock_facts(symbol: str) -> dict:
    db = SessionLocal()
    try:
        s = db.get(Stock, symbol.upper())
        if not s:
            return {}
        return {
            "symbol": s.symbol, "name": s.name, "exchange": s.exchange,
            "short_interest": s.short_interest, "prev_short_interest": s.prev_short_interest,
            "short_pct_float": s.short_pct_float, "short_pct_outstanding": s.short_pct_outstanding,
            "days_to_cover": s.days_to_cover, "change_percent": s.change_percent,
            "settlement_date": s.settlement_date, "float_shares": s.float_shares,
            "shares_outstanding": s.shares_outstanding, "market_cap": s.market_cap,
            "last_close": s.last_close, "dollar_volume": s.dollar_volume,
            "suspect_data": bool(s.short_pct_float and s.short_pct_float > 100),
        }
    finally:
        db.close()


def gather(symbol: str, mode: str = "short") -> dict:
    """Build the evidence bundle.

    mode='short'   -> full history, anchored on short-interest inflection points
    mode='squeeze' -> last 14 days, focused on what is moving the stock right now
    """
    symbol = symbol.upper()
    recent_start = (date.today() - timedelta(days=14 if mode == "squeeze" else 365)).isoformat()

    with futures.ThreadPoolExecutor(max_workers=8) as pool:
        jobs = {
            "filings": pool.submit(_safe, edgar.thesis_filings, symbol, recent_start),
            "dilution": pool.submit(_safe, edgar.dilution_signals, symbol, recent_start),
            "headlines": pool.submit(_safe, news.headlines, symbol),
            "stocktwits": pool.submit(_safe, social.stocktwits, symbol),
            "reddit": pool.submit(_safe, social.reddit, symbol),
            "fails_to_deliver": pool.submit(_safe, ftd.recent, symbol, 2),
            "short_volume_trend": pool.submit(_safe, short_volume.trend, symbol),
            "si_timeline": pool.submit(_safe, finra_history.timeline, symbol),
            "inflections": pool.submit(_safe, finra_history.inflections, symbol),
        }
        out = {k: f.result() for k, f in jobs.items()}

    heads = out["headlines"] if isinstance(out["headlines"], list) else []
    out["news_classification"] = news.classify(heads) if heads else {}

    # The causal step: for each period where short interest jumped hardest, pull
    # the filings actually made inside that window.
    infl = out["inflections"] if isinstance(out["inflections"], list) else []
    linked = []
    for i in infl:
        linked.append({
            **i,
            "filings_in_window": _safe(
                edgar.filings_in_window, symbol, i["window_start"], i["window_end"]
            ),
        })
    out["inflections"] = linked

    out["stock"] = _stock_facts(symbol)
    out["x_search_url"] = social.x_search_url(symbol)
    out["mode"] = mode
    out["as_of"] = date.today().isoformat()
    return out


def compact_for_llm(bundle: dict) -> dict:
    """Trim the bundle to what the model needs — keeps token cost and noise down."""
    heads = bundle.get("headlines")
    heads = heads[:20] if isinstance(heads, list) else []
    tl = bundle.get("si_timeline")
    tl = tl[-12:] if isinstance(tl, list) else []

    st = bundle.get("stocktwits") or {}
    rd = bundle.get("reddit") or {}
    ftd_ = bundle.get("fails_to_deliver") or {}

    return {
        "stock": bundle.get("stock", {}),
        "short_interest_timeline": tl,
        "inflection_points": [
            {
                "settlement_date": i["settlement_date"],
                "change_pct": i["change_pct"],
                "window": [i["window_start"], i["window_end"]],
                "filings_in_window": [
                    {"form": f["form"], "filed": f["filed"], "meaning": f.get("meaning"),
                     "url": f.get("url")}
                    for f in (i.get("filings_in_window") or [])
                    if isinstance(f, dict)
                ][:8],
            }
            for i in (bundle.get("inflections") or [])
        ],
        "recent_filings": [
            {"form": f["form"], "filed": f["filed"], "meaning": f.get("meaning"), "url": f.get("url")}
            for f in (bundle.get("filings") or []) if isinstance(f, dict)
        ][:15],
        "dilution": bundle.get("dilution"),
        "headlines": [{"title": h["title"], "url": h.get("url"),
                       "published": h.get("published"), "source": h.get("source")}
                      for h in heads],
        "news_classification": bundle.get("news_classification"),
        "short_volume_trend": {
            "direction": (bundle.get("short_volume_trend") or {}).get("direction"),
            "recent_avg": (bundle.get("short_volume_trend") or {}).get("recent_avg"),
            "earlier_avg": (bundle.get("short_volume_trend") or {}).get("earlier_avg"),
            "note": "FLOW not position; includes market-maker hedging.",
        },
        "fails_to_deliver": {k: ftd_.get(k) for k in ("available", "days", "max_fails", "avg_fails")},
        "social": {
            "stocktwits_messages": st.get("messages"),
            "stocktwits_bull_ratio": st.get("bull_ratio"),
            "reddit_available": rd.get("available"),
            "reddit_post_count": rd.get("post_count"),
        },
    }
